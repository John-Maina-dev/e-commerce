import logging
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from .models import (AccountAuditLog, ContactMessage, CouponUsage, DataDeletionAuditLog,
                     InventoryAlert, InventoryChange, MpesaTransaction,
                     NewsletterSubscriber, Notification, Order, OrderItem,
                     OrderReturn, OrderStatusHistory, Payment, Product,
                     Review, UserProfile, WishlistItem)

logger = logging.getLogger('store')


def get_client_ip(request):
    """Retrieve client IP address considering proxy headers."""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        return x_forwarded_for.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR')


DATA_TYPE_CONFIGS = {
    'notifications': {
        'title': 'Notifications',
        'description': 'In-app alert records for staff and customers.',
        'icon': 'bell',
        'model': Notification,
    },
    'inventory_history': {
        'title': 'Inventory & Stock Logs',
        'description': 'Historical stock movement logs and resolved restock alerts.',
        'icon': 'archive',
        'model': InventoryChange,
    },
    'orders': {
        'title': 'Orders (All)',
        'description': 'Store orders, items, status histories, and associated records.',
        'icon': 'shopping-bag',
        'model': Order,
    },
    'guest_checkouts': {
        'title': 'Guest Checkouts',
        'description': 'Orders and details placed by unauthenticated guest customers.',
        'icon': 'user-x',
        'model': Order,
    },
    'mpesa_transactions': {
        'title': 'M-Pesa Transactions',
        'description': 'Daraja STK push and callback logs (pending, successful, failed, cancelled).',
        'icon': 'credit-card',
        'model': MpesaTransaction,
    },
    'users': {
        'title': 'User Accounts',
        'description': 'Customer and staff accounts (excluding protected Super Admins).',
        'icon': 'users',
        'model': User,
    },
    'subscriptions': {
        'title': 'Newsletter Subscriptions',
        'description': 'Email newsletter subscriber records and category preferences.',
        'icon': 'mail',
        'model': NewsletterSubscriber,
    },
    'contact_messages': {
        'title': 'Contact Messages',
        'description': 'Customer inquiries submitted via the Contact Us form.',
        'icon': 'message-square',
        'model': ContactMessage,
    },
    'reviews': {
        'title': 'Product Reviews',
        'description': 'Customer product ratings, feedback, and moderation flags.',
        'icon': 'star',
        'model': Review,
    },
}


def get_data_counts():
    """Returns total record counts for each manageable data type."""
    now = timezone.now()
    d30 = now - timedelta(days=30)
    super_admin_ids = UserProfile.objects.filter(role='super_admin').values_list('user_id', flat=True)

    return {
        'notifications': {
            'total': Notification.objects.count(),
            'read': Notification.objects.filter(read=True).count(),
            'older_30': Notification.objects.filter(created_at__lt=d30).count(),
        },
        'inventory_history': {
            'total': InventoryChange.objects.count(),
            'older_30': InventoryChange.objects.filter(created_at__lt=d30).count(),
            'alerts': InventoryAlert.objects.filter(is_resolved=True).count(),
        },
        'orders': {
            'total': Order.objects.count(),
            'cancelled': Order.objects.filter(status='cancelled').count(),
            'older_30': Order.objects.filter(created_at__lt=d30).count(),
        },
        'guest_checkouts': {
            'total': Order.objects.filter(user__isnull=True).count(),
            'older_30': Order.objects.filter(user__isnull=True, created_at__lt=d30).count(),
        },
        'mpesa_transactions': {
            'total': MpesaTransaction.objects.count(),
            'failed': MpesaTransaction.objects.filter(status__in=['failed', 'cancelled', 'timeout']).count(),
            'older_30': MpesaTransaction.objects.filter(created_at__lt=d30).count(),
        },
        'users': {
            'total': User.objects.exclude(is_superuser=True).exclude(id__in=super_admin_ids).count(),
            'customers': User.objects.filter(profile__role='customer').count(),
            'pending_or_suspended': User.objects.filter(profile__status__in=['pending', 'suspended', 'rejected']).count(),
        },
        'subscriptions': {
            'total': NewsletterSubscriber.objects.count(),
            'inactive': NewsletterSubscriber.objects.filter(active=False).count(),
        },
        'contact_messages': {
            'total': ContactMessage.objects.count(),
            'handled': ContactMessage.objects.filter(handled=True).count(),
        },
        'reviews': {
            'total': Review.objects.count(),
            'inactive': Review.objects.filter(active=False).count(),
        },
    }


