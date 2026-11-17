"""Regression tests for M-Pesa robustness fixes.

These prove that an actual Safaricom rejection (HTTP error, HTML WAF page) is
no longer masked behind the old generic "Could not reach the M-Pesa API"
network error, and that the stub helper surfaces the real cause for operators.
"""
from decimal import Decimal
from unittest import mock

import requests
from django.test import TestCase

from store import mpesa
from store.models import Order, SiteSettings


def enable_mpesa():
    s = SiteSettings.get()
    s.mpesa_enabled = True
    s.mpesa_environment = 'sandbox'
    s.mpesa_account_type = 'paybill'
    s.mpesa_consumer_key = 'consumer_key_x'
    s.mpesa_consumer_secret = 'consumer_secret_x'
    s.mpesa_shortcode = '174379'
    s.mpesa_passkey = 'passkey_x'
    s.mpesa_callback_url = 'https://example.com/payments/mpesa/callback/'
    s.save()
    return s


def make_order():
    return Order.objects.create(number='RB-T-ROBUST', customer_name='Test',
                                phone='0712345678', total=100, payment_method='mpesa')


class MpesaErrorClassificationTests(TestCase):
    def setUp(self):
        enable_mpesa()
        mpesa._token_cache.clear()

    def _stub_token(self):
        resp = mock.MagicMock(status_code=200)
        resp.json.return_value = {'access_token': 'TOKEN'}
        return resp

    def test_html_waf_error_is_classified_as_api_not_network(self):
        """A 403 HTML edge response must not become the generic reach message."""
        order = make_order()
        push = mock.MagicMock(status_code=403)
        push.json.side_effect = ValueError('no json here')  # HTML body
        push.text = '<html>blocked</html>'
        with mock.patch('store.mpesa.requests.get', return_value=self._stub_token()), \
             mock.patch('store.mpesa.requests.post', return_value=push):
            with self.assertRaises(mpesa.MpesaError) as ctx:
                mpesa.stk_push(order, '0712345678')
        err = ctx.exception
        self.assertEqual(err.kind, 'api')
        self.assertEqual(err.status, 403)
        self.assertNotIn('reach', str(err))
        order.refresh_from_db()
        tx = order.mpesa_transactions.get()
        self.assertEqual(tx.status, 'failed')

    def test_json_http_error_carries_safaricom_code(self):
        """A 404 JSON body supplies the Safaricom error code for operators."""
        order = make_order()
        push = mock.MagicMock(status_code=404)
        push.json.return_value = {'errorCode': '404.001.03',
                                  'errorMessage': 'Invalid Access Token'}
        with mock.patch('store.mpesa.requests.get', return_value=self._stub_token()), \
             mock.patch('store.mpesa.requests.post', return_value=push):
            with self.assertRaises(mpesa.MpesaError) as ctx:
                mpesa.stk_push(order, '0712345678')
        err = ctx.exception
        self.assertEqual(err.kind, 'api')
        self.assertEqual(err.status, 404)
        self.assertEqual(err.code, '404.001.03')
        tx = order.mpesa_transactions.get()
        self.assertEqual(tx.result_code, '404.001.03')
        self.assertNotIn('SUPER_SECRET', str(err))

    def test_stk_amount_is_rounded_to_whole_shillings(self):
        """Daraja only charges whole shillings; the stored tx must match."""
        order = Order.objects.create(number='RB-T-ROUND', customer_name='Test',
                                     phone='0712345678', total=Decimal('100.60'),
                                     payment_method='mpesa')
        push = mock.MagicMock(status_code=200)
        push.json.return_value = {'ResponseCode': '0', 'CheckoutRequestID': 'cid-1',
                                  'MerchantRequestID': 'mid-1',
                                  'ResponseDescription': 'Success'}
        with mock.patch('store.mpesa.requests.get', return_value=self._stub_token()), \
             mock.patch('store.mpesa.requests.post', return_value=push) as post:
            tx, _data = mpesa.stk_push(order, '0712345678')
        self.assertEqual(post.call_args.kwargs['json']['Amount'], 101)
        self.assertEqual(tx.amount, Decimal('101'))
        self.assertEqual(tx.status, 'sent')

    def test_status_query_with_unreadable_error_body_raises_cleanly(self):
        """A non-JSON error body must not crash the status-query fallback."""
        s = SiteSettings.get()
        bad = mock.MagicMock(status_code=500)
        bad.headers = {'Content-Type': 'text/html'}
        bad.json.side_effect = ValueError('not json')
        with mock.patch('store.mpesa.requests.get', return_value=self._stub_token()), \
             mock.patch('store.mpesa.requests.post', return_value=bad):
            with self.assertRaises(mpesa.MpesaError) as ctx:
                mpesa.query_stk_status(s, 'cid-1')
        self.assertEqual(ctx.exception.kind, 'api')
        self.assertEqual(ctx.exception.status, 500)

    def test_connection_error_is_classified_as_network(self):
        order = make_order()
        with mock.patch('store.mpesa.requests.get', return_value=self._stub_token()), \
             mock.patch('store.mpesa.requests.post',
                        side_effect=requests.exceptions.ConnectionError('boom')):
            with self.assertRaises(mpesa.MpesaError) as ctx:
                mpesa.stk_push(order, '0712345678')
        self.assertEqual(ctx.exception.kind, 'network')
        order.refresh_from_db()
        self.assertEqual(order.mpesa_transactions.get().status, 'failed')

    def test_token_cache_is_keyed_by_environment(self):
        """Switching sandbox -> production must mint a fresh token."""
        s = SiteSettings.get()
        calls = []

        def fake_get(url, **kwargs):
            env = 'prod' if 'api.safaricom' in url else 'sand'
            calls.append(env)
            resp = mock.MagicMock(status_code=200)
            resp.json.return_value = {'access_token': 'TOKEN-' + env}
            return resp

        mpesa._token_cache.clear()
        with mock.patch('store.mpesa.requests.get', side_effect=fake_get):
            t1 = mpesa.get_access_token(s)
            t2 = mpesa.get_access_token(s)             # cached
            s.mpesa_environment = 'production'; s.save()
            t3 = mpesa.get_access_token(s)             # new env -> new token
            s.mpesa_environment = 'sandbox'; s.save()
        self.assertEqual(t1, t2)
        self.assertEqual(t1, 'TOKEN-sand')
        self.assertEqual(t3, 'TOKEN-prod')
        self.assertEqual(calls, ['sand', 'prod'])


class RelatedProductsTests(TestCase):
    def test_related_excludes_self_and_respects_visibility(self):
        from store.models import Category, Product
        from store.services import related_products
        cat = Category.objects.create(name='Dresses')
        a = Product.objects.create(name='Red Dress', category=cat, sku='R1',
                                   price=100, stock=5, sales_count=3)
        Product.objects.create(name='Red Dress Same Brand', category=cat, sku='R2',
                               price=110, stock=5, brand='X', sales_count=10)
        Product.objects.create(name='Hidden Dupe', category=cat, sku='R3',
                               price=90, stock=5, hidden=True, sales_count=50)
        Product.objects.create(name='Archived Dupe', category=cat, sku='R4',
                               price=90, stock=5, is_archived=True, sales_count=50)
        related = related_products(a)
        slugs = [p.sku for p in related]
        self.assertIn('R2', slugs)
        self.assertNotIn('R3', slugs)   # hidden product excluded
        self.assertNotIn('R4', slugs)   # archived product excluded
        self.assertNotIn('R1', slugs)   # current product never in its own list