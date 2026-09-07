import json
from decimal import Decimal
from unittest import mock

from django.contrib.auth.models import Group, User
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from store import pos
from store.models import (InventoryChange, Order, Payment, PosSession, Product,
                          SiteSettings)
from store.tests.test_models import make_category, make_product


def make_staff(username='cashier1', role=None):
    user = User.objects.create_user(username=username, password='pass12345',
                                    first_name='Cash', last_name='Ier')
    user.is_staff = True
    user.save()
    if role:
        group, _ = Group.objects.get_or_create(name=role)
        user.groups.add(group)
    return user


class StaffUserMixin:
    def login(self, user):
        client = Client()
        client.login(username=user.username, password='pass12345')
        return client


# --------------------------------------------------------------------------- #
# Search
# --------------------------------------------------------------------------- #

class PosSearchTests(StaffUserMixin, TestCase):
    def setUp(self):
        self.user = make_staff()
        self.client = self.login(self.user)
        cat = make_category()
        self.cola = make_product(name='Coca Cola 500ml', category=cat, sku='COKE-500',
                                 price='100.00', stock=25)
        self.bread = make_product(name='Bread', category=cat, sku='BRD-1',
                                  price='80.00', stock=10)
        Product.objects.filter(pk=self.cola.pk).update(barcode='1234567890123')
        self.cola.refresh_from_db()

    def test_search_by_name(self):
        resp = self.client.get(reverse('pos_search'), {'q': 'cola'})
        data = resp.json()
        self.assertEqual(data['results'][0]['name'], 'Coca Cola 500ml')
        self.assertEqual(data['results'][0]['price'], '100.00')

    def test_search_exact_sku_and_barcode_first(self):
        for q in ('BRD-1', '1234567890123'):
            resp = self.client.get(reverse('pos_search'), {'q': q})
            results = resp.json()['results']
            self.assertEqual(len(results), 1)
            self.assertIn(results[0]['sku'], {self.bread.sku, self.cola.sku})

    def test_search_requires_staff(self):
        resp = Client().get(reverse('pos_search'), {'q': 'cola'})
        self.assertEqual(resp.status_code, 302)

    def test_service_layer_barcode_exact_match(self):
        found = pos.search_products('1234567890123')
        self.assertEqual([p.pk for p in found], [self.cola.pk])


# --------------------------------------------------------------------------- #
# Checkout (cash, MPesa, idempotency, oversell, discount)
# --------------------------------------------------------------------------- #