def get_filtered_queryset(data_type, params=None):
    """
    Builds the filtered queryset for browsing, counting, and deleting records
    based on GET/POST parameters.
    """
    params = params or {}
    q = (params.get('q') or '').strip()
    status = (params.get('status') or '').strip()
    period = (params.get('period') or '').strip()
    scope = (params.get('scope') or '').strip()
    now = timezone.now()

    def get_period_cutoff(p):
        if p == 'older_7':
            return now - timedelta(days=7)
        if p == 'older_30':
            return now - timedelta(days=30)
        if p == 'older_60':
            return now - timedelta(days=60)
        if p == 'older_90':
            return now - timedelta(days=90)
        if p == 'older_365':
            return now - timedelta(days=365)
        return None

    if data_type == 'notifications':
        qs = Notification.objects.all().order_by('-created_at')
        if scope == 'read':
            qs = qs.filter(read=True)
        elif scope == 'unread':
            qs = qs.filter(read=False)
        elif scope == 'staff':
            qs = qs.filter(for_staff=True)
        elif scope == 'customer':
            qs = qs.filter(for_staff=False)
        cutoff = get_period_cutoff(period)
        if cutoff:
            qs = qs.filter(created_at__lt=cutoff)
        if q:
            qs = qs.filter(Q(title__icontains=q) | Q(message__icontains=q))
        return qs

    elif data_type == 'inventory_history':
        qs = InventoryChange.objects.select_related('product', 'user').order_by('-created_at')
        if status in ['create', 'adjust', 'sale', 'restock', 'return']:
            qs = qs.filter(action=status)
        cutoff = get_period_cutoff(period)
        if cutoff:
            qs = qs.filter(created_at__lt=cutoff)
        if q:
            qs = qs.filter(Q(product__name__icontains=q) | Q(note__icontains=q) | Q(user__username__icontains=q))
        return qs

    elif data_type == 'orders':
        qs = Order.objects.select_related('user').order_by('-created_at')
        if status and status != 'all':
            qs = qs.filter(status=status)
        if scope == 'registered':
            qs = qs.filter(user__isnull=False)
        elif scope == 'guest':
            qs = qs.filter(user__isnull=True)
        cutoff = get_period_cutoff(period)
        if cutoff:
            qs = qs.filter(created_at__lt=cutoff)
        if q:
            qs = qs.filter(Q(number__icontains=q) | Q(customer_name__icontains=q) | Q(email__icontains=q) | Q(phone__icontains=q))
        return qs

    elif data_type == 'guest_checkouts':
        qs = Order.objects.filter(user__isnull=True).order_by('-created_at')
        if status and status != 'all':
            qs = qs.filter(status=status)
        cutoff = get_period_cutoff(period)
        if cutoff:
            qs = qs.filter(created_at__lt=cutoff)
        if q:
            qs = qs.filter(Q(number__icontains=q) | Q(customer_name__icontains=q) | Q(email__icontains=q) | Q(phone__icontains=q))
        return qs

    elif data_type == 'mpesa_transactions':
        qs = MpesaTransaction.objects.select_related('order').order_by('-created_at')
        if status and status != 'all':
            qs = qs.filter(status=status)
        cutoff = get_period_cutoff(period)
        if cutoff:
            qs = qs.filter(created_at__lt=cutoff)
        if q:
            qs = qs.filter(Q(phone__icontains=q) | Q(mpesa_receipt__icontains=q) | Q(checkout_request_id__icontains=q) | Q(transaction_id__icontains=q))
        return qs

    elif data_type == 'users':
        # Super Admins are strictly excluded from deletion querysets
        super_admin_ids = UserProfile.objects.filter(role='super_admin').values_list('user_id', flat=True)
        qs = User.objects.exclude(is_superuser=True).exclude(id__in=super_admin_ids).select_related('profile').order_by('-date_joined')
        if scope in ['customer', 'cashier', 'admin']:
            qs = qs.filter(profile__role=scope)
        if status in ['pending', 'approved', 'rejected', 'suspended']:
            qs = qs.filter(profile__status=status)
        cutoff = get_period_cutoff(period)
        if cutoff:
            qs = qs.filter(date_joined__lt=cutoff)
        if q:
            qs = qs.filter(Q(username__icontains=q) | Q(email__icontains=q) | Q(first_name__icontains=q) | Q(last_name__icontains=q) | Q(profile__phone__icontains=q))
        return qs

    elif data_type == 'subscriptions':
        qs = NewsletterSubscriber.objects.select_related('user').order_by('-subscribed_at')
        if status == 'active':
            qs = qs.filter(active=True)
        elif status == 'inactive':
            qs = qs.filter(active=False)
        cutoff = get_period_cutoff(period)
        if cutoff:
            qs = qs.filter(subscribed_at__lt=cutoff)
        if q:
            qs = qs.filter(email__icontains=q)
        return qs

    elif data_type == 'contact_messages':
        qs = ContactMessage.objects.all().order_by('-created_at')
        if status == 'handled':
            qs = qs.filter(handled=True)
        elif status == 'unhandled':
            qs = qs.filter(handled=False)
        cutoff = get_period_cutoff(period)
        if cutoff:
            qs = qs.filter(created_at__lt=cutoff)
        if q:
            qs = qs.filter(Q(name__icontains=q) | Q(email__icontains=q) | Q(subject__icontains=q) | Q(message__icontains=q))
        return qs

    elif data_type == 'reviews':
        qs = Review.objects.select_related('product', 'user').order_by('-created_at')
        if status == 'active':
            qs = qs.filter(active=True)
        elif status == 'inactive':
            qs = qs.filter(active=False)
        if scope == 'verified':
            qs = qs.filter(verified_purchase=True)
        elif scope == 'unverified':
            qs = qs.filter(verified_purchase=False)
        cutoff = get_period_cutoff(period)
        if cutoff:
            qs = qs.filter(created_at__lt=cutoff)
        if q:
            qs = qs.filter(Q(product__name__icontains=q) | Q(name__icontains=q) | Q(comment__icontains=q))
        return qs

    return None


