"""Check stuck M-Pesa payments that never received a callback.

Run manually or via cron when payments are stuck in 'processing' or 'sent'
status for too long. Queries Daraja TransactionStatusQuery to determine
the actual state and updates Payment / Order accordingly.

Usage:
    python manage.py check_mpesa_timeouts
    python manage.py check_mpesa_timeouts --minutes 10
"""
import logging
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from store import mpesa, notify, services
from store.models import MpesaTransaction, Order, Payment, SiteSettings

logger = logging.getLogger('store')


class Command(BaseCommand):
    help = 'Query Daraja for M-Pesa payments stuck without a callback.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--minutes', type=int, default=5,
            help='Only check transactions older than N minutes (default: 5).')

    def handle(self, *args, **options):
        minutes = options['minutes']
        cutoff = timezone.now() - timedelta(minutes=minutes)

        stuck = MpesaTransaction.objects.select_related('order').filter(
            status__in=('sent',),
            created_at__lt=cutoff,
            checkout_request_id__isnull=False,
        ).exclude(checkout_request_id='')

        if not stuck.exists():
            self.stdout.write(self.style.SUCCESS('No stuck M-Pesa transactions found.'))
            return

        s = SiteSettings.get()
        self.stdout.write(f'Found {stuck.count()} stuck transaction(s) older than {minutes} min.')

        for tx in stuck:
            self._process_transaction(tx, s)

    def _process_transaction(self, tx, s):
        self.stdout.write(f'  Checking {tx.transaction_id} (checkout: {tx.checkout_request_id})...')
        try:
            data = mpesa.query_stk_status(s, tx.checkout_request_id)
        except Exception as e:
            self.stdout.write(self.style.WARNING(f'    Query failed: {e}'))
            logger.error('Timeout query failed for %s: %s', tx.transaction_id, e)
            return

        result_code = str(data.get('ResultCode', ''))
        result_desc = data.get('ResultDesc', '')
        self.stdout.write(f'    ResultCode={result_code} ResultDesc={result_desc[:80]}')

        if result_code == '0':
            # Payment succeeded but callback was lost — process it now.
            self._handle_success(tx, data)
        elif result_code in ('1032', '1037'):
            # 1032 = user timed out on the prompt; 1037 = no callback yet.
            # Mark as timed out so the order is not stuck forever.
            self._handle_timeout(tx, result_code, result_desc)
        else:
            # Other failure codes.
            self._handle_failure(tx, result_code, result_desc)

    @transaction.atomic
    def _handle_success(self, tx, data):
        """Process a successful payment that was discovered via timeout query."""
        if tx.status == 'completed':
            self.stdout.write('    Already completed — skipping.')
            return

        # Extract metadata from the query response.
        metadata = {}
        for item in (data.get('ResultParameters', {}) or {}).get('ResultParameter', []):
            if 'Key' in item:
                metadata[item['Key']] = item.get('Value')

        tx.status = 'completed'
        tx.mpesa_receipt = str(metadata.get('MpesaReceiptNumber', '') or tx.mpesa_receipt or '')
        tx.transaction_date = str(metadata.get('TransactionDate', '') or tx.transaction_date or '')
        tx.result_code = '0'
        tx.result_description = 'Confirmed via timeout query.'
        tx.save()

        order = tx.order
        if not order:
            self.stdout.write(self.style.WARNING('    No order attached — cannot process.'))
            return

        payment = services.get_or_create_payment(order, 'mpesa')
        if payment.status == 'paid':
            self.stdout.write('    Payment already marked paid — skipping.')
            return

        services.mark_order_paid(
            order, method='mpesa', reference=tx.mpesa_receipt,
            verification='gateway', transaction_id=tx.checkout_request_id,
            result_code='0', result_description='Confirmed via timeout query.')
        notify.payment_received(order, tx.mpesa_receipt)
        self.stdout.write(self.style.SUCCESS(f'    Payment confirmed for order {order.number}.'))

    @transaction.atomic
    def _handle_timeout(self, tx, result_code, result_desc):
        """Mark a timed-out payment."""
        if tx.status in ('completed', 'failed', 'timeout'):
            return
        tx.status = 'timeout'
        tx.result_code = result_code
        tx.result_description = result_desc
        tx.save()
        if tx.order:
            order = tx.order
            services.mark_order_payment_failed(
                order, method='mpesa', status='timeout',
                result_code=result_code, result_description=result_desc,
                note='Customer did not complete the M-Pesa prompt (timeout).')
            notify.payment_failed(order, 'Payment timed out — the prompt was not completed.', cancelled=True)
        self.stdout.write(self.style.WARNING(f'    Marked as timed out.'))

    @transaction.atomic
    def _handle_failure(self, tx, result_code, result_desc):
        """Mark a failed payment."""
        if tx.status in ('completed', 'failed'):
            return
        tx.status = 'failed'
        tx.result_code = result_code
        tx.result_description = result_desc
        tx.save()
        if tx.order:
            order = tx.order
            services.mark_order_payment_failed(
                order, method='mpesa', status='failed',
                result_code=result_code, result_description=result_desc,
                note=f'M-Pesa query returned failure: {result_desc[:200]}')
            notify.payment_failed(order, result_desc[:200])
        self.stdout.write(self.style.WARNING(f'    Marked as failed.'))
