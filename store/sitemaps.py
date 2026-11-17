from django.contrib.sitemaps import Sitemap
from django.urls import reverse

from .models import Category, Product


class StaticViewSitemap(Sitemap):
    priority = 0.5
    changefreq = 'weekly'

    def items(self):
        return ['home', 'catalogue', 'contact']

    def location(self, item):
        return reverse(item)


class ProductSitemap(Sitemap):
    priority = 0.8
    changefreq = 'daily'

    def items(self):
        return Product.objects.visible()

    def location(self, obj):
        return reverse('product_detail', args=[obj.slug])

    def lastmod(self, obj):
        return obj.updated_at


class CategorySitemap(Sitemap):
    priority = 0.6
    changefreq = 'weekly'

    def items(self):
        return Category.objects.filter(active=True)

    def location(self, obj):
        return reverse('catalogue')
