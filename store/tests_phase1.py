from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from store.models import AccountAuditLog, UserProfile

User = get_user_model()


class Phase1AccountApprovalAndRBACTests(TestCase):

    def setUp(self):
        self.client = Client()
        # Create Super Admin
        self.super_admin = User.objects.create_superuser(
            username='test_superadmin',
            email='superadmin@test.com',
            password='Password123!',
        )
        self.super_admin_profile = UserProfile.objects.create(
            user=self.super_admin,
            role=UserProfile.ROLE_SUPER_ADMIN,
            status=UserProfile.STATUS_APPROVED,
        )

        # Create Admin
        self.admin_user = User.objects.create_user(
            username='test_admin',
            email='admin@test.com',
            password='Password123!',
            is_staff=True,
        )
        self.admin_profile = UserProfile.objects.create(
            user=self.admin_user,
            role=UserProfile.ROLE_ADMIN,
            status=UserProfile.STATUS_APPROVED,
        )

        # Create Cashier
        self.cashier_user = User.objects.create_user(
            username='test_cashier',
            email='cashier@test.com',
            password='Password123!',
            is_staff=True,
        )
        self.cashier_profile = UserProfile.objects.create(
            user=self.cashier_user,
            role=UserProfile.ROLE_CASHIER,
            status=UserProfile.STATUS_APPROVED,
        )

    def test_existing_super_admin_preserved_and_functional(self):
        """Super Admin can authenticate and access the account management center."""
        login_ok = self.client.login(username='test_superadmin', password='Password123!')
        self.assertTrue(login_ok)
        response = self.client.get(reverse('manage_accounts'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Account Approvals &amp; Roles')

    def test_new_registration_defaults_to_customer_and_pending(self):
        """Newly registered user must be CUSTOMER, PENDING, and inactive."""
        response = self.client.post(reverse('register'), {
            'username': 'bob_customer',
            'email': 'bob@example.com',
            'first_name': 'Bob',
            'last_name': 'Builder',
            'password1': 'StrongP@ssw0rd!',
            'password2': 'StrongP@ssw0rd!',
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Registration Pending Approval')

        bob = User.objects.get(username='bob_customer')
        self.assertFalse(bob.is_active)
        self.assertEqual(bob.profile.role, UserProfile.ROLE_CUSTOMER)
        self.assertEqual(bob.profile.status, UserProfile.STATUS_PENDING)

        # Verify audit log was recorded
        audit = AccountAuditLog.objects.filter(target_username='bob_customer', action='register').first()
        self.assertIsNotNone(audit)

    def test_pending_user_cannot_log_in(self):
        """A user in PENDING status must be blocked from logging in with a clear explanation."""
        User.objects.create_user(
            username='pending_user',
            email='pending@example.com',
            password='Password123!',
            is_active=False,
        )
        user = User.objects.get(username='pending_user')
        UserProfile.objects.create(
            user=user,
            role=UserProfile.ROLE_CUSTOMER,
            status=UserProfile.STATUS_PENDING,
        )

        response = self.client.post(reverse('login'), {
            'username': 'pending_user',
            'password': 'Password123!',
        }, follow=True)

        self.assertContains(response, 'pending administrator approval')
        # Ensure session did not log in
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_super_admin_can_approve_account_and_user_can_then_login(self):
        """Super Admin approves a pending user, enabling login."""
        user = User.objects.create_user(
            username='user_to_approve',
            email='approveme@example.com',
            password='Password123!',
            is_active=False,
        )
        profile = UserProfile.objects.create(
            user=user,
            role=UserProfile.ROLE_CUSTOMER,
            status=UserProfile.STATUS_PENDING,
        )

        # Super Admin logs in and approves
        self.client.login(username='test_superadmin', password='Password123!')
        response = self.client.post(reverse('account_action', args=[user.pk]), {
            'action': 'approve',
        }, follow=True)
        self.assertEqual(response.status_code, 200)

        # Refresh state
        user.refresh_from_db()
        profile.refresh_from_db()
        self.assertTrue(user.is_active)
        self.assertEqual(profile.status, UserProfile.STATUS_APPROVED)
        self.assertEqual(profile.approved_by, self.super_admin)

        # Verify audit log
        audit = AccountAuditLog.objects.filter(target_username='user_to_approve', action='approve').first()
        self.assertIsNotNone(audit)
        self.assertEqual(audit.actor, self.super_admin)

        # User can now log in successfully
        self.client.logout()
        login_ok = self.client.login(username='user_to_approve', password='Password123!')
        self.assertTrue(login_ok)

    def test_rejected_and_suspended_accounts_cannot_log_in(self):
        """Rejected or suspended accounts must not be able to log in."""
        user = User.objects.create_user(
            username='rejected_user',
            email='rejected@example.com',
            password='Password123!',
            is_active=False,
        )
        UserProfile.objects.create(
            user=user,
            role=UserProfile.ROLE_CUSTOMER,
            status=UserProfile.STATUS_REJECTED,
            rejection_reason='Duplicate identity',
        )

        # Login attempt for rejected user
        response = self.client.post(reverse('login'), {
            'username': 'rejected_user',
            'password': 'Password123!',
        }, follow=True)
        self.assertContains(response, 'rejected')
        self.assertNotIn('_auth_user_id', self.client.session)

        # Suspended user
        user2 = User.objects.create_user(
            username='suspended_user',
            email='suspended@example.com',
            password='Password123!',
            is_active=False,
        )
        UserProfile.objects.create(
            user=user2,
            role=UserProfile.ROLE_CUSTOMER,
            status=UserProfile.STATUS_SUSPENDED,
            suspension_reason='Violation of terms',
        )

        response2 = self.client.post(reverse('login'), {
            'username': 'suspended_user',
            'password': 'Password123!',
        }, follow=True)
        self.assertContains(response2, 'suspended')
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_admin_cannot_approve_accounts(self):
        """Admin users (level 3) cannot access account approvals (Super Admin only)."""
        self.client.login(username='test_admin', password='Password123!')
        response = self.client.get(reverse('manage_accounts'))
        self.assertEqual(response.status_code, 403)

        # Try to post an approve action
        target = User.objects.create_user(username='victim', password='Password123!', is_active=False)
        UserProfile.objects.create(user=target, role=UserProfile.ROLE_CUSTOMER, status=UserProfile.STATUS_PENDING)
        response2 = self.client.post(reverse('account_action', args=[target.pk]), {'action': 'approve'})
        self.assertEqual(response2.status_code, 403)

    def test_cashier_cannot_access_administrative_functions(self):
        """Cashier users (level 1) can access POS, but cannot access administrative functions."""
        self.client.login(username='test_cashier', password='Password123!')

        # Restricted admin sections
        self.assertEqual(self.client.get(reverse('manage_accounts')).status_code, 403)
        self.assertEqual(self.client.get(reverse('manage_settings')).status_code, 403)
        self.assertEqual(self.client.get(reverse('manage_payment_settings')).status_code, 403)
        self.assertEqual(self.client.get(reverse('manage_customers')).status_code, 403)

        # Permitted POS section
        pos_resp = self.client.get(reverse('pos_terminal'))
        self.assertEqual(pos_resp.status_code, 200)

    def test_primary_superadmin_protected_from_demotion_or_deletion(self):
        """Primary superadmin account cannot be demoted or deleted."""
        self.client.login(username='test_superadmin', password='Password123!')

        # Try to change primary super admin role
        response = self.client.post(reverse('account_role_update', args=[self.super_admin.pk]), {
            'role': 'customer',
        }, follow=True)
        self.super_admin_profile.refresh_from_db()
        self.assertEqual(self.super_admin_profile.role, UserProfile.ROLE_SUPER_ADMIN)
        self.assertContains(response, 'cannot be demoted')

        # Try to delete primary super admin
        del_resp = self.client.post(reverse('account_delete', args=[self.super_admin.pk]), follow=True)
        self.assertTrue(User.objects.filter(pk=self.super_admin.pk).exists())
        self.assertContains(del_resp, 'cannot delete the primary Super Admin account')
