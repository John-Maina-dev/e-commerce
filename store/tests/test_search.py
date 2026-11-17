import json
from decimal import Decimal

from django.test import Client, TestCase
from django.urls import reverse

from store.models import Product
from store.tests.test_models import make_category, make_product


class SearchSuggestionTests(TestCase):
    def setUp(self):
        self.cat = make_category('Accessories')
        self.product = make_product(name='Leather Belt', category=self.cat, sku='ACC-100',
                                    price='1800.00', stock=5, brand='Nordic')
        self.client = Client()

    def get_suggestions(self, q):
        resp = self.client.get(reverse('search_suggestions'), {'q': q})
        self.assertEqual(resp.status_code, 200)
        return resp, json.loads(resp.content)['results']

    def test_empty_and_short_queries_return_nothing(self):
        _, results = self.get_suggestions('')
        self.assertEqual(results, [])
        _, results = self.get_suggestions('a')
        self.assertEqual(results, [])

    def test_matches_name(self):
        _, results = self.get_suggestions('leather')
        self.assertEqual([r['name'] for r in results], ['Leather Belt'])

    def test_matches_sku(self):
        _, results = self.get_suggestions('acc-100')
        self.assertIn('Leather Belt', [r['name'] for r in results])

    def test_matches_brand(self):
        _, results = self.get_suggestions('nordic')
        self.assertIn('Leather Belt', [r['name'] for r in results])

    def test_matches_category_name(self):
        _, results = self.get_suggestions('accessor')
        self.assertIn('Leather Belt', [r['name'] for r in results])

    def test_payload_fields(self):
        _, results = self.get_suggestions('leather')
        item = results[0]
        self.assertEqual(item['slug'], 'leather-belt')
        self.assertEqual(item['category'], 'Accessories')
        self.assertEqual(item['price'], '1,800')
        self.assertFalse(item['out_of_stock'])

    def test_excludes_inactive_hidden_archived(self):
        make_product(name='Dormant Belt', category=self.cat, sku='INACTIVE-1', active=False)
        make_product(name='Ghost Belt', category=self.cat, sku='HIDDEN-1', hidden=True)
        make_product(name='Archive Belt', category=self.cat, sku='ARCHIVED-1', is_archived=True)
        _, results = self.get_suggestions('belt')
        self.assertEqual([r['name'] for r in results], ['Leather Belt'])

    def test_limits_to_six_results(self):
        for i in range(9):
            make_product(name=f'Belt Variant {i}', category=self.cat, sku=f'ACC-{200 + i}')
        _, results = self.get_suggestions('belt')
        self.assertLessEqual(len(results), 6)

    def test_new_product_appears_immediately(self):
        make_product(name='New Silk Scarf', category=self.cat, sku='ACC-900')
        _, results = self.get_suggestions('silk')
        self.assertIn('New Silk Scarf', [r['name'] for r in results])


class CatalogueSearchTests(TestCase):
    def setUp(self):
        self.cat = make_category('Footwear')
        self.product = make_product(name='Canvas Sneakers', category=self.cat, sku='FW-1',
                                    price='3200.00', stock=4, brand='Trail',
                                    description='Lightweight walking shoes')
        self.client = Client()

    def test_search_by_sku(self):
        resp = self.client.get(reverse('catalogue'), {'q': 'FW-1'})
        self.assertContains(resp, 'Canvas Sneakers')

    def test_search_by_brand(self):
        resp = self.client.get(reverse('catalogue'), {'q': 'trail'})
        self.assertContains(resp, 'Canvas Sneakers')

    def test_search_by_description(self):
        resp = self.client.get(reverse('catalogue'), {'q': 'walking'})
        self.assertContains(resp, 'Canvas Sneakers')

    def test_search_by_category_name(self):
        resp = self.client.get(reverse('catalogue'), {'q': 'footwear'})
        self.assertContains(resp, 'Canvas Sneakers')

    def test_does_not_match_inactive(self):
        make_product(name='Boot Liner', category=self.cat, sku='FW-2', active=False)
        resp = self.client.get(reverse('catalogue'), {'q': 'liner'})
        self.assertNotContains(resp, 'Boot Liner')

    def test_empty_state_with_query(self):
        resp = self.client.get(reverse('catalogue'), {'q': 'zzzznomatch'})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'No products found')
        self.assertContains(resp, 'Results for')


class HeaderSearchTests(TestCase):
    def setUp(self):
        self.cat = make_category('Dresses')
        self.product = make_product(name='Silk Dress', category=self.cat, sku='HDR-1')
        self.client = Client()

    def test_search_bar_markup(self):
        resp = self.client.get(reverse('home'))
        self.assertContains(resp, 'id="searchForm"')
        self.assertContains(resp, 'id="searchInput"')
        self.assertContains(resp, 'id="searchClear"')
        self.assertContains(resp, 'id="searchSuggestions"')
        self.assertContains(resp, reverse('search_suggestions'))

    def test_categories_dropdown_renders(self):
        resp = self.client.get(reverse('home'))
        self.assertContains(resp, 'nav-dropdown')
        self.assertContains(resp, f"?category={self.cat.slug}")

    def test_primary_nav_links_reachable(self):
        redirects_to_login = {'wishlist'}
        for name in ('home', 'catalogue', 'contact', 'cart', 'wishlist', 'login', 'register'):
            resp = self.client.get(reverse(name))
            if name in redirects_to_login:
                self.assertIn(resp.status_code, (200, 302), f'{name} failed')
            else:
                self.assertEqual(resp.status_code, 200, f'{name} failed')
