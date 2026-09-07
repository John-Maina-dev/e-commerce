from decimal import Decimal

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse

from store.models import (InventoryAlert, InventoryChange, Order, OrderItem, Product,
                          SiteSettings)
from store.services import create_order_from_cart, evaluate_product_stock, record_inventory_change
from store.tests.test_models import make_category, make_product


class InventoryModelTests(TestCase):
    def setUp(self):
        s = SiteSettings.get()
        s.restock_lookback_days = 10
        s.restock_lead_time_days = 7
        s.restock_min_sales_orders = 2
        s.save()
        self.product = make_product(price='1000.00', stock=10, desired_stock_level=20)

    def _record_paid_sale(self, quantity, days_ago=0):
        from django.utils import timezone
        from datetime import timedelta
        order = Order.objects.create(
            number=Order.next_number(), customer_name='X', phone='0712',
            total=Decimal(str(quantity * 1000)), status='delivered',
            created_at=timezone.now() - timedelta(days=days_ago))
        OrderItem.objects.create(order=order, product=self.product, product_name=self.product.name,
                                 price=Decimal('1000.00'), quantity=quantity,
                                 subtotal=Decimal(str(quantity * 1000)))

    def test_no_sales_falls_back_to_desired_level(self):
        self.assertIsNone(self.product.sales_based_restock_recommendation)
        self.assertEqual(self.product.restock_recommendation_source, 'desired')
        self.assertEqual(self.product.recommended_restock_qty, 10)

    def test_sparse_sales_does_not_predict(self):
        self._record_paid_sale(2)
        self.assertIsNone(self.product.sales_based_restock_recommendation)
        self.assertEqual(self.product.restock_recommendation_source, 'desired')

    def test_enough_sales_predicts_restock(self):
        self._record_paid_sale(5)
        self._record_paid_sale(5)
        # 10 units / 10 days * 7 lead = 7 projected -> 7 - 3 = 4
        self.product.stock = 3
        self.assertEqual(self.product.sales_based_restock_recommendation, 4)
        self.assertEqual(self.product.restock_recommendation_source, 'sales')
        self.assertEqual(self.product.recommended_restock_qty, 4)


class InventoryAlertServiceTests(TestCase):
    def setUp(self):
        self.product = make_product(price='1000.00', stock=10, low_stock_threshold=5)

    def test_low_stock_creates_alert(self):
        self.product.stock = 3
        evaluate_product_stock(self.product)
        alert = InventoryAlert.objects.get(product=self.product, alert_type=InventoryAlert.TYPE_LOW)
        self.assertFalse(alert.is_resolved)
        self.assertEqual(alert.stock_at_alert, 3)

    def test_out_of_stock_creates_alert(self):
        self.product.stock = 0
        evaluate_product_stock(self.product)
        alert = InventoryAlert.objects.get(product=self.product, alert_type=InventoryAlert.TYPE_OUT)
        self.assertFalse(alert.is_resolved)

    def test_restock_resolves_alert(self):
        self.product.stock = 0
        evaluate_product_stock(self.product)
        self.product.stock = 20
        evaluate_product_stock(self.product)
        self.assertEqual(InventoryAlert.objects.filter(product=self.product, is_resolved=False).count(), 0)

    def test_alerts_are_deduplicated(self):
        self.product.stock = 2
        evaluate_product_stock(self.product)
        evaluate_product_stock(self.product)
        self.assertEqual(InventoryAlert.objects.filter(product=self.product, is_resolved=False).count(), 1)

    def test_out_supersedes_low_alert(self):
        self.product.stock = 2
        evaluate_product_stock(self.product)
        self.product.stock = 0
        evaluate_product_stock(self.product)
        self.assertEqual(InventoryAlert.objects.filter(product=self.product, is_resolved=False).count(), 1)
        self.assertEqual(InventoryAlert.objects.get(product=self.product, is_resolved=False).alert_type,
                         InventoryAlert.TYPE_OUT)

    def test_record_inventory_change(self):
        change = record_inventory_change(self.product, 'restock', old_qty=3, new_qty=15, note='delivery')
        self.assertEqual(change.change, 12)
        self.assertEqual(change.new_qty, 15)

    def test_order_sale_records_change_and_alert(self):
        from django.contrib.auth.models import AnonymousUser
        from django.test import RequestFactory
        from store.tests.test_services import FakeSession
        request = RequestFactory().get('/')
        request.session = FakeSession()
        request.user = AnonymousUser()
        from store.services import add_to_cart, totals_for
        self.product.stock = 6
        self.product.save()
        add_to_cart(request, self.product, 4)
        data = {'customer_name': 'X', 'phone': '0712', 'email': '', 'address_line1': '', 'city': '', 'county': ''}
        create_order_from_cart(request, data, 'cod', totals_for(request))
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 2)
        self.assertTrue(InventoryChange.objects.filter(product=self.product, action='sale').exists())
        self.assertTrue(InventoryAlert.objects.filter(product=self.product, is_resolved=False).exists())

    def test_release_stock_resolves_alert(self):
        from django.contrib.auth.models import AnonymousUser
        from django.test import RequestFactory
        from store.services import release_stock
        from store.tests.test_services import FakeSession
        order = Order.objects.create(
            number=Order.next_number(), customer_name='X', phone='0712', total=Decimal('100.00'),
            stock_deducted=True)
        OrderItem.objects.create(order=order, product=self.product, product_name=self.product.name,
                                 price=Decimal('100.00'), quantity=6, subtotal=Decimal('600.00'))
        self.product.stock = 0
        self.product.save()
        evaluate_product_stock(self.product)
        self.assertTrue(InventoryAlert.objects.filter(product=self.product, is_resolved=False).exists())
        release_stock(order)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 6)
        self.assertEqual(InventoryAlert.objects.filter(product=self.product, is_resolved=False).count(), 0)


