"""Intelligent Product Recommendation & Cross-Selling Service for Reeves Boutique.

Provides dynamic, context-aware product recommendations for both the in-store POS
terminal and the online customer shopping cart.

Recommendation Strategies:
1. Frequently Bought Together: products co-purchased in past customer orders.
2. Complete Your Look: complementary cross-category matching (e.g. Shoes -> Bags,
   Dresses -> Shoes/Accessories) and same-brand pairings.
3. Related Products: same category or brand alternatives.
4. Popular & Best-Sellers: high-velocity items with high ratings/sales.

Guarantees:
- Never recommends products already in the cart.
- Never recommends out-of-stock items (stock <= 0).
- Only recommends active, visible storefront products.
- Always delivers fresh, server-verified database prices and stock.
"""
from collections import OrderedDict
from decimal import Decimal
import logging

from django.db.models import Count, Q

from .models import OrderItem, Product

logger = logging.getLogger('store')

# Complementary category relationships for intelligent retail cross-selling
COMPLEMENTARY_MAP = {
    'clothing': ['shoes', 'bags', 'accessories', 'jewelry'],
    'clothes': ['shoes', 'bags', 'accessories', 'jewelry'],
    'dress': ['shoes', 'bags', 'accessories', 'jewelry'],
    'dresses': ['shoes', 'bags', 'accessories', 'jewelry'],
    'tops': ['pants', 'skirts', 'accessories', 'jackets'],
    'shirts': ['pants', 'suits', 'ties', 'belts', 'shoes'],
    'shoes': ['socks', 'accessories', 'bags', 'shoe-care'],
    'footwear': ['socks', 'accessories', 'bags'],
    'bags': ['wallets', 'accessories', 'shoes', 'scarves'],
    'handbags': ['wallets', 'accessories', 'shoes', 'scarves'],
    'accessories': ['bags', 'shoes', 'clothing', 'dresses'],
}


def serialize_rec_product(p, reason='Recommended for you'):
    """Serialize product into standard format for UI display and cart insertion."""
    return {
        'id': p.pk,
        'name': p.name,
        'slug': p.slug,
        'sku': p.sku,
        'barcode': p.barcode or '',
        'price': str(p.effective_price),
        'regular_price': str(p.price),
        'sale_price': str(p.sale_price) if p.sale_price is not None else None,
        'has_discount': p.has_discount,
        'discount_percent': p.discount_percent,
        'stock': p.stock,
        'stock_status': p.stock_status,
        'image': p.image_src or '',
        'category': p.category.name if p.category_id else '',
        'category_slug': p.category.slug if p.category_id else '',
        'brand': p.brand or '',
        'rating': str(p.rating),
        'reviews_count': p.reviews_count,
        'recommendation_reason': reason,
    }


