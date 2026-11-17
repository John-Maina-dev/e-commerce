import json
import uuid
from decimal import Decimal
from unittest import mock

from django.contrib.auth.models import AnonymousUser, User
from django.test import Client, RequestFactory, TestCase
from django.urls import reverse

from store.models import MpesaTransaction, Notification, Order, Payment, Product, SiteSettings
from store.services import (create_order_from_cart, debit_stock_for_order, mark_order_paid,
                            mark_order_payment_failed, release_stock)
from store.tests.test_models import make_category, make_product
from store.tests.test_services import FakeSession


def build_request():
    request = RequestFactory().get('/')
    request.session = FakeSession()
    request.user = AnonymousUser()
    return request


def make_order(stock=5, strategy='hold', payment_method='cod', category=None):
    settings = SiteSettings.get()
    settings.inventory_strategy = strategy
    settings.save()
    product = make_product(price='1000.00', stock=stock, category=category,
                           sku=f'PAY-{uuid.uuid4().hex[:10].upper()}')
    request = build_request()
    from store.services import add_to_cart, totals_for
    add_to_cart(request, product, 2)
    data = {'customer_name': 'Jane Doe', 'phone': '0712345678', 'email': 'jane@example.com',
            'address_line1': '1 Main St', 'city': 'Nairobi', 'county': 'Nairobi'}
    order = create_order_from_cart(request, data, payment_method, totals_for(request))
    return order, product


class PaymentStatusTests(TestCase):
    def test_required_payment_statuses_exist(self):
        statuses = dict(Payment.STATUS_CHOICES)
        for key in ('pending', 'processing', 'paid', 'failed', 'cancelled', 'refunded', 'requires_review'):
            self.assertIn(key, statuses)

    def test_verification_choices(self):
        self.assertEqual(dict(Payment.VERIFICATION_CHOICES)['gateway'], 'Gateway verified')
        self.assertEqual(dict(Payment.VERIFICATION_CHOICES)['manual'], 'Manually reviewed')


class PaymentRecordTests(TestCase):
    def test_order_creation_creates_pending_payment(self):
        order, product = make_order()
        payment = order.payments.get()
        self.assertEqual(payment.status, 'pending')
        self.assertEqual(payment.method, 'manual')
        self.assertEqual(payment.amount, order.total)
        self.assertEqual(payment.phone, order.phone)

    def test_mpesa_order_creates_mpesa_payment(self):
        order, product = make_order(payment_method='mpesa')
        self.assertEqual(order.payments.get().method, 'mpesa')


class InventoryStrategyTests(TestCase):
    def test_hold_strategy_deducts_at_order_time(self):
        order, product = make_order(strategy='hold', stock=5)
        product.refresh_from_db()
        self.assertEqual(product.stock, 3)
        self.assertTrue(order.stock_deducted)
        self.assertEqual(debit_stock_for_order(order), 0)
        product.refresh_from_db()
        self.assertEqual(product.stock, 3)

    def test_paid_strategy_deducts_only_when_paid(self):
        order, product = make_order(strategy='paid', stock=5)
        product.refresh_from_db()
        self.assertEqual(product.stock, 5)
        self.assertFalse(order.stock_deducted)
        self.assertEqual(debit_stock_for_order(order), 2)
        product.refresh_from_db()
        self.assertEqual(product.stock, 3)
        self.assertTrue(order.stock_deducted)
        # never deduct twice
        self.assertEqual(debit_stock_for_order(order), 0)

    def test_paid_strategy_release_without_payment_does_nothing(self):
        order, product = make_order(strategy='paid', stock=5)
        product.refresh_from_db()
        self.assertEqual(release_stock(order), 0)
        product.refresh_from_db()
        self.assertEqual(product.stock, 5)
        self.assertTrue(order.stock_released)

    def test_paid_strategy_release_after_debit_restores(self):
        order, product = make_order(strategy='paid', stock=5)
        debit_stock_for_order(order)
        product.refresh_from_db()
        self.assertEqual(product.stock, 3)
        self.assertEqual(release_stock(order), 2)
        product.refresh_from_db()
        self.assertEqual(product.stock, 5)


