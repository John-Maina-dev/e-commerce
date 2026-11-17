"""Manual M-Pesa fallback for when Daraja refuses to start STK Push.

Safaricom returns ``404.001.03`` until the Daraja app is entitled to
"Lipa na M-Pesa Online". No code can grant that entitlement, so the store
keeps the order and lets the customer pay the same amount straight to the
store's PayBill/Till, then submit the confirmation code for staff review.

These tests also pin the safety rules:

* the fallback is only offered when the prompt can never have reached a phone
  (a timeout may have been delivered, so paying again could double-charge);
* a customer can never mark an order paid — only staff verification can;
* one M-Pesa code can only ever be claimed once.
"""
from decimal import Decimal
from unittest import mock

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse

from store import mpesa
from store.models import Order, Payment, SiteSettings


def enable_mpesa(shortcode='174379'):
    s = SiteSettings.get()
    s.mpesa_enabled = True
    s.mpesa_environment = 'sandbox'
    s.mpesa_account_type = 'paybill'
    s.mpesa_consumer_key = 'consumer_key_x'
    s.mpesa_consumer_secret = 'consumer_secret_x'
    s.mpesa_shortcode = shortcode
    s.mpesa_passkey = 'passkey_x'
    s.mpesa_callback_url = 'https://shop.example.com/payments/mpesa/callback/'
    s.save()
    return s


def make_order(number, user=None, total='1000.00', payment_status='failed'):
    order = Order.objects.create(
        number=number, user=user, customer_name='Jane Doe', phone='0712345678',
        total=Decimal(total), payment_method='mpesa', payment_status=payment_status)
    Payment.objects.create(order=order, method='mpesa', amount=order.total,
                           status=payment_status, phone=order.phone)
    return order


def entitlement_error():
    return mpesa.MpesaError(
        'M-Pesa payments are unavailable at the moment.',
        kind='api', status=404, code='404.001.03',
        description='Invalid Access Token', endpoint=mpesa.STK_PUSH_PATH)


class StkPushStillWorksTests(TestCase):
    """The fallback must never replace a working STK Push."""

    def setUp(self):
        enable_mpesa()
        mpesa._token_cache.clear()
        from store.tests.test_models import make_product
        self.product = make_product(price='1000.00', stock=5)
        self.client = Client()
        self.client.post(reverse('cart_add', args=[self.product.id]), {'quantity': 1})

    def test_successful_stk_push_starts_payment_instead_of_fallback(self):
        token = mock.MagicMock(status_code=200,
                               headers={'Content-Type': 'application/json'})
        token.json.return_value = {'access_token': 'TOKEN', 'expires_in': 3599}
        push = mock.MagicMock(status_code=200,
                              headers={'Content-Type': 'application/json'})
        push.json.return_value = {
            'ResponseCode': '0', 'CheckoutRequestID': 'ws_CO_1',
            'MerchantRequestID': 'm1', 'ResponseDescription': 'Success.'}
        with mock.patch('store.mpesa.requests.get', return_value=token), \
             mock.patch('store.mpesa.requests.post', return_value=push) as post:
            resp = self.client.post(reverse('checkout'), {
                'customer_name': 'Jane Doe', 'phone': '0712345678',
                'email': 'jane@example.com', 'payment_method': 'mpesa',
            })
        order = Order.objects.get()
        self.assertRedirects(resp, reverse('order_detail', args=[order.number]))
        self.assertEqual(order.payment_status, 'processing')
        payment = order.payments.get()
        self.assertEqual(payment.status, 'processing')
        self.assertEqual(payment.transaction_id, 'ws_CO_1')
        self.assertFalse(payment.manual_code)
        payload = post.call_args.kwargs['json']
        self.assertEqual(payload['PhoneNumber'], '254712345678')
        self.assertEqual(payload['Amount'], int(order.total))


class ManualFallbackClassificationTests(TestCase):
    def test_entitlement_failure_offers_fallback(self):
        self.assertTrue(mpesa.manual_fallback_available(entitlement_error()))

    def test_auth_and_config_failures_offer_fallback(self):
        self.assertTrue(mpesa.manual_fallback_available(
            mpesa.MpesaError('bad credentials', kind='auth')))
        self.assertTrue(mpesa.manual_fallback_available(
            mpesa.MpesaError('not configured', kind='config')))

    def test_timeout_does_not_offer_fallback(self):
        """A timeout may already have reached the phone — never suggest re-paying."""
        self.assertFalse(mpesa.manual_fallback_available(
            mpesa.MpesaError('network down', kind='network')))

    def test_generic_stk_rejection_does_not_offer_fallback(self):
        self.assertFalse(mpesa.manual_fallback_available(
            mpesa.MpesaError('rejected', kind='api', code='500.001.01')))


