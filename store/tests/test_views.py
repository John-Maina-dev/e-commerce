import json
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse

from store.models import MpesaTransaction, Order, Payment, Product, Review, SiteSettings, WishlistItem
from store.tests.test_models import make_category, make_product


class StorefrontViewTests(TestCase):
    def setUp(self):
        self.category = make_category()
        self.product = make_product(name='Silk Dress', category=self.category,
                                    sku='V-1', price='2400.00', stock=8, is_bestseller=True)
        self.client = Client()

    def test_home_renders(self):
        resp = self.client.get(reverse('home'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Silk Dress')

    def test_catalogue_lists_active_products(self):
        make_product(name='Hidden Item', category=self.category, sku='V-2', active=False)
        resp = self.client.get(reverse('catalogue'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Silk Dress')
        self.assertNotContains(resp, 'Hidden Item')

    def test_catalogue_search_and_category_filter(self):
        resp = self.client.get(reverse('catalogue'), {'q': 'silk'})
        self.assertContains(resp, 'Silk Dress')
        resp = self.client.get(reverse('catalogue'), {'category': self.category.slug})
        self.assertEqual(resp.status_code, 200)

    def test_catalogue_shows_out_of_stock_products(self):
        make_product(name='Sold Out', category=self.category, sku='V-3', stock=0)
        resp = self.client.get(reverse('catalogue'), {'in_stock': '1'})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Silk Dress')
        self.assertContains(resp, 'Sold Out')

    def test_catalogue_ignores_legacy_filter_params(self):
        out = make_product(name='Filtered Away', category=self.category, sku='V-4', brand='NoSuchBrand')
        resp = self.client.get(reverse('catalogue'), {'brand': 'NoSuchBrand', 'min_price': '999999', 'in_stock': '1'})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Filtered Away')

    def test_product_detail(self):
        resp = self.client.get(reverse('product_detail', args=[self.product.slug]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Silk Dress')
        self.assertContains(resp, self.product.sku)

    def test_product_detail_404_for_inactive(self):
        self.product.active = False
        self.product.save()
        resp = self.client.get(reverse('product_detail', args=[self.product.slug]))
        self.assertEqual(resp.status_code, 404)

    def test_contact_form_submission(self):
        resp = self.client.post(reverse('contact'), {
            'name': 'Sam', 'email': 'sam@example.com', 'subject': 'Hi', 'message': 'Hello store!'})
        self.assertRedirects(resp, reverse('contact'))
        from store.models import ContactMessage
        self.assertTrue(ContactMessage.objects.filter(email='sam@example.com').exists())

    def test_newsletter_subscribe(self):
        resp = self.client.post(reverse('newsletter'), {'email': 'n@example.com'})
        self.assertRedirects(resp, reverse('home'))
        from store.models import NewsletterSubscriber
        self.assertTrue(NewsletterSubscriber.objects.filter(email='n@example.com').exists())


class CartViewTests(TestCase):
    def setUp(self):
        self.product = make_product(price='1000.00', stock=5)
        self.client = Client()

    def test_add_to_cart_and_view(self):
        resp = self.client.post(reverse('cart_add', args=[self.product.id]), {'quantity': 2})
        self.assertRedirects(resp, reverse('cart'))
        resp = self.client.get(reverse('cart'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, '2,000')

    def test_add_more_than_stock_is_rejected(self):
        self.client.post(reverse('cart_add', args=[self.product.id]), {'quantity': 99})
        resp = self.client.get(reverse('cart'))
        self.assertContains(resp, 'Only 5 units of Summer Dress are available.')
        self.assertContains(resp, 'Your cart is empty')

    def test_cart_update_and_remove(self):
        self.client.post(reverse('cart_add', args=[self.product.id]), {'quantity': 2})
        self.client.post(reverse('cart_update', args=[self.product.id]), {'quantity': 1})
        self.client.post(reverse('cart_remove', args=[self.product.id]))
        resp = self.client.get(reverse('cart'))
        self.assertContains(resp, 'Your cart is empty')


class CouponViewTests(TestCase):
    def setUp(self):
        self.product = make_product(price='1000.00', stock=5)
        self.client = Client()
        from store.models import Coupon
        self.coupon = Coupon.objects.create(code='SAVE10', discount_type='percent', value=Decimal('10.00'))
        self.client.post(reverse('cart_add', args=[self.product.id]), {'quantity': 2})

    def test_apply_coupon(self):
        resp = self.client.post(reverse('cart_apply_coupon'), {'code': 'save10'})
        self.assertRedirects(resp, reverse('cart'))
        resp = self.client.get(reverse('cart'))
        self.assertContains(resp, 'SAVE10')

    def test_apply_invalid_coupon(self):
        resp = self.client.post(reverse('cart_apply_coupon'), {'code': 'NOPE'})
        self.assertRedirects(resp, reverse('cart'))


class CheckoutViewTests(TestCase):
    def setUp(self):
        self.product = make_product(price='1000.00', stock=5)
        self.client = Client()
        self.client.post(reverse('cart_add', args=[self.product.id]), {'quantity': 2})
        self.post_data = {
            'customer_name': 'Jane Doe',
            'phone': '0712345678',
            'email': 'jane@example.com',
            'address_line1': '1 Main St',
            'city': 'Nairobi',
            'county': 'Nairobi',
            'payment_method': 'cod',
        }

    def test_checkout_get_renders(self):
        resp = self.client.get(reverse('checkout'))
        self.assertEqual(resp.status_code, 200)

    def test_checkout_get_redirects_when_cart_empty(self):
        self.client.post(reverse('cart_remove', args=[self.product.id]))
        resp = self.client.get(reverse('checkout'))
        self.assertRedirects(resp, reverse('cart'))

    def test_checkout_requires_name_and_phone(self):
        data = dict(self.post_data)
        del data['phone']
        resp = self.client.post(reverse('checkout'), data)
        self.assertRedirects(resp, reverse('checkout'))

    def test_checkout_creates_order(self):
        resp = self.client.post(reverse('checkout'), self.post_data)
        order = Order.objects.get()
        self.assertEqual(order.customer_name, 'Jane Doe')
        self.assertEqual(order.total, Decimal('2150.00'))
        self.assertEqual(order.payment_method, 'cod')
        self.assertRedirects(resp, reverse('order_detail', args=[order.number]))
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 3)

    def test_guest_can_view_order_via_session(self):
        resp = self.client.post(reverse('checkout'), self.post_data)
        order = Order.objects.get()
        resp = self.client.get(reverse('order_detail', args=[order.number]))
        self.assertEqual(resp.status_code, 200)


class AccountViewTests(TestCase):
    def setUp(self):
        self.client = Client()

    def test_register_creates_user_and_logs_in(self):
        resp = self.client.post(reverse('register'), {
            'username': 'jane',
            'first_name': 'Jane',
            'last_name': 'Doe',
            'email': 'jane@example.com',
            'password1': 'TestPass123!',
            'password2': 'TestPass123!',
        })
        self.assertTrue(User.objects.filter(username='jane').exists())
        self.assertRedirects(resp, reverse('account'))

    def test_login_and_account(self):
        user = User.objects.create_user(username='jane', password='TestPass123!')
        resp = self.client.post(reverse('login'), {'username': 'jane', 'password': 'TestPass123!'})
        self.assertRedirects(resp, reverse('account'))
        resp = self.client.get(reverse('account'))
        self.assertEqual(resp.status_code, 200)

    def test_account_requires_login(self):
        resp = self.client.get(reverse('account'))
        self.assertEqual(resp.status_code, 302)

    def test_wishlist_requires_login(self):
        resp = self.client.get(reverse('wishlist'))
        self.assertEqual(resp.status_code, 302)

    def test_wishlist_toggle(self):
        product = make_product(price='100.00', stock=2)
        User.objects.create_user(username='jane', password='TestPass123!')
        self.client.login(username='jane', password='TestPass123!')
        resp = self.client.post(reverse('wishlist_toggle', args=[product.id]))
        self.assertTrue(WishlistItem.objects.filter(user__username='jane', product=product).exists())
        resp = self.client.post(reverse('wishlist_toggle', args=[product.id]))
        self.assertFalse(WishlistItem.objects.filter(user__username='jane', product=product).exists())

    def test_address_crud(self):
        user = User.objects.create_user(username='jane', password='TestPass123!')
        self.client.login(username='jane', password='TestPass123!')
        resp = self.client.post(reverse('address_add'), {
            'full_name': 'Jane Doe', 'phone': '0712345678', 'line1': '1 Main St',
            'city': 'Nairobi', 'county': 'Nairobi', 'postal_code': '', 'is_default': 'on'})
        self.assertRedirects(resp, reverse('account_addresses'))
        from store.models import Address
        addr = Address.objects.get(user=user)
        self.assertTrue(addr.is_default)


class ManageViewTests(TestCase):
    def setUp(self):
        self.product = make_product(price='100.00', stock=2)
        self.anon = Client()
        self.staff = Client()
        self.user = User.objects.create_superuser(username='admin', email='a@b.com', password='TestPass123!')
        self.staff.login(username='admin', password='TestPass123!')

    def test_manage_requires_staff(self):
        for url in ('dashboard', 'manage_products', 'inventory', 'manage_orders', 'manage_settings'):
            resp = self.anon.get(reverse(url))
            self.assertEqual(resp.status_code, 302)

    def test_dashboard_for_staff(self):
        resp = self.staff.get(reverse('dashboard'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Store overview')

    def test_manage_products_lists(self):
        resp = self.staff.get(reverse('manage_products'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, self.product.name)

    def test_inventory_page(self):
        resp = self.staff.get(reverse('inventory'))
        self.assertEqual(resp.status_code, 200)

    def test_analytics_page(self):
        resp = self.staff.get(reverse('manage_analytics'))
        self.assertEqual(resp.status_code, 200)

    def test_system_health_page(self):
        resp = self.staff.get(reverse('system_health'))
        self.assertEqual(resp.status_code, 200)

    def test_manage_order_detail_renders_mpesa_badge(self):
        order = Order.objects.create(
            number=Order.next_number(), customer_name='X', phone='0712', total=Decimal('100.00'))
        MpesaTransaction.objects.create(
            transaction_id='tx-1', order=order, phone='254712345678', amount=Decimal('100.00'),
            checkout_request_id='req-1', status='completed', mpesa_receipt='PJX123ABC')
        resp = self.staff.get(reverse('manage_order_detail', args=[order.number]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'PJX123ABC')

    def test_order_status_update_releases_stock_on_cancel(self):
        order = Order.objects.create(
            number=Order.next_number(), customer_name='X', phone='0712',
            total=Decimal('100.00'), status='confirmed', payment_status='success',
            stock_deducted=True)
        from store.services import release_stock
        # stock already deducted at order time; simulate
        self.product.stock = 0
        self.product.save()
        from store.models import OrderItem
        OrderItem.objects.create(order=order, product=self.product, product_name=self.product.name,
                                 price=Decimal('100.00'), quantity=2, subtotal=Decimal('200.00'))
        resp = self.staff.post(reverse('order_status_update', args=[order.number]), {'status': 'cancelled'})
        self.assertRedirects(resp, reverse('manage_order_detail', args=[order.number]))
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 2)


class ProductControlTests(TestCase):
    def setUp(self):
        self.category = make_category('Shoes')
        self.product = make_product(name='Leather Boots', category=self.category, sku='BOOT-1', price='12000.00', stock=4)
        self.anon = Client()
        self.staff = Client()
        self.user = User.objects.create_superuser(username='admin2', email='a@c.com', password='TestPass123!')
        self.staff.login(username='admin2', password='TestPass123!')

    def test_manage_products_lists_product(self):
        resp = self.staff.get(reverse('manage_products'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Leather Boots')

    def test_product_form_pages_render(self):
        resp = self.staff.get(reverse('product_add'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'name="image"')
        resp = self.staff.get(reverse('product_edit', args=[self.product.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Leather Boots')

    def test_manage_products_filters_by_category(self):
        other = make_product(name='Cotton Tee', category=make_category('Tops'))
        resp = self.staff.get(reverse('manage_products'), {'category': self.category.slug})
        self.assertContains(resp, 'Leather Boots')
        self.assertNotContains(resp, 'Cotton Tee')

    def test_manage_products_sorts_by_price(self):
        make_product(name='Cheap Sock', category=self.category, price='200.00', stock=2)
        resp = self.staff.get(reverse('manage_products'), {'sort': 'price'})
        content = resp.content.decode()
        self.assertLess(content.index('Cheap Sock'), content.index('Leather Boots'))

    def test_manage_products_hides_archived_by_default(self):
        self.product.is_archived = True
        self.product.save()
        resp = self.staff.get(reverse('manage_products'))
        self.assertNotContains(resp, 'Leather Boots')
        resp = self.staff.get(reverse('manage_products'), {'status': 'archived'})
        self.assertContains(resp, 'Leather Boots')

    def test_manage_products_requires_staff(self):
        self.assertEqual(self.anon.get(reverse('manage_products')).status_code, 302)

    def _action(self, action, pk=None, as_anon=False):
        client = self.anon if as_anon else self.staff
        return client.post(reverse('product_action', args=[pk or self.product.pk]), {'action': action})

    def test_action_hide_and_unhide(self):
        self._action('hide')
        self.product.refresh_from_db()
        self.assertTrue(self.product.hidden)
        self.assertFalse(self.product.is_visible)
        self._action('unhide')
        self.product.refresh_from_db()
        self.assertFalse(self.product.hidden)

    def test_action_activate_and_deactivate(self):
        self._action('deactivate')
        self.product.refresh_from_db()
        self.assertFalse(self.product.active)
        self._action('activate')
        self.product.refresh_from_db()
        self.assertTrue(self.product.active)

    def test_action_archive_and_restore(self):
        self._action('archive')
        self.product.refresh_from_db()
        self.assertTrue(self.product.is_archived)
        self._action('restore')
        self.product.refresh_from_db()
        self.assertFalse(self.product.is_archived)

    def test_action_requires_staff_and_post(self):
        self.assertEqual(self._action('hide', as_anon=True).status_code, 302)
        self.assertEqual(self.staff.get(reverse('product_action', args=[self.product.pk])).status_code, 400)

    def test_bulk_action_hide_and_archive(self):
        other = make_product(name='Slippers', category=self.category, sku='SLIP-1', price='800.00', stock=3)
        resp = self.staff.post(reverse('product_bulk_action'), {
            'bulk_action': 'hide', 'selected': [self.product.pk, other.pk]})
        self.assertRedirects(resp, reverse('manage_products'))
        self.product.refresh_from_db()
        other.refresh_from_db()
        self.assertTrue(self.product.hidden and other.hidden)
        resp = self.staff.post(reverse('product_bulk_action'), {
            'bulk_action': 'archive', 'selected': [other.pk]})
        other.refresh_from_db()
        self.assertTrue(other.is_archived)

    def test_bulk_delete_keeps_products_with_order_history(self):
        from store.models import OrderItem
        other = make_product(name='Keep Me', category=self.category, sku='KEEP-1', price='500.00', stock=3)
        order = Order.objects.create(number=Order.next_number(), customer_name='X', phone='0712', total=Decimal('500.00'))
        OrderItem.objects.create(order=order, product=other, product_name=other.name,
                                 price=Decimal('500.00'), quantity=1, subtotal=Decimal('500.00'))
        self.staff.post(reverse('product_bulk_action'), {
            'bulk_action': 'delete', 'selected': [self.product.pk, other.pk]})
        self.assertFalse(Product.objects.filter(pk=self.product.pk).exists())
        self.assertTrue(Product.objects.filter(pk=other.pk).exists())

    def test_delete_blocked_when_product_has_order_history(self):
        from store.models import OrderItem
        order = Order.objects.create(number=Order.next_number(), customer_name='X', phone='0712', total=Decimal('12000.00'))
        OrderItem.objects.create(order=order, product=self.product, product_name=self.product.name,
                                 price=Decimal('12000.00'), quantity=1, subtotal=Decimal('12000.00'))
        self.staff.post(reverse('product_delete', args=[self.product.pk]))
        self.assertTrue(Product.objects.filter(pk=self.product.pk).exists())

    def test_hidden_and_archived_are_not_on_storefront(self):
        for flag in ('hidden', 'is_archived'):
            self.product.__dict__[flag] = True
            self.product.save()
            resp = self.client.get(reverse('catalogue'))
            self.assertNotContains(resp, 'Leather Boots')
            self.assertEqual(self.client.get(reverse('product_detail', args=[self.product.slug])).status_code, 404)
            self.product.__dict__[flag] = False
            self.product.save()

    def test_new_product_is_live_searchable_and_in_category(self):
        from io import BytesIO

        from PIL import Image
        from django.core.files.uploadedfile import SimpleUploadedFile

        buf = BytesIO()
        Image.new('RGB', (8, 8), color='blue').save(buf, format='PNG')
        image = SimpleUploadedFile('gown.png', buf.getvalue(), content_type='image/png')
        resp = self.staff.post(reverse('product_add'), {
            'name': 'Elegant Gown', 'sku': 'GOWN-1', 'category': make_category('Gowns').pk,
            'price': '7500.00', 'stock': 5, 'active': 'on', 'image': image})
        self.assertRedirects(resp, reverse('manage_products'))
        product = Product.objects.get(sku='GOWN-1')
        self.assertTrue(product.is_visible)
        resp = self.client.get(reverse('catalogue'), {'q': 'Elegant'})
        self.assertContains(resp, 'Elegant Gown')
        resp = self.client.get(reverse('catalogue'), {'category': product.category.slug})
        self.assertContains(resp, 'Elegant Gown')
        self.assertEqual(self.client.get(reverse('product_detail', args=[product.slug])).status_code, 200)

    def test_product_without_image_is_rejected(self):
        resp = self.staff.post(reverse('product_add'), {
            'name': 'No Photo Dress', 'sku': 'NOIMG-1',
            'category': make_category('Dresses').pk,
            'price': '2500.00', 'stock': 3, 'active': 'on'})
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Product.objects.filter(sku='NOIMG-1').exists())
        form = resp.context['form']
        self.assertIn('image', form.errors)

    def test_product_form_rejects_invalid_pricing(self):
        from store.forms import ProductForm
        form = ProductForm(data={'name': 'Bad Price', 'sku': 'BAD-1', 'category': self.category.pk,
                                 'price': '100.00', 'sale_price': '150.00'})
        self.assertFalse(form.is_valid())
        self.assertIn('sale_price', form.errors)


class MpesaCallbackViewTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.product = make_product(price='1000.00', stock=5)
        self.order = Order.objects.create(
            number=Order.next_number(), customer_name='Jane', phone='0712345678',
            total=Decimal('2150.00'), payment_status='pending', payment_method='mpesa')
        self.tx = MpesaTransaction.objects.create(
            transaction_id='tx-1', order=self.order, phone='254712345678',
            amount=Decimal('2150.00'), checkout_request_id='req-1', status='sent')

    def _callback_body(self, result_code='0'):
        return json.dumps({'Body': {'stkCallback': {
            'CheckoutRequestID': 'req-1',
            'ResultCode': result_code,
            'ResultDesc': 'The service request is processed successfully.',
            'CallbackMetadata': {'Item': [
                {'Name': 'MpesaReceiptNumber', 'Value': 'PJX123ABC'},
                {'Name': 'PhoneNumber', 'Value': 254712345678},
                {'Name': 'Amount', 'Value': 2150},
            ]},
        }}})

    def test_success_callback_updates_order(self):
        resp = self.client.post(reverse('mpesa_callback'), self._callback_body(), content_type='application/json')
        self.assertEqual(resp.status_code, 200)
        self.order.refresh_from_db()
        self.assertEqual(self.order.payment_status, 'paid')
        self.assertEqual(self.order.status, 'confirmed')
        self.tx.refresh_from_db()
        self.assertEqual(self.tx.status, 'completed')
        self.assertEqual(self.tx.mpesa_receipt, 'PJX123ABC')

    def test_success_callback_records_gateway_verified_payment(self):
        self.client.post(reverse('mpesa_callback'), self._callback_body(), content_type='application/json')
        payment = Payment.objects.get(order=self.order)
        self.assertEqual(payment.status, 'paid')
        self.assertEqual(payment.verification, 'gateway')
        self.assertEqual(payment.reference, 'PJX123ABC')
        self.assertEqual(payment.method, 'mpesa')

    def test_callback_is_idempotent(self):
        self.client.post(reverse('mpesa_callback'), self._callback_body(), content_type='application/json')
        self.client.post(reverse('mpesa_callback'), self._callback_body(), content_type='application/json')
        self.assertEqual(Payment.objects.filter(order=self.order).count(), 1)

    def test_failure_callback_marks_payment_failed(self):
        body = self._callback_body(result_code='1')
        resp = self.client.post(reverse('mpesa_callback'), body, content_type='application/json')
        self.order.refresh_from_db()
        self.assertEqual(self.order.payment_status, 'failed')
        self.tx.refresh_from_db()
        self.assertEqual(self.tx.status, 'failed')

    def test_cancel_callback_marks_payment_cancelled(self):
        body = self._callback_body(result_code='1032')
        self.client.post(reverse('mpesa_callback'), body, content_type='application/json')
        self.order.refresh_from_db()
        self.assertEqual(self.order.payment_status, 'cancelled')
        self.assertEqual(self.order.status, 'cancelled')
        payment = Payment.objects.get(order=self.order)
        self.assertEqual(payment.status, 'cancelled')

    def test_amount_mismatch_callback_requires_review(self):
        body = json.dumps({'Body': {'stkCallback': {
            'CheckoutRequestID': 'req-1',
            'ResultCode': '0',
            'ResultDesc': 'The service request is processed successfully.',
            'CallbackMetadata': {'Item': [
                {'Name': 'MpesaReceiptNumber', 'Value': 'PJX123ABC'},
                {'Name': 'Amount', 'Value': 1},
            ]},
        }}})
        self.client.post(reverse('mpesa_callback'), body, content_type='application/json')
        self.order.refresh_from_db()
        self.assertEqual(self.order.payment_status, 'requires_review')
        self.assertEqual(self.order.status, 'pending')
        self.tx.refresh_from_db()
        self.assertEqual(self.tx.status, 'completed')
