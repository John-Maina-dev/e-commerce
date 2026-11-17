from io import BytesIO

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import Client, TestCase
from django.urls import reverse

from store.models import NewsletterSubscriber, ProductImage, SiteSettings
from store.services import validate_image_upload
from store.tests.test_models import make_category, make_product


def tiny_png():
    from PIL import Image
    buf = BytesIO()
    Image.new('RGB', (4, 4), color='red').save(buf, format='PNG')
    buf.seek(0)
    return buf


class OpenRedirectTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username='jane', password='TestPass123!')
        self.product = make_product(price='1000.00', stock=5)

    def _assert_not_external(self, resp):
        self.assertTrue(resp.url.startswith('/'))
        self.assertFalse(resp.url.startswith('//'))

    def test_login_next_blocked_when_external(self):
        resp = self.client.post(reverse('login'),
                                {'username': 'jane', 'password': 'TestPass123!',
                                 'next': 'https://evil.example.com/phish'})
        self.assertRedirects(resp, reverse('account'))

    def test_login_next_blocked_when_protocol_relative(self):
        resp = self.client.post(reverse('login'),
                                {'username': 'jane', 'password': 'TestPass123!',
                                 'next': '//evil.example.com/phish'})
        self.assertRedirects(resp, reverse('account'))

    def test_login_next_allowed_when_relative(self):
        resp = self.client.post(reverse('login'),
                                {'username': 'jane', 'password': 'TestPass123!',
                                 'next': '/account/profile/'})
        self.assertRedirects(resp, '/account/profile/')

    def test_cart_add_next_blocked_when_external(self):
        resp = self.client.post(reverse('cart_add', args=[self.product.pk]),
                                {'quantity': 1, 'next': 'https://evil.example.com/phish'})
        self.assertRedirects(resp, reverse('cart'))

    def test_wishlist_next_blocked_when_external(self):
        self.client.login(username='jane', password='TestPass123!')
        resp = self.client.post(reverse('wishlist_toggle', args=[self.product.pk]),
                                {'next': 'https://evil.example.com/phish'})
        self.assertRedirects(resp, reverse('wishlist'))

    def test_newsletter_next_blocked_when_external(self):
        resp = self.client.post(reverse('newsletter'),
                                {'email': 'n@example.com', 'next': 'https://evil.example.com/phish'})
        self.assertRedirects(resp, reverse('home'))


class ManageRedirectTests(TestCase):
    def setUp(self):
        self.product = make_product(price='1000.00', stock=5)
        self.staff = Client()
        User.objects.create_superuser(username='admin', email='a@b.com', password='TestPass123!')
        self.staff.login(username='admin', password='TestPass123!')

    def test_product_action_next_blocked_when_external(self):
        resp = self.staff.post(reverse('product_action', args=[self.product.pk]),
                               {'action': 'hide', 'next': 'https://evil.example.com/phish'})
        self.assertRedirects(resp, reverse('manage_products'))

    def test_inventory_update_next_blocked_when_external(self):
        resp = self.staff.post(reverse('inventory_update'),
                               {'product_id': self.product.pk, 'stock': 4,
                                'next': 'https://evil.example.com/phish'})
        self.assertRedirects(resp, reverse('inventory'))


class NewsletterValidationTests(TestCase):
    def test_invalid_email_not_subscribed(self):
        resp = self.client.post(reverse('newsletter'), {'email': 'not-an-email'})
        self.assertRedirects(resp, reverse('home'))
        self.assertFalse(NewsletterSubscriber.objects.exists())


class UploadValidationTests(TestCase):
    def setUp(self):
        self.staff = Client()
        User.objects.create_superuser(username='admin', email='a@b.com', password='TestPass123!')
        self.staff.login(username='admin', password='TestPass123!')
        self.category = make_category('Shoes')
        self.product = make_product(name='Boots', category=self.category, sku='B-1', price='5000.00', stock=3)

    def _text_upload(self, name='evil.html'):
        from django.core.files.uploadedfile import SimpleUploadedFile
        return SimpleUploadedFile(name, b'<script>alert(1)</script>', content_type='text/html')

    def test_branding_upload_rejects_non_image(self):
        s = SiteSettings.get()
        resp = self.staff.post(reverse('manage_settings'), {'logo': self._text_upload()})
        self.assertRedirects(resp, reverse('manage_settings'))
        s.refresh_from_db()
        self.assertFalse(s.logo)

    def test_branding_upload_rejects_svg(self):
        s = SiteSettings.get()
        resp = self.staff.post(reverse('manage_settings'), {'banner': self._text_upload('banner.svg')})
        self.assertRedirects(resp, reverse('manage_settings'))
        s.refresh_from_db()
        self.assertFalse(s.banner)

    def test_branding_upload_accepts_valid_image(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        s = SiteSettings.get()
        resp = self.staff.post(reverse('manage_settings'),
                               {'logo': SimpleUploadedFile('logo.png', tiny_png().read(),
                                                          content_type='image/png')})
        self.assertRedirects(resp, reverse('manage_settings'))
        s.refresh_from_db()
        self.assertTrue(s.logo)

    def test_extra_product_image_rejects_non_image(self):
        self.staff.post(reverse('product_edit', args=[self.product.pk]),
                        {'images': [self._text_upload()]})
        self.assertFalse(ProductImage.objects.filter(product=self.product).exists())

    def test_validate_image_upload_rejects_oversized(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        big = SimpleUploadedFile('big.png', b'x' * (5 * 1024 * 1024 + 1),
                                 content_type='image/png')
        with self.assertRaises(ValidationError):
            validate_image_upload(big)


class AdminSecretMaskingTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_superuser(username='root', email='root@example.com',
                                                 password='TestPass123!')
        self.client.login(username='root', password='TestPass123!')
        s = SiteSettings.get()
        s.smtp_password = 'SMTP_SECRET_1'
        s.mpesa_consumer_key = 'KEY_2'
        s.mpesa_consumer_secret = 'SECRET_3'
        s.mpesa_passkey = 'PASSKEY_4'
        s.save()
        self.pk = s.pk

    def test_admin_site_settings_masks_secrets(self):
        resp = self.client.get(reverse('admin:store_sitesettings_change', args=[self.pk]))
        self.assertEqual(resp.status_code, 200)
        for secret in ('SMTP_SECRET_1', 'KEY_2', 'SECRET_3', 'PASSKEY_4'):
            self.assertNotContains(resp, secret)
        self.assertContains(resp, '********')
