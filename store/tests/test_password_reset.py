import re
from unittest import mock

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse

from store.models import SiteSettings
from store.tokens import site_token_generator

RESET_URL = 'account/reset/([0-9A-Za-z_\\-=]+)/([0-9A-Za-z_\\-]+)/'
DONE_URL = '/account/password-reset/done/'


def make_user(username='jane', email='jane@example.com', password='OldPass123!'):
    return User.objects.create_user(username=username, email=email, password=password)


def enable_smtp(**overrides):
    s = SiteSettings.get()
    s.smtp_enabled = True
    s.smtp_host = 'smtp.gmail.com'
    s.smtp_port = 587
    s.smtp_username = 'store@example.com'
    s.smtp_password = 'app-password'
    s.smtp_from_email = 'noreply@store.com'
    s.smtp_sender_name = 'Reeves Boutique'
    for k, v in overrides.items():
        setattr(s, k, v)
    s.save()
    return s


class CaptureMail:
    """Patches EmailMultiAlternatives and captures what would be sent."""

    def __init__(self):
        self.message = None
        self.args = None
        self.html = ''
        self.attach_count = 0
        self._patcher = mock.patch('store.emails.EmailMultiAlternatives')

    def __enter__(self):
        self.mock_class = self._patcher.start()
        self.mock_class.side_effect = self._factory
        return self

    def __exit__(self, *exc):
        self._patcher.stop()

    def _factory(self, *args, **kwargs):
        self.args = args
        self.message = mock.MagicMock()

        def attach(html, mime):
            self.attach_count += 1
            self.html = html

        self.message.attach_alternative.side_effect = attach
        return self.message

    def reset_credentials(self):
        return re.search(RESET_URL, self.html)


