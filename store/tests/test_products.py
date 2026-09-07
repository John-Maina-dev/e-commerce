from decimal import Decimal

from django.contrib.auth.models import User
from django.db import connection
from django.test import Client, TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from store.models import Order, OrderItem, Product
from store.tests.test_models import make_category, make_product


def make_order_with_item(product, user=None):
    order = Order.objects.create(
        number=Order.next_number(), user=user, customer_name='Jane Doe', phone='0712345678',
        total=product.effective_price,
    )
    OrderItem.objects.create(order=order, product=product, product_name=product.name,
                             product_sku=product.sku, price=product.effective_price,
                             quantity=1, subtotal=product.effective_price)
    return order


class UnlimitedCatalogueTests(TestCase):
    def setUp(self):
        self.category = make_category('Shoes')
        self.products = [make_product(name=f'Shoe {i}', category=self.category,
                                      sku=f'SH-{i:03}') for i in range(35)]
        self.client = Client()

    def test_all_products_reachable_across_pages(self):
        seen = set()
        for page_num in (1, 2, 3, 4):
            resp = self.client.get(reverse('catalogue'), {'page': page_num})
            self.assertEqual(resp.status_code, 200)
            seen.update(p.slug for p in resp.context['page'].object_list)
        self.assertEqual(len(seen), 35)

    def test_paginator_reports_full_count(self):
        resp = self.client.get(reverse('catalogue'))
        self.assertEqual(resp.context['page'].paginator.count, 35)
        self.assertEqual(len(resp.context['page'].object_list), 12)
        last = self.client.get(reverse('catalogue'), {'page': 4})
        self.assertEqual(len(last.context['page'].object_list), 11)

    def test_last_page_is_last_page_not_error(self):
        resp = self.client.get(reverse('catalogue'), {'page': 4})
        self.assertEqual(resp.status_code, 200)


class AutomaticAppearanceTests(TestCase):
    def setUp(self):
        self.category = make_category('Bags')
        self.client = Client()

    def test_new_product_appears_in_catalogue(self):
        product = make_product(name='Tote Bag', category=self.category, sku='BG-1')
        resp = self.client.get(reverse('catalogue'))
        self.assertContains(resp, 'Tote Bag')
        self.assertTrue(Product.objects.filter(pk=product.pk).exists())

    def test_new_product_appears_in_category_listing(self):
        make_product(name='Clutch', category=self.category, sku='BG-2')
        resp = self.client.get(reverse('catalogue'), {'category': self.category.slug})
        self.assertContains(resp, 'Clutch')

    def test_new_product_appears_in_search_and_suggestions(self):
        make_product(name='Leather Satchel', category=self.category, sku='BG-3', brand='Tanner')
        resp = self.client.get(reverse('catalogue'), {'q': 'satchel'})
        self.assertContains(resp, 'Leather Satchel')
        sug = self.client.get(reverse('search_suggestions'), {'q': 'tanner'})
        self.assertEqual(sug.status_code, 200)
        self.assertIn('Leather Satchel', str(sug.content))

    def test_new_product_shows_on_home_new_arrivals(self):
        make_product(name='Weekender', category=self.category, sku='BG-4', is_new=True)
        resp = self.client.get(reverse('home'))
        self.assertContains(resp, 'Weekender')


class VisibilityTests(TestCase):
    def setUp(self):
        self.category = make_category('Tops')
        self.product = make_product(name='Linen Shirt', category=self.category, sku='TP-1')
        self.client = Client()

    def _assert_absent(self, resp):
        self.assertNotContains(resp, 'Linen Shirt')
        self.assertEqual(self.client.get(reverse('product_detail', args=[self.product.slug])).status_code, 404)

    def test_hidden_product_hidden_from_storefront_but_record_kept(self):
        self.product.hidden = True
        self.product.save()
        self._assert_absent(self.client.get(reverse('catalogue')))
        self.assertTrue(Product.objects.filter(pk=self.product.pk).exists())

    def test_deactivated_product_hidden_from_storefront_but_record_kept(self):
        self.product.active = False
        self.product.save()
        self._assert_absent(self.client.get(reverse('catalogue')))
        self.assertTrue(Product.objects.filter(pk=self.product.pk).exists())

    def test_archived_product_hidden_from_storefront_but_record_kept(self):
        self.product.is_archived = True
        self.product.save()
        self._assert_absent(self.client.get(reverse('catalogue')))
        self.assertTrue(Product.objects.filter(pk=self.product.pk).exists())

    def test_reactivating_restores_product(self):
        self.product.active = False
        self.product.save()
        self.product.active = True
        self.product.save()
        resp = self.client.get(reverse('catalogue'))
        self.assertContains(resp, 'Linen Shirt')