class PosCheckoutTests(StaffUserMixin, TestCase):
    def setUp(self):
        SiteSettings.objects.all().delete()
        s = SiteSettings.get()
        s.inventory_strategy = 'hold'
        s.mpesa_enabled = True
        s.save()
        self.user = make_staff(username='till1', role='Cashier')
        self.client = self.login(self.user)
        pos.open_session(self.user, Decimal('1000.00'))
        cat = make_category('Groceries')
        self.cola = make_product(name='Coca Cola', category=cat, sku='COKE-1', price='100.00', stock=50)
        self.bread = make_product(name='Bread', category=cat, sku='BRD-9', price='80.00', stock=20)

    def _checkout(self, **overrides):
        payload = {
            'items': [{'id': self.cola.pk, 'quantity': 3},
                      {'id': self.bread.pk, 'quantity': 1}],
            'payment_method': 'cash',
            'cash_received': '400.00',
            'token': 'tok-1',
            'customer_name': 'Walk-in customer',
        }
        payload.update(overrides)
        return self.client.post(reverse('pos_checkout'),
                                data=json.dumps(payload),
                                content_type='application/json')

    def test_cash_sale_deducts_stock_and_records_change(self):
        resp = self._checkout(cash_received='450.00')
        self.assertEqual(resp.status_code, 200)
        sale = resp.json()['sale']
        self.assertTrue(sale['created'])
        self.assertEqual(sale['payment_status'], 'paid')

        order = Order.objects.get(number=sale['number'])
        self.assertEqual(order.sales_channel, 'pos')
        self.assertEqual(order.subtotal, Decimal('380.00'))
        self.assertEqual(order.total, Decimal('380.00'))
        self.assertEqual(order.pos_payment_method, 'cash')
        self.assertEqual(order.served_by, self.user)

        payment = order.payments.first()
        self.assertEqual(payment.status, 'paid')
        self.assertEqual(payment.amount_paid, Decimal('450.00'))
        self.assertEqual(payment.change_given, Decimal('70.00'))

        self.cola.refresh_from_db()
        self.bread.refresh_from_db()
        self.assertEqual(self.cola.stock, 47)
        self.assertEqual(self.bread.stock, 19)

        actions = list(InventoryChange.objects.filter(product=self.cola)
                       .values_list('action', flat=True))
        self.assertIn('sale', actions)

        session = PosSession.objects.get(user=self.user,
                                         status=PosSession.STATUS_OPEN)
        self.assertEqual(session.orders_count, 1)
        self.assertEqual(session.sales_total, Decimal('380.00'))

    def test_insufficient_cash_rejected(self):
        resp = self._checkout(cash_received='100.00')
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(Order.objects.exists())
        self.cola.refresh_from_db()
        self.assertEqual(self.cola.stock, 50)

    def test_oversell_rejected(self):
        resp = self._checkout(items=[{'id': self.cola.pk, 'quantity': 51}])
        self.assertEqual(resp.status_code, 400)
        self.assertIn('Not enough stock', resp.json()['error'])
        self.assertFalse(Order.objects.exists())

    def test_idempotent_token_prevents_duplicate(self):
        first = self._checkout()
        second = self._checkout()   # same token
        self.assertEqual(first.json()['sale']['number'],
                         second.json()['sale']['number'])
        self.assertFalse(second.json()['sale']['created'])
        self.assertEqual(Order.objects.count(), 1)
        self.cola.refresh_from_db()
        self.assertEqual(self.cola.stock, 47)

    def test_discount_requires_manager_role(self):
        resp = self._checkout(discount='100.00')
        self.assertEqual(resp.status_code, 403)
        self.assertFalse(Order.objects.exists())

        mgr = make_staff(username='mgr', role='Manager')
        mgr_client = self.login(mgr)
        payload = {
            'items': [{'id': self.cola.pk, 'quantity': 2}],
            'payment_method': 'card',
            'discount': '50.00',
            'token': 'tok-disc',
        }
        resp = mgr_client.post(reverse('pos_checkout'),
                               data=json.dumps(payload),
                               content_type='application/json')
        self.assertEqual(resp.status_code, 200)
        order = Order.objects.get(pos_token='tok-disc')
        self.assertEqual(order.discount, Decimal('50.00'))
        self.assertEqual(order.total, Decimal('150.00'))

    @mock.patch('store.pos._start_mpesa')
    def test_mpesa_pending_until_confirmed(self, _mock):
        resp = self._checkout(items=[{'id': self.cola.pk, 'quantity': 2}],
                              payment_method='mpesa', phone='0712345678',
                              cash_received=None)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()['sale']['pending_mpesa'])

        order = Order.objects.get(number=resp.json()['sale']['number'])
        self.assertEqual(order.payment_status, 'pending')
        self.cola.refresh_from_db()
        self.assertEqual(self.cola.stock, 50)

        from store.services import mark_order_paid
        mark_order_paid(order, method='mpesa', reference='QK7TEST',
                        verification='gateway', transaction_id='req-1')
        self.cola.refresh_from_db()
        self.assertEqual(self.cola.stock, 48)
        order.refresh_from_db()
        self.assertEqual(order.payment_status, 'paid')

    def test_mpesa_stk_failure_cancels_sale(self):
        resp = self._checkout(items=[{'id': self.bread.pk, 'quantity': 1}],
                              payment_method='mpesa', phone='0712345678',
                              cash_received=None)
        self.assertEqual(resp.status_code, 200)
        order = Order.objects.get(number=resp.json()['sale']['number'])

        # on_commit never fires in TestCase, so call _start_mpesa directly.
        with mock.patch('store.pos.mpesa.stk_push',
                        side_effect=RuntimeError('Daraja down')):
            pos._start_mpesa(order.pk)

        order.refresh_from_db()
        self.assertEqual(order.payment_status, 'failed')
        self.assertEqual(order.status, 'cancelled')
        self.bread.refresh_from_db()
        self.assertEqual(self.bread.stock, 20)

    def test_receipt_renders_and_downloads(self):
        resp = self._checkout(cash_received='400.00')
        number = resp.json()['sale']['number']

        page = self.client.get(reverse('receipt', args=[number]))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, number)

        dl = self.client.get(reverse('receipt', args=[number]),
                             {'download': '1'})
        self.assertEqual(dl.status_code, 200)
        self.assertIn('attachment', dl['Content-Disposition'])


# --------------------------------------------------------------------------- #
# POS sessions
# --------------------------------------------------------------------------- #

class PosSessionTests(StaffUserMixin, TestCase):
    def setUp(self):
        self.user = make_staff()
        self.client = self.login(self.user)
        self.product = make_product(price='100.00', stock=30)

    def test_terminal_shows_open_form_when_no_shift(self):
        page = self.client.get(reverse('pos_terminal'))
        self.assertContains(page, 'Open your shift')

    def test_open_close_session_flow(self):
        self.client.post(reverse('pos_session_open'), {'opening_cash': '500'})
        session = PosSession.objects.get(user=self.user,
                                         status=PosSession.STATUS_OPEN)
        self.assertEqual(session.opening_cash, Decimal('500.00'))

        self.assertNotContains(self.client.get(reverse('pos_terminal')),
                               'Open your shift')

        payload = {'items': [{'id': self.product.pk, 'quantity': 2}],
                   'payment_method': 'cash', 'cash_received': '200.00',
                   'token': 'tok-ses'}
        self.client.post(reverse('pos_checkout'),
                         data=json.dumps(payload),
                         content_type='application/json')

        self.client.post(reverse('pos_session_close'),
                         {'closing_cash': '700', 'confirm': '1'})
        session.refresh_from_db()
        self.assertEqual(session.status, PosSession.STATUS_CLOSED)
        self.assertEqual(session.closing_cash, Decimal('700.00'))