class RetryFallsBackToManualTests(TestCase):
    def setUp(self):
        enable_mpesa()
        self.user = User.objects.create_user(username='jane', password='TestPass123!')
        self.client = Client()
        self.client.login(username='jane', password='TestPass123!')
        self.order = make_order('RB-MANUAL-1', user=self.user)

    def test_entitlement_failure_redirects_to_manual_payment(self):
        with mock.patch('store.views.mpesa.stk_push', side_effect=entitlement_error()):
            resp = self.client.post(
                reverse('order_retry_payment', args=[self.order.number]),
                {'action': 'mpesa', 'phone': '0712345678'})
        self.assertRedirects(resp, reverse('mpesa_manual', args=[self.order.number]))
        self.order.refresh_from_db()
        self.assertEqual(self.order.payment_status, 'failed')

    def test_timeout_stays_on_order_page(self):
        with mock.patch('store.views.mpesa.stk_push', side_effect=mpesa.MpesaError(
                'Unable to reach the M-Pesa service.', kind='network')):
            resp = self.client.post(
                reverse('order_retry_payment', args=[self.order.number]),
                {'action': 'mpesa', 'phone': '0712345678'})
        self.assertRedirects(resp, reverse('order_detail', args=[self.order.number]))

    def test_manual_page_shows_paybill_details(self):
        resp = self.client.get(reverse('mpesa_manual', args=[self.order.number]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, '174379')
        self.assertContains(resp, self.order.number)
        self.assertContains(resp, 'PayBill')
        self.assertContains(resp, '1000')

    def test_till_account_shows_till_number_without_account(self):
        s = SiteSettings.get()
        s.mpesa_account_type = 'till'
        s.save()
        resp = self.client.get(reverse('mpesa_manual', args=[self.order.number]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Till number')
        self.assertNotContains(resp, 'Account number')

    def test_manual_page_requires_order_access(self):
        stranger = User.objects.create_user(username='stranger', password='TestPass123!')
        client = Client()
        client.login(username='stranger', password='TestPass123!')
        resp = client.get(reverse('mpesa_manual', args=[self.order.number]))
        self.assertRedirects(resp, reverse('home'))


class ManualCodeSubmissionTests(TestCase):
    def setUp(self):
        enable_mpesa()
        self.user = User.objects.create_user(username='jane', password='TestPass123!')
        self.client = Client()
        self.client.login(username='jane', password='TestPass123!')
        self.order = make_order('RB-MANUAL-2', user=self.user)

    def _submit(self, code, order=None):
        return self.client.post(
            reverse('mpesa_manual_submit', args=[(order or self.order).number]),
            {'code': code})

    def test_valid_code_is_queued_for_staff_verification(self):
        resp = self._submit('qgh4 x8y2 z1')
        self.assertRedirects(resp, reverse('order_detail', args=[self.order.number]))
        self.order.refresh_from_db()
        payment = self.order.payments.get()
        self.assertEqual(self.order.payment_status, 'requires_review')
        self.assertEqual(payment.status, 'requires_review')
        self.assertEqual(payment.manual_code, 'QGH4X8Y2Z1')
        self.assertEqual(payment.reference, 'QGH4X8Y2Z1')
        self.assertIsNotNone(payment.manual_submitted_at)
        # The customer must never be marked as having paid themselves.
        self.assertNotEqual(payment.status, 'paid')
        self.assertEqual(payment.verification, '')

    def test_invalid_code_is_rejected(self):
        resp = self._submit('nope')
        self.assertRedirects(resp, reverse('mpesa_manual', args=[self.order.number]))
        self.order.refresh_from_db()
        self.assertEqual(self.order.payment_status, 'failed')
        self.assertEqual(self.order.payments.get().manual_code, '')

    def test_same_code_cannot_be_claimed_on_two_orders(self):
        self._submit('QGH4X8Y2Z1')
        other = make_order('RB-MANUAL-3', user=self.user)
        resp = self._submit('QGH4X8Y2Z1', order=other)
        self.assertRedirects(resp, reverse('mpesa_manual', args=[other.number]))
        other.refresh_from_db()
        self.assertEqual(other.payment_status, 'failed')
        self.assertEqual(other.payments.get().manual_code, '')

    def test_code_can_only_be_submitted_once_per_order(self):
        self._submit('QGH4X8Y2Z1')
        resp = self._submit('ZZZZ999999')
        self.assertRedirects(resp, reverse('order_detail', args=[self.order.number]))
        self.order.refresh_from_db()
        self.assertEqual(self.order.payment_status, 'requires_review')
        self.assertEqual(self.order.payments.get().manual_code, 'QGH4X8Y2Z1')

    def test_stranger_cannot_submit_a_code(self):
        stranger = User.objects.create_user(username='stranger', password='TestPass123!')
        client = Client()
        client.login(username='stranger', password='TestPass123!')
        resp = client.post(
            reverse('mpesa_manual_submit', args=[self.order.number]),
            {'code': 'QGH4X8Y2Z1'})
        self.assertRedirects(resp, reverse('home'))
        self.order.refresh_from_db()
        self.assertEqual(self.order.payments.get().manual_code, '')

    def test_staff_approval_after_code_submission_marks_paid(self):
        self._submit('QGH4X8Y2Z1')
        staff = User.objects.create_superuser(username='admin', email='a@b.com',
                                              password='TestPass123!')
        client = Client()
        client.login(username='admin', password='TestPass123!')
        payment = self.order.payments.get()
        resp = client.post(reverse('payment_action', args=[payment.pk]),
                           {'action': 'approve', 'reference': 'QGH4X8Y2Z1'})
        self.assertRedirects(resp, reverse('manage_payment_detail', args=[payment.pk]))
        self.order.refresh_from_db()
        payment.refresh_from_db()
        self.assertEqual(self.order.payment_status, 'paid')
        self.assertEqual(payment.verification, 'manual')
        self.assertEqual(payment.verified_by, staff)
