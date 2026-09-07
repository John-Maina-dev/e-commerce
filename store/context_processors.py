from .models import Category, Notification, SiteSettings
from .services import cart_count


def store_context(request):
    s = SiteSettings.get()
    cart = request.session.get('cart', {})
    wishlist_count = 0
    wishlist_ids = set()
    customer_unread_count = 0
    if request.user.is_authenticated:
        wishlist_ids = set(request.user.wishlist_items.values_list('product_id', flat=True))
        wishlist_count = len(wishlist_ids)
        customer_unread_count = request.user.notifications.filter(read=False).count()
    return {
        'site_settings': s,
        'cart_count': cart_count(request),
        'wishlist_count': wishlist_count,
        'wishlist_ids': wishlist_ids,
        'customer_unread_count': customer_unread_count,
        'currency': s.currency,
        'nav_categories': Category.objects.filter(active=True)[:8],
    }


def manage_nav(request):
    """Context for the admin top bar (notifications + unread count)."""
    if not (request.user.is_authenticated and request.user.is_staff):
        return {'recent_notifications': [], 'unread_notifications': 0}
    return {
        'recent_notifications': Notification.objects.filter(for_staff=True)
                               .order_by('read', '-created_at')[:6],
        'unread_notifications': Notification.objects.filter(read=False, for_staff=True).count(),
    }
