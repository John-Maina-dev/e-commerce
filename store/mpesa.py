import base64
import logging
import os
import socket
import sys
import time
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

import requests
from django.utils import timezone

logger = logging.getLogger('store')

# ---------------------------------------------------------------------------
# Resilient DNS resolution for Safaricom Daraja endpoints
# Windows and local Kenyan ISPs frequently experience transient DNS lookup
# drops (Errno 11001: getaddrinfo failed) for .co.ke domains.
# This interceptor transparently falls back to known Safaricom edge IPs or
# Google DoH while preserving TLS SNI and certificate validation.
# ---------------------------------------------------------------------------
_KNOWN_HOST_IPS = {
    'sandbox.safaricom.co.ke': '45.223.20.17',
    'api.safaricom.co.ke': '196.201.214.202',
}

_orig_getaddrinfo = socket.getaddrinfo


def _resolve_via_doh(host):
    """Fallback DNS resolution via Google DNS-over-HTTPS if system DNS fails."""
    try:
        r = requests.get(f'https://8.8.8.8/resolve?name={host}&type=A', timeout=2)
        if r.status_code == 200:
            answers = r.json().get('Answer', [])
            for a in answers:
                if a.get('type') == 1 and a.get('data'):
                    return a['data']
    except Exception:
        pass
    return None


def _resilient_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    """Transparently intercept DNS lookups to recover from Windows / ISP DNS drops."""
    try:
        res = _orig_getaddrinfo(host, port, family, type, proto, flags)
        if host in _KNOWN_HOST_IPS and res:
            try:
                ip = res[0][4][0]
                if ip and not ip.startswith('127.'):
                    _KNOWN_HOST_IPS[host] = ip
            except Exception:
                pass
        return res
    except socket.gaierror as e:
        if host in _KNOWN_HOST_IPS:
            doh_ip = _resolve_via_doh(host)
            ip_to_use = doh_ip or _KNOWN_HOST_IPS[host]
            _KNOWN_HOST_IPS[host] = ip_to_use
            logger.warning(
                'DNS resolution for %s failed (%s). Recovering via resilient IP %s.',
                host, e, ip_to_use
            )
            return _orig_getaddrinfo(ip_to_use, port, family, type, proto, flags)
        raise


if socket.getaddrinfo is not _resilient_getaddrinfo:
    socket.getaddrinfo = _resilient_getaddrinfo

SANDBOX_BASE = 'https://sandbox.safaricom.co.ke'
PRODUCTION_BASE = 'https://api.safaricom.co.ke'

OAUTH_PATH = '/oauth/v1/generate?grant_type=client_credentials'
STK_PUSH_PATH = '/mpesa/stkpush/v1/processrequest'
STK_QUERY_PATH = '/mpesa/transactionstatus/v1/query'

OAUTH_TIMEOUT = 20
API_TIMEOUT = 30
HTTP_RETRIES = 3

# Identify this client to Safaricom's edge. The default python-requests
# User-Agent is frequently served a WAF block page (HTTP 403 HTML) by the
# Daraja sandbox, which historically surfaced as a misleading "could not
# reach" error. A normal browser-style UA is what the portal itself sends.
_HEADERS = {
    'Accept': 'application/json',
    'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                   'AppleWebKit/537.36 (KHTML, like Gecko) '
                   'Chrome/120.0 Safari/537.36'),
}

# Transient statuses worth retrying rather than failing the customer's order.
_RETRY_STATUSES = {429, 500, 502, 503, 504}

# Daraja reports "Invalid Access Token" at two different layers and only the
# errorCode distinguishes them:
#   401.003.01 -> rejected at the authorisation layer (token from the wrong
#                 environment / truncated / credentials rotated).
#   404.001.03 -> passed authorisation and was refused by the API *product*.
#                 On a token that is seconds old this means the Daraja app (or
#                 its shortcode) is not subscribed to M-PESA Express / STK Push.
#                 Refreshing the token never fixes it; only the app entitlement
#                 on developer.safaricom.co.ke (or Safaricom API support) does.
# They are classified separately so neither the customer nor the operator is
# told to "try again" when retrying can never succeed.
AUTH_LAYER_CODES = {'401.003.01'}
ENTITLEMENT_CODES = {'404.001.03'}

# Machine-readable failure categories written to the log (never the secrets).
CATEGORY_OAUTH = 'MPESA_OAUTH_FAILED'
CATEGORY_STK = 'MPESA_STK_FAILED'
CATEGORY_INVALID_TOKEN = 'MPESA_INVALID_TOKEN'
CATEGORY_NETWORK = 'MPESA_TIMEOUT'
CATEGORY_CONFIG = 'MPESA_CONFIG_INVALID'
CATEGORY_CALLBACK = 'MPESA_CALLBACK_FAILED'


