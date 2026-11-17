from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from store.models import (Category, DataDeletionAuditLog, InventoryChange,
                          MpesaTransaction, Notification, Order, OrderItem,
                          Payment, Product, UserProfile)


class DataManagementTests(TestCase):
    def setUp(self):
        self.client = Client()

        # 1. Super Admin
        self.super_admin = User.objects.create_superuser(
            username='boss', password='SuperPassword123!', email='boss@example.com'
        )
        UserProfile.objects.create(user=self.super_admin, role='super_admin', status='approved')

        # 2. Regular Admin
        self.admin = User.objects.create_user(
            username='regularadmin', password='Password123!', email='admin@example.com', is_staff=True
        )
        UserProfile.objects.create(user=self.admin, role='admin', status='approved')

        # 3. Customer
        self.customer = User.objects.create_user(
            username='shopper', password='Password123!', email='shopper@example.com'
        )
        UserProfile.objects.create(user=self.customer, role='customer', status='approved')

        # Sample Category and Product
        self.category = Category.objects.create(name='Clothing', slug='clothing')
        self.product = Product.objects.create(
            name='Summer Dress', slug='summer-dress', category=self.category,
            price=Decimal('2500.00'), stock=10, sku='DRS-001'
        )

    def test_permission_enforcement(self):
        url = reverse('manage_data')

        # Anonymous -> redirect to login
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/account/login/', resp.url)

        # Customer -> 403 Forbidden
        self.client.login(username='shopper', password='Password123!')
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 403)
        self.client.logout()

        # Regular Admin -> 403 Forbidden
        self.client.login(username='regularadmin', password='Password123!')
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 403)
        self.client.logout()

        # Super Admin -> 200 OK
        self.client.login(username='boss', password='SuperPassword123!')
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Data Management &amp; Deletion Controls')

    def test_delete_selected_notifications_with_security_verification(self):
        self.client.login(username='boss', password='SuperPassword123!')

        n1 = Notification.objects.create(title='Alert 1', for_staff=True)
        n2 = Notification.objects.create(title='Alert 2', for_staff=True)
        n3 = Notification.objects.create(title='Alert 3', for_staff=True)

        url = reverse('manage_data_delete', args=['notifications'])

        # 1. Fail: Wrong Password
        resp = self.client.post(url, {
            'selection_mode': 'selected',
            'selected_ids': [n1.id, n2.id],
            'confirm_text': 'DELETE',
            'password': 'WrongPassword!',
        }, follow=True)
        self.assertContains(resp, 'Incorrect Super Admin password')
        self.assertEqual(Notification.objects.count(), 3)

        # 2. Fail: Missing or wrong confirm phrase
        resp = self.client.post(url, {
            'selection_mode': 'selected',
            'selected_ids': [n1.id, n2.id],
            'confirm_text': 'NOT_DELETE',
            'password': 'SuperPassword123!',
        }, follow=True)
        self.assertContains(resp, 'was not typed correctly')
        self.assertEqual(Notification.objects.count(), 3)

        # 3. Success: Valid password and confirmation
        resp = self.client.post(url, {
            'selection_mode': 'selected',
            'selected_ids': [n1.id, n2.id],
            'confirm_text': 'DELETE',
            'password': 'SuperPassword123!',
        }, follow=True)
        self.assertContains(resp, 'Successfully deleted 2 Notifications record(s)')
        self.assertEqual(Notification.objects.count(), 1)
        self.assertEqual(Notification.objects.first().id, n3.id)

        # Verify audit log creation
        audit = DataDeletionAuditLog.objects.filter(data_type='notifications').first()
        self.assertIsNotNone(audit)
        self.assertEqual(audit.records_deleted, 2)
        self.assertEqual(audit.actor_username, 'boss')

    def test_delete_orders_and_cascade(self):
        self.client.login(username='boss', password='SuperPassword123!')

        order = Order.objects.create(
            number='RB-TEST-001', customer_name='Jane Doe', email='jane@example.com',
            total=Decimal('2500.00'), status='cancelled'
        )
        item = OrderItem.objects.create(
            order=order, product=self.product, product_name=self.product.name,
            quantity=1, price=Decimal('2500.00')
        )
        payment = Payment.objects.create(
            order=order, method='cash', status='completed', amount=Decimal('2500.00')
        )

        url = reverse('manage_data_delete', args=['orders'])
        resp = self.client.post(url, {
            'selection_mode': 'selected',
            'selected_ids': [order.id],
            'confirm_text': 'DELETE',
            'password': 'SuperPassword123!',
        }, follow=True)

        self.assertContains(resp, 'Successfully deleted 1 Orders (All) record(s)')
        self.assertFalse(Order.objects.filter(id=order.id).exists())
        self.assertFalse(OrderItem.objects.filter(id=item.id).exists())
        self.assertFalse(Payment.objects.filter(id=payment.id).exists())

    def test_user_deletion_anonymizes_orders_and_protects_super_admin(self):
        self.client.login(username='boss', password='SuperPassword123!')

        # Create an order under customer
        order = Order.objects.create(
            number='RB-CUST-001', user=self.customer, customer_name='Shopper Doe',
            email='shopper@example.com', total=Decimal('5000.00'), status='paid'
        )

        url = reverse('manage_data_delete', args=['users'])

        # Attempting to delete logged-in Super Admin is blocked
        resp = self.client.post(url, {
            'selection_mode': 'selected',
            'selected_ids': [self.super_admin.id],
            'confirm_text': 'DELETE',
            'password': 'SuperPassword123!',
        }, follow=True)
        self.assertContains(resp, 'Action blocked: Super Admin accounts cannot be deleted')
        self.assertTrue(User.objects.filter(id=self.super_admin.id).exists())

        # Deleting customer account works and anonymizes order
        resp = self.client.post(url, {
            'selection_mode': 'selected',
            'selected_ids': [self.customer.id],
            'confirm_text': 'DELETE',
            'password': 'SuperPassword123!',
        }, follow=True)

        self.assertContains(resp, 'Successfully deleted 1 User Accounts record(s)')
        self.assertFalse(User.objects.filter(id=self.customer.id).exists())

        # Order must still exist with user=None and customer_name marked Anonymized
        order.refresh_from_db()
        self.assertIsNone(order.user)
        self.assertIn('(Anonymized Account)', order.customer_name)
        self.assertEqual(order.total, Decimal('5000.00'))

    def test_delete_mpesa_transactions_any_status(self):
        self.client.login(username='boss', password='SuperPassword123!')

        tx1 = MpesaTransaction.objects.create(
            transaction_id='TX1', phone='254712345678', amount=Decimal('100.00'),
            status='failed', checkout_request_id='cr1'
        )
        tx2 = MpesaTransaction.objects.create(
            transaction_id='TX2', phone='254712345679', amount=Decimal('200.00'),
            status='completed', checkout_request_id='cr2'
        )

        url = reverse('manage_data_delete', args=['mpesa_transactions'])
        resp = self.client.post(url, {
            'selection_mode': 'selected',
            'selected_ids': [tx1.id, tx2.id],
            'confirm_text': 'DELETE',
            'password': 'SuperPassword123!',
        }, follow=True)

        self.assertContains(resp, 'Successfully deleted 2 M-Pesa Transactions record(s)')
        self.assertEqual(MpesaTransaction.objects.count(), 0)
