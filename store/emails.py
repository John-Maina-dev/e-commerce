import logging

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.urls import reverse

from .models import SiteSettings

logger = logging.getLogger('store')


def order_url(order):
    return reverse('order_detail', args=[order.number])


def send_html_email(subject, to, template, context=None, from_email=None):
    s = SiteSettings.get()
    if not s.smtp_enabled:
        logger.info('Email not sent (%s) because SMTP is disabled in settings.', subject)
        return False
    context = context or {}
    context.setdefault('site', s)
    context.setdefault('protocol', 'https' if not settings.DEBUG else 'http')
    context.setdefault('domain', settings.ALLOWED_HOSTS[0] if settings.ALLOWED_HOSTS else 'localhost')
    html = render_to_string(template, context)
    text = render_to_string(template.replace('.html', '.txt'), context) if _txt_exists(template) else None
    sender = from_email or (s.smtp_from_email or settings.DEFAULT_FROM_EMAIL)
    if s.smtp_sender_name and sender and '<' not in sender:
        sender = f'{s.smtp_sender_name} <{sender}>'
    email = EmailMultiAlternatives(subject, text or '', sender, [to])
    email.attach_alternative(html, 'text/html')
    try:
        email.send(fail_silently=False)
        logger.info('Email sent to %s: %s', to, subject)
        return True
    except Exception as e:
        logger.error('Email failed to %s (%s): %s', to, subject, e)
        return False


def _txt_exists(template):
    from pathlib import Path
    from django.conf import settings as dj_settings
    path = Path(dj_settings.BASE_DIR) / 'templates' / template.replace('.html', '.txt')
    return path.exists()


def order_confirmation(order):
    subject = f'Order {order.number} received at {SiteSettings.get().store_name}'
    return send_html_email(subject, order.email, 'email/order_confirmation.html',
                           {'order': order, 'order_url': order_url(order)})


def payment_success(order, reference=''):
    subject = f'Payment confirmed for order {order.number}'
    return send_html_email(subject, order.email, 'email/payment_success.html',
                           {'order': order, 'reference': reference, 'order_url': order_url(order)})


def payment_failed(order, reason=''):
    subject = f'Payment failed for order {order.number}'
    return send_html_email(subject, order.email, 'email/payment_failed.html',
                           {'order': order, 'reason': reason, 'order_url': order_url(order)})


def order_status_change(order):
    subject = f'Order {order.number} is now {order.get_status_display()}'
    return send_html_email(subject, order.email, 'email/order_status.html',
                           {'order': order, 'order_url': order_url(order)})


def welcome(user):
    subject = f'Welcome to {SiteSettings.get().store_name}'
    return send_html_email(subject, user.email, 'email/welcome.html', {'user': user})


def password_reset(to_email, reset_url, subject, username=''):
    s = SiteSettings.get()
    return send_html_email(subject, to_email, 'email/password_reset.html', {
        'username': username,
        'reset_url': reset_url,
        'expires_hours': max(1, round(s.password_reset_timeout_seconds / 3600)),
    })


def contact_confirmation(contact):
    subject = 'We received your message'
    return send_html_email(subject, contact.email, 'email/contact.html', {'contact': contact})


def inventory_alert(alert):
    s = SiteSettings.get()
    to = (s.inventory_alert_email or '').strip()
    if not to:
        return False
    subject = f'{s.store_name} · {alert.get_alert_type_display()}: {alert.product.name}'
    return send_html_email(subject, to, 'email/inventory_alert.html', {
        'alert': alert,
        'product': alert.product,
        'stock': alert.product.stock,
        'low_stock_threshold': alert.product.low_stock_threshold,
        'desired_stock_level': alert.product.desired_stock_level,
        'recommended_restock_qty': alert.product.recommended_restock_qty,
    })


def staff_notification(to_email, title, message='', link=''):
    """Generic admin email for store events (new orders, payments, reviews...)."""
    s = SiteSettings.get()
    subject = f'{s.store_name} · {title}'
    return send_html_email(subject, to_email, 'email/staff_notification.html', {
        'title': title,
        'message': message,
        'link': link,
    })
