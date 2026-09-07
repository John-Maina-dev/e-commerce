import logging
from datetime import timedelta

from django.urls import reverse
from django.utils import timezone

from . import emails
from .models import Notification, SiteSettings

logger = logging.getLogger('store')

# Notification categories (mirror Notification.CATEGORY_CHOICES).
ORDER = 'order'
PAYMENT = 'payment'
INVENTORY = 'inventory'
REVIEW = 'review'
CUSTOMER = 'customer'
ACCOUNT = 'account'
SYSTEM = 'system'


def notify_staff(title, message='', *, category='', link=''):
    """Create an in-system notification for the admin inbox."""
    return Notification.create(title, message, for_staff=True, category=category, link=link)


def notify_user(user, title, message='', *, category='', link=''):
    """Create an in-system notification for a signed-in customer.

    Anonymous/None users have no inbox, so nothing is created (email is the
    only channel for guests).
    """
    if not user or not getattr(user, 'is_authenticated', False):
        return None
    return Notification.create(title, message, for_staff=False, user=user,
                               category=category, link=link)


def _staff_email(title, message='', link=''):
    """Send the generic admin notification email when one is configured."""
    s = SiteSettings.get()
    to = (s.staff_notifications_email or '').strip()
    if not to:
        return False
    try:
        return emails.staff_notification(to, title, message, link)
    except Exception:
        logger.exception('Failed to send staff notification email: %s', title)
        return False


# --------------------------------------------------------------------------- #
# Real-event notifications. Each is called only from the code path where the
# underlying event actually happened — no notifications are ever fabricated.
# --------------------------------------------------------------------------- #

def order_placed(order):
    """Customer placed an order: admin bell + admin email + customer email,
    and a customer inbox entry when the order belongs to an account."""
    s = SiteSettings.get()
    manage_link = reverse('manage_order_detail', args=[order.number])
    customer_link = reverse('order_detail', args=[order.number])
    notify_staff(f'New order {order.number}',
                 f'{order.customer_name} · {order.total} {s.currency}',
                 category=ORDER, link=manage_link)
    notify_user(order.user, f'Order {order.number} received',
                f'We received your order and will email you once it is confirmed.',
                category=ORDER, link=customer_link)
    _staff_email(f'New order {order.number}',
                 f'{order.customer_name} placed an order for {order.total} {s.currency}.',
                 manage_link)
    if order.email:
        emails.order_confirmation(order)


def payment_received(order, reference='', *, verified_by=None):
    """A payment was confirmed (gateway callback or staff approval)."""
    s = SiteSettings.get()
    manage_link = reverse('manage_order_detail', args=[order.number])
    customer_link = reverse('order_detail', args=[order.number])
    notify_staff(f'Payment received for {order.number}',
                 f'{reference or "Paid"} · {order.total} {s.currency}',
                 category=PAYMENT, link=manage_link)
    notify_user(order.user, f'Payment received for {order.number}',
                f'Your payment for order {order.number} has been received.',
                category=PAYMENT, link=customer_link)
    _staff_email(f'Payment received for {order.number}',
                 f'{reference or "Paid"} · {order.total} {s.currency}.',
                 manage_link)
    if order.email:
        emails.payment_success(order, reference)


def payment_failed(order, reason='', *, cancelled=False, verified_by=None):
    """A payment failed or was cancelled."""
    label = 'cancelled' if cancelled else 'failed'
    manage_link = reverse('manage_order_detail', args=[order.number])
    customer_link = reverse('order_detail', args=[order.number])
    detail = reason or f'The payment did not go through.'
    notify_staff(f'Payment {label} for {order.number}', detail,
                 category=PAYMENT, link=manage_link)
    notify_user(order.user, f'Payment {label} for {order.number}',
                detail, category=PAYMENT, link=customer_link)
    _staff_email(f'Payment {label} for {order.number}', detail, manage_link)
    if order.email:
        emails.payment_failed(order, reason)


def payment_requires_review(order, detail):
    """A gateway callback succeeded but the data needs a human check."""
    link = reverse('manage_payments')
    notify_staff(f'Payment requires review: {order.number}', detail,
                 category=PAYMENT, link=link)
    _staff_email(f'Payment requires review: {order.number}', detail, link)


def order_status_changed(order):
    """An order moved to a new status (processing/shipped/delivered/...)."""
    notify_user(order.user, f'Order {order.number} is now {order.get_status_display()}',
                f'Order {order.number} · {order.total} {SiteSettings.get().currency}',
                category=ORDER, link=reverse('order_detail', args=[order.number]))
    if order.email:
        emails.order_status_change(order)


def new_customer(user):
    """A customer account was created."""
    s = SiteSettings.get()
    link = reverse('manage_customers')
    notify_staff(f'New customer: {user.username}',
                 f'{user.email or "no email"} · joined {timezone.now():%d %b %Y}',
                 category=CUSTOMER, link=link)
    notify_user(user, f'Welcome to {s.store_name}',
                'Your account is ready. Track your orders and save your details.',
                category=ACCOUNT, link=reverse('account'))
    _staff_email(f'New customer: {user.username}', user.email or '', link)
    emails.welcome(user)


def new_review(review):
    """A customer submitted a product review (awaiting approval)."""
    link = reverse('manage_reviews')
    snippet = (review.comment or '')[:140]
    notify_staff(f'New review: {review.product.name}',
                 f'{review.rating}★ · {snippet}{"…" if len(review.comment or "") > 140 else ""}',
                 category=REVIEW, link=link)
    _staff_email(f'New review: {review.product.name}',
                 f'{review.rating}★ review by {review.user or review.name}', link)


def inventory_alert(alert):
    """A product crossed its low-stock / out-of-stock threshold."""
    notify_staff(f'{alert.get_alert_type_display()}: {alert.product.name}',
                 f'{alert.product.name} · {alert.product.stock} in stock · SKU {alert.product.sku}',
                 category=INVENTORY, link=reverse('inventory'))
    try:
        return emails.inventory_alert(alert)
    except Exception:
        logger.exception('Failed to send inventory alert email for %s', alert.product.name)
        return False


def fulfillment_blocked(order, detail):
    """An order was paid but stock can no longer cover its items."""
    link = reverse('manage_order_detail', args=[order.number])
    notify_staff(f'Paid but cannot be fulfilled: {order.number}',
                 f'{detail} — check stock and adjust the order.',
                 category=ORDER, link=link)
    _staff_email(f'Paid but cannot be fulfilled: {order.number}', detail, link)


def password_reset_sent(user, to_email):
    """A password reset email was sent to a customer."""
    notify_user(user, 'Password reset email sent',
                f'We emailed a reset link to {to_email}. The link expires in a few hours.',
                category=ACCOUNT)


def system_error(title, message=''):
    """Record a server error in the admin inbox, deduplicated.

    Only records one error per title in a 15-minute window so a repeated
    failure cannot flood the bell.
    """
    cutoff = timezone.now() - timedelta(minutes=15)
    if Notification.objects.filter(for_staff=True, category=SYSTEM, title=title,
                                   read=False, created_at__gte=cutoff).exists():
        return None
    notification = notify_staff(title, message, category=SYSTEM)
    _staff_email(title, message)
    return notification