def get_cart_recommendations(cart_product_ids, limit=8):
    """Generate categorized and ranked product recommendations based on cart items.

    Args:
        cart_product_ids: iterable of Product PKs currently in the cart.
        limit: maximum number of items per recommendation group.

    Returns:
        dict with keys:
            'you_may_also_like': list of prioritized deduplicated recommendations
            'frequently_bought': list of co-purchased items
            'complete_your_look': list of complementary cross-category items
            'related_products': list of same-category / brand alternatives
            'popular_products': list of storewide bestsellers
    """
    clean_pids = set()
    for pid in (cart_product_ids or []):
        try:
            clean_pids.add(int(pid))
        except (TypeError, ValueError):
            continue

    # Base queryset: visible, in stock, and strictly excluding products already in cart
    base_qs = Product.objects.visible().in_stock().select_related('category')
    if clean_pids:
        base_qs = base_qs.exclude(pk__in=clean_pids)

    # 1. Storewide Popular Products (Fallback and generic recommendation)
    popular_qs = (base_qs.order_by('-is_bestseller', '-sales_count', '-rating', '-created_at')[:limit])
    popular_products = list(popular_qs)

    # If cart is empty, return popular products as the default recommendations
    if not clean_pids:
        serialized_popular = [
            serialize_rec_product(p, 'Bestseller in store') for p in popular_products
        ]
        return {
            'you_may_also_like': serialized_popular,
            'frequently_bought': serialized_popular[:4],
            'complete_your_look': [],
            'related_products': [],
            'popular_products': serialized_popular,
        }

    # Fetch cart product models to inspect categories and brands
    cart_products = list(
        Product.objects.visible().filter(pk__in=clean_pids).select_related('category')
    )
    cart_category_ids = {p.category_id for p in cart_products if p.category_id}
    cart_category_slugs = {p.category.slug.lower() for p in cart_products if p.category}
    cart_category_names = {p.category.name.lower() for p in cart_products if p.category}
    cart_brands = {p.brand.strip().lower() for p in cart_products if p.brand and p.brand.strip()}

    # 2. Frequently Bought Together (Co-purchased in past completed/paid orders)
    past_order_ids = (
        OrderItem.objects.filter(product_id__in=clean_pids)
        .values_list('order_id', flat=True)[:150]
    )
    frequently_bought = []
    if past_order_ids:
        co_purchased_qs = (
            base_qs.filter(order_items__order_id__in=past_order_ids)
            .annotate(co_count=Count('id'))
            .order_by('-co_count', '-sales_count')[:limit]
        )
        frequently_bought = list(co_purchased_qs)

    # 3. Complete Your Look (Cross-category complementary styling & brand matches)
    target_comp_slugs = set()
    for cat_slug in cart_category_slugs:
        for pattern, targets in COMPLEMENTARY_MAP.items():
            if pattern in cat_slug:
                target_comp_slugs.update(targets)
    for cat_name in cart_category_names:
        for pattern, targets in COMPLEMENTARY_MAP.items():
            if pattern in cat_name:
                target_comp_slugs.update(targets)

    complete_look_q = Q()
    for target in target_comp_slugs:
        complete_look_q |= Q(category__slug__icontains=target) | Q(category__name__icontains=target)

    # Also match accessories or same brand if brand is known
    if cart_brands:
        for b in cart_brands:
            complete_look_q |= Q(brand__iexact=b)

    complete_your_look = []
    if complete_look_q:
        complete_your_look = list(
            base_qs.filter(complete_look_q)
            .order_by('-sales_count', '-rating', '-created_at')[:limit]
        )

    # 4. Related Products (Same category alternatives)
    related_products = []
    if cart_category_ids:
        related_qs = (
            base_qs.filter(category_id__in=cart_category_ids)
            .order_by('-sales_count', '-rating', '-created_at')[:limit]
        )
        related_products = list(related_qs)

    # 5. Composite Ranking for "YOU MAY ALSO LIKE"
    # Blend priorities:
    # 1st: Frequently Bought Together
    # 2nd: Complete Your Look
    # 3rd: Related Products (same category)
    # 4th: Popular Products
    ranked_dict = OrderedDict()

    for p in frequently_bought:
        if p.pk not in ranked_dict:
            ranked_dict[p.pk] = serialize_rec_product(p, 'Frequently bought together')

    for p in complete_your_look:
        if p.pk not in ranked_dict:
            ranked_dict[p.pk] = serialize_rec_product(p, 'Complete your look')

    for p in related_products:
        if p.pk not in ranked_dict:
            ranked_dict[p.pk] = serialize_rec_product(p, 'Related product')

    for p in popular_products:
        if p.pk not in ranked_dict:
            ranked_dict[p.pk] = serialize_rec_product(p, 'Popular choice')

    all_ranked = list(ranked_dict.values())[:limit]

    return {
        'all': all_ranked,
        'you_may_also_like': all_ranked,
        'frequently_bought': [
            serialize_rec_product(p, 'Frequently bought together') for p in frequently_bought
        ],
        'complete_your_look': [
            serialize_rec_product(p, 'Complete your look') for p in complete_your_look
        ],
        'complementary': [
            serialize_rec_product(p, 'Complete your look') for p in complete_your_look
        ],
        'related_products': [
            serialize_rec_product(p, 'Related product') for p in related_products
        ],
        'popular_products': [
            serialize_rec_product(p, 'Popular choice') for p in popular_products
        ],
    }


def get_frequently_bought_together(cart_product_ids, limit=4):
    """Convenience helper returning product instances co-purchased with cart items."""
    clean_pids = [int(p) for p in cart_product_ids if str(p).isdigit()]
    if not clean_pids:
        return []
    past_order_ids = (
        OrderItem.objects.filter(product_id__in=clean_pids)
        .values_list('order_id', flat=True)[:150]
    )
    if not past_order_ids:
        return []
    return list(
        Product.objects.visible().in_stock()
        .exclude(pk__in=clean_pids)
        .filter(order_items__order_id__in=past_order_ids)
        .annotate(co_count=Count('id'))
        .order_by('-co_count', '-sales_count')[:limit]
    )
