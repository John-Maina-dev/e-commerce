"""Remove products that have no usable image.

Safety-first by design:
  * default run is a DRY RUN — it only reports;
  * `--apply` performs the deletion, but only after exporting a JSON backup
    of every product it is about to remove (written to logs/);
  * a product counts as "imageless" only when it has no main image file,
    no external image_url AND no gallery images — i.e. nothing displayable.

Going forward the admin forms already refuse to publish an imageless
product; this command cleans up anything that predates that rule.
"""
import json
import logging
from pathlib import Path

from django.core.management.base import BaseCommand
from django.utils import timezone

from store.models import Product

logger = logging.getLogger('store')

BACKUP_DIR = Path('logs')


def imageless_products():
    def _is_imageless(p):
        return not p.image and not (p.image_url or '').strip() and not p.images.exists()
    return [p for p in Product.objects.prefetch_related('images') if _is_imageless(p)]


class Command(BaseCommand):
    help = 'Find (and optionally delete) products without any usable image.'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true',
                            help='Actually delete them (a JSON backup is written first).')

    def handle(self, *args, **options):
        targets = imageless_products()
        self.stdout.write(f'Products without a usable image: {len(targets)}')
        for p in targets:
            self.stdout.write(f'  - [{p.pk}] {p.name} (SKU {p.sku})')

        if not targets:
            self.stdout.write(self.style.SUCCESS('Nothing to do — every product has an image.'))
            return

        if not options['apply']:
            self.stdout.write('Dry run only. Re-run with --apply to export a backup and delete.')
            return

        BACKUP_DIR.mkdir(exist_ok=True)
        stamp = timezone.now().strftime('%Y%m%d-%H%M%S')
        backup_path = BACKUP_DIR / f'removed-imageless-products-{stamp}.json'
        payload = []
        for p in targets:
            payload.append({
                'name': p.name, 'slug': p.slug, 'sku': p.sku, 'barcode': p.barcode,
                'category': p.category.name if p.category_id else None,
                'price': str(p.price), 'sale_price': str(p.sale_price or ''),
                'cost_price': str(p.cost_price), 'stock': p.stock,
                'description': p.description, 'short_description': p.short_description,
                'image_url': p.image_url, 'created_at': str(p.created_at),
            })
        backup_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding='utf-8')
        self.stdout.write(f'Backup written to {backup_path}')

        for p in targets:
            logger.info('Deleting imageless product %s (%s)', p.name, p.sku)
            p.delete()
        self.stdout.write(self.style.SUCCESS(f'Deleted {len(targets)} product(s).'))