class MpesaError(RuntimeError):
    """A failed M-Pesa operation.

    ``str(error)`` is always safe to show to a customer. Full diagnostics
    (HTTP status, Safaricom error code/description, Daraja requestId,
    endpoint) are attached to the instance and written to the server log —
    never included in the customer-facing message.
    """

    def __init__(self, message, *, kind='api', status=None, code='',
                 description='', endpoint='', request_id='', category=''):
        super().__init__(message)
        self.kind = kind  # 'network' | 'auth' | 'api' | 'config' | 'entitlement'
        self.status = status
        self.code = code
        self.description = description
        self.endpoint = endpoint
        self.request_id = request_id
        self.category = category or _category_for(kind, code, endpoint)


def _category_for(kind, code, endpoint=''):
    if code in ENTITLEMENT_CODES:
        return CATEGORY_INVALID_TOKEN
    if code in AUTH_LAYER_CODES:
        return CATEGORY_OAUTH
    if kind == 'network':
        return CATEGORY_NETWORK
    if kind == 'config':
        return CATEGORY_CONFIG
    if kind == 'auth':
        return CATEGORY_OAUTH
    if 'callback' in (endpoint or ''):
        return CATEGORY_CALLBACK
    return CATEGORY_STK


def _stk_rejection_message(code):
    """Customer-safe message for a rejected STK request.

    Codes that a retry cannot possibly fix must not say "please try again".
    """
    if code in ENTITLEMENT_CODES:
        return ('M-Pesa payments are unavailable at the moment. '
                'Please choose another payment method or contact the store.')
    if code in AUTH_LAYER_CODES:
        return ('M-Pesa is temporarily unavailable. '
                'Please choose another payment method or try again later.')
    return 'M-Pesa could not start the payment. Please try again.'


def manual_fallback_available(error):
    """True when the failed STK start can never have reached a phone.

    Only these failures are safe to hand over to manual payment:
    the prompt was refused before delivery (entitlement / auth / config), so
    the customer cannot be double-charged by also paying via PayBill/Till.
    A timeout is deliberately excluded — Safaricom may already have delivered
    the prompt, and telling the customer to pay again could charge them twice.
    """
    if not isinstance(error, MpesaError):
        return False
    return (error.category in (CATEGORY_INVALID_TOKEN, CATEGORY_OAUTH, CATEGORY_CONFIG)
            or error.kind in ('config', 'auth', 'entitlement'))


def order_charge_amount(order):
    """Whole-shilling amount Daraja will charge for an order (0 when invalid).

    Daraja only accepts whole shillings; rounding (rather than truncating)
    keeps the gateway charge identical to the reconciliation checks.
    """
    try:
        charged = Decimal(order.total).quantize(Decimal('1'), rounding=ROUND_HALF_UP)
    except (InvalidOperation, TypeError, ValueError):
        return 0
    return int(charged)


def customer_message_for(error):
    """Map an internal failure onto a message that is safe and useful."""
    if isinstance(error, MpesaError):
        if error.code in ENTITLEMENT_CODES or error.category == CATEGORY_INVALID_TOKEN:
            return ('M-Pesa STK Push is not enabled for this Daraja app (Safaricom error 404.001.03: "Lipa na M-Pesa Sandbox" product must be ticked on developer.safaricom.co.ke). '
                    'Please enable it in Daraja My Apps or choose another payment method.')
        if error.category == CATEGORY_OAUTH:
            return ('M-Pesa authentication failed. Please verify Consumer Key and Secret in .env or Settings > Payments.')
    return str(error)


# ---------------------------------------------------------------------------
# OAuth token cache, keyed by environment + consumer key so that switching
# from sandbox to production (or rotating credentials) can never reuse a
# token issued for a different endpoint/app.
# ---------------------------------------------------------------------------
_token_cache = {}


def base_url(s):
    """Resolve the Daraja base URL for the configured environment.

    Checks MPESA_ENV, MPESA_ENVIRONMENT, or DARAJA_ENVIRONMENT.
    """
    env = _clean_env(os.environ.get('MPESA_ENV') or os.environ.get('MPESA_ENVIRONMENT')
                     or os.environ.get('DARAJA_ENVIRONMENT') or getattr(s, 'mpesa_environment', '')
                     or 'sandbox').lower()
    return PRODUCTION_BASE if env == 'production' else SANDBOX_BASE


def environment(s):
    return 'production' if base_url(s) == PRODUCTION_BASE else 'sandbox'


