import base64
import logging
import os
from datetime import datetime, timedelta

import requests
from django.utils import timezone

logger = logging.getLogger('store')

SANDBOX_BASE = 'https://sandbox.safaricom.co.ke'
PRODUCTION_BASE = 'https://api.safaricom.co.ke'

# ---------------------------------------------------------------------------
# OAuth token cache (module-level, survives across requests in the same
# process).  A new token is requested only when the cached one is within
# 60 seconds of expiry or missing entirely.
# ---------------------------------------------------------------------------
_token_cache = {'token': None, 'expires_at': None}


def base_url(s):
    return PRODUCTION_BASE if s.mpesa_environment == 'production' else SANDBOX_BASE


# ---------------------------------------------------------------------------
# Phone number handling
# ---------------------------------------------------------------------------

_KENYAN_MOBILE_RE = {
    '07':  10,   # 07XXXXXXXX  (10 digits)
    '01':  10,   # 01XXXXXXXX  (10 digits)
    '254': 12,   # 254XXXXXXXXX (12 digits)
}


def normalize_phone(phone):
    """Normalise a Kenyan phone number to the 254XXXXXXXXX format required
    by the Daraja API.

    Raises ``ValueError`` when the number is clearly invalid (wrong length,
    unknown prefix, non-digit characters that survive stripping, etc.).
    """
    digits = ''.join(ch for ch in str(phone) if ch.isdigit())
    if not digits:
        raise ValueError('Phone number is required.')

    if digits.startswith('+'):
        digits = digits[1:]

    # Already in international form without the +
    if digits.startswith('254'):
        if len(digits) != 12:
            raise ValueError(
                f'Invalid Kenyan phone number: {digits}. '
                'Expected 12 digits starting with 254 (e.g. 254712345678).')
        return digits

    # Local format: 07XX or 01XX
    if digits.startswith('0'):
        prefix = digits[:2]
        expected = _KENYAN_MOBILE_RE.get(prefix)
        if expected is None:
            raise ValueError(
                f'Invalid Kenyan phone prefix: {prefix}. '
                'Use a 07XX or 01XX number (e.g. 0712345678).')
        if len(digits) != expected:
            raise ValueError(
                f'Invalid phone number length: {digits}. '
                f'Expected {expected} digits for a {prefix} number.')
        return '254' + digits[1:]

    raise ValueError(
        f'Invalid phone number: {phone}. '
        'Use a Kenyan number like 0712345678 or 254712345678.')


def validate_phone(phone):
    """Return ``(normalised_number, None)`` on success, or ``(None, error_message)``."""
    try:
        return normalize_phone(phone), None
    except ValueError as e:
        return None, str(e)


# ---------------------------------------------------------------------------
# Daraja OAuth authentication with token caching
# ---------------------------------------------------------------------------

def _credentials(s):
    """Resolve Daraja credentials, preferring env vars over DB fields.

    This lets operators keep secrets out of the database (e.g. injected via
    Docker / systemd / CI).  When the env var is empty or missing the
    database value from SiteSettings is used.
    """
    return {
        'consumer_key': (os.environ.get('DARAJA_CONSUMER_KEY') or s.mpesa_consumer_key or '').strip(),
        'consumer_secret': (os.environ.get('DARAJA_CONSUMER_SECRET') or s.mpesa_consumer_secret or '').strip(),
        'shortcode': (os.environ.get('DARAJA_SHORTCODE') or s.mpesa_shortcode or '').strip(),
        'passkey': (os.environ.get('DARAJA_PASSKEY') or s.mpesa_passkey or '').strip(),
        'callback_url': (os.environ.get('DARAJA_CALLBACK_URL') or s.mpesa_callback_url or '').strip(),
    }


def get_access_token(s):
    """Obtain a Daraja OAuth access token, reusing a cached token when valid.

    Daraja tokens expire after ~59 minutes.  We request a new one when the
    cached token is within 60 seconds of expiry.
    """
    global _token_cache
    now = timezone.now()
    cached = _token_cache.get('token')
    expires = _token_cache.get('expires_at')
    if cached and expires and now < expires:
        return cached

    creds = _credentials(s)
    url = base_url(s) + '/oauth/v1/generate?grant_type=client_credentials'
    response = requests.get(
        url, auth=(creds['consumer_key'], creds['consumer_secret']), timeout=20)
    response.raise_for_status()
    data = response.json()
    token = data.get('access_token')
    if not token:
        raise RuntimeError('M-Pesa OAuth did not return an access token.')
    # Cache with a 59-minute TTL (Daraja tokens live ~60 min).
    _token_cache = {
        'token': token,
        'expires_at': now + timedelta(minutes=59),
    }
    return token


# ---------------------------------------------------------------------------
# Connection test
# ---------------------------------------------------------------------------

def test_connection(s):
    """Verify M-Pesa configuration as far as the Daraja API permits. Never fakes success."""
    creds = _credentials(s)
    if not creds['consumer_key'] or not creds['consumer_secret']:
        return False, 'Consumer Key and Consumer Secret are required before the connection can be tested.'
    try:
        token = get_access_token(s)
        if not token:
            return False, 'M-Pesa OAuth returned an empty access token.'
        return True, f'Connection successful. Environment: {s.mpesa_environment.upper()}. OAuth access token obtained.'
    except requests.exceptions.HTTPError as e:
        return False, f'M-Pesa API rejected credentials (HTTP {e.response.status_code}). Check your Consumer Key and Consumer Secret.'
    except requests.exceptions.RequestException as e:
        return False, f'Could not reach the Daraja API: {e}. Check your internet connection and environment.'
    except Exception as e:
        return False, f'Connection test failed: {e}'


# ---------------------------------------------------------------------------
# STK Push
# ---------------------------------------------------------------------------