class PaymentConfirmationTests(TestCase):
    def test_gateway_payment_marks_order_paid_and_confirmed(self):
        order, product = make_order(payment_method='mpesa')
        mark_order_paid(order, method='mpesa', reference='PJX999', verification='gateway',
                        transaction_id='req-xyz', result_code='0')
        order.refresh_from_db()
        self.assertEqual(order.payment_status, 'paid')
        self.assertEqual(order.status, 'confirmed')
        payment = order.payments.get()
        self.assertEqual(payment.status, 'paid')
        self.assertEqual(payment.verification, 'gateway')
        self.assertEqual(payment.reference, 'PJX999')
        self.assertEqual(payment.transaction_id, 'req-xyz')
        self.assertIsNone(payment.verified_by)

    def test_stk_push_does_not_mark_order_paid(self):
        settings = SiteSettings.get()
        settings.mpesa_enabled = True
        settings.mpesa_consumer_key = 'key'
        settings.mpesa_consumer_secret = 'secret'
        settings.mpesa_shortcode = '174379'
        settings.mpesa_passkey = 'passkey'
        settings.mpesa_callback_url = 'https://example.com/payments/mpesa/callback/'
        settings.save()

        order, product = make_order(payment_method='mpesa')
        token_resp = mock.MagicMock()
        token_resp.json.return_value = {'access_token': 'TOKEN'}
        push_resp = mock.MagicMock()
        push_resp.json.return_value = {'ResponseCode': '0', 'CheckoutRequestID': 'ws_CO_123',
                                       'MerchantRequestID': 'mreq_123', 'ResponseDescription': 'Success.'}
        push_resp.raise_for_status.return_value = None
        with mock.patch('store.mpesa.requests.get', return_value=token_resp), \
             mock.patch('store.mpesa.requests.post', return_value=push_resp) as post:
            from store import mpesa
            tx, data = mpesa.stk_push(order, '0712345678')

        order.refresh_from_db()
        self.assertEqual(order.payment_status, 'pending')
        self.assertEqual(order.status, 'pending')
        self.assertEqual(tx.status, 'sent')
        self.assertEqual(tx.checkout_request_id, 'ws_CO_123')
        payload = post.call_args.kwargs['json']
        self.assertEqual(payload['Amount'], int(order.total))
        self.assertEqual(payload['PhoneNumber'], '254712345678')

    def test_customer_cannot_mark_order_paid(self):
        order, product = make_order(payment_method='mpesa')
        user = User.objects.create_user(username='jane', password='TestPass123!')
        client = Client()
        client.login(username='jane', password='TestPass123!')
        # There is no customer-facing endpoint; even the staff action refuses non-staff.
        resp = client.post(reverse('payment_action', args=[order.payments.get().pk]), {'action': 'approve'})
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp.url.startswith('/account/login/'))
        order.refresh_from_db()
        self.assertEqual(order.payment_status, 'pending')

    def test_manual_approval_does_not_claim_gateway_verification(self):
        order, product = make_order(payment_method='cod')
        staff = User.objects.create_superuser(username='admin', email='a@b.com', password='TestPass123!')
        payment = mark_order_paid(order, method='manual', reference='',
                                  verification='manual', verified_by=staff, note='cash received')
        self.assertEqual(payment.verification, 'manual')
        self.assertFalse(payment.is_gateway_verified)
        self.assertTrue(payment.is_manually_reviewed)
        self.assertEqual(payment.verified_by, staff)
        self.assertIsNotNone(payment.verified_at)

    def test_manual_reject_records_who_and_when(self):
        order, product = make_order(payment_method='cod')
        staff = User.objects.create_superuser(username='admin2', email='a@c.com', password='TestPass123!')
        payment = mark_order_payment_failed(order, method='manual', status='cancelled',
                                            verified_by=staff, note='customer never paid')
        self.assertEqual(payment.status, 'cancelled')
        self.assertEqual(payment.verified_by, staff)
        self.assertIsNotNone(payment.verified_at)
        self.assertEqual(payment.action_note, 'customer never paid')
        order.refresh_from_db()
        self.assertEqual(order.payment_status, 'cancelled')
        self.assertEqual(order.status, 'cancelled')

    def test_paid_strategy_insufficient_stock_creates_notification(self):
        order, product = make_order(strategy='paid', stock=2)
        product.stock = 0
        product.save()
        mark_order_paid(order, method='manual', reference='', verification='manual',
                        note='approved')
        order.refresh_from_db()
        self.assertEqual(order.payment_status, 'paid')
        self.assertTrue(Notification.objects.filter(
            title__contains=order.number, message__contains='Not enough stock').exists())


