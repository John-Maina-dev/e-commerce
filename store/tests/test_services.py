from decimal import Decimal

from django.contrib.auth.models import AnonymousUser, User
from django.test import TestCase, RequestFactory

from store.models import Coupon, Order, OrderItem, Product, SiteSettings
from store.services import (
    add_to_cart, cart_count, cart_items, cart_subtotal, clear_cart, create_order_from_cart,
    get_cart, release_stock, set_cart_qty, totals_for, validate_coupon,
)
from store.tests.test_models import make_product


class FakeSession(dict):
    modified = False


class CartServiceTests(TestCase):
    def setUp(self):
        self.request = RequestFactory().get('/')
        self.request.session = FakeSession()
        self.request.user = AnonymousUser()
        self.product = make_product(price='1000.00', stock=5)

    def test_add_and_count(self):
        add_to_cart(self.request, self.product, 2)
        self.assertEqual(cart_count(self.request), 2)
        self.assertEqual(len(cart_items(self.request)), 1)

    def test_add_capped_at_stock(self):
        add_to_cart(self.request, self.product, 99)
        self.assertEqual(cart_count(self.request), 5)

    def test_add_zero_stock_does_not_add(self):
        self.product.stock = 0
        self.product.save()
        add_to_cart(self.request, self.product, 1)
        self.assertEqual(cart_count(self.request), 0)

    def test_set_cart_qty(self):
        add_to_cart(self.request, self.product, 2)
        set_cart_qty(self.request, self.product, 4)
        self.assertEqual(cart_count(self.request), 4)

    def test_cart_subtotal(self):
        add_to_cart(self.request, self.product, 3)
        items = cart_items(self.request)
        self.assertEqual(cart_subtotal(items), Decimal('3000.00'))

    def test_clear_cart(self):
        add_to_cart(self.request, self.product, 1)
        clear_cart(self.request)
        self.assertEqual(get_cart(self.request), {})


class CouponServiceTests(TestCase):
    def setUp(self):
        self.request = RequestFactory().get('/')
        self.request.session = FakeSession()
        self.request.user = AnonymousUser()
        self.product = make_product(price='1000.00', stock=5)
        add_to_cart(self.request, self.product, 3)
        self.coupon = Coupon.objects.create(code='SAVE10', discount_type='percent', value=Decimal('10.00'))

    def test_validate_coupon(self):
        coupon, err = validate_coupon(self.request, 'SAVE10')
        self.assertIsNotNone(coupon)
        self.assertIsNone(err)

    def test_validate_invalid_code(self):
        coupon, err = validate_coupon(self.request, 'NOPE')
        self.assertIsNone(coupon)
        self.assertIn('Invalid', err)

    def test_totals_include_discount_and_shipping(self):
        totals = totals_for(self.request, self.coupon)
        self.assertEqual(totals['subtotal'], Decimal('3000.00'))
        self.assertEqual(totals['discount'], Decimal('300.00'))
        self.assertEqual(totals['shipping'], Decimal('150.00'))
        self.assertEqual(totals['total'], Decimal('2850.00'))


class OrderServiceTests(TestCase):
    def setUp(self):
        self.request = RequestFactory().get('/')
        self.request.session = FakeSession()
        self.request.user = AnonymousUser()
        self.product = make_product(price='1000.00', stock=5)
        add_to_cart(self.request, self.product, 2)
        self.data = {
            'customer_name': 'Jane Doe',
            'phone': '0712345678',
            'email': 'jane@example.com',
            'address_line1': '1 Main St',
            'city': 'Nairobi',
            'county': 'Nairobi',
        }

    def _create(self):
        totals = totals_for(self.request)
        return create_order_from_cart(self.request, self.data, 'cod', totals)

    def test_create_order_deducts_stock_and_clears_cart(self):
        order = self._create()
        self.assertEqual(order.customer_name, 'Jane Doe')
        self.assertEqual(order.total, Decimal('2150.00'))
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 3)
        self.assertEqual(cart_count(self.request), 0)
        self.assertEqual(OrderItem.objects.filter(order=order).count(), 1)

    def test_create_order_raises_when_insufficient_stock(self):
        from unittest import mock
        from django.db import transaction
        overstock = [{'product': self.product, 'quantity': 10, 'line': Decimal('10000.00')}]
        with mock.patch('store.services.cart_items', return_value=overstock):
            totals = totals_for(self.request)
            with self.assertRaises(ValueError):
                with transaction.atomic():
                    create_order_from_cart(self.request, self.data, 'cod', totals)

    def test_release_stock_once(self):
        order = self._create()
        order.status = 'cancelled'
        order.save()
        self.assertEqual(release_stock(order), 2)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 5)
        self.assertTrue(order.stock_released)
        self.assertEqual(release_stock(order), 0)

    def test_coupon_usage_recorded(self):
        coupon = Coupon.objects.create(code='SAVE10', discount_type='percent', value=Decimal('10.00'))
        totals = totals_for(self.request, coupon)
        order = create_order_from_cart(self.request, self.data, 'cod', totals)
        self.assertEqual(order.coupon, coupon)
        self.assertEqual(order.discount, Decimal('200.00'))
        coupon.refresh_from_db()
        self.assertEqual(coupon.used_count, 1)