def stk_push(order, phone):
    """Initiate an M-Pesa STK Push for the given order.

    The amount is always taken from ``order.total`` (server-side truth).
    The phone is validated and normalised before use.
    """
    from .models import MpesaTransaction, SiteSettings

    s = SiteSettings.get()
    if not s.mpesa_enabled:
        raise RuntimeError('M-Pesa is disabled. Enable it in Payment Settings.')

    creds = _credentials(s)
    missing = [name for name, val in (
        ('Consumer Key', creds['consumer_key']),
        ('Consumer Secret', creds['consumer_secret']),
        ('Shortcode', creds['shortcode']),
        ('Passkey', creds['passkey']),
        ('Callback URL', creds['callback_url']),
    ) if not val]
    if missing:
        raise RuntimeError('M-Pesa settings are incomplete: ' + ', '.join(missing) + '.')

    # Validate and normalise phone number.
    normalized, phone_err = validate_phone(phone)
    if phone_err:
        raise RuntimeError(f'Invalid phone number: {phone_err}')

    amount = int(order.total)
    if amount < 1:
        raise RuntimeError('The order total must be at least KES 1 for M-Pesa.')

    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
    password = base64.b64encode(
        (creds['shortcode'] + creds['passkey'] + timestamp).encode()).decode()
    payload = {
        'BusinessShortCode': creds['shortcode'],
        'Password': password,
        'Timestamp': timestamp,
        'TransactionType': 'CustomerPayBillOnline',
        'Amount': amount,
        'PartyA': normalized,
        'PartyB': creds['shortcode'],
        'PhoneNumber': normalized,
        'CallBackURL': creds['callback_url'],
        'AccountReference': (s.mpesa_account_reference or 'Reeves Boutique')[:50],
        'TransactionDesc': (s.mpesa_transaction_desc or 'Payment for Reeves Boutique order')[:80],
    }
    tx = MpesaTransaction.objects.create(
        transaction_id='TXN-' + timezone.now().strftime('%Y%m%d%H%M%S%f'),
        order=order,
        phone=normalized,
        amount=order.total,
        status='sent',
    )
    try:
        token = get_access_token(s)
        response = requests.post(
            base_url(s) + '/mpesa/stkpush/v1/processrequest',
            json=payload,
            headers={'Authorization': 'Bearer ' + token},
            timeout=30,
        )
        data = response.json()
        response.raise_for_status()
        tx.checkout_request_id = data.get('CheckoutRequestID', '')
        tx.merchant_request_id = data.get('MerchantRequestID', '')
        tx.result_description = data.get('ResponseDescription', '')
        tx.save(update_fields=['checkout_request_id', 'merchant_request_id',
                               'result_description', 'updated_at'])
        if data.get('ResponseCode') != '0':
            tx.status = 'failed'
            tx.result_description = (data.get('errorMessage')
                                     or data.get('ResponseDescription')
                                     or 'STK request rejected.')
            tx.save(update_fields=['status', 'result_description', 'updated_at'])
            raise RuntimeError(tx.result_description)
        logger.info('STK push sent for order %s (%s) checkout id %s',
                     order.number, normalized, tx.checkout_request_id)
        return tx, data
    except requests.exceptions.RequestException as e:
        tx.status = 'failed'
        tx.result_description = f'Network error talking to Daraja: {e}'
        tx.save(update_fields=['status', 'result_description', 'updated_at'])
        logger.error('STK push network error for order %s: %s', order.number, e)
        raise RuntimeError('Could not reach the M-Pesa API. Please try again.') from e
    except RuntimeError:
        raise
    except Exception as e:
        tx.status = 'failed'
        tx.result_description = f'Unexpected error: {e}'
        tx.save(update_fields=['status', 'result_description', 'updated_at'])
        logger.exception('STK push failed for order %s', order.number)
        raise RuntimeError(f'Could not start M-Pesa payment: {e}') from e


# ---------------------------------------------------------------------------
# STK Push timeout / status query
# ---------------------------------------------------------------------------

def query_stk_status(s, checkout_request_id):
    """Query the status of an STK Push request via the Daraja TransactionStatusQuery.

    Used as a fallback when a callback is not received within the expected
    window.  Returns a dict with at least ``ResultCode`` and ``ResultDesc``.

    ``ResultCode`` values of interest:
        0    – success
        1032 – request timed out (user did not act on the prompt)
        1037 – the STK push was sent but no callback received yet
        1    – insufficient balance / generic failure
    """
    creds = _credentials(s)
    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
    password = base64.b64encode(
        (creds['shortcode'] + creds['passkey'] + timestamp).encode()).decode()
    payload = {
        'Initiator': creds['shortcode'],
        'SecurityCredential': password,
        'CommandID': 'TransactionStatusQuery',
        'TransactionID': checkout_request_id,
        'PartyA': creds['shortcode'],
        'IdentifierType': '4',
        'ResultURL': creds['callback_url'],
        'QueueTimeOutURL': creds['callback_url'],
        'Remarks': 'Status query',
        'Occasion': 'Timeout query',
    }
    try:
        token = get_access_token(s)
        response = requests.post(
            base_url(s) + '/mpesa/transactionstatus/v1/query',
            json=payload,
            headers={'Authorization': 'Bearer ' + token},
            timeout=30,
        )
        data = response.json()
        response.raise_for_status()
        return data
    except requests.exceptions.RequestException as e:
        logger.error('STK status query network error for %s: %s', checkout_request_id, e)
        raise RuntimeError('Could not reach the M-Pesa API for status query.') from e
    except Exception as e:
        logger.exception('STK status query failed for %s', checkout_request_id)
        raise RuntimeError(f'Status query failed: {e}') from e
