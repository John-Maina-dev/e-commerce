from decimal import Decimal
import json

from django.contrib.auth.models import User
from django.test import TestCase, Client
from django.urls import reverse

from store import pos, recommendations
from store.models import Category, Order, OrderItem, Payment, PosSession, Product, SiteSettings, UserProfile


class SmartSearchAndRecommendationsTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.settings = SiteSettings.get()
        self.settings.tax_enabled = True
        self.settings.tax_rate = Decimal('16.00')
        self.settings.save()

        # Cashier
        self.cashier = User.objects.create_user(
            username='cashier_alice', email='alice@reeves.com', password='CashierPass123!',
            first_name='Alice', last_name='Smith', is_staff=True, is_active=True
        )
        UserProfile.objects.create(
            user=self.cashier, role=UserProfile.ROLE_CASHIER, status=UserProfile.STATUS_APPROVED
        )

        # Categories
        self.cat_dresses = Category.objects.create(name='Dresses', slug='dresses')
        self.cat_shoes = Category.objects.create(name='Shoes', slug='shoes')
        self.cat_bags = Category.objects.create(name='Bags & Handbags', slug='bags')
        self.cat_accessories = Category.objects.create(name='Accessories', slug='accessories')

        # Products
        # 1. Evening Gown (Dresses) on Sale
        self.prod_dress = Product.objects.create(
            name='Emerald Velvet Evening Dress',
            slug='emerald-velvet-evening-dress',
            category=self.cat_dresses,
            brand='Reeves Signature',
            sku='DRS-EMR-01',
            barcode='7111222333441',
            price=Decimal('5000.00'),
            sale_price=Decimal('4000.00'),  # 20% discount
            stock=15,
            active=True,
            description='Stunning emerald velvet cocktail dress for gala and evening wear.'
        )

        # 2. Black Stiletto Heels (Shoes)
        self.prod_heels = Product.objects.create(
            name='Classic Pointed Stiletto Heels',
            slug='classic-pointed-stiletto-heels',
            category=self.cat_shoes,
            brand='Zara Fashion',
            sku='SHOE-STL-38',
            barcode='7111222333442',
            price=Decimal('3500.00'),
            stock=20,
            active=True,
            description='Black patent leather stiletto pumps, 4-inch heel.'
        )

        # 3. Evening Clutch Bag (Bags)
        self.prod_clutch = Product.objects.create(
            name='Gold Shimmer Evening Clutch',
            slug='gold-shimmer-evening-clutch',
            category=self.cat_bags,
            brand='Reeves Signature',
            sku='BAG-CLT-GOLD',
            barcode='7111222333443',
            price=Decimal('2200.00'),
            stock=12,
            active=True,
            description='Sparkling evening clutch bag with detachable chain strap.'
        )

        # 4. Pearl Drop Earrings (Accessories)
        self.prod_earrings = Product.objects.create(
            name='Freshwater Pearl Drop Earrings',
            slug='freshwater-pearl-drop-earrings',
            category=self.cat_accessories,
            brand='Luxe Jewels',
            sku='ACC-EAR-PRL',
            barcode='7111222333444',
            price=Decimal('1200.00'),
            stock=30,
            active=True,
            description='Elegant cultured freshwater pearl earrings with 18k gold plating.'
        )

        # 5. Out of stock dress
        self.prod_sold_out = Product.objects.create(
            name='Midnight Blue Satin Maxi Dress',
            slug='midnight-blue-satin-maxi-dress',
            category=self.cat_dresses,
            sku='DRS-SATIN-02',
            barcode='7111222333445',
            price=Decimal('4500.00'),
            stock=0,  # Out of stock!
            active=True,
            description='Sold out evening maxi.'
        )

        # Open POS session
        self.session, _ = pos.open_session(self.cashier, opening_cash=Decimal('1000.00'))

    def test_smart_search_by_various_fields(self):
        """Cashier can search by name, partial name, SKU, barcode, brand, description, category."""
        # 1. Partial name search
        res1 = pos.search_products('Velvet')
        self.assertTrue(any(p.pk == self.prod_dress.pk for p in res1))

        # 2. SKU search
        res2 = pos.search_products('SHOE-STL-38')
        self.assertEqual(res2[0].pk, self.prod_heels.pk)

        # 3. Barcode search
        res3 = pos.search_products('7111222333443')
        self.assertEqual(res3[0].pk, self.prod_clutch.pk)

        # 4. Brand search
        res4 = pos.search_products('Zara Fashion')
        self.assertTrue(any(p.pk == self.prod_heels.pk for p in res4))

        # 5. Category search
        res5 = pos.search_products('Accessories')
        self.assertTrue(any(p.pk == self.prod_earrings.pk for p in res5))

        # 6. Description search
        res6 = pos.search_products('freshwater pearl')
        self.assertTrue(any(p.pk == self.prod_earrings.pk for p in res6))

    def test_search_results_price_and_discount_serialization(self):
        """Search serialization includes DB selling price, regular price, sale price, and discount %."""
        serialized = pos.serialize_product(self.prod_dress)
        self.assertEqual(serialized['price'], '4000.00')  # Effective price is sale price
        self.assertEqual(serialized['regular_price'], '5000.00')
        self.assertEqual(serialized['sale_price'], '4000.00')
        self.assertTrue(serialized['has_discount'])
        self.assertEqual(serialized['discount_percent'], 20)
        self.assertEqual(serialized['stock_status_display'], 'In Stock')

    def test_catalogue_sorting(self):
        """Catalogue supports sorting by price_asc, price_desc, newest."""
        # Price ascending
        cat_asc = pos.catalogue_products(sort='price_asc')
        prices_asc = [p.effective_price for p in cat_asc]
        self.assertEqual(prices_asc, sorted(prices_asc))

        # Price descending
        cat_desc = pos.catalogue_products(sort='price_desc')
        prices_desc = [p.effective_price for p in cat_desc]
        self.assertEqual(prices_desc, sorted(prices_desc, reverse=True))

    def test_recommendation_engine_complementary_and_out_of_stock_exclusion(self):
        """Recommendation engine recommends complementary products and never out of stock or in-cart items."""
        # When dress is in cart
        recs = recommendations.get_cart_recommendations([self.prod_dress.pk])
        all_recs = recs['all']
        rec_ids = [p['id'] for p in all_recs]

        # 1. Dress itself must NOT be recommended
        self.assertNotIn(self.prod_dress.pk, rec_ids)

        # 2. Out of stock dress must NOT be recommended
        self.assertNotIn(self.prod_sold_out.pk, rec_ids)

        # 3. Complementary categories (Shoes, Bags, Accessories) should be recommended
        self.assertTrue(any(p['id'] in [self.prod_heels.pk, self.prod_clutch.pk, self.prod_earrings.pk] for p in all_recs))

        # 4. Complementary tier specific check
        comp_ids = [p['id'] for p in recs['complementary']]
        self.assertTrue(self.prod_heels.pk in comp_ids or self.prod_clutch.pk in comp_ids)

    def test_recommendation_engine_frequently_bought_together(self):
        """Historical orders with co-occurring items populate Frequently Bought Together tier."""
        # Create an order where dress and earrings were bought together
        order = Order.objects.create(
            number='ORD-TEST-HIST-01',
            status='confirmed',
            sales_channel='pos',
            total=Decimal('5200.00')
        )
        OrderItem.objects.create(
            order=order, product=self.prod_dress, quantity=1, price=self.prod_dress.effective_price
        )
        OrderItem.objects.create(
            order=order, product=self.prod_earrings, quantity=1, price=self.prod_earrings.effective_price
        )

        recs = recommendations.get_frequently_bought_together([self.prod_dress.pk])
        rec_ids = [p.pk for p in recs]
        self.assertIn(self.prod_earrings.pk, rec_ids)

    def test_pos_recommendations_endpoint(self):
        """Cashier POS till calls pos_recommendations endpoint dynamically."""
        self.client.force_login(self.cashier)
        url = reverse('pos_recommendations') + f'?items={self.prod_dress.pk}'
        resp = self.client.get(url, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get('ok'))
        self.assertIn('recommendations', data)
        rec_all = data['recommendations']['all']
        # Product in cart is excluded
        self.assertNotIn(self.prod_dress.pk, [p['id'] for p in rec_all])

    def test_storefront_cart_view_recommendations_context(self):
        """Storefront cart page renders recommendations context."""
        # Add dress to session cart
        session = self.client.session
        session['cart'] = {str(self.prod_dress.pk): 1}
        session.save()

        resp = self.client.get(reverse('cart'))
        self.assertEqual(resp.status_code, 200)
        self.assertIn('recommendations', resp.context)
        # Template includes "YOU MAY ALSO LIKE"
        self.assertContains(resp, 'YOU MAY ALSO LIKE')

    def test_storefront_ajax_cart_actions(self):
        """AJAX cart add, update, remove, and clear return JSON with new totals."""
        # 1. AJAX Cart Add
        add_url = reverse('cart_add', kwargs={'pk': self.prod_earrings.pk})
        resp1 = self.client.post(add_url, {'quantity': 2}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(resp1.status_code, 200)
        d1 = resp1.json()
        self.assertTrue(d1.get('ok'))
        self.assertEqual(d1.get('cart_count'), 2)
        self.assertIn('message', d1)

        # 2. AJAX Cart Update
        update_url = reverse('cart_update', kwargs={'pk': self.prod_earrings.pk})
        resp2 = self.client.post(update_url, {'quantity': 3}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(resp2.status_code, 200)
        d2 = resp2.json()
        self.assertTrue(d2.get('ok'))
        self.assertEqual(d2.get('cart_count'), 3)

        # 3. AJAX Cart Remove
        remove_url = reverse('cart_remove', kwargs={'pk': self.prod_earrings.pk})
        resp3 = self.client.post(remove_url, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(resp3.status_code, 200)
        d3 = resp3.json()
        self.assertTrue(d3.get('ok'))
        self.assertEqual(d3.get('cart_count'), 0)

        # 4. Cart Clear
        # Re-add item first
        self.client.post(add_url, {'quantity': 1})
        clear_url = reverse('cart_clear')
        resp4 = self.client.post(clear_url, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(resp4.status_code, 200)
        d4 = resp4.json()
        self.assertTrue(d4.get('ok'))
        self.assertEqual(d4.get('cart_count'), 0)
