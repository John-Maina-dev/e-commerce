"""Prove the real Safaricom failure is classified and reported honestly.

The live sandbox returns HTTP 404 ``404.001.03`` for STK Push even though
OAuth succeeds. These tests pin the behaviour that matters:

* the customer is not told to "try again" when retrying cannot help;
* the operator sees the Daraja ``requestId``/``errorCode`` in the log;
* "Test M-Pesa Connection" no longer reports success when only OAuth works.
"""
from unittest import mock

from django.test import TestCase

from store import mpesa
from store.models import Order, SiteSettings


def enable_mpesa(callback='https://shop.example.com/payments/mpesa/callback/'):
    s = SiteSettings.get()
    s.mpesa_enabled = True
    s.mpesa_environment = 'sandbox'
    s.mpesa_account_type = 'paybill'
    s.mpesa_consumer_key = 'consumer_key_x'
    s.mpesa_consumer_secret = 'consumer_secret_x'
    s.mpesa_shortcode = '174379'
    s.mpesa_passkey = 'passkey_x'
    s.mpesa_callback_url = callback
    s.save()
    return s


def response(status, body):
    resp = mock.MagicMock(status_code=status)
    resp.headers = {'Content-Type': 'application/json'}
    resp.json.return_value = body
    return resp


def token_response():
    return response(200, {'access_token': 'TOKEN', 'expires_in': 3599})


class CallbackUrlTests(TestCase):
    def test_empty_is_a_problem(self):
        self.assertTrue(mpesa.callback_url_problem(''))

    def test_plain_http_is_a_problem(self):
        self.assertIn('not HTTPS', mpesa.callback_url_problem('http://shop.example.com/cb/'))

    def test_localhost_over_https_is_a_problem(self):
        self.assertIn('localhost', mpesa.callback_url_problem('https://localhost/cb/'))
        self.assertIn('localhost', mpesa.callback_url_problem('https://127.0.0.1:8000/cb/'))

    def test_public_https_is_accepted(self):
        self.assertEqual(mpesa.callback_url_problem('https://shop.example.com/cb/'), '')


class StkEntitlementClassificationTests(TestCase):
    def setUp(self):
        enable_mpesa()
        mpesa._token_cache.clear()

    def test_entitlement_failure_does_not_tell_the_customer_to_retry(self):
        order = Order.objects.create(number='RB-T-ENTITLE', customer_name='Test',
                                     phone='0712345678', total=100,
                                     payment_method='mpesa')
        push = response(404, {'errorCode': '404.001.03',
                              'errorMessage': 'Invalid Access Token',
                              'requestId': 'req-abc-123'})
        with mock.patch('store.mpesa.requests.get', return_value=token_response()), \
             mock.patch('store.mpesa.requests.post', return_value=push):
            with self.assertRaises(mpesa.MpesaError) as ctx:
                mpesa.stk_push(order, '0712345678')
        err = ctx.exception
        self.assertEqual(err.code, '404.001.03')
        self.assertEqual(err.request_id, 'req-abc-123')
        self.assertEqual(err.category, mpesa.CATEGORY_ENTITLEMENT)
        self.assertNotIn('try again', str(err).lower())
        self.assertIn('unavailable', str(err).lower())

    def test_entitlement_failure_is_logged_with_request_id(self):
        order = Order.objects.create(number='RB-T-ENTITLE2', customer_name='Test',
                                     phone='0712345678', total=100,
                                     payment_method='mpesa')
        push = response(404, {'errorCode': '404.001.03',
                              'errorMessage': 'Invalid Access Token',
                              'requestId': 'req-abc-456'})
        with mock.patch('store.mpesa.requests.get', return_value=token_response()), \
             mock.patch('store.mpesa.requests.post', return_value=push), \
             mock.patch('store.mpesa.logger') as logger:
            with self.assertRaises(mpesa.MpesaError):
                mpesa.stk_push(order, '0712345678')
        text = ''.join(str(call) for call in logger.error.call_args_list)
        self.assertIn('req-abc-456', text)
        self.assertIn('404.001.03', text)
        self.assertIn('MPESA_STK_NOT_ENTITLED', text)
        self.assertNotIn('passkey_x', text)
        self.assertNotIn('consumer_secret_x', text)

    def test_transient_failure_still_says_try_again(self):
        order = Order.objects.create(number='RB-T-ENTITLE3', customer_name='Test',
                                     phone='0712345678', total=100,
                                     payment_method='mpesa')
        push = response(500, {'errorCode': '500.001.01', 'errorMessage': 'Server error'})
        with mock.patch('store.mpesa.requests.get', return_value=token_response()), \
             mock.patch('store.mpesa.requests.post', return_value=push):
            with self.assertRaises(mpesa.MpesaError) as ctx:
                mpesa.stk_push(order, '0712345678')
        self.assertIn('try again', str(ctx.exception).lower())


