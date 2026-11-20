from decimal import Decimal
from pathlib import Path

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from store.models import Category, Product, ProductImage, SiteSettings, UserProfile

BASE_DIR = Path(__file__).resolve().parent.parent.parent
ANIM_CSS = BASE_DIR / 'static' / 'css' / 'animations.css'
ANIM_JS = BASE_DIR / 'static' / 'js' / 'product-animations.js'

TINY_PNG = (
    b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01'
    b'\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00'
    b'\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82'
)


class StorefrontAnimationsTests(TestCase):
    def setUp(self):
        self.cat = Category.objects.create(name='Evening Wear', slug='evening-wear')
        self.boss = User.objects.create_superuser(
            username='boss_anim', password='SuperPassword123!', email='boss_anim@example.com'
        )
        UserProfile.objects.create(user=self.boss, role='super_admin', status='approved')

    def _make_product(self, idx, **kwargs):
        defaults = dict(
            name=f'Boutique Piece {idx}',
            sku=f'RB-AN-{idx:03d}',
            category=self.cat,
            price=Decimal('4500.00'),
            stock=8,
            active=True,
            image_url=f'https://example.com/img-{idx}.jpg',
        )
        defaults.update(kwargs)
        return Product.objects.create(**defaults)

    def test_empty_storefront_handles_gracefully(self):
        resp = self.client.get(reverse('home'))
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn('rb-hero-static', html)
        self.assertIn('animations.css', html)
        self.assertIn('product-animations.js', html)

    def test_single_product_renders_without_breaking(self):
        self._make_product(1, showcase_hero=True, showcase_coverflow=True, featured=True, is_new=True, image_url='')
        resp = self.client.get(reverse('home'))
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn('data-hero-slider', html)
        self.assertIn('data-coverflow', html)
        self.assertIn('is-single', html)
        self.assertIn('is-static', html)
        self.assertIn('rb-card-placeholder', html)

    def test_all_homepage_animation_styles_and_display_order(self):
        p2 = self._make_product(2, name='Second Dress', showcase_hero=True, showcase_coverflow=True,
                                featured=True, is_new=True, is_bestseller=True, display_order=20)
        p1 = self._make_product(1, name='First Gown', showcase_hero=True, showcase_coverflow=True,
                                featured=True, is_new=True, is_bestseller=True, display_order=5)
        p3 = self._make_product(3, name='Third Coat', showcase_hero=True, showcase_coverflow=True,
                                featured=True, is_new=True, is_bestseller=True, display_order=30)

        resp = self.client.get(reverse('home'))
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()

        # All 5 homepage showcase styles present
        self.assertIn('data-hero-slider', html)
        self.assertIn('data-coverflow', html)
        self.assertIn('data-marquee', html)
        self.assertIn('data-direction="left"', html)
        self.assertIn('data-direction="right"', html)
        self.assertIn('data-tilt-card', html)
        self.assertIn('data-reveal-grid', html)
        self.assertIn('id="rbQuickViewModal"', html)

        # Display order respected: First Gown (5) before Second Dress (20) before Third Coat (30)
        self.assertLess(html.index(p1.name), html.index(p2.name))
        self.assertLess(html.index(p2.name), html.index(p3.name))

    def test_catalogue_uses_scroll_reveal_grid(self):
        self._make_product(1)
        self._make_product(2)
        resp = self.client.get(reverse('catalogue'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'data-reveal-grid')
        self.assertContains(resp, 'data-tilt-card')
        self.assertContains(resp, 'data-quick-view')

    def test_product_detail_360_spin_activates_with_3_plus_angles(self):
        p = self._make_product(10, name='Spin Jacket')
        resp_1 = self.client.get(reverse('product_detail', args=[p.slug]))
        self.assertEqual(resp_1.status_code, 200)
        self.assertContains(resp_1, 'data-product-gallery')
        self.assertNotContains(resp_1, 'data-spin-ready="true"')

        # Add 2 gallery images (total 3 unique frames including main image_url)
        for i in range(2):
            ProductImage.objects.create(
                product=p,
                image=SimpleUploadedFile(f'angle_{i}.png', TINY_PNG, content_type='image/png'),
                order=i,
            )

        resp_3 = self.client.get(reverse('product_detail', args=[p.slug]))
        self.assertEqual(resp_3.status_code, 200)
        self.assertContains(resp_3, 'data-spin-ready="true"')
        self.assertContains(resp_3, '360° Spin')

    def test_admin_can_toggle_animation_styles_and_showcase_order(self):
        p = self._make_product(1, name='Curated Coat', display_order=50)
        self.client.login(username='boss_anim', password='SuperPassword123!')

        # 1. Turn animations off & change speed/styles
        resp = self.client.post(reverse('manage_settings'), {
            'store_name': 'Reeves Boutique',
            'animations_enabled_present': '1',
            'animation_speed': 'slow',
            'hero_style': 'off',
            'featured_style': 'grid',
            'arrivals_style': 'off',
            'catalogue_style': 'off',
        }, follow=True)
        self.assertEqual(resp.status_code, 200)
        s = SiteSettings.get()
        self.assertFalse(s.animations_enabled)
        self.assertEqual(s.animation_speed, 'slow')
        self.assertEqual(s.hero_style, 'off')
        self.assertEqual(s.featured_style, 'grid')

        home_off = self.client.get(reverse('home'))
        self.assertContains(home_off, 'data-animations="off"')
        self.assertContains(home_off, 'data-anim-speed="slow"')
        self.assertContains(home_off, 'rb-hero-static')

        # 2. Update showcase product flags & display order from Store Settings
        resp2 = self.client.post(reverse('manage_settings'), {
            'form_section': 'showcase_products',
            'showcase_pid': [str(p.pk)],
            f'display_order_{p.pk}': '3',
            f'showcase_hero_{p.pk}': 'on',
            f'showcase_coverflow_{p.pk}': 'on',
            f'featured_{p.pk}': 'on',
            f'is_new_{p.pk}': 'on',
            f'is_bestseller_{p.pk}': 'on',
        }, follow=True)
        self.assertEqual(resp2.status_code, 200)
        p.refresh_from_db()
        self.assertEqual(p.display_order, 3)
        self.assertTrue(p.showcase_hero)
        self.assertTrue(p.showcase_coverflow)
        self.assertTrue(p.is_featured)
        self.assertTrue(p.is_new)
        self.assertTrue(p.is_bestseller)

    def test_assets_support_dark_mode_and_reduced_motion(self):
        css = ANIM_CSS.read_text(encoding='utf-8')
        js = ANIM_JS.read_text(encoding='utf-8')

        self.assertIn('html[data-theme="dark"]', css)
        self.assertIn('prefers-reduced-motion: reduce', css)
        self.assertIn('--rb-marquee-duration', css)
        self.assertIn('rb-ken-burns', css)

        self.assertIn('IntersectionObserver', js)
        self.assertIn('visibilitychange', js)
        self.assertIn('prefers-reduced-motion', js)
        self.assertIn('initCoverflows', js)
        self.assertIn('initProductGalleries', js)