# --------------------------------------------------------------------------- #
# Role permissions
# --------------------------------------------------------------------------- #

class RolePermissionTests(StaffUserMixin, TestCase):
    def setUp(self):
        self.cashier = make_staff(username='till1', role='Cashier')
        self.admin = make_staff(username='boss1')   # no group => Admin
        self.client = self.login(self.cashier)

    def test_cashier_can_open_pos_not_products(self):
        self.assertEqual(self.client.get(reverse('pos_terminal')).status_code, 200)
        self.assertEqual(self.client.get(reverse('product_add')).status_code, 302)
        self.assertEqual(self.client.get(reverse('inventory_update')).status_code, 302)

    def test_cashier_blocked_from_settings(self):
        self.assertEqual(self.client.get(reverse('manage_settings')).status_code, 302)

    def test_admin_retains_full_access(self):
        boss = Client()
        boss.login(username='boss1', password='pass12345')
        self.assertEqual(boss.get(reverse('product_add')).status_code, 200)
        self.assertEqual(boss.get(reverse('manage_settings')).status_code, 200)


# --------------------------------------------------------------------------- #
# Returns
# --------------------------------------------------------------------------- #

class ReturnTests(StaffUserMixin, TestCase):
    def setUp(self):
        SiteSettings.objects.all().delete()
        SiteSettings.get()
        self.manager = make_staff(username='ret-mgr', role='Manager')
        self.client = self.login(self.manager)
        self.product = make_product(name='Returnable', price='300.00', stock=5)

        pos.open_session(self.manager)
        payload = {'items': [{'id': self.product.pk, 'quantity': 3}],
                   'payment_method': 'cash', 'cash_received': '900.00',
                   'token': 'tok-ret'}
        resp = self.client.post(reverse('pos_checkout'),
                                data=json.dumps(payload),
                                content_type='application/json')
        self.assertEqual(resp.status_code, 200)
        self.order = Order.objects.get(pos_token='tok-ret')
        self.item = self.order.items.first()

    def test_partial_return_restocks_original_intact(self):
        self.client.post(reverse('order_return_item', args=[self.order.number]), {
            'item_id': self.item.pk, 'quantity': 1,
            'reason': 'Customer changed mind', 'restock': 'on'})

        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 3)  # 2 after sale, +1 restocked

        ret = self.order.returns.first()
        self.assertIsNotNone(ret)
        self.assertEqual(ret.quantity, 1)
        self.assertEqual(ret.refunded_amount, Decimal('300.00'))
        self.assertEqual(ret.processed_by, self.manager)

        self.item.refresh_from_db()
        self.assertEqual(self.item.quantity, 3)
        self.assertEqual(self.order.total, Decimal('900.00'))

        movement = InventoryChange.objects.filter(
            product=self.product, action='return').first()
        self.assertIsNotNone(movement)
        self.assertEqual(movement.change, 1)

        # Attempting to return more than was bought is rejected.
        self.client.post(reverse('order_return_item', args=[self.order.number]), {
            'item_id': self.item.pk, 'quantity': 3,
            'reason': 'over', 'restock': 'on'})
        # Still only the one successful return record.
        self.assertEqual(self.order.returns.count(), 1)
        self.assertEqual(self.order.returns.first().quantity, 1)

    def test_return_without_restock_preserves_stock(self):
        self.product.refresh_from_db()
        stock_before = self.product.stock  # 2 after the sale

        self.client.post(reverse('order_return_item', args=[self.order.number]), {
            'item_id': self.item.pk, 'quantity': 1,
            'reason': 'Damaged goods'})
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, stock_before)
        self.assertEqual(self.order.returns.count(), 1)
        self.assertFalse(self.order.returns.first().restocked)


# --------------------------------------------------------------------------- #
# Edge cases
# --------------------------------------------------------------------------- #

class PosEdgeCaseTests(TestCase):
    def test_out_of_stock_never_sellable(self):
        product = make_product(price='50.00', stock=0)
        staff = User.objects.create_user('u1', password='pass12345')
        staff.is_staff = True
        staff.save()
        pos.open_session(staff)

        client = Client()
        client.login(username='u1', password='pass12345')
        payload = {'items': [{'id': product.pk, 'quantity': 1}],
                   'payment_method': 'cash', 'cash_received': '50.00'}
        resp = client.post(reverse('pos_checkout'),
                           data=json.dumps(payload),
                           content_type='application/json')
        self.assertEqual(resp.status_code, 400)
