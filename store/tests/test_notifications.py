import json
from decimal import Decimal
from unittest import mock

from django.contrib.auth.models import AnonymousUser, User
from django.test import Client, RequestFactory, TestCase, override_settings
from django.urls import reverse

from store import notify
from store.models import (MpesaTransaction, Notification, Order, OrderItem, Payment,
                          Product, SiteSettings)
from store.services import evaluate_product_stock, mark_order_paid
from store.tests.test_models import make_category, make_product


class NotificationModelTests(TestCase):
    def test_create_with_full_fields(self):
        user = User.objects.create_user(username='bob', email='bob@example.com', password='pw-123456')
        n = Notification.create('Hello', 'World', user=user, category='account', link='/account/')
        self.assertEqual(n.user, user)
        self.assertEqual(n.category, 'account')
        self.assertEqual(n.link, '/account/')
        self.assertTrue(n.for_staff)
        self.assertFalse(n.read)

    def test_defaults_to_staff(self):
        n = Notification.create('Staff only')
        self.assertTrue(n.for_staff)
        self.assertIsNone(n.user)

    def test_ordering_newest_first(self):
        Notification.create('one')
        Notification.create('two')
        self.assertEqual(list(Notification.objects.values_list('title', flat=True)), ['two', 'one'])


class NotifyServiceTests(TestCase):
    def test_notify_staff(self):
        n = notify.notify_staff('Title', 'Body', category='order', link='/manage/')
        self.assertTrue(n.for_staff)
        self.assertEqual(n.category, 'order')
        self.assertEqual(n.link, '/manage/')

    def test_notify_user_skips_anonymous(self):
        self.assertIsNone(notify.notify_user(AnonymousUser(), 'X'))
        self.assertIsNone(notify.notify_user(None, 'X'))

    def test_notify_user_creates_inbox_entry(self):
        user = User.objects.create_user(username='bob', email='bob@example.com', password='pw-123456')
        n = notify.notify_user(user, 'X', category='order', link='/orders/')
        self.assertFalse(n.for_staff)
        self.assertEqual(n.user, user)

    def test_staff_email_skipped_when_unconfigured(self):
        s = SiteSettings.get()
        s.staff_notifications_email = ''
        s.save()
        self.assertFalse(notify._staff_email('T', 'M'))

    def test_staff_email_sent_when_configured(self):
        s = SiteSettings.get()
        s.staff_notifications_email = 'admin@example.com'
        s.save()
        with mock.patch('store.emails.staff_notification', return_value=True) as send:
            self.assertTrue(notify._staff_email('T', 'M', '/manage/'))
        send.assert_called_once()
        self.assertEqual(send.call_args[0][0], 'admin@example.com')

    def test_system_error_deduplicates(self):
        with override_settings(DEBUG=False):
            a = notify.system_error('Server error: ValueError', 'boom')
            b = notify.system_error('Server error: ValueError', 'boom')
        self.assertIsNotNone(a)
        self.assertIsNone(b)
        self.assertEqual(Notification.objects.filter(category='system').count(), 1)


class OrderEventTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username='jane', email='jane@example.com', password='pw-123456')
        self.product = make_product(price='1000.00', stock=10)
        self.client.login(username='jane', password='pw-123456')

    def _checkout(self):
        self.client.post(reverse('cart_add', args=[self.product.pk]), {'quantity': 2})
        resp = self.client.post(reverse('checkout'), {
            'customer_name': 'Jane Doe', 'phone': '0712345678', 'email': 'jane@example.com',
            'address_line1': '1 Main St', 'city': 'Nairobi', 'county': 'Nairobi',
            'payment_method': 'cod'}, follow=True)
        self.assertEqual(resp.status_code, 200)
        return Order.objects.latest('id')

    def test_order_placed_notifies_staff_and_customer(self):
        with mock.patch('store.emails.order_confirmation') as email:
            order = self._checkout()
        self.assertTrue(Notification.objects.filter(
            for_staff=True, category='order', title__contains=order.number).exists())
        self.assertTrue(Notification.objects.filter(
            for_staff=False, user=self.user, category='order').exists())
        email.assert_called_once()
        self.assertEqual(email.call_args[0][0], order)

    def test_order_placed_sends_admin_email_when_configured(self):
        s = SiteSettings.get()
        s.staff_notifications_email = 'admin@example.com'
        s.save()
        with mock.patch('store.emails.staff_notification') as admin_email, \
                mock.patch('store.emails.order_confirmation'):
            self._checkout()
        admin_email.assert_called_once()

    def test_guest_order_has_no_inbox_entry(self):
        self.client.logout()
        with mock.patch('store.emails.order_confirmation'):
            self._checkout()
        self.assertFalse(Notification.objects.filter(for_staff=False, user__isnull=False).exists())

    def test_paid_but_unfulfillable_creates_staff_notification(self):
        s = SiteSettings.get()
        s.inventory_strategy = 'paid'
        s.save()
        self.product.stock = 0
        self.product.save()
        order = Order.objects.create(
            number=Order.next_number(), customer_name='X', phone='0712',
            total=Decimal('2000.00'), payment_status='pending', payment_method='cod')
        OrderItem.objects.create(order=order, product=self.product, product_name=self.product.name,
                                 price=Decimal('1000.00'), quantity=2, subtotal=Decimal('2000.00'))
        mark_order_paid(order, method='manual', reference='', verification='manual', note='approved')
        self.assertTrue(Notification.objects.filter(
            for_staff=True, category='order', title__contains=order.number,
            message__contains='Not enough stock').exists())


class PaymentEventTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username='jane', email='jane@example.com', password='pw-123456')
        self.client.login(username='jane', password='pw-123456')
        self.product = make_product(price='1000.00', stock=5)
        self.order = Order.objects.create(
            number=Order.next_number(), customer_name='Jane', phone='0712345678',
            email='jane@example.com', user=self.user,
            total=Decimal('2150.00'), payment_status='pending', payment_method='mpesa')
        self.tx = MpesaTransaction.objects.create(
            transaction_id='tx-1', order=self.order, phone='254712345678',
            amount=Decimal('2150.00'), checkout_request_id='req-1', status='sent')

    def _callback(self, result_code='0', amount=2150):
        body = {'Body': {'stkCallback': {
            'CheckoutRequestID': 'req-1',
            'ResultCode': result_code,
            'ResultDesc': 'The service request is processed successfully.',
            'CallbackMetadata': {'Item': [
                {'Name': 'MpesaReceiptNumber', 'Value': 'PJX123ABC'},
                {'Name': 'PhoneNumber', 'Value': 254712345678},
                {'Name': 'Amount', 'Value': amount},
            ]},
        }}}
        return self.client.post(reverse('mpesa_callback'), json.dumps(body),
                                content_type='application/json')

    def test_payment_received_notifies_staff_and_customer(self):
        with mock.patch('store.emails.payment_success') as email:
            self._callback()
        self.assertTrue(Notification.objects.filter(
            for_staff=True, category='payment', title__contains=self.order.number).exists())
        self.assertTrue(Notification.objects.filter(
            for_staff=False, user=self.user, category='payment').exists())
        email.assert_called_once()

    def test_payment_failed_notifies_staff_and_customer(self):
        with mock.patch('store.emails.payment_failed') as email:
            self._callback(result_code='1')
        self.assertTrue(Notification.objects.filter(
            for_staff=True, category='payment', title__contains=self.order.number).exists())
        self.assertTrue(Notification.objects.filter(
            for_staff=False, user=self.user, category='payment').exists())
        email.assert_called_once()

    def test_cancelled_payment_uses_cancelled_label(self):
        with mock.patch('store.emails.payment_failed'):
            self._callback(result_code='1032')
        self.assertTrue(Notification.objects.filter(
            category='payment', title__contains='cancelled').exists())

    def test_amount_mismatch_requires_review_notifies_staff(self):
        self._callback(amount=1)
        self.assertTrue(Notification.objects.filter(
            for_staff=True, category='payment',
            title__contains='Payment requires review').exists())


