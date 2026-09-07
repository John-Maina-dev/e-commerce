import json
import random
from decimal import Decimal
from pathlib import Path

from django.core.management.base import BaseCommand
from django.utils.text import slugify

from store.models import Category, Coupon, Product, SiteSettings


class Command(BaseCommand):
    help = 'Seeds the Reeves Boutique product catalogue. Idempotent: safe to run repeatedly (keyed by SKU).'

    def add_arguments(self, parser):
        parser.add_argument('--stock', type=int, default=10, help='Default stock quantity for seeded products.')
        parser.add_argument('--reset', action='store_true', help='Reset stock to the given value for all products.')

    def handle(self, *args, **opts):
        file_path = Path(__file__).resolve().parents[2] / 'legacy_products.json'
        rows = json.loads(file_path.read_text(encoding='utf-8'))
        settings = SiteSettings.get()
        threshold = settings.low_stock_default or 5
        desired = settings.desired_stock_level or 10
        stock = opts['stock']

        counts = {'created': 0, 'updated': 0, 'categories': 0}
        n = len(rows)
        for i, row in enumerate(rows, 1):
            name, cat, price, old, rating, reviews, image = (list(row) + [None] * 7)[:7]
            category, created = Category.objects.get_or_create(name=cat)
            if created:
                counts['categories'] += 1
            defaults = {
                'name': name,
                'category': category,
                'brand': cat,
                'price': Decimal(str(price)),
                'old_price': Decimal(str(old)) if old is not None else None,
                'sale_price': None,
                'image_url': image or '',
                'stock': stock,
                'low_stock_threshold': threshold,
                'desired_stock_level': desired,
                'rating': Decimal(str(rating)) if rating else Decimal('4.5'),
                'reviews_count': int(reviews or 0),
                'featured': i <= 12,
                'is_new': i > n - 8,
                'is_bestseller': (reviews or 0) >= 200,
                'active': True,
            }
            obj, was_created = Product.objects.update_or_create(sku=f'RB-{i:04}', defaults=defaults)
            if was_created:
                counts['created'] += 1
            else:
                counts['updated'] += 1

        if opts['reset']:
            Product.objects.all().update(stock=stock)

        Coupon.objects.get_or_create(
            code='WELCOME10',
            defaults={
                'discount_type': Coupon.PERCENT,
                'value': Decimal('10.00'),
                'min_order_amount': Decimal('2000.00'),
                'max_uses': 0,
                'per_user_limit': 1,
                'active': True,
            },
        )

        self.stdout.write(self.style.SUCCESS(
            f'Seed complete: {counts["created"]} created, {counts["updated"]} updated, '
            f'{counts["categories"]} categories added. Try coupon WELCOME10 at checkout.'))