class OrderHistoryPreservationTests(TestCase):
    def setUp(self):
        self.category = make_category('Coats')
        self.product = make_product(name='Trench Coat', category=self.category, sku='CT-1',
                                    price='8000.00', stock=3)
        self.user = User.objects.create_user(username='buyer', password='pw-123456')
        self.order = make_order_with_item(self.product, user=self.user)
        self.client = Client()

    def test_archive_preserves_order_history(self):
        self.product.is_archived = True
        self.product.save()
        self.order.refresh_from_db()
        item = self.order.items.get()
        self.assertEqual(item.product_name, 'Trench Coat')
        self.assertEqual(item.product_id, self.product.pk)
        self.client.login(username='buyer', password='pw-123456')
        resp = self.client.get(reverse('account_order_detail', args=[self.order.number]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Trench Coat')

    def test_order_item_keeps_name_snapshot_if_product_unlinked(self):
        item = self.order.items.get()
        item.product = None
        item.save()
        self.assertEqual(item.product_name, 'Trench Coat')
        self.assertEqual(item.subtotal, Decimal('8000.00'))


class DeleteGuardsTests(TestCase):
    def setUp(self):
        self.category = make_category('Denim')
        self.used = make_product(name='Used Jeans', category=self.category, sku='DN-1')
        self.unused = make_product(name='Spare Jeans', category=self.category, sku='DN-2')
        self.order = make_order_with_item(self.used)
        self.staff = User.objects.create_user(username='boss', password='pw-123456', is_staff=True)
        self.client = Client()
        self.client.login(username='boss', password='pw-123456')

    def test_single_delete_refused_when_order_history_exists(self):
        resp = self.client.post(reverse('product_delete', args=[self.used.pk]))
        self.assertTrue(Product.objects.filter(pk=self.used.pk).exists())
        self.assertEqual(self.order.items.get().product_id, self.used.pk)

    def test_bulk_delete_preserves_products_with_orders(self):
        resp = self.client.post(reverse('product_bulk_action'), {
            'bulk_action': 'delete', 'selected': [self.used.pk, self.unused.pk]})
        self.assertFalse(Product.objects.filter(pk=self.unused.pk).exists())
        self.assertTrue(Product.objects.filter(pk=self.used.pk).exists())
        self.assertEqual(self.order.items.get().product_name, 'Used Jeans')


class ProductIndexTests(TestCase):
    def test_storefront_indexes_present(self):
        names = {tuple(i.fields) for i in Product._meta.indexes}
        self.assertIn(('active', 'hidden', 'is_archived'), names)
        self.assertIn(('active', 'hidden', 'is_archived', '-created_at'), names)
        self.assertIn(('brand',), names)
        self.assertIn(('stock',), names)


class QueryEfficiencyTests(TestCase):
    def setUp(self):
        self.category = make_category('Accessories')
        for i in range(30):
            make_product(name=f'Item {i}', category=self.category, sku=f'AX-{i:03}', brand='BrandX')
        self.client = Client()

    def test_catalogue_queries_constant_with_many_products(self):
        with CaptureQueriesContext(connection) as ctx:
            self.client.get(reverse('catalogue'))
            self.client.get(reverse('catalogue'), {'category': self.category.slug})
            self.client.get(reverse('catalogue'), {'q': 'item', 'page': 2})
        self.assertLess(len(ctx.captured_queries), 30)

    def test_home_queries_constant_with_many_products(self):
        with CaptureQueriesContext(connection) as ctx:
            self.client.get(reverse('home'))
        self.assertLess(len(ctx.captured_queries), 20)
