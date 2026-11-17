import re
from pathlib import Path

from django.test import TestCase
from django.urls import reverse

from store.tests.test_models import make_category, make_product

BASE_DIR = Path(__file__).resolve().parent.parent.parent
CSS_PATH = BASE_DIR / 'static' / 'store.css'
JS_PATH = BASE_DIR / 'static' / 'store.js'


def _luminance(hex_color):
    rgb = [int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def contrast_ratio(a, b):
    la, lb = _luminance(a), _luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def theme_block_vars(css, selector):
    match = re.search(re.escape(selector) + r'\s*{(.*?)}', css, re.S)
    if not match:
        return {}
    return dict(re.findall(r'(--[\w-]+):\s*(#[0-9a-fA-F]{3,8})\s*;', match.group(1)))


class ThemeMarkupTests(TestCase):
    def setUp(self):
        self.category = make_category('Dresses')
        self.product = make_product(name='Silk Dress', category=self.category, sku='TH-1')
        self.client = None
        from django.test import Client
        self.client = Client()

    def test_theme_picker_present(self):
        resp = self.client.get(reverse('home'))
        self.assertContains(resp, 'id="themeToggle"')
        self.assertContains(resp, 'id="themeMenu"')
        self.assertContains(resp, 'role="menu"')
        self.assertContains(resp, 'data-theme-choice="light"')
        self.assertContains(resp, 'data-theme-choice="dark"')
        self.assertContains(resp, 'data-theme-choice="system"')

    def test_theme_options_labeled(self):
        resp = self.client.get(reverse('home'))
        html = re.sub(r'\s+', ' ', resp.content.decode())
        self.assertIn('data-theme-choice="light"', html)
        self.assertIn('data-theme-choice="dark"', html)
        self.assertIn('data-theme-choice="system"', html)
        for word in ('Light', 'Dark', 'System'):
            self.assertIn(f'> {word} <', html)

    def test_inline_script_respects_stored_preference(self):
        resp = self.client.get(reverse('home'))
        self.assertContains(resp, "rb-theme")
        self.assertContains(resp, "data-theme-pref")
        self.assertContains(resp, "'system'")

    def test_manage_pages_share_theme(self):
        from django.contrib.auth.models import User
        user = User.objects.create_user(username='owner', password='pw-123456')
        user.is_staff = True
        user.save()
        self.client.login(username='owner', password='pw-123456')
        resp = self.client.get(reverse('dashboard'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'id="themeToggle"')
        self.assertContains(resp, 'data-theme-choice="system"')


class ThemeAssetTests(TestCase):
    def test_both_themes_define_tokens(self):
        css = CSS_PATH.read_text(encoding='utf-8')
        light = theme_block_vars(css, ':root')
        dark = theme_block_vars(css, 'html[data-theme="dark"]')
        for token in ('--ink', '--muted', '--line', '--bg', '--card'):
            self.assertIn(token, light, f'missing {token} in light')
            self.assertIn(token, dark, f'missing {token} in dark')

    def test_color_scheme_declared_for_both(self):
        css = CSS_PATH.read_text(encoding='utf-8')
        self.assertIn('color-scheme: light', css)
        self.assertIn('color-scheme: dark', css)

    def test_contrast_meets_wcag(self):
        css = CSS_PATH.read_text(encoding='utf-8')
        light = theme_block_vars(css, ':root')
        dark = theme_block_vars(css, 'html[data-theme="dark"]')
        for name, palette in (('light', light), ('dark', dark)):
            self.assertGreaterEqual(contrast_ratio(palette['--ink'], palette['--bg']), 4.5,
                                    f'{name}: ink/bg contrast too low')
            self.assertGreaterEqual(contrast_ratio(palette['--ink'], palette['--card']), 4.5,
                                    f'{name}: ink/card contrast too low')

    def test_js_supports_three_choices_without_forced_light(self):
        js = JS_PATH.read_text(encoding='utf-8')
        self.assertIn("'system'", js)
        self.assertNotIn("|| 'light'", js)
        self.assertIn("prefers-color-scheme: dark", js)
        self.assertIn("data-theme-pref", js)
