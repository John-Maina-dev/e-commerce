from decimal import Decimal
from unittest import mock

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse

from store.models import Category, NewsletterSubscriber, Notification, Product, UserProfile
from store.services import notify_subscribers_new_arrival


class SubscriptionTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username='subscriberuser', password='Password123!', email='sub@example.com')
        UserProfile.objects.create(user=self.user, role='customer', status='approved')

        self.category = Category.objects.create(name='Shoes', slug='shoes')

    def test_subscribe_flow_standard_and_ajax(self):
        url = reverse('newsletter')

        # 1. Invalid email
        resp = self.client.post(url, {'email': 'invalid-email'}, follow=True)
        self.assertContains(resp, 'Please enter a valid email address')
        self.assertEqual(NewsletterSubscriber.objects.count(), 0)

        # 2. Standard subscription
        resp = self.client.post(url, {'email': 'newuser@example.com'}, follow=True)
        self.assertContains(resp, 'Thank you for subscribing')
        self.assertEqual(NewsletterSubscriber.objects.count(), 1)
        sub = NewsletterSubscriber.objects.first()
        self.assertEqual(sub.email, 'newuser@example.com')
        self.assertTrue(sub.active)
        self.assertTrue(len(sub.unsubscribe_token) >= 32)

        # 3. Duplicate active subscription
        resp = self.client.post(url, {'email': 'newuser@example.com'}, follow=True)
        self.assertContains(resp, 'already subscribed')
        self.assertEqual(NewsletterSubscriber.objects.count(), 1)

        # 4. AJAX subscription
        resp = self.client.post(
            url, {'email': 'ajaxuser@example.com'},
            headers={'x-requested-with': 'XMLHttpRequest'}
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data['status'], 'ok')
        self.assertIn('Thank you for subscribing', data['message'])
        self.assertEqual(NewsletterSubscriber.objects.count(), 2)

    def test_unsubscribe_and_resubscribe_flow(self):
        sub = NewsletterSubscriber.objects.create(email='unsub@example.com')
        unsub_url = reverse('newsletter_unsubscribe', args=[sub.unsubscribe_token])

        # 1. Click unsubscribe link
        resp = self.client.get(unsub_url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'You have been unsubscribed')
        sub.refresh_from_db()
        self.assertFalse(sub.active)

        # 2. Click resubscribe button
        resp = self.client.post(unsub_url, {'action': 'resubscribe'})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Subscription restored')
        sub.refresh_from_db()
        self.assertTrue(sub.active)

        # 3. Invalid token
        bad_url = reverse('newsletter_unsubscribe', args=['nonexistent-token'])
        resp = self.client.get(bad_url)
        self.assertContains(resp, 'Invalid or expired unsubscribe link')

    def test_account_subscription_management(self):
        self.client.login(username='subscriberuser', password='Password123!')
        url = reverse('account_subscription')

        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'New Arrival Alerts &amp; Subscriptions')

        # Toggle pause/active
        resp = self.client.post(url, {'action': 'toggle'}, follow=True)
        sub = NewsletterSubscriber.objects.get(email='sub@example.com')
        self.assertFalse(sub.active)

        # Update category preferences
        resp = self.client.post(url, {'action': 'categories', 'categories': [self.category.id]}, follow=True)
        sub.refresh_from_db()
        self.assertFalse(sub.all_categories)
        self.assertIn(self.category, sub.categories.all())

    def test_new_arrival_notification_fires_only_once(self):
        # Create active subscriber linked to a registered account
        sub = NewsletterSubscriber.objects.create(
            email='sub@example.com', user=self.user, active=True, all_categories=True
        )

        product = Product.objects.create(
            name='Designer Heels', slug='designer-heels', category=self.category,
            price=Decimal('7500.00'), stock=5, sku='HLS-001', is_new=True
        )

        # First call: triggers notifications
        with mock.patch('store.emails.send_html_email', return_value=True):
            count = notify_subscribers_new_arrival(product)

        self.assertEqual(count, 1)
        product.refresh_from_db()
        self.assertTrue(product.subscribers_notified)

        # In-app notification created for registered subscriber
        notif = Notification.objects.filter(user=self.user, category='product').first()
        self.assertIsNotNone(notif)
        self.assertIn('New Arrival: Designer Heels', notif.title)

        # Second call (e.g. subsequent product edit): MUST NOT re-notify
        count2 = notify_subscribers_new_arrival(product)
        self.assertEqual(count2, 0)
        self.assertEqual(Notification.objects.filter(user=self.user, category='product').count(), 1)

    def test_subscribers_export_csv(self):
        NewsletterSubscriber.objects.create(email='csv1@example.com', active=True)
        NewsletterSubscriber.objects.create(email='csv2@example.com', active=False)

        # Staff user
        staff = User.objects.create_user(username='staffmember', password='Password123!', email='st@example.com', is_staff=True)
        UserProfile.objects.create(user=staff, role='admin', status='approved')
        self.client.login(username='staffmember', password='Password123!')

        resp = self.client.get(reverse('subscribers_export_csv'))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp['Content-Type'], 'text/csv')
        content = resp.content.decode('utf-8')
        self.assertIn('Email,Active,Confirmed', content)
        self.assertIn('csv1@example.com', content)
        self.assertIn('csv2@example.com', content)