def get_active_ngrok_url():
    """Attempt to discover an active ngrok tunnel from the local agent API."""
    if 'test' in sys.argv:
        return ''
    try:
        r = requests.get('http://127.0.0.1:4040/api/tunnels', timeout=0.3)
        if r.status_code == 200:
            data = r.json()
            tunnels = data.get('tunnels', [])
            for t in tunnels:
                if t.get('proto') == 'https' and t.get('public_url'):
                    return t['public_url'].rstrip('/')
    except Exception:
        pass
    return ''


def resolve_callback_url(s=None):
    """Build the callback URL, preferring public HTTPS URLs.
    Order of precedence:
    1. Auto-discovered live local ngrok tunnel (http://127.0.0.1:4040)
    2. MPESA_CALLBACK_URL from env (if valid and not placeholder)
    3. MPESA_CALLBACK_BASE_URL from env (if valid and not placeholder)
    4. SiteSettings.mpesa_callback_url from DB (if set)
    """
    from django.urls import reverse

    discovered = get_active_ngrok_url()
    if discovered:
        try:
            return discovered.rstrip('/') + reverse('mpesa_callback')
        except Exception:
            return discovered.rstrip('/') + '/payments/mpesa/callback/'

    direct_cb = _clean_env(os.environ.get('MPESA_CALLBACK_URL') or os.environ.get('DARAJA_CALLBACK_URL'))
    if direct_cb:
        return direct_cb

    base_cb = _clean_env(os.environ.get('MPESA_CALLBACK_BASE_URL'))
    if base_cb:
        try:
            return base_cb.rstrip('/') + reverse('mpesa_callback')
        except Exception:
            return base_cb.rstrip('/') + '/payments/mpesa/callback/'

    db_cb = _clean_env(getattr(s, 'mpesa_callback_url', '')) if s else ''
    if db_cb:
        return db_cb

    return ''


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
    unknown prefix, etc.).
    """
    digits = ''.join(ch for ch in str(phone) if ch.isdigit())
    if not digits:
        raise ValueError('Phone number is required.')

    # Already in international form (with or without the leading +)
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
# Daraja credentials
# ---------------------------------------------------------------------------

PLACEHOLDER_MARKERS = (
    'your_', 'your-', 'change-me', 'example.com', 'ngrok-domain',
    'your-ngrok', 'placeholder', 'dummy'
)


def _is_placeholder(val):
    if not val:
        return True
    s = str(val).strip().lower()
    return any(p in s for p in PLACEHOLDER_MARKERS)


def _clean_env(val):
    """Strip whitespace, newlines, and surrounding quotes from configuration values.
    Returns empty string if val is None or matches a known dummy placeholder.
    """
    if val is None:
        return ''
    s = str(val).strip().strip("'\"").strip()
    if _is_placeholder(s):
        return ''
    return s


def _credentials(s):
    """Resolve Daraja credentials, preferring non-empty env vars over DB fields.
    Falls back to SiteSettings if env var is missing or a placeholder.
    """
    key = _clean_env(os.environ.get('MPESA_CONSUMER_KEY') or os.environ.get('DARAJA_CONSUMER_KEY')) or _clean_env(getattr(s, 'mpesa_consumer_key', ''))
    secret = _clean_env(os.environ.get('MPESA_CONSUMER_SECRET') or os.environ.get('DARAJA_CONSUMER_SECRET')) or _clean_env(getattr(s, 'mpesa_consumer_secret', ''))
    shortcode = _clean_env(os.environ.get('MPESA_SHORTCODE') or os.environ.get('DARAJA_SHORTCODE')) or _clean_env(getattr(s, 'mpesa_shortcode', ''))
    passkey = _clean_env(os.environ.get('MPESA_PASSKEY') or os.environ.get('DARAJA_PASSKEY')) or _clean_env(getattr(s, 'mpesa_passkey', ''))
    callback_url = resolve_callback_url(s)
    account_type = (_clean_env(os.environ.get('MPESA_ACCOUNT_TYPE') or os.environ.get('DARAJA_ACCOUNT_TYPE'))
                    or _clean_env(getattr(s, 'mpesa_account_type', '')) or 'paybill').lower()

    return {
        'consumer_key': key,
        'consumer_secret': secret,
        'shortcode': shortcode,
        'passkey': passkey,
        'callback_url': callback_url,
        'account_type': account_type,
    }


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def _safe_json(response):
    """Return ``(data, None)`` when the body is valid JSON, else ``(None, reason)``.

    Safaricom (and the WAF in front of it) can return HTML error pages. Calling
    ``response.json()`` directly raises and previously masked the real HTTP
    status behind a generic network error.
    """
    try:
        return response.json(), None
    except ValueError:
        return None, 'response was not valid JSON'


def _api_error_details(response):
    """Best-effort extraction of Safaricom's error code/message/requestId.

    ``requestId`` is the only identifier Safaricom support can use to look the
    failure up on their side, so it is captured for every non-2xx response.
    """
    status = getattr(response, 'status_code', None)
    data, _ = _safe_json(response)
    code = ''
    description = ''
    request_id = ''
    if isinstance(data, dict):
        code = str(data.get('errorCode') or data.get('ResponseCode') or '')
        description = str(data.get('errorMessage') or data.get('ResponseDescription')
                          or data.get('ResultDesc') or '')
        request_id = str(data.get('requestId') or '')
    if not description:
        ctype = (getattr(response, 'headers', {}) or {}).get('Content-Type', '') if hasattr(response, 'headers') else ''
        if 'html' in str(ctype).lower() or status in (403, 404):
            description = 'Safaricom returned an unexpected response (possible edge/WAF block).'
    return status, code, description, request_id


def _sleep_between_attempts(attempt):
    time.sleep(0.6 * (attempt + 1))


def _http_get(url, *, auth, timeout=OAUTH_TIMEOUT):
    last_exc = None
    for attempt in range(HTTP_RETRIES):
        try:
            response = requests.get(url, auth=auth, timeout=timeout, headers=_HEADERS)
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
            last_exc = e
            if attempt + 1 < HTTP_RETRIES:
                _sleep_between_attempts(attempt)
                continue
            raise
        if getattr(response, 'status_code', None) in _RETRY_STATUSES and attempt + 1 < HTTP_RETRIES:
            _sleep_between_attempts(attempt)
            continue
        return response
    raise last_exc


def _http_post(url, *, payload, token, timeout=API_TIMEOUT):
    last_exc = None
    headers = dict(_HEADERS)
    headers['Authorization'] = 'Bearer ' + token
    headers['Content-Type'] = 'application/json'
    for attempt in range(HTTP_RETRIES):
        try:
            response = requests.post(url, json=payload, headers=headers, timeout=timeout)
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
            last_exc = e
            if attempt + 1 < HTTP_RETRIES:
                _sleep_between_attempts(attempt)
                continue
            raise
        if getattr(response, 'status_code', None) in _RETRY_STATUSES and attempt + 1 < HTTP_RETRIES:
            _sleep_between_attempts(attempt)
            continue
        return response
    raise last_exc


def _is_http_error(status):
    """True only for a real integer HTTP error status.

    Guards against mock/None responses and, more importantly, makes the
    difference between a transport failure and a Safaricom rejection explicit.
    """
    return isinstance(status, int) and status >= 400


def _log_failure(operation, s, endpoint, *, order=None, status=None, code='',
                 description='', elapsed=None, request_id='', category=''):
    """Log the real failure for operators without ever logging secrets.

    Contains the identifiers Safaricom support needs (requestId, errorCode,
    HTTP status, endpoint, elapsed) plus the order number — and never the
    consumer secret, passkey, access token or STK password.
    """
    logger.error(
        'M-PESA_%s failed | category=%s environment=%s endpoint=%s order=%s '
        'status=%s code=%s requestId=%s description=%s elapsed=%.2fs',
        operation.replace(' ', '_').upper(),
        category or '-', environment(s), endpoint,
        getattr(order, 'number', '') or '-', status, code or '-',
        request_id or '-', (description or '-')[:300],
        elapsed if elapsed is not None else -1.0,
    )


# ---------------------------------------------------------------------------
# OAuth
# ---------------------------------------------------------------------------

def get_access_token(s, force_refresh=False):
    """Obtain a Daraja OAuth access token, reusing a cached token when valid.

    Daraja tokens expire after ~59 minutes. We request a new one when the
    cached token is within 60 seconds of expiry or when force_refresh=True.
    The cache is keyed by environment + consumer key so it can never leak
    a token across environments or credential sets.
    """
    creds = _credentials(s)
    key = (base_url(s), creds['consumer_key'])
    now = timezone.now()
    if not force_refresh:
        cached = _token_cache.get(key)
        if cached and now < cached['expires_at']:
            return cached['token']
    else:
        _token_cache.pop(key, None)

    if not creds['consumer_key'] or not creds['consumer_secret']:
        raise MpesaError(
            'M-Pesa credentials missing. Ensure MPESA_CONSUMER_KEY and MPESA_CONSUMER_SECRET are configured.',
            kind='config', endpoint=OAUTH_PATH)

    url = base_url(s) + OAUTH_PATH
    started = time.monotonic()
    try:
        response = _http_get(url, auth=(creds['consumer_key'], creds['consumer_secret']))
    except requests.exceptions.RequestException as e:
        _log_failure('OAuth', s, OAUTH_PATH, description=str(e),
                     elapsed=time.monotonic() - started, category=CATEGORY_NETWORK)
        raise MpesaError(
            'Unable to reach the M-Pesa service. Please try again.',
            kind='network', endpoint=OAUTH_PATH) from e

    data, parse_error = _safe_json(response)
    status = getattr(response, 'status_code', None)
    logger.info('Daraja OAuth HTTP status=%s (keys=%s)', status, list(data.keys()) if isinstance(data, dict) else 'non-json')

    if data is None:
        _, code, description, request_id = _api_error_details(response)
        _log_failure('OAuth', s, OAUTH_PATH, status=status, code=code,
                     description=description or parse_error, request_id=request_id,
                     elapsed=time.monotonic() - started, category=CATEGORY_OAUTH)
        raise MpesaError(
            'M-Pesa returned an unreadable response. Please try again.',
            kind='api', status=status, code=code,
            description=description or parse_error, endpoint=OAUTH_PATH,
            request_id=request_id, category=CATEGORY_OAUTH)

    token = data.get('access_token')
    if not token:
        status, code, description, request_id = _api_error_details(response)
        _log_failure('OAuth', s, OAUTH_PATH, status=status, code=code,
                     description=description, request_id=request_id,
                     elapsed=time.monotonic() - started, category=CATEGORY_OAUTH)
        raise MpesaError(
            'M-Pesa authentication failed. Please check the M-Pesa configuration.',
            kind='auth', status=status, code=code, description=description,
            endpoint=OAUTH_PATH, request_id=request_id, category=CATEGORY_OAUTH)

    # Cache with a small safety margin below Daraja's ~60-minute lifetime.
    _token_cache[key] = {
        'token': token,
        'expires_at': now + timedelta(seconds=max(int(data.get('expires_in') or 3599) - 60, 60)),
    }
    return token


# ---------------------------------------------------------------------------
# Connection test
# ---------------------------------------------------------------------------

def callback_url_problem(callback_url, check_reachable=False):
    """Return a human-readable problem with the configured callback URL, or ''.

    Safaricom posts the STK result from its own network, so the URL has to be
    a publicly reachable HTTPS address. ``http://127.0.0.1``/``localhost`` can
    never work — this is checked rather than assumed.
    """
    url = (callback_url or '').strip()
    if not url:
        return 'no callback URL is configured (set MPESA_CALLBACK_BASE_URL or MPESA_CALLBACK_URL)'
    if not url.lower().startswith('https://'):
        return f'callback URL is not HTTPS ({url.split("//")[0]}//…)'
    host = url.split('//', 1)[1].split('/', 1)[0].split('@')[-1].split(':')[0].lower()
    if host in ('localhost', '127.0.0.1', '0.0.0.0', '::1'):
        return 'callback URL points at localhost/127.0.0.1, which Safaricom cannot reach (use ngrok HTTPS)'

    if check_reachable:
        try:
            r = requests.get(url, timeout=5, headers=_HEADERS)
            if r.headers.get('Ngrok-Error-Code') == 'ERR_NGROK_3200':
                return 'configured ngrok tunnel is offline (ERR_NGROK_3200: start ngrok via "ngrok http 8001")'
            # Any HTTP response (even 405 Method Not Allowed for GET) proves the server is reachable
        except Exception as e:
            return f'callback URL is not reachable: {e}'

    return ''


def probe_stk_entitlement(s, token):
    """Ask Daraja whether this app may call STK Push — without sending a prompt.

    Sends a deliberately incomplete payload. Daraja validates authorisation
    and product entitlement *before* it validates the payload, so:

    * ``404 / 404.001.03`` -> the app is not subscribed to M-PESA Express
      (nothing can be paid for until Safaricom enables the product);
    * a payload/validation error (400/405/422 or a business-level rejection)
      -> entitlement is fine, the request simply cannot be executed.

    Because no valid STK request is ever formed, no prompt can reach a phone.

    Returns ``(ok, status, code, description, request_id)`` where ``ok`` is
    ``True`` (entitled), ``False`` (refused) or ``None`` (inconclusive).
    """
    payload = {'BusinessShortCode': '0', 'Amount': 0}
    try:
        response = _http_post(base_url(s) + STK_PUSH_PATH, payload=payload,
                              token=token, timeout=API_TIMEOUT)
    except requests.exceptions.RequestException as e:
        return False, None, '', f'network error while probing STK Push: {e}', ''
    status, code, description, request_id = _api_error_details(response)
    if code in ENTITLEMENT_CODES:
        return False, status, code, description, request_id
    if code in AUTH_LAYER_CODES:
        return False, status, code, description, request_id
    if _is_http_error(status) and status not in (400, 401, 405, 415, 422):
        return None, status, code, description, request_id   # inconclusive
    return True, status, code, description, request_id


def test_connection(s):
    """Verify the whole outbound payment path. Never fakes success.

    Checks, in order:

    1. credentials are present;
    2. OAuth actually returns an access token;
    3. the app is entitled to call the STK Push API;
    4. the callback URL is one Safaricom can reach.

    Returns ``(ok, message)``. The message is safe to display to an
    administrator and never contains a secret. Real diagnostics are logged.
    """
    creds = _credentials(s)
    if not creds['consumer_key'] or not creds['consumer_secret']:
        return False, ('Connection failed: Consumer Key and Consumer Secret are required '
                       'before the connection can be tested.')

    env = environment(s).upper()
    try:
        token = get_access_token(s)
    except MpesaError as e:
        _log_failure('Connection test', s, OAUTH_PATH, status=e.status, code=e.code,
                     description=e.description or str(e), request_id=e.request_id,
                     category=e.category)
        if e.kind == 'network':
            return False, ('Connection failed: the Daraja API could not be reached. '
                           'Check your network connection and environment.')
        if e.kind == 'auth':
            detail = f' (HTTP {e.status})' if e.status else ''
            return False, ('Connection failed: M-Pesa rejected the credentials'
                           f'{detail}. Check the Consumer Key, Consumer Secret and environment.')
        return False, ('Connection failed: M-Pesa returned an unexpected response. '
                       'Check the environment and try again.')
    except Exception:
        logger.exception('Unexpected error while testing M-Pesa connection')
        return False, ('Connection failed: an unexpected error occurred. '
                       'Check the logs for details.')

    oauth_ok = f'OAuth OK ({env})'

    # 2 — STK Push entitlement. This is the check that OAuth alone cannot make:
    # a perfectly valid token can still be refused by the API product.
    probe_started = time.monotonic()
    entitled, status, code, description, request_id = probe_stk_entitlement(s, token)
    if entitled is False:
        _log_failure('Connection test', s, STK_PUSH_PATH, status=status, code=code,
                     description=description, request_id=request_id,
                     elapsed=time.monotonic() - probe_started,
                     category=_category_for('api', code, STK_PUSH_PATH))
        if code in ENTITLEMENT_CODES:
            rid = f' — requestId {request_id}' if request_id else ''
            return False, (
                f'{oauth_ok}, but STK Push is NOT enabled for this app or shortcode '
                f'(Safaricom error {code}{rid}). The Consumer Key/Secret are valid, yet '
                'Safaricom has not enabled the "Lipa na M-Pesa Online" '
                '(M-PESA Express) product for them. Open My Apps on '
                'developer.safaricom.co.ke and make sure that product is added to '
                'this app and that the Shortcode belongs to it. If it already is, '
                'email apisupport@safaricom.co.ke with the app ID, shortcode and '
                'this requestId and ask them to enable the product. Retrying will '
                'not fix this — only Safaricom can. Customers can still pay '
                'manually via the PayBill/Till fallback until it is enabled.')
        if code in AUTH_LAYER_CODES:
            return False, (
                f'{oauth_ok}, but the STK Push API rejected the token '
                f'({code}). The token and the base URL come from different '
                'environments — check that Environment matches the credentials.')
        return False, (f'{oauth_ok}, but the STK Push request was rejected '
                       f'({code or "HTTP error"}: {description}). Check the logs.')
    if entitled is None:
        logger.warning('STK entitlement probe inconclusive | status=%s code=%s requestId=%s',
                       code, description, request_id)

    # 3 — callback reachability (Safaricom must be able to post back to us).
    callback_problem = callback_url_problem(creds['callback_url'])
    if callback_problem:
        return False, (f'{oauth_ok}; STK Push API reachable, but the callback URL is '
                       f'not usable: {callback_problem}. Safaricom can only deliver '
                       'payment results to a public HTTPS URL.')

    ok = f'M-Pesa connection successful. Environment: {env}. OAuth OK; STK Push API reachable; callback URL OK.'
    if entitled is None:
        ok += ' (STK entitlement could not be confirmed from here.)'
    return True, ok


# ---------------------------------------------------------------------------
# STK Push
# ---------------------------------------------------------------------------

def _stk_payload(s, creds, phone, amount):
    timestamp = timezone.localtime().strftime('%Y%m%d%H%M%S')
    password = base64.b64encode(
        (creds['shortcode'] + creds['passkey'] + timestamp).encode()).decode()
    # PayBill uses CustomerPayBillOnline; a Till (Buy Goods) number uses
    # CustomerBuyGoodsOnline. The configured account type decides this.
    transaction_type = ('CustomerBuyGoodsOnline' if creds.get('account_type') == 'till'
                        else 'CustomerPayBillOnline')
    return {
        'BusinessShortCode': creds['shortcode'],
        'Password': password,
        'Timestamp': timestamp,
        'TransactionType': transaction_type,
        'Amount': amount,
        'PartyA': phone,
        'PartyB': creds['shortcode'],
        'PhoneNumber': phone,
        'CallBackURL': creds['callback_url'],
        'AccountReference': (s.mpesa_account_reference or 'Reeves Boutique')[:50],
        'TransactionDesc': (s.mpesa_transaction_desc or 'Payment for Reeves Boutique order')[:80],
    }


def stk_push(order, phone, amount=None):
    """Initiate an M-Pesa STK Push for the given order.

    The amount is taken from ``amount`` (for split payments) or ``order.total`` (server-side truth).
    The phone is validated and normalised before use. Raises ``MpesaError``
    whose message is safe to show the customer; the real Safaricom failure is
    stored on the transaction and logged.
    """
    from .models import MpesaTransaction, SiteSettings

    s = SiteSettings.get()
    if not s.mpesa_enabled:
        raise MpesaError('M-Pesa is disabled. Enable it in Payment Settings.',
                         kind='config')

    creds = _credentials(s)
    missing = [name for name, val in (
        ('Consumer Key', creds['consumer_key']),
        ('Consumer Secret', creds['consumer_secret']),
        ('Shortcode', creds['shortcode']),
        ('Passkey', creds['passkey']),
        ('Callback URL', creds['callback_url']),
    ) if not val]
    if missing:
        raise MpesaError('M-Pesa settings are incomplete: ' + ', '.join(missing) + '.',
                         kind='config')

    normalized, phone_err = validate_phone(phone)
    if phone_err:
        raise MpesaError(f'Invalid phone number: {phone_err}', kind='config')

    # Daraja only accepts whole shillings. Rounding (rather than truncating)
    # keeps the amount the gateway charges identical to what the callback
    # reconciliation checks — otherwise a total like KES 1500.50 would return
    # KES 1500 and be flagged as a mismatch even though it was correct.
    if amount is not None:
        try:
            charge_amount = int(Decimal(str(amount)).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
        except (InvalidOperation, TypeError, ValueError):
            charge_amount = 0
    else:
        charge_amount = order_charge_amount(order)

    if charge_amount < 1:
        raise MpesaError('The payment amount must be at least KES 1 for M-Pesa.',
                         kind='config')

    payload = _stk_payload(s, creds, normalized, charge_amount)
    endpoint = STK_PUSH_PATH
    tx = MpesaTransaction.objects.create(
        transaction_id='TXN-' + timezone.now().strftime('%Y%m%d%H%M%S%f'),
        order=order,
        phone=normalized,
        amount=Decimal(charge_amount),
        status='sent',
    )

    def _fail(user_message, *, kind, status=None, code='', description='',
              request_id='', exc=None):
        tx.status = 'failed'
        tx.result_code = code or tx.result_code
        tx.result_description = description or str(user_message)
        tx.save(update_fields=['status', 'result_code', 'result_description', 'updated_at'])
        err = MpesaError(user_message, kind=kind, status=status, code=code,
                         description=description, endpoint=endpoint,
                         request_id=request_id)
        if exc is not None:
            raise err from exc
        raise err

    # Refuse to send STK push if the callback URL is not public HTTPS
    callback_err = callback_url_problem(creds['callback_url'])
    if callback_err:
        logger.error(
            'M-PESA_CALLBACK_URL_INVALID | order=%s endpoint=%s callback=%s error=%s',
            order.number, endpoint, creds['callback_url'], callback_err)
        raise MpesaError(
            f'Callback URL is invalid ({callback_err}). STK Push requires a public HTTPS URL (e.g. ngrok).',
            kind='config', endpoint=endpoint, category=CATEGORY_CALLBACK)

    started = time.monotonic()
    retried_auth = False

    while True:
        try:
            token = get_access_token(s, force_refresh=retried_auth)
            response = _http_post(base_url(s) + endpoint, payload=payload, token=token)
        except MpesaError as e:
            tx.status = 'failed'
            tx.result_code = e.code or tx.result_code
            tx.result_description = e.description or str(e)
            tx.save(update_fields=['status', 'result_code', 'result_description', 'updated_at'])
            raise
        except requests.exceptions.RequestException as e:
            _log_failure('STK push', s, endpoint, order=order, description=str(e),
                         elapsed=time.monotonic() - started, category=CATEGORY_NETWORK)
            _fail('Unable to reach the M-Pesa service. Please try again.',
                  kind='network', description=str(e), exc=e)

        elapsed = time.monotonic() - started
        data, parse_error = _safe_json(response)
        status = getattr(response, 'status_code', None)

        # A non-2xx HTTP status means Safaricom (or its edge) rejected the request.
        if _is_http_error(status):
            _, code, description, request_id = _api_error_details(response)
            if not retried_auth and (status == 401 or code in AUTH_LAYER_CODES or code in ENTITLEMENT_CODES):
                logger.warning('STK push rejected with %s (%s). Retrying once with fresh token...', status, code)
                retried_auth = True
                continue

            category = _category_for('api', code, endpoint)
            _log_failure('STK push', s, endpoint, order=order, status=status, code=code,
                         description=description or parse_error, request_id=request_id,
                         elapsed=elapsed, category=category)
            _fail(_stk_rejection_message(code),
                  kind='api',
                  status=status, code=code, request_id=request_id,
                  description=description or parse_error or f'HTTP {status}')
        break

    if data is None:
        _log_failure('STK push', s, endpoint, order=order, status=status,
                     description=parse_error, elapsed=elapsed, category=CATEGORY_STK)
        _fail('M-Pesa returned an unreadable response. Please try again.',
              kind='api', status=status, description=parse_error or '')

    tx.checkout_request_id = data.get('CheckoutRequestID', '')
    tx.merchant_request_id = data.get('MerchantRequestID', '')
    tx.result_description = data.get('ResponseDescription', '')
    tx.save(update_fields=['checkout_request_id', 'merchant_request_id',
                           'result_description', 'updated_at'])

    if data.get('ResponseCode') != '0':
        description = (data.get('errorMessage') or data.get('ResponseDescription')
                       or 'STK request rejected.')
        code = str(data.get('errorCode') or data.get('ResponseCode') or '')
        request_id = str(data.get('requestId') or '')
        category = _category_for('api', code, endpoint)
        _log_failure('STK push', s, endpoint, order=order, status=status, code=code,
                     description=description, request_id=request_id,
                     elapsed=elapsed, category=category)
        _fail(_stk_rejection_message(code),
              kind='api',
              status=status, code=code, description=description,
              request_id=request_id)

    logger.info('STK push sent for order %s (%s) checkout id %s in %.2fs',
                order.number, normalized, tx.checkout_request_id, elapsed)
    return tx, data


# ---------------------------------------------------------------------------
# STK Push timeout / status query
# ---------------------------------------------------------------------------

def query_stk_status(s, checkout_request_id):
    """Query the status of an STK Push via the Daraja TransactionStatusQuery.

    Used as a fallback when a callback is not received within the expected
    window. Returns a dict with at least ``ResultCode`` and ``ResultDesc``.
    """
    creds = _credentials(s)
    timestamp = timezone.localtime().strftime('%Y%m%d%H%M%S')
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
    endpoint = STK_QUERY_PATH
    started = time.monotonic()
    try:
        token = get_access_token(s)
        response = _http_post(base_url(s) + endpoint, payload=payload, token=token)
    except MpesaError:
        raise
    except requests.exceptions.RequestException as e:
        _log_failure('Status query', s, endpoint, description=str(e),
                     elapsed=time.monotonic() - started)
        raise MpesaError('Unable to reach the M-Pesa service for the status query.',
                         kind='network', endpoint=endpoint) from e

    elapsed = time.monotonic() - started
    data, parse_error = _safe_json(response)
    if data is None:
        status, code, description, request_id = _api_error_details(response)
        _log_failure('Status query', s, endpoint, status=status, code=code,
                     description=description or parse_error,
                     request_id=request_id, elapsed=elapsed)
        raise MpesaError('M-Pesa returned an unreadable response to the status query.',
                         kind='api', status=status, code=code,
                         description=description or parse_error, endpoint=endpoint,
                         request_id=request_id)

    status = getattr(response, 'status_code', None)
    if _is_http_error(status):
        _, code, description, request_id = _api_error_details(response)
        _log_failure('Status query', s, endpoint, status=status, code=code,
                     description=description, request_id=request_id, elapsed=elapsed)
        raise MpesaError('M-Pesa rejected the status query.',
                         kind='api', status=status, code=code,
                         description=description, endpoint=endpoint,
                         request_id=request_id)
    return data