class ConnectionTestEntitlementTests(TestCase):
    """The connection test must exercise the STK API, not just OAuth."""

    def setUp(self):
        self.s = enable_mpesa()
        mpesa._token_cache.clear()

    def test_reports_failure_when_app_is_not_entitled(self):
        not_entitled = response(404, {'errorCode': '404.001.03',
                                      'errorMessage': 'Invalid Access Token',
                                      'requestId': 'req-1'})
        with mock.patch('store.mpesa.requests.get', return_value=token_response()), \
             mock.patch('store.mpesa.requests.post', return_value=not_entitled):
            ok, message = mpesa.test_connection(self.s)
        self.assertFalse(ok)
        self.assertIn('404.001.03', message)
        self.assertIn('NOT enabled', message)
        self.assertNotIn('consumer_secret_x', message)

    def test_succeeds_when_entitled_and_callback_is_public_https(self):
        # A payload/validation rejection proves the entitlement check passed.
        validation_error = response(400, {'errorCode': '400.001.16',
                                          'errorMessage': 'Bad Request',
                                          'requestId': 'req-2'})
        with mock.patch('store.mpesa.requests.get', return_value=token_response()), \
             mock.patch('store.mpesa.requests.post', return_value=validation_error):
            ok, message = mpesa.test_connection(self.s)
        self.assertTrue(ok, message)
        self.assertIn('STK Push API reachable', message)

    def test_fails_when_callback_is_not_reachable(self):
        self.s.mpesa_callback_url = 'http://127.0.0.1:8000/payments/mpesa/callback/'
        self.s.save()
        validation_error = response(400, {'errorCode': '400.001.16',
                                          'errorMessage': 'Bad Request'})
        with mock.patch('store.mpesa.requests.get', return_value=token_response()), \
             mock.patch('store.mpesa.requests.post', return_value=validation_error):
            ok, message = mpesa.test_connection(self.s)
        self.assertFalse(ok)
        self.assertIn('callback URL', message)
        self.assertIn('not usable', message)

    def test_still_hides_secrets_on_oauth_failure(self):
        import requests as requests_lib
        self.s.mpesa_consumer_key = 'SUPER_SECRET_KEY_123'
        self.s.save()
        with mock.patch('store.mpesa.requests.get',
                        side_effect=requests_lib.HTTPError('boom')):
            ok, message = mpesa.test_connection(self.s)
        self.assertFalse(ok)
        self.assertIn('Connection failed', message)
        self.assertNotIn('SUPER_SECRET', message)

    def test_probe_never_sends_a_callable_payment_request(self):
        """The entitlement probe must not be able to reach a customer phone."""
        seen = {}
        validation_error = response(400, {'errorCode': '400.001.16'})

        def fake_post(url, **kwargs):
            seen.update(kwargs.get('json') or {})
            return validation_error

        with mock.patch('store.mpesa.requests.get', return_value=token_response()), \
             mock.patch('store.mpesa.requests.post', side_effect=fake_post):
            ok, message = mpesa.test_connection(self.s)
        self.assertTrue(ok, message)
        # No phone number, no password, no amount that could trigger a prompt.
        self.assertNotIn('PhoneNumber', seen)
        self.assertNotIn('PartyA', seen)
        self.assertNotIn('Password', seen)
        self.assertNotIn('CallBackURL', seen)


class RelatedProductsTopUpTests(TestCase):
    def test_thin_category_is_topped_up_from_other_categories(self):
        from store.models import Category, Product
        from store.services import related_products
        a_cat = Category.objects.create(name='A')
        b_cat = Category.objects.create(name='B')
        current = Product.objects.create(name='Current', category=a_cat, sku='C1',
                                         price=100, stock=5)
        other = Product.objects.create(name='Other', category=b_cat, sku='B1',
                                       price=100, stock=5, sales_count=99)
        related = related_products(current, limit=4)
        skus = [p.sku for p in related]
        self.assertIn('B1', skus)
        self.assertNotIn('C1', skus)

    def test_hidden_products_are_never_used_to_fill_the_shelf(self):
        from store.models import Category, Product
        from store.services import related_products
        cat = Category.objects.create(name='A')
        current = Product.objects.create(name='Current', category=cat, sku='C1',
                                         price=100, stock=5)
        Product.objects.create(name='Hidden', category=cat, sku='H1',
                               price=100, stock=5, hidden=True)
        related = related_products(current, limit=4)
        self.assertEqual([p.sku for p in related], [])