class RegistrationEventTests(TestCase):
    def test_register_notifies_staff_and_welcomes_customer(self):
        client = Client()
        with mock.patch('store.emails.welcome') as email:
            resp = client.post(reverse('register'), {
                'username': 'newbie', 'email': 'new@example.com',
                'first_name': 'New', 'last_name': 'User',
                'password1': 'StrongPass123!', 'password2': 'StrongPass123!'})
        self.assertRedirects(resp, reverse('account'))
        user = User.objects.get(username='newbie')
        self.assertTrue(Notification.objects.filter(
            for_staff=True, category='customer', title__contains='newbie').exists())
        self.assertTrue(Notification.objects.filter(
            for_staff=False, user=user, category='account').exists())
        email.assert_called_once()


class ReviewEventTests(TestCase):
    def test_review_notifies_staff(self):
        client = Client()
        user = User.objects.create_user(username='bob', email='bob@example.com', password='pw-123456')
        client.login(username='bob', password='pw-123456')
        product = make_product(price='1000.00', stock=5)
        resp = client.post(reverse('product_detail', args=[product.slug]),
                           {'rating': 5, 'comment': 'Lovely dress, highly recommend it!'})
        self.assertRedirects(resp, reverse('product_detail', args=[product.slug]))
        self.assertTrue(Notification.objects.filter(
            for_staff=True, category='review', title__contains=product.name).exists())


class InventoryEventTests(TestCase):
    def test_low_stock_creates_notification(self):
        product = make_product(price='1000.00', stock=2, low_stock_threshold=5)
        evaluate_product_stock(product)
        self.assertTrue(Notification.objects.filter(
            for_staff=True, category='inventory', title__contains=product.name).exists())

    def test_restock_does_not_notify(self):
        product = make_product(price='1000.00', stock=20, low_stock_threshold=5)
        evaluate_product_stock(product)
        self.assertFalse(Notification.objects.filter(for_staff=True).exists())


class ManageEventTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username='jane', email='jane@example.com', password='pw-123456')
        self.staff_client = Client()
        User.objects.create_superuser(username='admin', email='a@b.com', password='TestPass123!')
        self.staff_client.login(username='admin', password='TestPass123!')
        self.client.login(username='jane', password='pw-123456')
        self.order = Order.objects.create(
            number=Order.next_number(), customer_name='Jane', phone='0712345678',
            email='jane@example.com', user=self.user,
            total=Decimal('2150.00'), payment_status='paid', status='confirmed')

    def test_order_status_change_notifies_customer(self):
        with mock.patch('store.emails.order_status_change') as email:
            resp = self.staff_client.post(reverse('order_status_update', args=[self.order.number]),
                                          {'status': 'shipped'}, follow=True)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(Notification.objects.filter(
            for_staff=False, user=self.user, category='order',
            title__contains='shipped').exists())
        email.assert_called_once()

    def test_manual_payment_approve_notifies(self):
        payment = Payment.objects.create(order=self.order, method='manual', amount=self.order.total, status='pending')
        with mock.patch('store.emails.payment_success') as email:
            resp = self.staff_client.post(reverse('payment_action', args=[payment.pk]),
                                          {'action': 'approve'}, follow=True)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(Notification.objects.filter(
            for_staff=True, category='payment', title__contains=self.order.number).exists())
        email.assert_called_once()

    def test_manual_payment_reject_notifies(self):
        payment = Payment.objects.create(order=self.order, method='manual', amount=self.order.total, status='pending')
        with mock.patch('store.emails.payment_failed') as email:
            resp = self.staff_client.post(reverse('payment_action', args=[payment.pk]),
                                          {'action': 'reject', 'mark_cancelled': '1'}, follow=True)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(Notification.objects.filter(
            for_staff=True, category='payment', title__contains='cancelled').exists())
        email.assert_called_once()


