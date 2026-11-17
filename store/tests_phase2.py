from decimal import Decimal
import json

from django.contrib.auth.models import User
from django.test import TestCase, Client
from django.urls import reverse

from store import pos
from store.models import Category, Order, Payment, PosSession, Product, SiteSettings, UserProfile
from store.receipt_pdf import generate_receipt_pdf


class PosPhase2Tests(TestCase):
    def setUp(self):
        self.client = Client()
        self.settings = SiteSettings.get()
        self.settings.tax_enabled = True
        self.settings.tax_rate = Decimal('16.00')
        self.settings.mpesa_enabled = True
        self.settings.mpesa_consumer_key = 'test_key'
        self.settings.mpesa_consumer_secret = 'test_secret'
        self.settings.mpesa_shortcode = '174379'
        self.settings.mpesa_passkey = 'test_passkey'
        self.settings.mpesa_callback_url = 'https://ngrok.test/payments/mpesa/callback/'
        self.settings.save()

        # Create cashier staff user
        self.cashier = User.objects.create_user(
            username='cashier_jane', email='jane@reeves.com', password='CashierPass123!',
            first_name='Jane', last_name='Doe', is_staff=True, is_active=True
        )
        self.cashier_profile, _ = UserProfile.objects.get_or_create(
            user=self.cashier, defaults={'role': UserProfile.ROLE_CASHIER, 'status': UserProfile.STATUS_APPROVED}
        )

        # Create product category
        self.category = Category.objects.create(name='Apparel', slug='apparel')

        # Create products with SKU and barcodes
        self.prod_shirt = Product.objects.create(
            name='Silk Button Shirt',
            slug='silk-button-shirt',
            category=self.category,
            sku='SHIRT-SILK-01',
            barcode='6161109876543',
            price=Decimal('1000.00'),
            cost_price=Decimal('600.00'),
            stock=50,
            active=True
        )
        self.prod_shoes = Product.objects.create(
            name='Leather Loafers',
            slug='leather-loafers',
            category=self.category,
            sku='SHOE-LOAF-42',
            barcode='6161101234567',
            price=Decimal('2500.00'),
            cost_price=Decimal('1500.00'),
            stock=10,
            active=True
        )

        # Open a POS session for the cashier
        self.session, _ = pos.open_session(self.cashier, opening_cash=Decimal('2000.00'))

    def test_barcode_lookup_and_scan_api(self):
        """Hardware barcode scanners query exact barcode or SKU."""
        # 1. Lookup by barcode
        p1 = pos.lookup_barcode('6161109876543')
        self.assertIsNotNone(p1)
        self.assertEqual(p1.pk, self.prod_shirt.pk)

        # 2. Lookup by SKU
        p2 = pos.lookup_barcode('SHOE-LOAF-42')
        self.assertIsNotNone(p2)
        self.assertEqual(p2.pk, self.prod_shoes.pk)

        # 3. Barcode scan view
        self.client.force_login(self.cashier)
        resp = self.client.get(reverse('pos_barcode_scan') + '?code=6161109876543')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['ok'])
        self.assertEqual(data['product']['id'], self.prod_shirt.pk)
        self.assertEqual(data['product']['barcode'], '6161109876543')

        # 4. Unknown barcode
        resp_404 = self.client.get(reverse('pos_barcode_scan') + '?code=0000000000000')
        self.assertEqual(resp_404.status_code, 404)

    def test_customer_search_and_quick_create_api(self):
        """Cashiers can search customers and register a new customer without leaving the till."""
        self.client.force_login(self.cashier)

        # Create an existing customer
        cust_user = User.objects.create_user(
            username='alice_w', email='alice@example.com', password='Pass!',
            first_name='Alice', last_name='Wanjiku', is_active=True
        )
        UserProfile.objects.create(user=cust_user, role='customer', status='approved', phone='0722111222')

        # 1. Customer search
        resp = self.client.get(reverse('pos_customer_search') + '?q=Alice')
        self.assertEqual(resp.status_code, 200)
        customers = resp.json()['customers']
        self.assertTrue(any(c['name'] == 'Alice Wanjiku' and c['phone'] == '0722111222' for c in customers))

        # 2. Customer quick create
        create_payload = {
            'name': 'Brian Omondi',
            'phone': '0711999888',
            'email': 'brian@example.com'
        }
        create_resp = self.client.post(
            reverse('pos_customer_create'),
            data=json.dumps(create_payload),
            content_type='application/json'
        )
        self.assertEqual(create_resp.status_code, 200)
        c_data = create_resp.json()
        self.assertTrue(c_data['ok'])
        self.assertEqual(c_data['customer']['name'], 'Brian Omondi')
        self.assertEqual(c_data['customer']['phone'], '0711999888')

        # Verify DB records
        created_user = User.objects.get(pk=c_data['customer']['id'])
        self.assertEqual(created_user.profile.role, UserProfile.ROLE_CUSTOMER)
        self.assertEqual(created_user.profile.status, UserProfile.STATUS_APPROVED)

    def test_tax_calculation_in_pos_sale(self):
        """SiteSettings.tax_enabled and tax_rate are accurately computed for POS orders."""
        order, created = pos.create_pos_sale(
            user=self.cashier,
            items_payload=[{'id': self.prod_shirt.pk, 'quantity': 2}], # 2 * 1000 = 2000
            payment_method='cash',
            cash_received=Decimal('2500.00'),
            discount=Decimal('0.00')
        )
        self.assertTrue(created)
        self.assertEqual(order.subtotal, Decimal('2000.00'))
        # 16% tax on 2,000 = 320.00
        self.assertEqual(order.tax, Decimal('320.00'))
        # Total = 2,000 + 320 = 2,320.00
        self.assertEqual(order.total, Decimal('2320.00'))

    def test_cash_sale_with_change_calculation(self):
        """Cash checkout calculates change correctly and deduces live inventory."""
        initial_stock = self.prod_shirt.stock
        order, created = pos.create_pos_sale(
            user=self.cashier,
            items_payload=[{'id': self.prod_shirt.pk, 'quantity': 1}], # 1000 + 160 tax = 1160
            payment_method='cash',
            cash_received=Decimal('1500.00')
        )
        self.assertEqual(order.status, 'confirmed')
        self.assertEqual(order.payment_status, 'paid')
        self.assertEqual(order.total, Decimal('1160.00'))

        payment = order.payments.first()
        self.assertIsNotNone(payment)
        self.assertEqual(payment.method, 'manual')
        self.assertEqual(payment.amount, Decimal('1160.00'))
        self.assertEqual(payment.amount_paid, Decimal('1500.00'))
        self.assertEqual(payment.change_given, Decimal('340.00'))

        # Verify stock decreased
        self.prod_shirt.refresh_from_db()
        self.assertEqual(self.prod_shirt.stock, initial_stock - 1)

    def test_bank_transfer_sale(self):
        """Bank transfer settles synchronously and stores reference."""
        order, created = pos.create_pos_sale(
            user=self.cashier,
            items_payload=[{'id': self.prod_shirt.pk, 'quantity': 1}],
            payment_method='bank',
            bank_reference='KCB-TXN-9988'
        )
        self.assertEqual(order.status, 'confirmed')
        self.assertEqual(order.payment_status, 'paid')
        self.assertEqual(order.pos_payment_method, 'bank')

        payment = order.payments.first()
        self.assertEqual(payment.method, 'bank')
        self.assertEqual(payment.reference, 'KCB-TXN-9988')
        self.assertEqual(payment.status, 'paid')

    def test_card_payment_sale(self):
        """Card payment settles synchronously and stores authorization code."""
        order, created = pos.create_pos_sale(
            user=self.cashier,
            items_payload=[{'id': self.prod_shirt.pk, 'quantity': 1}],
            payment_method='card',
            card_reference='AUTH-12345'
        )
        self.assertEqual(order.status, 'confirmed')
        self.assertEqual(order.payment_status, 'paid')
        self.assertEqual(order.pos_payment_method, 'card')

        payment = order.payments.first()
        self.assertEqual(payment.method, 'card')
        self.assertEqual(payment.reference, 'AUTH-12345')

    def test_split_payment_cash_and_card(self):
        """Multi-tender split payment across Cash and Card settles immediately."""
        # Total with tax: 1 shirt = 1000 + 160 tax = 1160.00
        total = Decimal('1160.00')
        tenders = [
            {'method': 'cash', 'amount': Decimal('500.00'), 'cash_received': Decimal('600.00')},
            {'method': 'card', 'amount': Decimal('660.00'), 'reference': 'CARD-AUTH-99'}
        ]
        order, created = pos.create_pos_sale(
            user=self.cashier,
            items_payload=[{'id': self.prod_shirt.pk, 'quantity': 1}],
            payment_method='split',
            tenders_payload=tenders
        )
        self.assertEqual(order.status, 'confirmed')
        self.assertEqual(order.payment_status, 'paid')
        self.assertEqual(order.total, total)

        # Check payments
        self.assertEqual(order.payments.count(), 2)
        cash_pay = order.payments.filter(method='manual').first()
        self.assertEqual(cash_pay.amount, Decimal('500.00'))
        self.assertEqual(cash_pay.amount_paid, Decimal('600.00'))
        self.assertEqual(cash_pay.change_given, Decimal('100.00'))

        card_pay = order.payments.filter(method='card').first()
        self.assertEqual(card_pay.amount, Decimal('660.00'))
        self.assertEqual(card_pay.reference, 'CARD-AUTH-99')

    def test_session_report_with_split_payments(self):
        """Session report reconciles cash drawer accurately including split cash tenders."""
        # Sale 1: Pure cash 1160 (cash 1160)
        pos.create_pos_sale(
            user=self.cashier,
            items_payload=[{'id': self.prod_shirt.pk, 'quantity': 1}],
            payment_method='cash',
            cash_received=Decimal('1160.00')
        )
        # Sale 2: Split tender (cash 500 + card 660)
        tenders = [
            {'method': 'cash', 'amount': Decimal('500.00'), 'cash_received': Decimal('500.00')},
            {'method': 'card', 'amount': Decimal('660.00'), 'reference': 'CARD-1'}
        ]
        pos.create_pos_sale(
            user=self.cashier,
            items_payload=[{'id': self.prod_shirt.pk, 'quantity': 1}],
            payment_method='split',
            tenders_payload=tenders
        )

        rep = pos.session_report(self.session)
        self.assertEqual(rep['orders'], 2)
        # Expected cash = opening float (2000) + pure cash (1160) + split cash (500) = 3660.00
        self.assertEqual(rep['expected_cash'], Decimal('3660.00'))
        self.assertEqual(rep['by_method']['cash']['total'], Decimal('1660.00'))
        self.assertEqual(rep['by_method']['card']['total'], Decimal('660.00'))

    def test_pdf_receipt_generation_and_view(self):
        """ReportLab PDF receipt generation runs cleanly and produces valid PDF bytes."""
        order, _ = pos.create_pos_sale(
            user=self.cashier,
            items_payload=[{'id': self.prod_shirt.pk, 'quantity': 1}],
            payment_method='cash',
            cash_received=Decimal('1500.00')
        )
        # 1. 80mm PDF
        pdf_80 = generate_receipt_pdf(order, size='80')
        self.assertGreater(len(pdf_80.getvalue()), 1000)
        self.assertTrue(pdf_80.getvalue().startswith(b'%PDF'))

        # 2. 58mm PDF
        pdf_58 = generate_receipt_pdf(order, size='58')
        self.assertGreater(len(pdf_58.getvalue()), 1000)
        self.assertTrue(pdf_58.getvalue().startswith(b'%PDF'))

        # 3. HTTP View
        self.client.force_login(self.cashier)
        resp = self.client.get(reverse('receipt_pdf', args=[order.number]))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp['Content-Type'], 'application/pdf')

    def test_pos_dashboard_and_customer_display_views(self):
        """Staff can load the POS Analytics Dashboard and Standalone Customer Display."""
        self.client.force_login(self.cashier)

        # 1. Dashboard
        resp_dash = self.client.get(reverse('pos_dashboard'))
        self.assertEqual(resp_dash.status_code, 200)
        self.assertContains(resp_dash, 'POS Dashboard')

        # 2. Standalone Customer Display Screen
        resp_disp = self.client.get(reverse('pos_customer_display'))
        self.assertEqual(resp_disp.status_code, 200)
        self.assertContains(resp_disp, 'Customer Display')
        self.assertContains(resp_disp, 'Scanned Items')