class PaymentAdminViewTests(TestCase):
    def setUp(self):
        self.order, self.product = make_order(payment_method='cod')
        self.other_order, _ = make_order(payment_method='mpesa', category=make_category('Party Wear'))
        self.staff = Client()
        User.objects.create_superuser(username='admin', email='a@b.com', password='TestPass123!')
        self.staff.login(username='admin', password='TestPass123!')

    def test_payments_dashboard_shows_required_columns(self):
        resp = self.staff.get(reverse('manage_payments'))
        self.assertEqual(resp.status_code, 200)
        for text in ('Order', 'Customer', 'Amount', 'Phone', 'Method', 'Transaction ID',
                     'Status / verification', 'Date', 'Result'):
            self.assertContains(resp, text)
        self.assertContains(resp, self.order.number)

    def test_payments_dashboard_filter_by_status_and_method(self):
        resp = self.staff.get(reverse('manage_payments'), {'method': 'mpesa'})
        self.assertContains(resp, self.other_order.number)
        self.assertNotContains(resp, self.order.number)
        resp = self.staff.get(reverse('manage_payments'), {'status': 'pending'})
        self.assertContains(resp, self.order.number)

    def test_payments_dashboard_search(self):
        resp = self.staff.get(reverse('manage_payments'), {'q': self.order.number})
        self.assertContains(resp, self.order.number)
        self.assertNotContains(resp, self.other_order.number)

    def test_approve_reject_buttons_shown_for_reviewable(self):
        resp = self.staff.get(reverse('manage_payments'))
        self.assertContains(resp, 'Approve')
        self.assertContains(resp, 'Reject')

    def test_admin_approve_cod_payment(self):
        payment = self.order.payments.get()
        resp = self.staff.post(reverse('payment_action', args=[payment.pk]),
                               {'action': 'approve', 'note': 'paid at the shop'})
        self.assertRedirects(resp, reverse('manage_payment_detail', args=[payment.pk]))
        payment.refresh_from_db()
        self.order.refresh_from_db()
        self.assertEqual(payment.status, 'paid')
        self.assertEqual(payment.verification, 'manual')
        self.assertEqual(self.order.payment_status, 'paid')
        self.assertEqual(self.order.status, 'confirmed')
        self.assertEqual(payment.action_note, 'paid at the shop')
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 3)

    def test_admin_reject_payment(self):
        payment = self.order.payments.get()
        resp = self.staff.post(reverse('payment_action', args=[payment.pk]),
                               {'action': 'reject', 'mark_cancelled': 'on'})
        self.assertRedirects(resp, reverse('manage_payment_detail', args=[payment.pk]))
        payment.refresh_from_db()
        self.assertEqual(payment.status, 'cancelled')
        self.order.refresh_from_db()
        self.assertEqual(self.order.payment_status, 'cancelled')
        self.assertEqual(self.order.status, 'cancelled')

    def test_terminal_payment_cannot_be_reviewed(self):
        mark_order_paid(self.order, method='manual', reference='', verification='manual')
        payment = self.order.payments.get()
        resp = self.staff.post(reverse('payment_action', args=[payment.pk]), {'action': 'approve'})
        self.assertRedirects(resp, reverse('manage_payment_detail', args=[payment.pk]))
        payment.refresh_from_db()
        self.assertEqual(payment.status, 'paid')

    def test_payment_detail_shows_verification_badges(self):
        payment = self.order.payments.get()
        resp = self.staff.get(reverse('manage_payment_detail', args=[payment.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Approve or reject')

    def test_guest_cannot_access_payment_dashboard(self):
        resp = Client().get(reverse('manage_payments'))
        self.assertEqual(resp.status_code, 302)


class MpesaCallbackFlowTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.order, self.product = make_order(payment_method='mpesa')
        self.tx = MpesaTransaction.objects.create(
            transaction_id='tx-1', order=self.order, phone='254712345678',
            amount=self.order.total, checkout_request_id='req-1', status='sent')

    def _callback(self, result_code='0', amount=None):
        meta_items = [
            {'Name': 'MpesaReceiptNumber', 'Value': 'PJX123ABC'},
            {'Name': 'Amount', 'Value': amount if amount is not None else int(self.order.total)},
        ]
        body = {'Body': {'stkCallback': {
            'CheckoutRequestID': 'req-1', 'ResultCode': result_code,
            'ResultDesc': 'processed', 'CallbackMetadata': {'Item': meta_items}}}}
        return self.client.post(reverse('mpesa_callback'), json.dumps(body),
                                content_type='application/json')

    def test_callback_success_deducts_stock_under_paid_strategy(self):
        order, product = make_order(strategy='paid', payment_method='mpesa',
                                    category=make_category('Party Wear'))
        product.refresh_from_db()
        self.assertEqual(product.stock, 5)
        MpesaTransaction.objects.create(
            transaction_id='tx-paid', order=order, phone='254712345678',
            amount=order.total, checkout_request_id='req-paid', status='sent')
        body = {'Body': {'stkCallback': {
            'CheckoutRequestID': 'req-paid', 'ResultCode': '0',
            'ResultDesc': 'processed',
            'CallbackMetadata': {'Item': [
                {'Name': 'MpesaReceiptNumber', 'Value': 'PJXPAID1'},
                {'Name': 'Amount', 'Value': int(order.total)}]}}}}
        self.client.post(reverse('mpesa_callback'), json.dumps(body), content_type='application/json')
        product.refresh_from_db()
        self.assertEqual(product.stock, 3)

    def test_callback_success_keeps_stock_under_hold_strategy(self):
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 3)
        self._callback()
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 3)

    def test_callback_failure_releases_held_stock(self):
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 3)
        self._callback(result_code='1')
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 5)
        self.order.refresh_from_db()
        self.assertEqual(self.order.payment_status, 'failed')
        self.assertEqual(self.order.status, 'cancelled')

    def test_callback_unknown_checkout_ignored(self):
        body = {'Body': {'stkCallback': {'CheckoutRequestID': 'nope', 'ResultCode': '0'}}}
        resp = self.client.post(reverse('mpesa_callback'), json.dumps(body), content_type='application/json')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['ResultCode'], 0)

    def test_bad_payload_returns_error_json(self):
        resp = self.client.post(reverse('mpesa_callback'), 'not json', content_type='application/json')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['ResultCode'], 1)