class PasswordResetEventTests(TestCase):
    def test_reset_email_creates_user_notification(self):
        user = User.objects.create_user(username='jane', email='jane@example.com', password='pw-123456')
        client = Client()
        with mock.patch('store.emails.password_reset'):
            resp = client.post(reverse('password_reset'), {'email': 'jane@example.com'})
        self.assertRedirects(resp, '/account/password-reset/done/')
        self.assertTrue(Notification.objects.filter(
            for_staff=False, user=user, category='account',
            title__contains='Password reset').exists())


class SystemErrorTests(TestCase):
    def test_error_500_records_system_notification_when_not_debug(self):
        from store import views
        request = RequestFactory().get('/boom')
        from django.contrib.sessions.middleware import SessionMiddleware
        from django.contrib.auth.models import AnonymousUser
        SessionMiddleware(lambda req: None).process_request(request)
        request.session['cart'] = {}
        request.user = AnonymousUser()
        with override_settings(DEBUG=False):
            resp = views.error_500(request, exception=ValueError('database broke'))
        self.assertEqual(resp.status_code, 500)
        self.assertTrue(Notification.objects.filter(
            for_staff=True, category='system', title='Server error: ValueError').exists())

    def test_error_500_skips_in_debug(self):
        from store import views
        request = RequestFactory().get('/boom')
        from django.contrib.sessions.middleware import SessionMiddleware
        from django.contrib.auth.models import AnonymousUser
        SessionMiddleware(lambda req: None).process_request(request)
        request.session['cart'] = {}
        request.user = AnonymousUser()
        with override_settings(DEBUG=True):
            views.error_500(request, exception=ValueError('boom'))
        self.assertFalse(Notification.objects.filter(category='system').exists())


class NotificationUITests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='jane', email='jane@example.com', password='pw-123456')
        User.objects.create_superuser(username='admin', email='a@b.com', password='TestPass123!')
        self.notification = Notification.create(
            'Order RB-1 shipped', user=self.user, for_staff=False, category='order', link='/orders/RB-1/')

    def test_account_notifications_page_requires_login(self):
        resp = Client().get(reverse('account_notifications'))
        self.assertEqual(resp.status_code, 302)

    def test_account_notifications_lists_and_marks_read(self):
        client = Client()
        client.login(username='jane', password='pw-123456')
        resp = client.get(reverse('account_notifications'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Order RB-1 shipped')
        self.assertContains(resp, 'cat-order')
        client.post(reverse('account_notifications_clear'))
        self.notification.refresh_from_db()
        self.assertTrue(self.notification.read)

    def test_header_bell_shows_unread_badge(self):
        client = Client()
        client.login(username='jane', password='pw-123456')
        resp = client.get(reverse('home'))
        self.assertContains(resp, 'aria-label="Notifications"')
        self.assertContains(resp, 'badge-count')
        self.assertContains(resp, '>1<')

    def test_manage_notifications_requires_staff(self):
        resp = Client().get(reverse('manage_notifications'))
        self.assertEqual(resp.status_code, 302)

    def test_manage_notifications_lists_staff_entries(self):
        Notification.create('Low stock: Shoes', category='inventory', link='/manage/inventory/')
        staff = Client()
        staff.login(username='admin', password='TestPass123!')
        resp = staff.get(reverse('manage_notifications'))
        self.assertContains(resp, 'Low stock: Shoes')
        self.assertNotContains(resp, 'Order RB-1 shipped')
        resp = staff.get(reverse('manage_notifications'), {'state': 'unread'})
        self.assertContains(resp, 'Low stock: Shoes')

    def test_manage_notifications_clear(self):
        staff = Client()
        staff.login(username='admin', password='TestPass123!')
        n = Notification.create('Order RB-9 placed', category='order')
        staff.post(reverse('notifications_clear'))
        n.refresh_from_db()
        self.assertTrue(n.read)
