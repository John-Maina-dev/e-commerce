from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase

from store.models import Category, Coupon, Order, OrderStatusHistory, Product, SiteSettings


def make_category(name='Dresses'):
    return Category.objects.create(name=name)


def make_product(name='Summer Dress', category=None, price='2500.00', stock=10, **kwargs):
    cat = category or make_category()
    return Product.objects.create(name=name, category=cat, price=Decimal(price), stock=stock, **kwargs)


class CategoryModelTests(TestCase):
    def test_slug_auto_generated(self):
        cat = make_category('Party Wear')
        self.assertEqual(cat.slug, 'party-wear')


class ProductModelTests(TestCase):
    def setUp(self):
        self.product = make_product(sku='SKU-1')

    def test_effective_price_uses_sale_price(self):
        self.product.sale_price = Decimal('1900.00')
        self.assertEqual(self.product.effective_price, Decimal('1900.00'))
        self.assertTrue(self.product.has_discount)
        self.assertEqual(self.product.discount_percent, 24)

    def test_stock_status_healthy_low_out(self):
        self.assertEqual(self.product.stock_status, Product.STATUS_HEALTHY)
        self.product.stock = 3
        self.assertEqual(self.product.stock_status, Product.STATUS_LOW)
        self.assertTrue(self.product.low_stock)
        self.product.stock = 0
        self.assertEqual(self.product.stock_status, Product.STATUS_OUT)
        self.assertTrue(self.product.out_of_stock)
        self.assertTrue(self.product.needs_restock)

    def test_recommended_restock_qty(self):
        self.product.desired_stock_level = 20
        self.product.stock = 7
        self.assertEqual(self.product.recommended_restock_qty, 13)

    def test_slug_auto_generated(self):
        self.assertEqual(self.product.slug, 'summer-dress')


class CouponModelTests(TestCase):
    def setUp(self):
        self.coupon = Coupon.objects.create(code='SAVE10', discount_type='percent', value=Decimal('10.00'))

    def test_percent_discount(self):
        self.assertEqual(self.coupon.discount_for(Decimal('1000.00')), Decimal('100.00'))

    def test_fixed_discount_capped_at_subtotal(self):
        self.coupon.discount_type = 'fixed'
        self.coupon.value = Decimal('5000.00')
        self.assertEqual(self.coupon.discount_for(Decimal('1000.00')), Decimal('1000.00'))

    def test_is_valid_checks_active_and_uses(self):
        self.assertTrue(self.coupon.is_valid)
        self.coupon.active = False
        self.assertFalse(self.coupon.is_valid)
        self.coupon.active = True
        self.coupon.max_uses = 1
        self.coupon.used_count = 1
        self.assertFalse(self.coupon.is_valid)


class SiteSettingsModelTests(TestCase):
    def test_get_creates_singleton(self):
        s1 = SiteSettings.get()
        s2 = SiteSettings.get()
        self.assertEqual(s1.pk, s2.pk)

    def test_shipping_for(self):
        s = SiteSettings.get()
        s.shipping_enabled = True
        s.flat_rate = Decimal('150.00')
        s.free_shipping_threshold = Decimal('5000.00')
        self.assertEqual(s.shipping_for(Decimal('1000.00')), Decimal('150.00'))
        self.assertEqual(s.shipping_for(Decimal('6000.00')), Decimal('0.00'))

    def test_shipping_disabled(self):
        s = SiteSettings.get()
        s.shipping_enabled = False
        self.assertEqual(s.shipping_for(Decimal('1.00')), Decimal('0.00'))

    def test_tax_for(self):
        s = SiteSettings.get()
        s.tax_enabled = True
        s.tax_rate = Decimal('16.00')
        self.assertEqual(s.tax_for(Decimal('1000.00')), Decimal('160.00'))


class OrderModelTests(TestCase):
    def test_next_number_format(self):
        number = Order.next_number()
        self.assertTrue(number.startswith('RB-'))
        self.assertEqual(len(number.split('-')), 3)

    def test_record_status_creates_history(self):
        order = Order.objects.create(
            number=Order.next_number(), customer_name='Test', phone='0712345678', total=Decimal('100.00'))
        order.record_status('confirmed', note='paid')
        order.refresh_from_db()
        self.assertEqual(order.status, 'confirmed')
        self.assertEqual(OrderStatusHistory.objects.filter(order=order).count(), 1)
        self.assertEqual(order.status_history.first().note, 'paid')