class PaymentSettingsSecretTests(TestCase):
    def setUp(self):
        self.staff = Client()
        User.objects.create_superuser(username='admin', email='a@b.com', password='TestPass123!')
        self.staff.login(username='admin', password='TestPass123!')

    def test_secrets_never_rendered_in_settings_page(self):
        s = SiteSettings.get()
        s.mpesa_consumer_key = 'SUPER_SECRET_KEY_123'
        s.mpesa_consumer_secret = 'SUPER_SECRET_SECRET_456'
        s.mpesa_passkey = 'SUPER_SECRET_PASSKEY_789'
        s.save()
        resp = self.staff.get(reverse('manage_payment_settings'))
        self.assertEqual(resp.status_code, 200)
        for secret in ('SUPER_SECRET_KEY_123', 'SUPER_SECRET_SECRET_456', 'SUPER_SECRET_PASSKEY_789'):
            self.assertNotContains(resp, secret)
        self.assertContains(resp, 'configured')

    def test_save_keeps_existing_secrets_when_blank(self):
        s = SiteSettings.get()
        s.mpesa_consumer_key = 'KEY_A'
        s.mpesa_consumer_secret = 'SECRET_A'
        s.mpesa_passkey = 'PASSKEY_A'
        s.save()
        self.staff.post(reverse('manage_payment_settings'), {
            'mpesa_enabled': 'on', 'mpesa_environment': 'sandbox', 'mpesa_shortcode': '174379',
            'mpesa_callback_url': 'https://example.com/cb/', 'mpesa_account_reference': 'Ref',
            'mpesa_transaction_desc': 'desc', 'inventory_strategy': 'paid',
            'mpesa_consumer_key': '', 'mpesa_consumer_secret': '', 'mpesa_passkey': ''})
        s.refresh_from_db()
        self.assertEqual(s.mpesa_consumer_key, 'KEY_A')
        self.assertEqual(s.mpesa_consumer_secret, 'SECRET_A')
        self.assertEqual(s.mpesa_passkey, 'PASSKEY_A')
        self.assertEqual(s.inventory_strategy, 'paid')

    def test_save_overwrites_secret_with_new_value(self):
        s = SiteSettings.get()
        s.mpesa_consumer_secret = 'SECRET_A'
        s.save()
        self.staff.post(reverse('manage_payment_settings'), {
            'mpesa_environment': 'sandbox', 'mpesa_consumer_key': 'KEY_NEW',
            'mpesa_consumer_secret': 'SECRET_NEW', 'mpesa_passkey': 'PASSKEY_NEW'})
        s.refresh_from_db()
        self.assertEqual(s.mpesa_consumer_key, 'KEY_NEW')
        self.assertEqual(s.mpesa_consumer_secret, 'SECRET_NEW')
        self.assertEqual(s.mpesa_passkey, 'PASSKEY_NEW')