class PasswordResetTests(TestCase):
    def test_reset_page_renders(self):
        resp = self.client.get(reverse('password_reset'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Send reset link')
        self.assertContains(resp, 'id_email')

    def test_known_email_sends_branded_email_and_redirects(self):
        enable_smtp()
        make_user()
        with CaptureMail() as mail:
            resp = self.client.post(reverse('password_reset'), {'email': 'jane@example.com'})
        self.assertRedirects(resp, DONE_URL)
        self.assertEqual(mail.attach_count, 1)
        self.assertIsNotNone(mail.args)
        subject, body, sender, recipients = mail.args
        self.assertEqual(recipients, ['jane@example.com'])
        self.assertIn('Password reset for Reeves Boutique', subject)
        self.assertIn('Reeves Boutique <noreply@store.com>', sender)
        self.assertIn('Reeves Boutique', mail.html)
        self.assertIn('expires in', mail.html)
        match = mail.reset_credentials()
        self.assertIsNotNone(match, mail.html)

    def test_unknown_email_does_not_send_and_does_not_reveal(self):
        enable_smtp()
        with CaptureMail() as mail:
            resp = self.client.post(reverse('password_reset'), {'email': 'nobody@example.com'})
        self.assertRedirects(resp, DONE_URL)
        self.assertIsNone(mail.message)
        # Same response URL as an existing account — no account enumeration.
        make_user()
        with CaptureMail() as mail2:
            resp2 = self.client.post(reverse('password_reset'), {'email': 'jane@example.com'})
        self.assertEqual(resp2.url, resp.url)

    def test_reset_email_respects_smtp_disabled(self):
        make_user()
        with CaptureMail() as mail:
            resp = self.client.post(reverse('password_reset'), {'email': 'jane@example.com'})
        self.assertRedirects(resp, DONE_URL)
        self.assertIsNone(mail.message)

    def test_reset_link_end_to_end_and_token_invalidated(self):
        enable_smtp()
        user = make_user()
        with CaptureMail() as mail:
            self.client.post(reverse('password_reset'), {'email': 'jane@example.com'})
        match = mail.reset_credentials()
        uid, token = match.group(1), match.group(2)

        confirm_url = reverse('password_reset_confirm', args=[uid, token])
        # Django redirects a valid link to a token-less "set-password" URL.
        resp = self.client.get(confirm_url, follow=True)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Set a new password')
        self.assertEqual(resp.redirect_chain[-1][0], f'/account/reset/{uid}/set-password/')

        resp = self.client.post(resp.redirect_chain[-1][0], {
            'new_password1': 'NewSecure123!',
            'new_password2': 'NewSecure123!',
        })
        self.assertRedirects(resp, '/account/reset/done/')

        user.refresh_from_db()
        self.assertTrue(user.check_password('NewSecure123!'))
        self.assertFalse(user.check_password('OldPass123!'))

        # The old token must be invalid now.
        resp = self.client.get(confirm_url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Reset link invalid')

        # New password works for login.
        self.assertTrue(self.client.login(username='jane', password='NewSecure123!'))

    def test_fresh_token_valid(self):
        user = make_user()
        self.assertTrue(site_token_generator.check_token(user, site_token_generator.make_token(user)))

    def test_expired_token_rejected(self):
        enable_smtp(password_reset_timeout_seconds=3600)
        user = make_user()
        now = site_token_generator._num_seconds(site_token_generator._now())
        old_token = site_token_generator._make_token_with_timestamp(user, now - 3601, site_token_generator.secret)
        self.assertFalse(site_token_generator.check_token(user, old_token))

    def test_timeout_is_configurable(self):
        enable_smtp(password_reset_timeout_seconds=7200)
        user = make_user()
        fresh = site_token_generator.make_token(user)
        self.assertTrue(site_token_generator.check_token(user, fresh))
        now = site_token_generator._num_seconds(site_token_generator._now())
        two_hours_old = site_token_generator._make_token_with_timestamp(user, now - 7201, site_token_generator.secret)
        self.assertFalse(site_token_generator.check_token(user, two_hours_old))

    def test_password_change_still_works(self):
        user = make_user()
        self.client.login(username='jane', password='OldPass123!')
        resp = self.client.post(reverse('password_change'), {
            'old_password': 'OldPass123!',
            'new_password1': 'BrandNew123!',
            'new_password2': 'BrandNew123!',
        })
        self.assertEqual(resp.status_code, 302)
        user.refresh_from_db()
        self.assertTrue(user.check_password('BrandNew123!'))


class EmailSettingsTests(TestCase):
    def setUp(self):
        self.client = Client()
        User.objects.create_superuser(username='admin', email='a@b.com', password='TestPass123!')
        self.client.login(username='admin', password='TestPass123!')

    def test_page_hides_smtp_password(self):
        s = SiteSettings.get()
        s.smtp_password = 'SUPER_SECRET_PW_123'
        s.save()
        resp = self.client.get(reverse('manage_email_settings'))
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, 'SUPER_SECRET_PW_123')
        self.assertContains(resp, 'configured')

    def test_save_keeps_password_when_blank(self):
        s = SiteSettings.get()
        s.smtp_password = 'SECRET_A'
        s.save()
        self.client.post(reverse('manage_email_settings'), {'smtp_password': '', 'smtp_host': 'smtp.gmail.com'})
        s.refresh_from_db()
        self.assertEqual(s.smtp_password, 'SECRET_A')

    def test_save_overwrites_password(self):
        self.client.post(reverse('manage_email_settings'), {'smtp_password': 'SECRET_NEW', 'smtp_host': 'smtp.gmail.com'})
        s = SiteSettings.get()
        s.refresh_from_db()
        self.assertEqual(s.smtp_password, 'SECRET_NEW')

    def test_tls_and_ssl_mutually_exclusive(self):
        self.client.post(reverse('manage_email_settings'), {'smtp_use_tls': 'on', 'smtp_use_ssl': 'on'})
        s = SiteSettings.get()
        s.refresh_from_db()
        self.assertTrue(s.smtp_use_tls)
        self.assertFalse(s.smtp_use_ssl)

    def test_save_reset_timeout_hours(self):
        self.client.post(reverse('manage_email_settings'), {'password_reset_timeout_hours': '48'})
        s = SiteSettings.get()
        s.refresh_from_db()
        self.assertEqual(s.password_reset_timeout_seconds, 48 * 3600)

    def test_page_shows_reset_timeout_hours(self):
        s = SiteSettings.get()
        s.password_reset_timeout_seconds = 3 * 3600
        s.save()
        resp = self.client.get(reverse('manage_email_settings'))
        self.assertContains(resp, 'value="3"')

    def test_test_email_sends_and_reports_success(self):
        with mock.patch('django.core.mail.send_mail', return_value=1) as send:
            resp = self.client.post(reverse('test_email'), {'email': 'who@example.com'}, follow=True)
        self.assertContains(resp, 'Test email sent to who@example.com.')
        send.assert_called_once()
        args, kwargs = send.call_args
        self.assertEqual(kwargs['recipient_list'] if 'recipient_list' in kwargs else args[3], ['who@example.com'])

    def test_test_email_reports_failure(self):
        with mock.patch('django.core.mail.send_mail', side_effect=Exception('connection refused')):
            resp = self.client.post(reverse('test_email'), {'email': 'who@example.com'}, follow=True)
        self.assertContains(resp, 'SMTP test failed: connection refused')

    def test_test_email_requires_recipient(self):
        resp = self.client.post(reverse('test_email'), {'email': ''}, follow=True)
        self.assertContains(resp, 'Enter an email address to send the test to.')


class EmailBackendTests(TestCase):
    def test_backend_uses_db_settings_when_enabled(self):
        enable_smtp(smtp_host='mail.example.net', smtp_port=2525, smtp_username='u@example.net')
        from store.email_backend import DatabaseSMTPEmailBackend
        backend = DatabaseSMTPEmailBackend(fail_silently=True)
        self.assertEqual(backend.host, 'mail.example.net')
        self.assertEqual(backend.port, 2525)
        self.assertEqual(backend.username, 'u@example.net')
        self.assertEqual(backend.password, 'app-password')
        self.assertFalse(backend.use_ssl)
        self.assertTrue(backend.use_tls)

    def test_backend_uses_ssl_mode_when_configured(self):
        enable_smtp(smtp_use_tls=False, smtp_use_ssl=True)
        from store.email_backend import DatabaseSMTPEmailBackend
        backend = DatabaseSMTPEmailBackend(fail_silently=True)
        self.assertTrue(backend.use_ssl)
        self.assertFalse(backend.use_tls)

    def test_backend_falls_back_to_settings_when_disabled(self):
        s = SiteSettings.get()
        s.smtp_enabled = False
        s.smtp_host = 'db-override.example.net'
        s.save()
        from store.email_backend import DatabaseSMTPEmailBackend
        backend = DatabaseSMTPEmailBackend(fail_silently=True)
        self.assertEqual(backend.host, 'smtp.gmail.com')
        self.assertEqual(backend.username, '')
        self.assertEqual(backend.password, '')
