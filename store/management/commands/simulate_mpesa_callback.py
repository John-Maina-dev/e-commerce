"""Simulate a Daraja STK Push callback for an order in local development.

Usage:
    python manage.py simulate_mpesa_callback <order_number>
    python manage.py simulate_mpesa_callback <order_number> --fail
"""
from decimal import Decimal
import json
import uuid
from django.core.management.base import BaseCommand
from django.test import RequestFactory
from django.utils import timezone
from store.models import Order, MpesaTransaction
from store.views import mpesa_callback


class Command(BaseCommand):
    help = 'Simulates an incoming Safaricom Daraja STK Push callback.'

    def add_arguments(self, parser):
        parser.add_argument('order_number', type=str, help='The order number (e.g. RB-261106-764954)')
        parser.add_argument('--fail', action='store_true', help='Simulate user cancelled / failed payment')

    def handle(self, *args, **options):
        number = options['order_number']
        simulate_failure = options['fail']

        order = Order.objects.filter(number=number).first()
        if not order:
            self.stderr.write(self.style.ERROR(f'Order {number} not found.'))
            return

        tx = order.mpesa_transactions.order_by('-created_at').first()
        if not tx:
            # Create a mock pending transaction if none exists
            checkout_id = f"ws_CO_MOCK_{uuid.uuid4().hex[:12]}"
            tx = MpesaTransaction.objects.create(
                transaction_id=f"TXN-{timezone.now().strftime('%Y%m%d%H%M%S')}",
                order=order,
                phone=order.phone or "254700000000",
                amount=order.total,
                status="sent",
                checkout_request_id=checkout_id,
            )
            self.stdout.write(f"Created mock transaction with CheckoutRequestID: {checkout_id}")
        else:
            checkout_id = tx.checkout_request_id
            if not checkout_id:
                checkout_id = f"ws_CO_MOCK_{uuid.uuid4().hex[:12]}"
                tx.checkout_request_id = checkout_id
                tx.save(update_fields=['checkout_request_id'])

        if simulate_failure:
            callback_body = {
                "Body": {
                    "stkCallback": {
                        "MerchantRequestID": "MOCK-MERCHANT-REQ",
                        "CheckoutRequestID": checkout_id,
                        "ResultCode": 1032,
                        "ResultDesc": "Request cancelled by user."
                    }
                }
            }
        else:
            receipt = f"QGH{uuid.uuid4().hex[:7].upper()}"
            callback_body = {
                "Body": {
                    "stkCallback": {
                        "MerchantRequestID": "MOCK-MERCHANT-REQ",
                        "CheckoutRequestID": checkout_id,
                        "ResultCode": 0,
                        "ResultDesc": "The service request is processed successfully.",
                        "CallbackMetadata": {
                            "Item": [
                                {"Name": "Amount", "Value": float(order.total)},
                                {"Name": "MpesaReceiptNumber", "Value": receipt},
                                {"Name": "TransactionDate", "Value": timezone.now().strftime('%Y%m%d%H%M%S')},
                                {"Name": "PhoneNumber", "Value": int(order.phone or "254708374149")}
                            ]
                        }
                    }
                }
            }

        factory = RequestFactory()
        request = factory.post(
            '/payments/mpesa/callback/',
            data=json.dumps(callback_body),
            content_type='application/json'
        )

        response = mpesa_callback(request)
        self.stdout.write(self.style.SUCCESS(
            f"Callback dispatched! Response: {response.status_code} - {response.content.decode()}"
        ))

        order.refresh_from_db()
        self.stdout.write(f"Updated Order Status: {order.status} | Payment Status: {order.payment_status}")