class InventoryViewTests(TestCase):
    def setUp(self):
        self.category = make_category()
        self.low = make_product(name='Low Item', category=self.category, sku='LOW-1',
                                price='500.00', stock=2, low_stock_threshold=5)
        self.out = make_product(name='Gone Item', category=self.category, sku='OUT-1',
                                price='500.00', stock=0, low_stock_threshold=5)
        make_product(name='Healthy Item', category=self.category, sku='OK-1',
                     price='500.00', stock=20, low_stock_threshold=5)
        self.staff = Client()
        User.objects.create_superuser(username='admin', email='a@b.com', password='TestPass123!')
        self.staff.login(username='admin', password='TestPass123!')
        evaluate_product_stock(self.low)
        evaluate_product_stock(self.out)

    def test_inventory_page_summary_and_alerts(self):
        resp = self.staff.get(reverse('inventory'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Low Item')
        self.assertContains(resp, 'Gone Item')
        self.assertContains(resp, 'LOW STOCK')
        self.assertContains(resp, 'OUT OF STOCK')
        self.assertContains(resp, 'Total products')
        self.assertContains(resp, '2 products require attention')

    def test_inventory_filter_low_and_out(self):
        resp = self.staff.get(reverse('inventory'), {'status': 'low'})
        self.assertContains(resp, 'row-warn')
        self.assertNotContains(resp, 'row-danger')
        self.assertNotContains(resp, 'Healthy Item')
        resp = self.staff.get(reverse('inventory'), {'status': 'out'})
        self.assertContains(resp, 'row-danger')
        self.assertNotContains(resp, 'row-warn')
        self.assertNotContains(resp, 'Healthy Item')
        resp = self.staff.get(reverse('inventory'), {'status': 'healthy'})
        self.assertContains(resp, 'Healthy Item')
        self.assertNotContains(resp, 'row-warn')
        self.assertNotContains(resp, 'row-danger')

    def test_inventory_sort_by_stock(self):
        resp = self.staff.get(reverse('inventory'), {'sort': 'stock'})
        content = resp.content.decode()
        self.assertLess(content.index('Gone Item'), content.index('Low Item'))

    def test_inventory_update_records_history_and_restocks(self):
        resp = self.staff.post(reverse('inventory_update'), {
            'product_id': self.low.pk, 'stock': 20, 'low_stock_threshold': 5, 'desired_stock_level': 30})
        self.assertEqual(resp.status_code, 302)
        self.low.refresh_from_db()
        self.assertEqual(self.low.stock, 20)
        self.assertEqual(self.low.desired_stock_level, 30)
        self.assertTrue(InventoryChange.objects.filter(product=self.low, action='restock').exists())
        self.assertTrue(InventoryChange.objects.filter(product=self.low, action='desired').exists())
        self.assertEqual(InventoryAlert.objects.filter(product=self.low, is_resolved=False).count(), 0)

    def test_inventory_update_rejects_negative(self):
        resp = self.staff.post(reverse('inventory_update'), {
            'product_id': self.low.pk, 'stock': -5, 'low_stock_threshold': 5, 'desired_stock_level': 10})
        self.assertRedirects(resp, reverse('inventory'))
        self.low.refresh_from_db()
        self.assertEqual(self.low.stock, 2)

    def test_inventory_history_page(self):
        record_inventory_change(self.low, 'restock', old_qty=2, new_qty=12, user=User.objects.get(username='admin'))
        resp = self.staff.get(reverse('inventory_history'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Low Item')
        resp = self.staff.get(reverse('inventory_history'), {'action': 'restock'})
        self.assertContains(resp, 'Low Item')

    def test_inventory_alert_resolve(self):
        alert = InventoryAlert.objects.get(product=self.low, is_resolved=False)
        resp = self.staff.post(reverse('inventory_alert_resolve', args=[alert.pk]))
        self.assertRedirects(resp, reverse('inventory'))
        alert.refresh_from_db()
        self.assertTrue(alert.is_resolved)
        self.assertIsNotNone(alert.resolved_at)

    def test_dashboard_shows_alert_count(self):
        resp = self.staff.get(reverse('dashboard'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Open alerts')
        self.assertContains(resp, 'LOW STOCK')

    def test_products_page_marks_alerted_products(self):
        resp = self.staff.get(reverse('manage_products'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, '⚠ Alert')
