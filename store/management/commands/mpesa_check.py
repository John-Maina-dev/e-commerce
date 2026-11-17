"""Django management command to check Daraja M-Pesa setup, OAuth token,
callback reachability, and optionally fire a test KES 1 STK push.

Usage:
    python manage.py mpesa_check
    python manage.py mpesa_check --phone 254708374149
"""
import base64
import json
import os
import time
from decimal import Decimal
from django.core.management.base import BaseCommand
from django.utils import timezone
import requests

from store import mpesa
from store.models import SiteSettings, Order, Payment


class Command(BaseCommand):
    help = 'Verify M-Pesa environment, OAuth token, callback URL, and optionally test STK push.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--phone',
            type=str,
            default='',
            help='Kenyan phone number to send a KES 1 test STK push to (e.g. 254708374149)'
        )

    def handle(self, *args, **options):
        self.stdout.write(self.style.MIGRATE_HEADING('\n=== Reeves Boutique M-Pesa Health & Config Audit ===\n'))
        s = SiteSettings.get()
        creds = mpesa._credentials(s)

        # 1. Verify required environment variables
        self.stdout.write('1. Checking required credentials & env vars...')
        required_vars = [
            ('MPESA_CONSUMER_KEY', creds['consumer_key']),
            ('MPESA_CONSUMER_SECRET', creds['consumer_secret']),
            ('MPESA_SHORTCODE', creds['shortcode']),
            ('MPESA_PASSKEY', creds['passkey']),
            ('MPESA_CALLBACK_URL', creds['callback_url']),
        ]

        missing = []
        for name, val in required_vars:
            if not val:
                missing.append(name)
                self.stdout.write(self.style.ERROR(f'   [✗] {name}: Missing or empty'))
            else:
                masked = f"{val[:4]}...{val[-4:]}" if len(val) > 10 else "***"
                self.stdout.write(self.style.SUCCESS(f'   [✓] {name}: Set ({masked})'))

        if missing:
            self.stdout.write(self.style.ERROR(
                f'\n[FATAL] Missing required configuration: {", ".join(missing)}. '
                'Add them to your .env file or database settings.\n'
            ))
            return

        # 2. Check Callback URL format and HTTPS reachability
        self.stdout.write('\n2. Auditing Callback URL...')
        callback_url = creds['callback_url']
        self.stdout.write(f'   Callback Target: {callback_url}')
        cb_problem = mpesa.callback_url_problem(callback_url, check_reachable=True)
        if cb_problem:
            self.stdout.write(self.style.ERROR(f'   [✗] Callback check failed: {cb_problem}'))
            self.stdout.write(self.style.WARNING(
                '   Fix: Ensure ngrok is running and set MPESA_CALLBACK_BASE_URL=https://<your-ngrok>.ngrok-free.app\n'
            ))
        else:
            self.stdout.write(self.style.SUCCESS('   [✓] Callback URL is public HTTPS and reachable!'))

        # 3. Test OAuth Token generation
        self.stdout.write('\n3. Testing Daraja OAuth Token generation...')
        env_name = mpesa.environment(s).upper()
        oauth_url = mpesa.base_url(s) + mpesa.OAUTH_PATH
        self.stdout.write(f'   Environment: {env_name}')
        self.stdout.write(f'   Endpoint: {oauth_url}')
        try:
            token = mpesa.get_access_token(s, force_refresh=True)
            self.stdout.write(self.style.SUCCESS(f'   [✓] OAuth Token obtained successfully! (Length: {len(token)})'))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'   [✗] OAuth token generation failed: {e}'))
            return

        # 4. Probe STK Push Entitlement
        self.stdout.write('\n4. Testing Lipa na M-Pesa (STK Push) product entitlement on Daraja...')
        entitled, status, code, desc, req_id = mpesa.probe_stk_entitlement(s, token)
        if entitled is False:
            self.stdout.write(self.style.ERROR(
                f'   [✗] Safaricom rejected STK Push entitlement: HTTP {status} (Code {code}): {desc}'
            ))
            if code == '404.001.03':
                self.stdout.write(self.style.NOTICE(
                    '\n   [ACTION REQUIRED ON DARAJA PORTAL]:\n'
                    '   Safaricom error 404.001.03 (Invalid Access Token) means your app on\n'
                    '   https://developer.safaricom.co.ke does not have "Lipa na M-Pesa Sandbox" enabled!\n'
                    '   1. Log in to developer.safaricom.co.ke -> My Apps\n'
                    '   2. Create or edit an app and make sure "Lipa na M-Pesa Sandbox" is checked.\n'
                    '   3. Update MPESA_CONSUMER_KEY and MPESA_CONSUMER_SECRET in .env with the new keys.\n'
                ))
            return
        elif entitled is True:
            self.stdout.write(self.style.SUCCESS('   [✓] Daraja App is authorized and entitled to call STK Push!'))
        else:
            self.stdout.write(self.style.WARNING(f'   [?] Entitlement probe returned inconclusive: {desc}'))

        # 5. Optional live STK push test
        phone = options.get('phone', '').strip()
        if phone:
            self.stdout.write(self.style.MIGRATE_HEADING(f'\n5. Sending test KES 1 STK Push to {phone}...'))
            try:
                norm_phone, p_err = mpesa.validate_phone(phone)
                if p_err:
                    self.stdout.write(self.style.ERROR(f'   Invalid phone: {p_err}'))
                    return

                # Create a temporary test order
                order = Order.objects.create(
                    number=Order.next_number(),
                    customer_name='Daraja Test Runner',
                    phone=norm_phone,
                    subtotal=Decimal('1.00'),
                    total=Decimal('1.00'),
                    payment_method='mpesa',
                    status='pending',
                    payment_status='pending'
                )
                payment = Payment.objects.create(
                    order=order,
                    method='mpesa',
                    amount=Decimal('1.00'),
                    phone=norm_phone
                )

                tx, resp = mpesa.stk_push(order, norm_phone)
                payment.transaction_id = tx.checkout_request_id
                payment.reference = tx.merchant_request_id or tx.transaction_id
                payment.status = 'processing'
                payment.save()

                self.stdout.write(self.style.SUCCESS('\n[SUCCESS] STK Push sent successfully! Full Daraja response:'))
                self.stdout.write(json.dumps(resp, indent=2))
                self.stdout.write(f"\nCheckoutRequestID: {tx.checkout_request_id}")
                self.stdout.write(f"MerchantRequestID: {tx.merchant_request_id}")
                self.stdout.write(f"Order Number: {order.number}")
                self.stdout.write(self.style.SUCCESS('Check your phone handset now to enter your PIN!\n'))

            except Exception as e:
                self.stdout.write(self.style.ERROR(f'   STK Push failed: {e}'))
        else:
            self.stdout.write(self.style.NOTICE(
                '\nTo send a live test STK push prompt, run:\n'
                'python manage.py mpesa_check --phone 254708374149\n'
            ))