def execute_deletion(data_type, selection_mode, selected_ids, params, actor, ip_address):
    """
    Executes deletion within a database transaction, enforcing safety rules,
    proper relational cleanups (e.g. order anonymization on user deletion),
    and immutable audit logging.

    Returns:
        (success: bool, deleted_count: int, message: str)
    """
    if data_type not in DATA_TYPE_CONFIGS:
        return False, 0, f'Invalid data type: {data_type}'

    base_qs = get_filtered_queryset(data_type, params)
    if base_qs is None:
        return False, 0, 'Could not resolve target records.'

    if selection_mode == 'selected':
        if not selected_ids:
            return False, 0, 'No records were selected for deletion.'
        target_qs = base_qs.filter(id__in=selected_ids)
        filter_summary = f'Selected IDs: {len(selected_ids)} items'
    else:  # 'all' (filtered)
        target_qs = base_qs
        filter_summary = f'Filtered delete (status={params.get("status")}, period={params.get("period")}, q={params.get("q")})'

    with transaction.atomic():
        deleted_count = 0
        details_list = []

        if data_type == 'users':
            # Strict protection: ensure logged-in user or super admins are never deleted
            super_admin_ids = set(UserProfile.objects.filter(role='super_admin').values_list('user_id', flat=True))
            if selection_mode == 'selected' and selected_ids:
                attempted_protected = User.objects.filter(
                    Q(id__in=selected_ids),
                    Q(id=actor.pk) | Q(is_superuser=True) | Q(id__in=super_admin_ids)
                )
                if attempted_protected.exists():
                    return False, 0, 'Action blocked: Super Admin accounts cannot be deleted.'

            protected_users = target_qs.filter(Q(id=actor.pk) | Q(is_superuser=True) | Q(id__in=super_admin_ids))
            if protected_users.exists():
                return False, 0, 'Action blocked: Super Admin accounts cannot be deleted.'

            # Double check remaining super admins
            remaining_super_admins = User.objects.filter(Q(is_superuser=True) | Q(profile__role='super_admin')).exclude(id__in=target_qs.values_list('id', flat=True)).count()
            if remaining_super_admins < 1:
                return False, 0, 'Action blocked: System must have at least one active Super Admin.'

            for user in target_qs:
                username = user.username
                # 1. Anonymize user's orders so accounting, tax, revenue, and inventory are preserved
                orders_count = user.orders.count()
                for order in user.orders.all():
                    order.user = None
                    if '(Anonymized Account)' not in order.customer_name:
                        order.customer_name = f"{order.customer_name or username} (Anonymized Account)"
                    order.save(update_fields=['user', 'customer_name'])

                # 2. Unlink newsletter subscriptions
                NewsletterSubscriber.objects.filter(user=user).update(user=None)

                # 3. Clean up non-financial user-specific rows
                WishlistItem.objects.filter(user=user).delete()
                Notification.objects.filter(user=user).delete()

                # 4. Record individual account audit log
                AccountAuditLog.objects.create(
                    actor=actor,
                    target_user=None,
                    target_username=username,
                    action='delete',
                    old_value=getattr(user.profile, 'role', 'customer') if hasattr(user, 'profile') else 'unknown',
                    new_value='deleted',
                    note=f'Permanently deleted via Data Management. {orders_count} orders anonymized.',
                    ip_address=ip_address,
                )

                # 5. Delete profile and user
                if hasattr(user, 'profile'):
                    user.profile.delete()
                user.delete()
                deleted_count += 1
                details_list.append(f'User {username} (orders anonymized: {orders_count})')

        elif data_type in ['orders', 'guest_checkouts']:
            # Deleting orders safely removes order items, status history, and payments
            count = target_qs.count()
            sample_numbers = list(target_qs.values_list('number', flat=True)[:10])
            target_qs.delete()
            deleted_count = count
            details_list.append(f'Orders deleted: {sample_numbers}{"..." if count > 10 else ""}')

        elif data_type == 'inventory_history':
            # Also clean up resolved alerts if requested
            count = target_qs.count()
            target_qs.delete()
            deleted_count = count
            if params.get('delete_resolved_alerts') == '1':
                alerts_count = InventoryAlert.objects.filter(is_resolved=True).count()
                InventoryAlert.objects.filter(is_resolved=True).delete()
                deleted_count += alerts_count
                details_list.append(f'InventoryChanges deleted: {count}, Resolved Alerts deleted: {alerts_count}')
            else:
                details_list.append(f'InventoryChanges deleted: {count}')

        else:
            # Generic clean deletion
            count = target_qs.count()
            target_qs.delete()
            deleted_count = count
            details_list.append(f'{data_type} records deleted: {count}')

        # Create immutable DataDeletionAuditLog
        DataDeletionAuditLog.objects.create(
            actor=actor,
            actor_username=actor.username,
            data_type=data_type,
            records_deleted=deleted_count,
            filter_applied=filter_summary[:300],
            details='; '.join(details_list)[:2000],
            ip_address=ip_address,
        )

        logger.info(
            'DATA DELETION: %s deleted %d %s records from IP %s. Filters: %s',
            actor.username, deleted_count, data_type, ip_address, filter_summary
        )

    return True, deleted_count, f'Successfully deleted {deleted_count} {DATA_TYPE_CONFIGS[data_type]["title"]} record(s).'
