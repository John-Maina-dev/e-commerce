from unittest import mock

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse

from store import mpesa
from store.models import Order, SiteSettings


class MpesaSettingsUiVerifyTests(TestCase):
    def setUp(self):
        User.objects.create_superuser(username='admin', email='a@b.com', password='TestPass123!')
        self.client = Client()
        self.client.login(username='admin', password='TestPass123!')

    def test_page_loads_with_new_controls(self):
        resp = self.client.get(reverse('manage_payment_settings'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'M-Pesa STK Push')
        self.assertContains(resp, 'Till Number (Buy Goods)')
        self.assertContains(resp, 'Enable M-Pesa STK Push')
        self.assertContains(resp, 'Test M-Pesa Connection')
        self.assertContains(resp, '/payments/mpesa/callback/')

    def test_save_validates_and_persists_account_type_and_callback(self):
        resp = self.client.post(reverse('manage_payment_settings'), {
            'mpesa_enabled': 'on', 'mpesa_environment': 'sandbox',
            'mpesa_account_type': 'till', 'mpesa_business_name': 'My Shop',
            'mpesa_shortcode': '174379', 'mpesa_consumer_key': 'KEY',
            'mpesa_consumer_secret': 'SECRET', 'mpesa_passkey': 'PASS',
            'mpesa_account_reference': 'Shop', 'mpesa_transaction_desc': 'desc',
            'inventory_strategy': 'paid',
        })
        self.assertEqual(resp.status_code, 302)
        s = SiteSettings.get()
        self.assertEqual(s.mpesa_account_type, 'till')
        self.assertEqual(s.mpesa_business_name, 'My Shop')
        self.assertIn('/payments/mpesa/callback/', s.mpesa_callback_url)

    def test_invalid_shortcode_is_rejected(self):
        resp = self.client.post(reverse('manage_payment_settings'), {
            'mpesa_enabled': 'on', 'mpesa_environment': 'sandbox',
            'mpesa_account_type': 'paybill', 'mpesa_shortcode': 'ABC12',
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'digits only')
        self.assertFalse(SiteSettings.get().mpesa_enabled)

    def test_missing_required_when_enabled(self):
        resp = self.client.post(reverse('manage_payment_settings'), {
            'mpesa_enabled': 'on', 'mpesa_environment': 'sandbox',
            'mpesa_account_type': 'paybill',
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'required when M-Pesa is enabled')

    def test_normal_customer_cannot_access(self):
        User.objects.create_user(username='jane', password='TestPass123!')
        c = Client()
        c.login(username='jane', password='TestPass123!')
        resp = c.get(reverse('manage_payment_settings'))
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp.url.startswith('/account/login/'))

    def test_till_uses_buy_goods_transaction_type(self):
        s = SiteSettings.get()
        s.mpesa_enabled = True
        s.mpesa_account_type = 'till'
        s.mpesa_consumer_key = 'k'
        s.mpesa_consumer_secret = 's'
        s.mpesa_shortcode = '174379'
        s.mpesa_passkey = 'p'
        s.mpesa_callback_url = 'https://example.com/payments/mpesa/callback/'
        s.save()
        order = Order.objects.create(number='T-1', customer_name='X', phone='0712345678',
                                     total=100, payment_method='mpesa')
        token = mock.MagicMock(); token.json.return_value = {'access_token': 'T'}
        push = mock.MagicMock()
        push.json.return_value = {'ResponseCode': '0', 'CheckoutRequestID': 'ws',
                                  'MerchantRequestID': 'm', 'ResponseDescription': 'ok'}
        push.raise_for_status.return_value = None
        with mock.patch('store.mpesa.requests.get', return_value=token), \
             mock.patch('store.mpesa.requests.post', return_value=push) as post:
            mpesa.stk_push(order, '0712345678')
        self.assertEqual(post.call_args.kwargs['json']['TransactionType'], 'CustomerBuyGoodsOnline')

    def test_connection_failure_hides_secrets(self):
        s = SiteSettings.get()
        s.mpesa_consumer_key = 'SUPER_SECRET_KEY_123'
        s.mpesa_consumer_secret = 'SUPER_SECRET_SECRET_456'
        s.save()
        import requests
        with mock.patch('store.mpesa.requests.get',
                        side_effect=requests.exceptions.HTTPError('boom')):
            ok, message = mpesa.test_connection(s)
        self.assertFalse(ok)
        self.assertIn('Connection failed', message)
        self.assertNotIn('SUPER_SECRET', message)
