import re
from pathlib import Path

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from store.tests.test_models import make_category, make_product

BASE_DIR = Path(__file__).resolve().parent.parent.parent
CSS_PATH = BASE_DIR / 'static' / 'store.css'
JS_PATH = BASE_DIR / 'static' / 'store.js'


class Step10MarkupTests(TestCase):
    """End-to-end markup checks for the modernized UI."""

    def setUp(self):
        self.category = make_category('Dresses')
        self.product = make_product(name='Silk Dress', category=self.category, sku='TH-1')
        self.staff = User.objects.create_user(username='owner', password='pw-123456')
        self.staff.is_staff = True
        self.staff.save()

    def test_home_renders_modern_sections(self):
        resp = self.client.get(reverse('home'))
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        for marker in ('hero', 'promo-banner', 'newsletter-band', 'slider-track', 'site-header', 'themeToggle'):
            self.assertIn(marker, html)

    def test_home_product_card_uses_loading_and_fadein(self):
        resp = self.client.get(reverse('home'))
        self.assertContains(resp, 'data-submit-loading')
        self.assertContains(resp, 'data-loading-text')
        card = (BASE_DIR / 'templates' / 'partials' / 'product_card.html').read_text(encoding='utf-8')
        self.assertIn('lazy-img', card)
        self.assertIn('loading="lazy"', card)

    def test_catalogue_has_no_customer_filter_sidebar(self):
        resp = self.client.get(reverse('catalogue'))
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn('catalogue-wrap', html)
        self.assertIn('toolbar-row', html)
        self.assertNotIn('filter-group', html)
        self.assertNotIn('id="f-category"', html)

    def test_catalogue_empty_state_has_icon(self):
        resp = self.client.get(reverse('catalogue') + '?q=zzzznomatch')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'empty-icon')
        self.assertContains(resp, 'No products found')

    def test_product_page_has_sticky_buy_box_and_perks(self):
        resp = self.client.get(reverse('product_detail', args=[self.product.slug]))
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn('perks-row', html)
        self.assertIn('data-submit-loading', html)
        self.assertIn('data-loading-text', html)

    def test_login_has_auth_brand(self):
        resp = self.client.get(reverse('login'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'auth-brand')
        self.assertContains(resp, 'Welcome back')

    def test_register_has_auth_brand(self):
        resp = self.client.get(reverse('register'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'auth-brand')
        self.assertContains(resp, 'Create your account')

    def test_messages_have_dismiss_button(self):
        self.client.login(username='owner', password='pw-123456')
        resp = self.client.post(reverse('notifications_clear'), follow=True)
        self.assertContains(resp, 'message-close')
        self.assertContains(resp, 'Notifications marked as read.')

    def test_manage_dashboard_has_admin_shell(self):
        self.client.login(username='owner', password='pw-123456')
        resp = self.client.get(reverse('dashboard'))
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        # Admin top bar replaces the storefront header
        self.assertIn('manage-topbar', html)
        self.assertIn('id="manageToggle"', html)
        self.assertNotIn('class="site-header"', html)
        self.assertIn('id="notifToggle"', html)
        self.assertIn('id="notifMenu"', html)
        self.assertIn('id="profileToggle"', html)
        self.assertIn('id="profileMenu"', html)
        # Theme picker is still available in the admin shell
        self.assertIn('id="themeToggle"', html)
        self.assertIn('data-theme-choice="system"', html)
        # Quick actions + chart + recent orders
        self.assertIn('quick-actions', html)
        self.assertIn('data-chart', html)
        self.assertContains(resp, 'Recent orders')

    def test_manage_sidebar_uses_svg_icons_not_emoji(self):
        self.client.login(username='owner', password='pw-123456')
        resp = self.client.get(reverse('dashboard'))
        html = resp.content.decode()
        self.assertIn('<svg', html)
        for emoji in ('📊', '📦', '🧾', '👥', '⚙️', '💳'):
            self.assertNotIn(emoji, html)

    def test_products_list_has_delete_modal(self):
        self.client.login(username='owner', password='pw-123456')
        resp = self.client.get(reverse('manage_products'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'id="deleteModal"')
        self.assertContains(resp, 'data-modal-open="deleteModal"')
        self.assertContains(resp, 'role="dialog"')

    def test_dashboard_has_topbar_search(self):
        self.client.login(username='owner', password='pw-123456')
        resp = self.client.get(reverse('dashboard'))
        self.assertContains(resp, 'manage-search')
        self.assertContains(resp, 'Search products')


class Step10AssetTests(TestCase):
    def test_css_has_design_tokens_and_states(self):
        css = CSS_PATH.read_text(encoding='utf-8')
        for token in ('--ring', '--radius-lg', '--shadow-lg', '--brand-soft'):
            self.assertIn(token, css)
        self.assertIn('.btn.is-loading', css)
        self.assertIn('.modal-backdrop', css)
        self.assertIn('.empty-icon', css)
        self.assertIn('img.lazy-img', css)
        self.assertIn('@keyframes spin', css)
        self.assertIn('.skeleton', css)
        self.assertIn('.alert-error', css)
        self.assertIn(':focus-visible', css)
        self.assertIn('.table-hover', css)

    def test_css_admin_shell_present(self):
        css = CSS_PATH.read_text(encoding='utf-8')
        for rule in ('.manage-topbar', '.manage-toggle', '.topbar-menu', '.topbar-dropdown',
                     '.quick-action', '.dashboard-grid', '.profile-btn', '.manage-sidebar'):
            self.assertIn(rule, css)

    def test_css_responsive_product_grid(self):
        css = CSS_PATH.read_text(encoding='utf-8')
        self.assertIn('repeat(auto-fill, minmax(', css)
        self.assertIn('.product-body h3', css)
        self.assertIn('-webkit-line-clamp', css)

    def test_css_admin_mobile_responsive(self):
        css = CSS_PATH.read_text(encoding='utf-8')
        # Collapsible admin navigation on tablets/phones
        self.assertIn('.manage-toggle { display: grid; }', css)
        self.assertIn('.manage-sidebar', css)
        self.assertIn('transform: translateX(-100%)', css)
        # Responsive tables scroll instead of stretching layout
        self.assertIn('.table-wrap { overflow-x: auto; }', css)

    def test_css_reduced_motion(self):
        css = CSS_PATH.read_text(encoding='utf-8')
        self.assertIn('prefers-reduced-motion', css)
        self.assertIn('animation: none !important', css)

    def test_js_interactions_present(self):
        js = JS_PATH.read_text(encoding='utf-8')
        for marker in ('bindDropdown', 'manageToggle', 'data-submit-loading',
                       'closeModal', 'data-modal-open', 'lazy-img', 'message-close',
                       'data-theme-pref'):
            self.assertIn(marker, js)

    def test_no_horizontal_overflow_primitives(self):
        css = CSS_PATH.read_text(encoding='utf-8')
        # Image containers lock aspect ratio so cards never stretch images
        self.assertIn('object-fit: cover', css)
        self.assertIn('aspect-ratio: 1 / 1', css)
