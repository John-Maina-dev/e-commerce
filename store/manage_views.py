import logging
import os
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Case, Count, F, Q, Sum, When
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from . import mpesa, notify, services
from .decorators import (ROLE_ADMIN, ROLE_SUPER_ADMIN, admin_required, has_role,
                         manager_required, role_required, staff_required, super_admin_required)
from .forms import CouponForm, MpesaSettingsForm, ProductForm
from .models import (AccountAuditLog, Category, Coupon, InventoryAlert, InventoryChange, Notification,
                     Order, OrderItem, OrderStatusHistory, Payment, Product,
                     ProductImage, Review, SiteSettings, UserProfile)

logger = logging.getLogger('store')

ZERO = Decimal('0.00')


@staff_required
def dashboard(request):
    s = SiteSettings.get()
    now = timezone.now()
    today = now.date()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    paid = Q(status__in=Order.PAID_STATUSES)
    orders_all = Order.objects.all()
    paid_orders = orders_all.filter(paid)
    sales_agg = paid_orders.aggregate(v=Sum('total'))
    total_revenue = sales_agg['v'] or ZERO
    today_sales = paid_orders.filter(created_at__date=today).aggregate(v=Sum('total'))['v'] or ZERO
    monthly_sales = paid_orders.filter(created_at__gte=month_start).aggregate(v=Sum('total')) or {}
    monthly_sales = monthly_sales.get('v') or ZERO

    # Channel split for today (online store vs in-store till) and all-time.
    today_paid = paid_orders.filter(created_at__date=today)
    today_pos = today_paid.filter(sales_channel='pos').aggregate(v=Sum('total'))['v'] or ZERO
    today_online = today_paid.filter(sales_channel='online').aggregate(v=Sum('total'))['v'] or ZERO
    pos_revenue = paid_orders.filter(sales_channel='pos').aggregate(v=Sum('total'))['v'] or ZERO
    online_revenue = paid_orders.filter(sales_channel='online').aggregate(v=Sum('total'))['v'] or ZERO
    pending_payments = Payment.objects.filter(status__in=('pending', 'processing')).count()

    top_products = (Product.objects.annotate(units_sold=Sum('order_items__quantity'))
                    .filter(units_sold__gt=0).order_by('-units_sold')[:5])

    products = Product.objects.all()
    low_stock = products.filter(stock__gt=0, stock__lte=F('low_stock_threshold')).count()
    out_of_stock = products.filter(stock__lte=0).count()

    open_alerts = InventoryAlert.objects.filter(is_resolved=False).select_related('product')

    recent_orders = orders_all.select_related('user')[:8]
    recent_customers = (User.objects.annotate(order_count=Count('orders')).order_by('-date_joined')[:8])
    guest_orders = orders_all.filter(user__isnull=True)

    attention_payments = Payment.objects.filter(
        status__in=('pending', 'processing', 'requires_review')).select_related('order')

    week_days = [(now - timedelta(days=i)).date() for i in range(6, -1, -1)]
    day_totals = {
        d['created_at__date']: d['v']
        for d in paid_orders.filter(created_at__date__gte=week_days[0])
        .values('created_at__date').annotate(v=Sum('total'))
    }
    week_sales = [{'label': d.strftime('%a'), 'revenue': day_totals.get(d, ZERO)} for d in week_days]

    context = {
        'total_revenue': total_revenue,
        'total_orders': orders_all.count(),
        'pending_orders': orders_all.filter(status='pending').count(),
        'completed_orders': orders_all.filter(status='delivered').count(),
        'total_customers': User.objects.count() + guest_orders.values('phone').distinct().count(),
        'total_products': products.count(),
        'low_stock': low_stock,
        'out_of_stock': out_of_stock,
        'restock_required': low_stock + out_of_stock,
        'open_alerts': open_alerts.count(),
        'inventory_alerts': open_alerts[:5],
        'today_sales': today_sales,
        'today_pos_sales': today_pos,
        'today_online_sales': today_online,
        'pos_revenue': pos_revenue,
        'online_revenue': online_revenue,
        'pending_payments_count': pending_payments,
        'top_products': top_products,
        'monthly_sales': monthly_sales,
        'recent_orders': recent_orders,
        'recent_customers': recent_customers,
        'attention_payments': attention_payments[:5],
        'attention_payments_count': attention_payments.count(),
        'notifications': Notification.objects.filter(for_staff=True)[:10],
        'unread_notifications': Notification.objects.filter(read=False, for_staff=True).count(),
        'week_sales': week_sales,
    }
    return render(request, 'manage/dashboard.html', context)


# --------------------------------------------------------------------------- #
# Products
# --------------------------------------------------------------------------- #

PRODUCT_SORTS = {
    'name': 'name',
    '-name': '-name',
    'sku': 'sku',
    'category': 'category__name',
    'price': 'effective',
    '-price': '-effective',
    'stock': 'stock',
    '-stock': '-stock',
    'created': '-created_at',
}


def _set_product_flags(product, **flags):
    product.__dict__.update(flags)
    product.save(update_fields=list(flags) + ['updated_at'])


PRODUCT_ACTIONS = {
    'activate': lambda p: _set_product_flags(p, active=True),
    'deactivate': lambda p: _set_product_flags(p, active=False),
    'hide': lambda p: _set_product_flags(p, hidden=True),
    'unhide': lambda p: _set_product_flags(p, hidden=False),
    'archive': lambda p: _set_product_flags(p, is_archived=True),
    'restore': lambda p: _set_product_flags(p, is_archived=False),
}

PRODUCT_ACTION_VERBS = {
    'activate': 'activated',
    'deactivate': 'deactivated',
    'hide': 'hidden',
    'unhide': 'unhidden',
    'archive': 'archived',
    'restore': 'restored',
}


@staff_required
def manage_products(request):
    qs = Product.objects.select_related('category')
    q = request.GET.get('q', '').strip()
    category = request.GET.get('category', '')
    status = request.GET.get('status', '')
    stock = request.GET.get('stock', '')
    sort = request.GET.get('sort', '')

    if status == 'archived':
        qs = qs.filter(is_archived=True)
    else:
        qs = qs.filter(is_archived=False)
        if status == 'active':
            qs = qs.filter(active=True, hidden=False)
        elif status == 'inactive':
            qs = qs.filter(active=False)
        elif status == 'hidden':
            qs = qs.filter(hidden=True)
    if category:
        qs = qs.filter(category__slug=category)
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(sku__icontains=q) | Q(brand__icontains=q)
                       | Q(category__name__icontains=q))
    if stock == 'low':
        qs = qs.filter(stock__gt=0, stock__lte=F('low_stock_threshold'))
    elif stock == 'out':
        qs = qs.filter(stock__lte=0)
    elif stock == 'healthy':
        qs = qs.filter(stock__gt=F('low_stock_threshold'))

    qs = qs.annotate(
        effective=Case(When(sale_price__isnull=False, then=F('sale_price')), default=F('price')),
        order_count=Count('order_items'),
    )
    qs = qs.order_by(PRODUCT_SORTS.get(sort, '-created_at'))

    paginator = Paginator(qs, 20)
    page = paginator.get_page(request.GET.get('page'))
    open_alert_product_ids = set(InventoryAlert.objects.filter(is_resolved=False).values_list('product_id', flat=True))
    return render(request, 'manage/products.html', {
        'page': page, 'q': q, 'category': category, 'status': status, 'stock': stock, 'sort': sort,
        'categories': Category.objects.all(),
        'total_products': Product.objects.filter(is_archived=False).count(),
        'archived_count': Product.objects.filter(is_archived=True).count(),
        'open_alert_product_ids': open_alert_product_ids,
    })


@manager_required
def product_add(request):
    form = ProductForm()
    if request.method == 'POST':
        form = ProductForm(request.POST, request.FILES)
        if form.is_valid():
            product = form.save()
            _save_extra_images(product, request)
            services.record_inventory_change(product, 'create', old_qty=0, new_qty=product.stock,
                                             note='Product created', user=request.user)
            services.evaluate_product_stock(product, user=request.user)

            # Automatic or requested subscriber notifications for new items
            notify_subscribers = request.POST.get('notify_subscribers') == 'on' or (product.is_new and product.is_visible)
            if notify_subscribers:
                count = services.notify_subscribers_new_arrival(product, admin_user=request.user)
                if count:
                    messages.info(request, f'New arrival alert sent to {count} active subscriber(s).')

            if product.is_visible:
                messages.success(request, f'Product "{product.name}" created and is live on the storefront.')
            else:
                messages.success(request, f'Product "{product.name}" saved. It is not shown on the storefront yet.')
            return redirect('manage_products')
    return render(request, 'manage/product_form.html', {'form': form, 'title': 'Add product'})


@manager_required
def product_edit(request, pk):
    product = get_object_or_404(Product, pk=pk)
    form = ProductForm(instance=product)
    if request.method == 'POST':
        form = ProductForm(request.POST, request.FILES, instance=product)
        if form.is_valid():
            old_stock = product.stock
            old_image_name = product.image.name if product.image else None
            product = form.save()
            if product.stock != old_stock:
                services.record_inventory_change(product, 'restock' if product.stock > old_stock else 'adjust',
                                                 old_qty=old_stock, new_qty=product.stock,
                                                 note='Edited via product form', user=request.user)
            _save_extra_images(product, request)
            removed = request.POST.getlist('remove_image')
            if removed:
                delete_image_rows(ProductImage.objects.filter(pk__in=removed, product=product))
            new_image_name = product.image.name if product.image else None
            if old_image_name and new_image_name and old_image_name != new_image_name:
                try:
                    from django.core.files.storage import default_storage
                    if default_storage.exists(old_image_name):
                        default_storage.delete(old_image_name)
                except OSError:
                    logger.exception('Failed to remove replaced main image %s', old_image_name)
            services.evaluate_product_stock(product, user=request.user)
            if request.POST.get('notify_subscribers') == 'on':
                product.subscribers_notified = False  # allow manual re-dispatch if checked
                count = services.notify_subscribers_new_arrival(product, admin_user=request.user)
                if count:
                    messages.info(request, f'Product alert sent to {count} active subscriber(s).')
            messages.success(request, 'Product updated.')
            return redirect('manage_products')
    return render(request, 'manage/product_form.html', {'form': form, 'title': 'Edit product', 'product': product})


def _save_extra_images(product, request):
    order = product.images.count() or 0
    for f in request.FILES.getlist('images'):
        try:
            services.validate_image_upload(f)
        except ValidationError as e:
            messages.error(request, f'Image "{f.name}" skipped: {e.message}')
            continue
        ProductImage.objects.create(product=product, image=f, order=order)
        order += 1


def _delete_file_storage(field):
    """Best-effort removal of a stored image field's file on disk. Never
    raises — deletion must not block the product workflow."""
    try:
        if field and field.storage.exists(field.name):
            field.storage.delete(field.name)
    except OSError:
        logger.exception('Failed to remove product media file %s', field.name if field else 'n/a')


def delete_product_media(product):
    """Remove the physical image files owned by a product (main image and
    gallery images) without touching files that belong to any other product.

    The image DB rows themselves are removed by the ORM's cascade when the
    product (or the image row) is deleted; this helper only clears the files
    so we do not leave orphaned files behind.
    """
    files = []
    if product.image:
        files.append(product.image)
    for img in product.images.all():
        if img.image:
            files.append(img.image)
    for field in files:
        _delete_file_storage(field)


def delete_image_rows(images):
    """Delete ProductImage rows together with their files on disk."""
    for img in images:
        _delete_file_storage(img.image)
    images.delete()


@manager_required
def product_action(request, pk):
    if request.method != 'POST':
        return HttpResponseBadRequest('POST required')
    product = get_object_or_404(Product, pk=pk)
    action = request.POST.get('action', '')
    handler = PRODUCT_ACTIONS.get(action)
    if not handler:
        messages.error(request, 'Unknown action.')
        return redirect('manage_products')
    handler(product)
    messages.success(request, f'"{product.name}" {PRODUCT_ACTION_VERBS.get(action, action)}.')
    return redirect(services.safe_next(request, 'manage_products'))


@manager_required
def product_bulk_action(request):
    if request.method != 'POST':
        return HttpResponseBadRequest('POST required')
    action = request.POST.get('bulk_action', '')
    ids = request.POST.getlist('selected')
    next_url = services.safe_next(request, 'manage_products')
    if action not in PRODUCT_ACTIONS and action != 'delete':
        messages.error(request, 'Select a bulk action.')
        return redirect(next_url)
    if not ids:
        messages.error(request, 'Select at least one product.')
        return redirect(next_url)
    products = Product.objects.filter(pk__in=ids)
    if action == 'delete':
        deleted_count = 0
        for product in list(products):
            delete_product_media(product)
            product.delete()
            deleted_count += 1
        messages.success(request, f'{deleted_count} product(s) deleted.')
    else:
        handler = PRODUCT_ACTIONS[action]
        count = 0
        for product in products:
            handler(product)
            count += 1
        messages.success(request, f'{count} product(s) {PRODUCT_ACTION_VERBS[action]}.')
    return redirect(next_url)


@manager_required
def product_delete(request, pk):
    product = get_object_or_404(Product, pk=pk)
    has_orders = product.order_items.exists()
    if request.method == 'POST':
        name = product.name
        delete_product_media(product)
        product.delete()
        messages.success(request, f'Product "{name}" deleted.')
        return redirect('manage_products')
    msg = f'Delete "{product.name}"?'
    if has_orders:
        msg = (f'Delete "{product.name}"? This product was purchased in '
               f'{product.order_items.count()} past order(s). Order records '
               'and receipts will safely preserve product names and prices, '
               'but the product will be permanently removed from the catalog.')
    return render(request, 'manage/confirm.html', {'title': 'Delete product', 'object': product,
                                                   'message': msg})


# --------------------------------------------------------------------------- #
# Categories
# --------------------------------------------------------------------------- #

@staff_required
def manage_categories(request):
    categories = Category.objects.annotate(
        product_count=Count('products'),
        active_count=Count('products', filter=Q(products__is_archived=False)),
        archived_count=Count('products', filter=Q(products__is_archived=True)),
    )
    return render(request, 'manage/categories.html', {'categories': categories})


@manager_required
def category_add(request):
    return _category_form(request)


@manager_required
def category_edit(request, pk):
    return _category_form(request, pk)


def _category_form(request, pk=None):
    from django import forms

    class CategoryForm(forms.ModelForm):
        class Meta:
            model = Category
            fields = ('name', 'description', 'image', 'active')

    instance = get_object_or_404(Category, pk=pk) if pk else None
    form = CategoryForm(instance=instance)
    if request.method == 'POST':
        form = CategoryForm(request.POST, request.FILES, instance=instance)
        if form.is_valid():
            category = form.save()
            messages.success(request, f'Category "{category.name}" saved.')
            return redirect('manage_categories')
    return render(request, 'manage/category_form.html', {'form': form, 'category': instance})


@manager_required
def category_delete(request, pk):
    category = get_object_or_404(Category, pk=pk)
    total_products = category.products.count()
    active_products = category.products.filter(is_archived=False).count()
    archived_products = category.products.filter(is_archived=True).count()
    other_categories = Category.objects.exclude(pk=category.pk)

    if request.method == 'POST':
        move_to_id = request.POST.get('move_to')
        delete_products = request.POST.get('delete_products') == '1'

        if move_to_id and other_categories.filter(pk=move_to_id).exists():
            dest = other_categories.get(pk=move_to_id)
            category.products.all().update(category=dest)
            category.delete()
            messages.success(request, f'Category "{category.name}" deleted and products moved to "{dest.name}".')
            return redirect('manage_categories')

        if delete_products or total_products == 0:
            for p in list(category.products.all()):
                delete_product_media(p)
                p.delete()
            category.delete()
            messages.success(request, f'Category "{category.name}" deleted.')
            return redirect('manage_categories')

        if not other_categories.exists():
            messages.error(
                request,
                f'Cannot delete "{category.name}": it has {total_products} product(s) ({archived_products} archived), '
                'and there are no other categories to move them to. '
                'Please check "Also permanently delete" to confirm deletion.'
            )
        else:
            messages.error(
                request,
                f'Cannot delete "{category.name}": it still has {total_products} product(s). '
                'Please select a destination category or check "Also permanently delete".'
            )
        return redirect('category_delete', pk=category.pk)

    return render(request, 'manage/category_confirm_delete.html', {
        'title': 'Delete category',
        'category': category,
        'total_products': total_products,
        'active_products': active_products,
        'archived_products': archived_products,
        'other_categories': other_categories,
    })


# --------------------------------------------------------------------------- #
# Inventory
# --------------------------------------------------------------------------- #

INVENTORY_SORTS = {
    'stock': 'stock',
    '-stock': '-stock',
    'name': 'name',
    '-name': '-name',
    'updated': '-updated_at',
    'threshold': 'low_stock_threshold',
    '-threshold': '-low_stock_threshold',
}


@staff_required
def inventory(request):
    qs = Product.objects.select_related('category')
    q = request.GET.get('q', '').strip()
    status = request.GET.get('status', '')
    sort = request.GET.get('sort', '')

    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(sku__icontains=q) | Q(brand__icontains=q))
    if status == 'low':
        qs = qs.filter(stock__gt=0, stock__lte=F('low_stock_threshold'))
    elif status == 'out':
        qs = qs.filter(stock__lte=0)
    elif status == 'healthy':
        qs = qs.filter(stock__gt=F('low_stock_threshold'))

    qs = qs.order_by(INVENTORY_SORTS.get(sort, 'stock'), 'name')
    paginator = Paginator(qs, 25)
    page = paginator.get_page(request.GET.get('page'))

    base = Product.objects.all()
    low = Q(stock__gt=0, stock__lte=F('low_stock_threshold'))
    out = Q(stock__lte=0)
    summary = {
        'total': base.count(),
        'healthy': base.filter(stock__gt=F('low_stock_threshold')).count(),
        'low': base.filter(low).count(),
        'out': base.filter(out).count(),
        'restock': base.filter(low | out).count(),
    }
    open_alerts = InventoryAlert.objects.filter(is_resolved=False).select_related('product')
    recent_changes = InventoryChange.objects.select_related('product', 'user')[:10]
    return render(request, 'manage/inventory.html', {
        'page': page, 'q': q, 'status': status, 'sort': sort, 'summary': summary,
        'open_alerts': open_alerts, 'recent_changes': recent_changes,
    })


@manager_required
def inventory_update(request):
    if request.method != 'POST':
        return HttpResponseBadRequest('POST required')
    pk = request.POST.get('product_id')
    product = get_object_or_404(Product, pk=pk)
    try:
        stock = int(request.POST.get('stock', product.stock))
        threshold = int(request.POST.get('low_stock_threshold', product.low_stock_threshold))
        desired = int(request.POST.get('desired_stock_level', product.desired_stock_level))
        if stock < 0 or threshold < 0 or desired < 0:
            raise ValueError
    except ValueError:
        messages.error(request, 'Stock values must be whole numbers of 0 or more.')
        return redirect('inventory')

    old_stock = product.stock
    old_threshold = product.low_stock_threshold
    old_desired = product.desired_stock_level
    changed = False
    if stock != old_stock:
        product.stock = stock
        services.record_inventory_change(product, 'restock' if stock > old_stock else 'adjust',
                                         old_qty=old_stock, new_qty=stock, user=request.user)
        changed = True
    if threshold != old_threshold:
        product.low_stock_threshold = threshold
        services.record_inventory_change(product, 'threshold', old_qty=old_threshold, new_qty=threshold,
                                         user=request.user)
        changed = True
    if desired != old_desired:
        product.desired_stock_level = desired
        services.record_inventory_change(product, 'desired', old_qty=old_desired, new_qty=desired,
                                         user=request.user)
        changed = True
    if changed:
        product.save(update_fields=['stock', 'low_stock_threshold', 'desired_stock_level', 'updated_at'])
    services.evaluate_product_stock(product, user=request.user)
    messages.success(request, f'Inventory updated for {product.name}.')
    return redirect(services.safe_next(request, 'inventory'))


@staff_required
def inventory_history(request):
    qs = InventoryChange.objects.select_related('product', 'user')
    q = request.GET.get('q', '').strip()
    action = request.GET.get('action', '')
    if q:
        qs = qs.filter(Q(product__name__icontains=q) | Q(product__sku__icontains=q) | Q(note__icontains=q))
    if action:
        qs = qs.filter(action=action)
    paginator = Paginator(qs, 25)
    page = paginator.get_page(request.GET.get('page'))
    return render(request, 'manage/inventory_history.html', {
        'page': page, 'q': q, 'action': action, 'action_choices': InventoryChange.ACTION_CHOICES,
    })


@staff_required
def inventory_alert_resolve(request, pk):
    if request.method != 'POST':
        return HttpResponseBadRequest('POST required')
    alert = get_object_or_404(InventoryAlert, pk=pk)
    alert.is_resolved = True
    alert.resolved_at = timezone.now()
    alert.save(update_fields=['is_resolved', 'resolved_at', 'updated_at'])
    messages.success(request, f'Alert resolved for {alert.product.name}.')
    return redirect(services.safe_next(request, 'inventory'))


# --------------------------------------------------------------------------- #
# Orders
# --------------------------------------------------------------------------- #

@staff_required
def manage_orders(request):
    qs = Order.objects.select_related('user', 'served_by')
    q = request.GET.get('q', '').strip()
    status = request.GET.get('status', '')
    payment = request.GET.get('payment', '')
    channel = request.GET.get('channel', '')
    method = request.GET.get('method', '')
    seller = request.GET.get('seller', '')
    date_from = request.GET.get('from', '')
    date_to = request.GET.get('to', '')
    preset = request.GET.get('range', '')

    today = timezone.now().date()
    presets = {
        'today': (today, today),
        'yesterday': (today - timedelta(days=1), today - timedelta(days=1)),
        'week': (today - timedelta(days=today.weekday()), today),
        'month': (today.replace(day=1), today),
    }
    if preset in presets and not date_from:
        date_from, date_to = presets[preset]
        date_from, date_to = date_from.isoformat(), date_to.isoformat()

    if q:
        qs = qs.filter(Q(number__icontains=q) | Q(customer_name__icontains=q) | Q(phone__icontains=q) | Q(email__icontains=q))
    if status:
        qs = qs.filter(status=status)
    if payment:
        qs = qs.filter(payment_status=payment)
    if channel:
        qs = qs.filter(sales_channel=channel)
    if method == 'cash':
        # "Cash" at the till: POS orders recorded as manual/cod payments.
        qs = qs.filter(payment_method='cod', sales_channel='pos')
    elif method:
        qs = qs.filter(payment_method=method)
    if seller:
        qs = qs.filter(served_by_id=seller)
    try:
        from datetime import date as _date
        if date_from:
            qs = qs.filter(created_at__date__gte=_date.fromisoformat(date_from))
        if date_to:
            qs = qs.filter(created_at__date__lte=_date.fromisoformat(date_to))
    except ValueError:
        messages.error(request, 'Invalid date filter ignored.')

    paginator = Paginator(qs, 25)
    page = paginator.get_page(request.GET.get('page'))
    return render(request, 'manage/orders.html', {
        'page': page, 'q': q, 'status': status, 'payment': payment,
        'channel': channel, 'method': method, 'seller': seller,
        'date_from': date_from, 'date_to': date_to, 'preset': preset,
        'order_statuses': Order.STATUS_CHOICES, 'payment_statuses': Order.PAYMENT_STATUS_CHOICES,
        'method_choices': [('cash', 'Cash (till)'), ('mpesa', 'M-Pesa'), ('card', 'Card'),
                           ('cod', 'Cash on delivery / manual')],
        'sellers': User.objects.filter(is_staff=True).order_by('first_name', 'username'),
    })


@staff_required
def manage_order_detail(request, number):
    order = get_object_or_404(
        Order.objects.prefetch_related('items', 'status_history', 'payments',
                                       'mpesa_transactions', 'items__returns', 'returns'),
        number=number)
    return render(request, 'manage/order_detail.html', {
        'order': order,
        'status_choices': Order.STATUS_CHOICES,
        'can_manage_returns': has_role(request.user, 'Manager', 'Admin'),
    })


@staff_required
def order_status_update(request, number):
    order = get_object_or_404(Order, number=number)
    if request.method != 'POST':
        return HttpResponseBadRequest('POST required')
    new_status = request.POST.get('status', '')
    note = request.POST.get('note', '').strip()
    valid = dict(Order.STATUS_CHOICES)
    if new_status not in valid:
        messages.error(request, 'Invalid status.')
        return redirect('manage_order_detail', number=number)

    old_status = order.status
    cancelled = new_status in ('cancelled', 'refunded')
    if cancelled and old_status not in ('cancelled', 'refunded') and not order.stock_released:
        services.release_stock(order)
    if new_status != old_status:
        order.record_status(new_status, note=note, actor=request.user)
        if cancelled:
            order.payment_status = 'refunded' if new_status == 'refunded' else order.payment_status
            order.save(update_fields=['payment_status', 'updated_at'])
        messages.success(request, f'Order {order.number} marked as {order.get_status_display()}.')
        logger.info('Order %s status changed to %s by %s', order.number, new_status, request.user.username)
        notify.order_status_changed(order)
        Notification.create(f'Order {order.number} is now {order.get_status_display()}')
    else:
        messages.info(request, 'Order status unchanged.')
    return redirect('manage_order_detail', number=order.number)


@manager_required
def order_return_item(request, number):
    """Process a partial product return against an existing sale.

    The original transaction is kept intact: a return adds an OrderReturn
    record, optionally restores stock through the audited inventory pipeline,
    and appends a timeline note.
    """
    order = get_object_or_404(Order, number=number)
    if request.method != 'POST':
        return HttpResponseBadRequest('POST required')
    item = get_object_or_404(OrderItem.objects.select_related('order'), pk=request.POST.get('item_id'),
                             order=order)
    try:
        quantity = int(request.POST.get('quantity', 1))
    except (TypeError, ValueError):
        quantity = 0
    reason = request.POST.get('reason', '').strip()
    restock = request.POST.get('restock') == 'on'
    try:
        services.process_return(order, item, quantity, reason=reason,
                                restock=restock, user=request.user)
        messages.success(request, f'Return recorded: {quantity} × {item.product_name}.')
        logger.info('Return on %s: %s x %s by %s', number, item.product_name, quantity,
                    request.user.username)
        Notification.create(f'Return processed · {order.number}',
                            message=f'{quantity} × {item.product_name} — {reason}',
                            category='order')
    except ValueError as e:
        messages.error(request, str(e))
    return redirect('manage_order_detail', number=order.number)


# --------------------------------------------------------------------------- #
# Customers
# --------------------------------------------------------------------------- #

@admin_required
def manage_customers(request):
    users = User.objects.annotate(order_count=Count('orders')).order_by('-date_joined')
    guest_phones = (Order.objects.filter(user__isnull=True)
                    .exclude(phone='').values('phone', 'customer_name', 'email')
                    .annotate(order_count=Count('id'), total=Sum('total')).order_by('-order_count'))
    return render(request, 'manage/customers.html', {'users': users, 'guest_phones': guest_phones})


# --------------------------------------------------------------------------- #
# Super Admin: Account Approval & User Management
# --------------------------------------------------------------------------- #

@super_admin_required
def manage_accounts(request):
    """Super Admin Account Control Center: review registrations, manage roles,
    and monitor user approval status across the entire system."""
    status_tab = request.GET.get('status', 'all').strip().lower()
    role_filter = request.GET.get('role', '').strip().lower()
    search_q = request.GET.get('q', '').strip()

    total_accounts = User.objects.count()
    pending_count = UserProfile.objects.filter(status='pending').count()
    approved_count = UserProfile.objects.filter(status='approved').count()
    rejected_count = UserProfile.objects.filter(status='rejected').count()
    suspended_count = UserProfile.objects.filter(status='suspended').count()

    qs = User.objects.select_related('profile').annotate(
        order_count=Count('orders')
    ).order_by('-date_joined')

    if status_tab in ('pending', 'approved', 'rejected', 'suspended'):
        qs = qs.filter(profile__status=status_tab)

    if role_filter in ('super_admin', 'admin', 'cashier', 'customer'):
        qs = qs.filter(profile__role=role_filter)

    if search_q:
        qs = qs.filter(
            Q(username__icontains=search_q) |
            Q(email__icontains=search_q) |
            Q(first_name__icontains=search_q) |
            Q(last_name__icontains=search_q) |
            Q(profile__phone__icontains=search_q)
        )

    paginator = Paginator(qs, 25)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'page': page_obj,
        'users': page_obj.object_list,
        'status_tab': status_tab,
        'role_filter': role_filter,
        'search_q': search_q,
        'total_accounts': total_accounts,
        'pending_count': pending_count,
        'approved_count': approved_count,
        'rejected_count': rejected_count,
        'suspended_count': suspended_count,
        'roles': UserProfile.ROLE_CHOICES,
    }
    return render(request, 'manage/accounts.html', context)


@require_POST
@super_admin_required
def account_action(request, pk):
    """Approve, reject, suspend, or reactivate a user account."""
    target_user = get_object_or_404(User.objects.select_related('profile'), pk=pk)
    action = request.POST.get('action', '').strip().lower()
    reason = request.POST.get('reason', '').strip()[:300]
    profile = target_user.profile
    old_status = profile.status
    ip = request.META.get('REMOTE_ADDR')

    if action == 'approve':
        if profile.status == 'approved':
            messages.info(request, f'Account {target_user.username} is already approved.')
            return redirect('manage_accounts')
        with transaction.atomic():
            profile.status = UserProfile.STATUS_APPROVED
            profile.approved_by = request.user
            profile.approved_at = timezone.now()
            profile.rejection_reason = ''
            profile.suspension_reason = ''
            profile.save()
            profile.sync_user_permissions()
            AccountAuditLog.objects.create(
                actor=request.user,
                target_user=target_user,
                target_username=target_user.username,
                action='approve',
                old_value=old_status,
                new_value='approved',
                note='Account approved by Super Admin',
                ip_address=ip
            )
        notify.account_approved(target_user)
        messages.success(request, f'Account {target_user.username} has been approved. The user can now log in.')

    elif action == 'reject':
        if target_user.id == request.user.id or target_user.id == 1 or target_user.is_superuser:
            messages.error(request, 'A Super Admin account cannot be rejected.')
            return redirect('manage_accounts')
        with transaction.atomic():
            profile.status = UserProfile.STATUS_REJECTED
            profile.rejection_reason = reason or 'Registration rejected by administrator.'
            profile.save()
            profile.sync_user_permissions()
            AccountAuditLog.objects.create(
                actor=request.user,
                target_user=target_user,
                target_username=target_user.username,
                action='reject',
                old_value=old_status,
                new_value='rejected',
                note=profile.rejection_reason,
                ip_address=ip
            )
        messages.warning(request, f'Account {target_user.username} has been rejected.')

    elif action == 'suspend':
        if target_user.id == request.user.id or target_user.id == 1 or target_user.is_superuser:
            messages.error(request, 'A Super Admin account cannot be suspended.')
            return redirect('manage_accounts')
        with transaction.atomic():
            profile.status = UserProfile.STATUS_SUSPENDED
            profile.suspension_reason = reason or 'Account suspended by administrator.'
            profile.save()
            profile.sync_user_permissions()
            AccountAuditLog.objects.create(
                actor=request.user,
                target_user=target_user,
                target_username=target_user.username,
                action='suspend',
                old_value=old_status,
                new_value='suspended',
                note=profile.suspension_reason,
                ip_address=ip
            )
        messages.warning(request, f'Account {target_user.username} has been suspended.')

    elif action == 'reactivate':
        with transaction.atomic():
            profile.status = UserProfile.STATUS_APPROVED
            profile.suspension_reason = ''
            profile.save()
            profile.sync_user_permissions()
            AccountAuditLog.objects.create(
                actor=request.user,
                target_user=target_user,
                target_username=target_user.username,
                action='reactivate',
                old_value=old_status,
                new_value='approved',
                note='Account reactivated by Super Admin',
                ip_address=ip
            )
        messages.success(request, f'Account {target_user.username} has been reactivated.')

    else:
        messages.error(request, 'Unknown account action.')

    return redirect('manage_accounts')


@require_POST
@super_admin_required
def account_role_update(request, pk):
    """Change user role (super_admin, admin, cashier, customer) with safety checks."""
    target_user = get_object_or_404(User.objects.select_related('profile'), pk=pk)
    new_role = request.POST.get('role', '').strip().lower()
    valid_roles = dict(UserProfile.ROLE_CHOICES)

    if new_role not in valid_roles:
        messages.error(request, 'Invalid role selection.')
        return redirect('manage_accounts')

    if (target_user.id == 1 or target_user.username == 'mash') and new_role != UserProfile.ROLE_SUPER_ADMIN:
        messages.error(request, 'The initial primary Super Admin account cannot be demoted.')
        return redirect('manage_accounts')

    if target_user.id == request.user.id and new_role != UserProfile.ROLE_SUPER_ADMIN:
        messages.error(request, 'You cannot remove your own Super Admin privileges.')
        return redirect('manage_accounts')

    profile = target_user.profile
    old_role = profile.role

    if old_role != new_role:
        with transaction.atomic():
            profile.role = new_role
            profile.save()
            profile.sync_user_permissions()
            AccountAuditLog.objects.create(
                actor=request.user,
                target_user=target_user,
                target_username=target_user.username,
                action='role_change',
                old_value=old_role,
                new_value=new_role,
                note=f'Role changed from {valid_roles.get(old_role, old_role)} to {valid_roles.get(new_role, new_role)}',
                ip_address=request.META.get('REMOTE_ADDR')
            )
        messages.success(request, f'Role for {target_user.username} updated to {valid_roles[new_role]}.')

    return redirect('manage_accounts')


@require_POST
@super_admin_required
def account_delete(request, pk):
    """Safely delete or soft-suspend a user account."""
    target_user = get_object_or_404(User, pk=pk)
    username = target_user.username

    if target_user.id == 1 or target_user.username == 'mash' or (target_user.is_superuser and target_user.id == request.user.id):
        messages.error(request, 'You cannot delete the primary Super Admin account.')
        return redirect('manage_accounts')

    if target_user.orders.exists():
        with transaction.atomic():
            profile = target_user.profile
            profile.status = UserProfile.STATUS_SUSPENDED
            profile.suspension_reason = 'Deactivated (retained due to associated order history).'
            profile.save()
            profile.sync_user_permissions()
            AccountAuditLog.objects.create(
                actor=request.user,
                target_user=target_user,
                target_username=username,
                action='suspend',
                old_value='approved',
                new_value='suspended',
                note='Account deactivated instead of deleted to protect order history integrity.',
                ip_address=request.META.get('REMOTE_ADDR')
            )
        messages.info(request, f'Account {username} has order history so it was suspended rather than deleted.')
        return redirect('manage_accounts')

    with transaction.atomic():
        AccountAuditLog.objects.create(
            actor=request.user,
            target_username=username,
            action='delete',
            note='Account permanently deleted by Super Admin',
            ip_address=request.META.get('REMOTE_ADDR')
        )
        target_user.delete()

    messages.success(request, f'Account {username} deleted successfully.')
    return redirect('manage_accounts')


@super_admin_required
def account_audit_logs(request):
    """View chronological audit records for administrator and security actions."""
    logs = AccountAuditLog.objects.select_related('actor', 'target_user').order_by('-created_at')
    action_filter = request.GET.get('action', '').strip()
    if action_filter:
        logs = logs.filter(action=action_filter)

    paginator = Paginator(logs, 40)
    page_obj = paginator.get_page(request.GET.get('page'))
    return render(request, 'manage/account_audit_logs.html', {
        'page': page_obj,
        'logs': page_obj.object_list,
        'action_filter': action_filter,
        'action_choices': AccountAuditLog.ACTION_CHOICES,
    })


# --------------------------------------------------------------------------- #
# Reviews
# --------------------------------------------------------------------------- #

@staff_required
def manage_reviews(request):
    qs = Review.objects.select_related('product', 'user')
    status = request.GET.get('status', '')
    if status == 'pending':
        qs = qs.filter(active=False)
    elif status == 'approved':
        qs = qs.filter(active=True)
    paginator = Paginator(qs, 25)
    page = paginator.get_page(request.GET.get('page'))
    return render(request, 'manage/reviews.html', {'page': page, 'status': status})


@staff_required
def review_action(request, pk):
    review = get_object_or_404(Review, pk=pk)
    action = request.POST.get('action', '')
    if request.method == 'POST':
        if action == 'approve':
            review.active = True
            review.save()
            services.recompute_product_rating(review.product)
            messages.success(request, 'Review approved and published.')
        elif action == 'reject':
            review.active = False
            review.save()
            services.recompute_product_rating(review.product)
            messages.success(request, 'Review rejected.')
        elif action == 'delete':
            product = review.product
            review.delete()
            services.recompute_product_rating(product)
            messages.success(request, 'Review deleted.')
    return redirect('manage_reviews')


# --------------------------------------------------------------------------- #
# Coupons
# --------------------------------------------------------------------------- #

@staff_required
def manage_coupons(request):
    coupons = Coupon.objects.annotate(usage_count=Count('usages'))
    return render(request, 'manage/coupons.html', {'coupons': coupons})


@manager_required
def coupon_add(request):
    return _coupon_form(request)


@manager_required
def coupon_edit(request, pk):
    return _coupon_form(request, pk)


def _coupon_form(request, pk=None):
    instance = get_object_or_404(Coupon, pk=pk) if pk else None
    form = CouponForm(instance=instance)
    if request.method == 'POST':
        form = CouponForm(request.POST, instance=instance)
        if form.is_valid():
            form.save()
            messages.success(request, f'Coupon "{form.instance.code}" saved.')
            return redirect('manage_coupons')
    return render(request, 'manage/coupon_form.html', {'form': form, 'coupon': instance})


@manager_required
def coupon_delete(request, pk):
    coupon = get_object_or_404(Coupon, pk=pk)
    if request.method == 'POST':
        coupon.delete()
        messages.success(request, 'Coupon deleted.')
        return redirect('manage_coupons')
    return render(request, 'manage/confirm.html', {'title': 'Delete coupon', 'object': coupon,
                                                   'message': f'Delete coupon "{coupon.code}"?'})


# --------------------------------------------------------------------------- #
# Payments
# --------------------------------------------------------------------------- #

PAYMENT_SORTS = {
    'date': '-created_at',
    '-date': 'created_at',
    'amount': '-amount',
    '-amount': 'amount',
    'order': '-order__number',
    'customer': 'order__customer_name',
}

MANUAL_REVIEWABLE_STATUSES = ('pending', 'processing', 'timeout', 'requires_review')


@staff_required
def manage_payments(request):
    qs = Payment.objects.select_related('order', 'verified_by')
    q = request.GET.get('q', '').strip()
    status = request.GET.get('status', '')
    method = request.GET.get('method', '')
    sort = request.GET.get('sort', '')

    if q:
        qs = qs.filter(Q(order__number__icontains=q) | Q(order__customer_name__icontains=q)
                       | Q(order__phone__icontains=q) | Q(reference__icontains=q)
                       | Q(transaction_id__icontains=q))
    if status:
        qs = qs.filter(status=status)
    if method:
        qs = qs.filter(method=method)

    qs = qs.order_by(PAYMENT_SORTS.get(sort, '-created_at'))
    paginator = Paginator(qs, 25)
    page = paginator.get_page(request.GET.get('page'))

    base = Payment.objects.all()
    summary = {
        'total': base.count(),
        'pending': base.filter(status__in=('pending', 'processing')).count(),
        'paid': base.filter(status='paid').count(),
        'review': base.filter(status='requires_review').count(),
        'failed': base.filter(status__in=('failed', 'cancelled')).count(),
        'refunded': base.filter(status='refunded').count(),
    }
    return render(request, 'manage/payments.html', {
        'page': page, 'q': q, 'status': status, 'method': method, 'sort': sort,
        'summary': summary,
        'status_choices': Payment.STATUS_CHOICES,
        'method_choices': Payment.METHOD_CHOICES,
        'reviewable_statuses': MANUAL_REVIEWABLE_STATUSES,
    })


@staff_required
def manage_payment_detail(request, pk):
    payment = get_object_or_404(Payment.objects.select_related('order', 'verified_by'), pk=pk)
    transactions = payment.order.mpesa_transactions.order_by('-created_at') if payment.order else []
    return render(request, 'manage/payment_detail.html', {
        'payment': payment,
        'transactions': transactions,
        'reviewable': payment.status in MANUAL_REVIEWABLE_STATUSES,
    })


@manager_required
def payment_action(request, pk):
    if request.method != 'POST':
        return HttpResponseBadRequest('POST required')
    payment = get_object_or_404(Payment.objects.select_related('order'), pk=pk)
    action = request.POST.get('action', '')
    note = request.POST.get('note', '').strip()

    if action == 'query_timeout':
        return _query_payment_timeout(request, payment)

    if payment.status not in MANUAL_REVIEWABLE_STATUSES:
        messages.error(request, f'This payment is already {payment.get_status_display().lower()} and cannot be reviewed.')
        return redirect('manage_payment_detail', pk=pk)

    if action == 'approve':
        services.mark_order_paid(
            payment.order, method=payment.method,
            reference=request.POST.get('reference', '').strip() or payment.reference,
            verification='manual', transaction_id=payment.transaction_id,
            verified_by=request.user, note=note or 'Approved manually')
        messages.success(request, f'Payment approved for {payment.order.number}. '
                                  f'Marked as manually reviewed — not gateway-verified.')
        logger.info('Payment %s approved manually for order %s by %s',
                    pk, payment.order.number, request.user.username)
        notify.payment_received(payment.order, payment.reference or '', verified_by=request.user)
    elif action == 'reject':
        status = 'cancelled' if request.POST.get('mark_cancelled') else 'failed'
        services.mark_order_payment_failed(
            payment.order, method=payment.method, status=status,
            verified_by=request.user, note=note or f'Rejected manually by {request.user.username}')
        messages.success(request, f'Payment rejected for {payment.order.number} (marked {status}).')
        logger.info('Payment %s rejected for order %s by %s', pk, payment.order.number, request.user.username)
        notify.payment_failed(payment.order, note or 'Payment was rejected',
                              cancelled=(status == 'cancelled'), verified_by=request.user)
    else:
        messages.error(request, 'Unknown payment action.')
    next_url = services.safe_next(request, '')
    if next_url:
        return redirect(next_url)
    return redirect('manage_payment_detail', pk=pk)


def _query_payment_timeout(request, payment):
    """Query Daraja for the status of a stuck M-Pesa payment."""
    from decimal import InvalidOperation
    from .models import MpesaTransaction
    s = SiteSettings.get()
    tx = (payment.order.mpesa_transactions
          .filter(checkout_request_id__isnull=False)
          .exclude(checkout_request_id='')
          .order_by('-created_at').first())
    if not tx:
        messages.error(request, 'No M-Pesa transaction found for this payment to query.')
        return redirect('manage_payment_detail', pk=pk)
    try:
        data = mpesa.query_stk_status(s, tx.checkout_request_id)
    except Exception as e:
        messages.error(request, f'Daraja query failed: {e}')
        return redirect('manage_payment_detail', pk=pk)

    result_code = str(data.get('ResultCode', ''))
    result_desc = data.get('ResultDesc', '')
    logger.info('Manual timeout query for payment %s: code=%s desc=%s',
                payment.pk, result_code, result_desc[:100])

    if result_code == '0':
        metadata = {}
        for item in (data.get('ResultParameters', {}) or {}).get('ResultParameter', []):
            if 'Key' in item:
                metadata[item['Key']] = item.get('Value')
        receipt = str(metadata.get('MpesaReceiptNumber', '') or tx.mpesa_receipt or '')
        tx.status = 'completed'
        tx.mpesa_receipt = receipt
        tx.result_code = '0'
        tx.result_description = 'Confirmed via manual query.'
        tx.save()
        if payment.status != 'paid':
            services.mark_order_paid(
                payment.order, method='mpesa', reference=receipt,
                verification='gateway', transaction_id=tx.checkout_request_id,
                result_code='0', result_description='Confirmed via manual query.')
            notify.payment_received(payment.order, receipt)
        messages.success(request, f'Payment confirmed! M-Pesa receipt: {receipt or "N/A"}')
    elif result_code in ('1032', '1037'):
        tx.status = 'timeout'
        tx.result_code = result_code
        tx.result_description = result_desc
        tx.save()
        if payment.status not in ('paid', 'timeout', 'failed', 'cancelled'):
            services.mark_order_payment_failed(
                payment.order, method='mpesa', status='timeout',
                result_code=result_code, result_description=result_desc,
                note='Customer did not complete the M-Pesa prompt (timeout).')
        messages.warning(request, f'Payment timed out. Customer did not complete the prompt.')
    else:
        tx.status = 'failed'
        tx.result_code = result_code
        tx.result_description = result_desc
        tx.save()
        if payment.status not in ('paid', 'failed', 'cancelled'):
            services.mark_order_payment_failed(
                payment.order, method='mpesa', status='failed',
                result_code=result_code, result_description=result_desc,
                note=f'Query returned failure: {result_desc[:200]}')
        messages.warning(request, f'Payment failed: {result_desc[:200]}')
    return redirect('manage_payment_detail', pk=payment.pk)


# --------------------------------------------------------------------------- #
# Settings (Super Admin Only)
# --------------------------------------------------------------------------- #

@super_admin_required
def manage_settings(request):
    s = SiteSettings.get()
    if request.method == 'POST':
        if request.POST.get('form_section') == 'showcase_products':
            product_ids = [int(pid) for pid in request.POST.getlist('showcase_pid') if pid.isdigit()]
            with transaction.atomic():
                for prod in Product.objects.filter(pk__in=product_ids):
                    pid = str(prod.pk)
                    try:
                        order_val = max(0, int(request.POST.get(f'display_order_{pid}', prod.display_order) or 0))
                    except (TypeError, ValueError):
                        order_val = prod.display_order
                    prod.display_order = order_val
                    prod.showcase_hero = request.POST.get(f'showcase_hero_{pid}') == 'on'
                    prod.showcase_coverflow = request.POST.get(f'showcase_coverflow_{pid}') == 'on'
                    prod.featured = request.POST.get(f'featured_{pid}') == 'on'
                    prod.is_new = request.POST.get(f'is_new_{pid}') == 'on'
                    prod.is_bestseller = request.POST.get(f'is_bestseller_{pid}') == 'on'
                    prod.save(update_fields=[
                        'display_order', 'showcase_hero', 'showcase_coverflow',
                        'featured', 'is_new', 'is_bestseller', 'updated_at'
                    ])
            messages.success(request, 'Storefront showcase assignments and display order saved.')
            return redirect(f"{reverse('manage_settings')}#showcase-products")

        s.store_name = request.POST.get('store_name', s.store_name)
        s.tagline = request.POST.get('tagline', s.tagline)
        s.description = request.POST.get('description', s.description)
        s.announcement = request.POST.get('announcement', s.announcement)
        s.hero_title = request.POST.get('hero_title', s.hero_title)
        s.hero_subtitle = request.POST.get('hero_subtitle', s.hero_subtitle)
        s.primary_color = request.POST.get('primary_color', s.primary_color)
        s.currency = request.POST.get('currency', s.currency)
        s.phone = request.POST.get('phone', s.phone)
        s.contact_email = request.POST.get('contact_email', s.contact_email)
        s.address = request.POST.get('address', s.address)
        s.footer_text = request.POST.get('footer_text', s.footer_text)
        s.social_facebook = request.POST.get('social_facebook', s.social_facebook)
        s.social_instagram = request.POST.get('social_instagram', s.social_instagram)
        s.social_twitter = request.POST.get('social_twitter', s.social_twitter)
        s.social_whatsapp = request.POST.get('social_whatsapp', s.social_whatsapp)
        for field in ('low_stock_default', 'desired_stock_level',
                      'restock_lookback_days', 'restock_lead_time_days', 'restock_min_sales_orders'):
            try:
                setattr(s, field, int(request.POST.get(field, getattr(s, field))))
            except (TypeError, ValueError):
                pass
        s.inventory_alert_email = request.POST.get('inventory_alert_email', s.inventory_alert_email).strip()
        s.staff_notifications_email = request.POST.get('staff_notifications_email', s.staff_notifications_email).strip()
        s.shipping_enabled = request.POST.get('shipping_enabled') == 'on'
        try:
            s.flat_rate = Decimal(request.POST.get('flat_rate', s.flat_rate))
            s.free_shipping_threshold = Decimal(request.POST.get('free_shipping_threshold', s.free_shipping_threshold))
            s.tax_rate = Decimal(request.POST.get('tax_rate', s.tax_rate))
        except Exception:
            pass
        s.tax_enabled = request.POST.get('tax_enabled') == 'on'

        # Storefront animations settings
        if 'animations_enabled_present' in request.POST:
            s.animations_enabled = request.POST.get('animations_enabled') == 'on'
        speed = request.POST.get('animation_speed', '').strip()
        if speed in dict(SiteSettings.ANIMATION_SPEED_CHOICES):
            s.animation_speed = speed
        hero_style = request.POST.get('hero_style', '').strip()
        if hero_style in dict(SiteSettings.HERO_STYLE_CHOICES):
            s.hero_style = hero_style
        featured_style = request.POST.get('featured_style', '').strip()
        if featured_style in dict(SiteSettings.SECTION_STYLE_CHOICES):
            s.featured_style = featured_style
        arrivals_style = request.POST.get('arrivals_style', '').strip()
        if arrivals_style in dict(SiteSettings.SECTION_STYLE_CHOICES):
            s.arrivals_style = arrivals_style
        catalogue_style = request.POST.get('catalogue_style', '').strip()
        if catalogue_style in dict(SiteSettings.CATALOGUE_STYLE_CHOICES):
            s.catalogue_style = catalogue_style

        for field in ('logo', 'favicon', 'banner'):
            upload = request.FILES.get(field)
            if upload:
                try:
                    services.validate_image_upload(upload)
                except ValidationError as e:
                    messages.error(request, f'{field.capitalize()}: {e.message}')
                    return redirect('manage_settings')
                setattr(s, field, upload)
        s.save()
        messages.success(request, 'Store settings saved.')
        return redirect('manage_settings')

    showcase_products = (
        Product.objects.filter(is_archived=False)
        .select_related('category')
        .order_by('display_order', '-created_at')[:50]
    )
    return render(request, 'manage/settings.html', {
        's': s,
        'showcase_products': showcase_products,
        'speed_choices': SiteSettings.ANIMATION_SPEED_CHOICES,
        'hero_style_choices': SiteSettings.HERO_STYLE_CHOICES,
        'section_style_choices': SiteSettings.SECTION_STYLE_CHOICES,
        'catalogue_style_choices': SiteSettings.CATALOGUE_STYLE_CHOICES,
    })


@super_admin_required
def manage_email_settings(request):
    s = SiteSettings.get()
    if request.method == 'POST':
        s.smtp_enabled = request.POST.get('smtp_enabled') == 'on'
        s.smtp_host = request.POST.get('smtp_host', s.smtp_host).strip() or s.smtp_host
        try:
            s.smtp_port = int(request.POST.get('smtp_port', s.smtp_port))
        except (TypeError, ValueError):
            pass
        s.smtp_username = request.POST.get('smtp_username', s.smtp_username).strip()
        s.smtp_from_email = request.POST.get('smtp_from_email', s.smtp_from_email).strip()
        s.smtp_sender_name = request.POST.get('smtp_sender_name', s.smtp_sender_name).strip()

        sec_mode = request.POST.get('smtp_security_mode')
        if sec_mode == 'ssl':
            use_ssl, use_tls = True, False
        elif sec_mode == 'tls':
            use_ssl, use_tls = False, True
        elif sec_mode == 'none':
            use_ssl, use_tls = False, False
        else:
            use_tls = request.POST.get('smtp_use_tls') == 'on'
            use_ssl = request.POST.get('smtp_use_ssl') == 'on'
            # TLS and SSL are mutually exclusive connection modes.
            if use_tls and use_ssl:
                use_ssl = False

        # Guard against port/protocol mismatch (e.g. port 587 + SSL)
        if s.smtp_port == 587 and use_ssl and not use_tls:
            use_ssl = False
            use_tls = True
        elif s.smtp_port == 465 and use_tls and not use_ssl:
            use_ssl = True
            use_tls = False

        s.smtp_use_tls = use_tls
        s.smtp_use_ssl = use_ssl

        new_password = request.POST.get('smtp_password', '').strip()
        if new_password and new_password != '********':
            s.smtp_password = new_password
        try:
            hours = int(request.POST.get('password_reset_timeout_hours', 0))
            if 1 <= hours <= 168:
                s.password_reset_timeout_seconds = hours * 3600
        except (TypeError, ValueError):
            pass
        s.save()
        messages.success(request, 'SMTP settings saved.')
        return redirect('manage_email_settings')
    return render(request, 'manage/email_settings.html', {
        's': s,
        'reset_timeout_hours': max(1, round(s.password_reset_timeout_seconds / 3600)),
    })


@super_admin_required
def test_email(request):
    s = SiteSettings.get()
    recipient = request.POST.get('email', '').strip()
    if not recipient:
        messages.error(request, 'Enter an email address to send the test to.')
        return redirect('manage_email_settings')
    try:
        from django.core.mail import send_mail
        sender = s.smtp_from_email or s.smtp_username or getattr(settings, 'DEFAULT_FROM_EMAIL', None) or 'no-reply@reevesboutique.local'
        if 'your-email@' in sender or 'example.com' in sender:
            sender = s.smtp_username or getattr(settings, 'EMAIL_HOST_USER', None) or 'no-reply@reevesboutique.local'
        if s.smtp_sender_name and sender and '<' not in sender:
            sender = f'{s.smtp_sender_name} <{sender}>'
        send_mail(
            f'Reeves Boutique SMTP test from {s.store_name}',
            'SMTP configuration is working. This email confirms your store can send mail.',
            sender,
            [recipient],
            fail_silently=False,
        )
        messages.success(request, f'Test email sent to {recipient}.')
        logger.info('SMTP test email sent to %s via %s', recipient, s.smtp_host)
    except Exception as e:
        logger.error('SMTP test failed for %s: %s', recipient, e)
        err = str(e)
        if 'WRONG_VERSION_NUMBER' in err:
            err += ' (Port 587 requires TLS/STARTTLS, while Port 465 requires SSL)'
        elif 'Username and Password not accepted' in err:
            err += ' (For Gmail, verify 2-Step Verification is active and use a 16-character Google App Password)'
        messages.error(request, f'SMTP test failed: {err}')
    return redirect('manage_email_settings')


@super_admin_required
def manage_payment_settings(request):
    s = SiteSettings.get()
    # Check if MPESA_CALLBACK_URL is defined in env; otherwise use database or request fallback
    env_callback = os.environ.get('MPESA_CALLBACK_URL') or os.environ.get('DARAJA_CALLBACK_URL')
    default_callback = env_callback or s.mpesa_callback_url or request.build_absolute_uri(reverse('mpesa_callback'))

    if request.method == 'POST':
        form = MpesaSettingsForm(request.POST, instance=s)
        if form.is_valid():
            cd = form.cleaned_data
            s.mpesa_enabled = cd.get('mpesa_enabled', False)
            if cd.get('mpesa_environment'):
                s.mpesa_environment = cd['mpesa_environment']
            if cd.get('mpesa_account_type'):
                s.mpesa_account_type = cd['mpesa_account_type']

            # Allow user to specify a custom public HTTPS callback (e.g. ngrok), or fall back to env/derived
            submitted_callback = (request.POST.get('mpesa_callback_url') or '').strip()
            s.mpesa_callback_url = submitted_callback or default_callback

            # Only touch fields that were actually submitted so partial posts
            # (and the secret-preservation behaviour) cannot wipe settings.
            if 'mpesa_business_name' in request.POST:
                s.mpesa_business_name = cd.get('mpesa_business_name', '').strip()
            if 'mpesa_shortcode' in request.POST:
                s.mpesa_shortcode = cd.get('mpesa_shortcode', '')
            if 'mpesa_account_reference' in request.POST:
                s.mpesa_account_reference = cd.get('mpesa_account_reference', '').strip()
            if 'mpesa_transaction_desc' in request.POST:
                s.mpesa_transaction_desc = cd.get('mpesa_transaction_desc', '').strip()
            strategy = cd.get('inventory_strategy')
            if strategy in dict(SiteSettings.INVENTORY_STRATEGY_CHOICES):
                s.inventory_strategy = strategy
            # Secrets are write-only: a blank or masked value keeps the store.
            for field in ('mpesa_consumer_key', 'mpesa_consumer_secret', 'mpesa_passkey'):
                new_value = (cd.get(field) or '').strip()
                if new_value and new_value != '********':
                    setattr(s, field, new_value)
            s.save()
            logger.info('M-Pesa settings updated by %s', request.user.get_username())
            messages.success(request, 'M-Pesa settings saved successfully.')
            return redirect('manage_payment_settings')
        messages.error(request, 'Please correct the highlighted errors and save again.')
    else:
        form = MpesaSettingsForm(initial={
            'mpesa_enabled': s.mpesa_enabled,
            'mpesa_environment': s.mpesa_environment,
            'mpesa_account_type': s.mpesa_account_type,
            'mpesa_business_name': s.mpesa_business_name,
            'mpesa_shortcode': s.mpesa_shortcode,
            'mpesa_callback_url': s.mpesa_callback_url or default_callback,
            'mpesa_account_reference': s.mpesa_account_reference,
            'mpesa_transaction_desc': s.mpesa_transaction_desc,
            'inventory_strategy': s.inventory_strategy,
        }, instance=s)

    callback_url = s.mpesa_callback_url or default_callback
    return render(request, 'manage/payment_settings.html', {
        's': s,
        'form': form,
        'callback_url': callback_url,
    })

    return render(request, 'manage/payment_settings.html', {
        's': s,
        'form': form,
        'callback_url': callback_url,
    })


@super_admin_required
def test_mpesa(request):
    s = SiteSettings.get()
    ok, message = mpesa.test_connection(s)
    if ok:
        messages.success(request, message)
    else:
        messages.error(request, message)
    logger.info('M-Pesa connection test: %s', 'OK' if ok else 'FAILED: ' + message)
    return redirect('manage_payment_settings')


# --------------------------------------------------------------------------- #
# Analytics
# --------------------------------------------------------------------------- #

@staff_required
def manage_analytics(request):
    now = timezone.now()
    paid = Q(status__in=Order.PAID_STATUSES)

    daily, weekly, monthly = [], [], []
    for i in range(7):
        day = (now - timedelta(days=i)).date()
        agg = Order.objects.filter(created_at__date=day).filter(paid).aggregate(rev=Sum('total'), n=Count('id'))
        daily.append({'label': day.strftime('%a %d'), 'revenue': agg['rev'] or ZERO, 'orders': agg['n'] or 0})
    daily.reverse()

    for i in range(8):
        start = (now - timedelta(weeks=i)).replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(weeks=1)
        agg = Order.objects.filter(created_at__gte=start, created_at__lt=end).filter(paid).aggregate(
            rev=Sum('total'), n=Count('id'))
        weekly.append({'label': start.strftime('%d %b'), 'revenue': agg['rev'] or ZERO, 'orders': agg['n'] or 0})
    weekly.reverse()

    for i in range(11, -1, -1):
        start = (now - timedelta(days=30 * i)).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        end = (start + timedelta(days=32)).replace(day=1)
        agg = Order.objects.filter(created_at__gte=start, created_at__lt=end).filter(paid).aggregate(
            rev=Sum('total'), n=Count('id'))
        monthly.append({'label': start.strftime('%b %y'), 'revenue': agg['rev'] or ZERO, 'orders': agg['n'] or 0})

    top_products = (OrderItem.objects.filter(order__status__in=Order.PAID_STATUSES)
                    .values('product_name').annotate(units=Sum('quantity'), revenue=Sum('subtotal'))
                    .order_by('-units')[:10])
    top_categories = (OrderItem.objects.filter(order__status__in=Order.PAID_STATUSES)
                      .values('product__category__name')
                      .annotate(units=Sum('quantity'), revenue=Sum('subtotal'))
                      .order_by('-revenue')[:10])
    orders_by_status = (Order.objects.values('status').annotate(n=Count('id')).order_by('status'))
    payment_breakdown = (Order.objects.values('payment_status').annotate(n=Count('id')).order_by('payment_status'))

    has_data = Order.objects.filter(paid).exists()
    return render(request, 'manage/analytics.html', {
        'daily': daily, 'weekly': weekly, 'monthly': monthly,
        'top_products': top_products, 'top_categories': top_categories,
        'orders_by_status': orders_by_status, 'payment_breakdown': payment_breakdown,
        'has_data': has_data,
    })


# --------------------------------------------------------------------------- #
# System health
# --------------------------------------------------------------------------- #

@staff_required
def system_health(request):
    import sys

    import django
    from django.core.management import call_command
    from django.db import connection

    checks = []
    db_ok = True
    try:
        with connection.cursor() as cur:
            cur.execute('SELECT 1')
    except Exception as e:
        db_ok = False
        checks.append({'name': 'Database connection', 'ok': False, 'detail': str(e)})
    else:
        checks.append({'name': 'Database connection', 'ok': True,
                       'detail': connection.vendor + ' (' + str(connection.settings_dict.get('NAME', '')) + ')'})

    from django.db.migrations.executor import MigrationExecutor
    executor = MigrationExecutor(connection)
    plan = executor.migration_plan(executor.loader.graph.leaf_nodes())
    checks.append({'name': 'Migrations', 'ok': not plan, 'detail': f'{len(plan)} pending migration(s)' if plan else 'Up to date'})

    from django.conf import settings
    checks.append({'name': 'Static files', 'ok': True,
                   'detail': str(settings.STATIC_ROOT) + (' (exists)' if settings.STATIC_ROOT.exists() else ' (missing)')})
    checks.append({'name': 'Media files', 'ok': settings.MEDIA_ROOT.exists(),
                   'detail': str(settings.MEDIA_ROOT) + (' (exists)' if settings.MEDIA_ROOT.exists() else ' (missing — will be created on first upload)')})

    s = SiteSettings.get()
    checks.append({'name': 'SMTP', 'ok': s.smtp_enabled, 'detail': 'Enabled' if s.smtp_enabled else 'Disabled',
                   'sub': s.smtp_host if s.smtp_host else 'No host configured'})
    checks.append({'name': 'M-Pesa', 'ok': s.mpesa_enabled, 'detail': 'Enabled' if s.mpesa_enabled else 'Disabled',
                   'sub': s.mpesa_environment.upper() + (' · configured' if s.mpesa_consumer_key else ' · credentials missing')})

    checks.append({'name': 'Debug mode', 'ok': not settings.DEBUG,
                   'detail': 'DEBUG=True' if settings.DEBUG else 'DEBUG=False (safe for production)'})
    checks.append({'name': 'Allowed hosts', 'ok': bool(settings.ALLOWED_HOSTS),
                   'detail': ', '.join(settings.ALLOWED_HOSTS)})
    checks.append({'name': 'Session cookie secure', 'ok': settings.SESSION_COOKIE_SECURE,
                   'detail': 'On (HTTPS)' if settings.SESSION_COOKIE_SECURE else 'Off (local HTTP)'})

    info = {
        'django': django.get_version(),
        'python': sys.version.split()[0],
        'timezone': settings.TIME_ZONE,
        'environment': 'production' if not settings.DEBUG else 'development',
        'products': Product.objects.count(),
        'orders': Order.objects.count(),
        'reviews': Review.objects.count(),
        'customers': User.objects.count(),
        'db_ok': db_ok,
    }
    return render(request, 'manage/system_health.html', {'checks': checks, 'info': info})


@staff_required
def notifications_clear(request):
    if request.method == 'POST':
        Notification.objects.filter(for_staff=True).update(read=True)
        messages.success(request, 'Notifications marked as read.')
    return redirect(services.safe_next(request, 'dashboard'))


@staff_required
def manage_notifications(request):
    qs = Notification.objects.filter(for_staff=True)
    state = request.GET.get('state', '')
    if state == 'unread':
        qs = qs.filter(read=False)
    paginator = Paginator(qs, 25)
    page = paginator.get_page(request.GET.get('page'))
    return render(request, 'manage/notifications.html', {'page': page, 'state': state})


# --------------------------------------------------------------------------- #
# Data Management & Deletion Controls (Super Admin strictly)
# --------------------------------------------------------------------------- #

@super_admin_required
def manage_data(request):
    from .data_management import DATA_TYPE_CONFIGS, get_data_counts, get_filtered_queryset
    from .models import DataDeletionAuditLog

    tab = request.GET.get('tab', 'notifications')
    if tab not in DATA_TYPE_CONFIGS:
        tab = 'notifications'

    counts = get_data_counts()
    config = DATA_TYPE_CONFIGS[tab]
    qs = get_filtered_queryset(tab, request.GET)

    paginator = Paginator(qs, 20)
    page = paginator.get_page(request.GET.get('page'))
    audit_logs = DataDeletionAuditLog.objects.select_related('actor')[:15]

    return render(request, 'manage/data_management.html', {
        'tab': tab,
        'config': config,
        'configs': DATA_TYPE_CONFIGS,
        'counts': counts,
        'page': page,
        'total_matching': qs.count() if qs is not None else 0,
        'audit_logs': audit_logs,
        'params': request.GET,
    })


@require_POST
@super_admin_required
def manage_data_delete(request, data_type):
    from .data_management import DATA_TYPE_CONFIGS, execute_deletion, get_client_ip

    if data_type not in DATA_TYPE_CONFIGS:
        messages.error(request, 'Invalid data category.')
        return redirect('manage_data')

    # 1. Require Password Verification
    password = request.POST.get('password', '').strip()
    if not request.user.check_password(password):
        messages.error(request, 'Security verification failed: Incorrect Super Admin password. Deletion cancelled.')
        return redirect(f"{reverse('manage_data')}?tab={data_type}")

    # 2. Require Typing the Confirmation Word "DELETE"
    confirm_text = request.POST.get('confirm_text', '').strip().upper()
    if confirm_text != 'DELETE':
        messages.error(request, 'Confirmation phrase "DELETE" was not typed correctly. Deletion aborted.')
        return redirect(f"{reverse('manage_data')}?tab={data_type}")

    selection_mode = request.POST.get('selection_mode', 'selected')  # 'selected' or 'all'
    selected_ids = [int(x) for x in request.POST.getlist('selected_ids') if x.isdigit()]

    ip = get_client_ip(request)
    success, count, msg = execute_deletion(
        data_type=data_type,
        selection_mode=selection_mode,
        selected_ids=selected_ids,
        params=request.POST,
        actor=request.user,
        ip_address=ip,
    )

    if success:
        messages.success(request, msg)
    else:
        messages.error(request, msg)

    return redirect(f"{reverse('manage_data')}?tab={data_type}")


# --------------------------------------------------------------------------- #
# Subscribers Management (Staff)
# --------------------------------------------------------------------------- #

@staff_required
def manage_subscribers(request):
    from .models import NewsletterSubscriber

    qs = NewsletterSubscriber.objects.select_related('user').order_by('-subscribed_at')
    q = request.GET.get('q', '').strip()
    status = request.GET.get('status', '')

    if status == 'active':
        qs = qs.filter(active=True)
    elif status == 'inactive':
        qs = qs.filter(active=False)

    if q:
        qs = qs.filter(Q(email__icontains=q) | Q(user__username__icontains=q))

    total_count = NewsletterSubscriber.objects.count()
    active_count = NewsletterSubscriber.objects.filter(active=True).count()
    inactive_count = NewsletterSubscriber.objects.filter(active=False).count()

    paginator = Paginator(qs, 25)
    page = paginator.get_page(request.GET.get('page'))

    return render(request, 'manage/subscribers.html', {
        'page': page,
        'q': q,
        'status': status,
        'total_count': total_count,
        'active_count': active_count,
        'inactive_count': inactive_count,
    })


@staff_required
def subscribers_export_csv(request):
    import csv
    from django.http import HttpResponse
    from .models import NewsletterSubscriber

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="subscribers_{timezone.now():%Y%m%d_%H%M}.csv"'

    writer = csv.writer(response)
    writer.writerow(['Email', 'Active', 'Confirmed', 'Subscribed At', 'User Account', 'Unsubscribe Token'])

    qs = NewsletterSubscriber.objects.select_related('user').order_by('-subscribed_at')
    status = request.GET.get('status', '')
    if status == 'active':
        qs = qs.filter(active=True)
    elif status == 'inactive':
        qs = qs.filter(active=False)

    for sub in qs:
        writer.writerow([
            sub.email,
            'Yes' if sub.active else 'No',
            'Yes' if sub.confirmed else 'No',
            sub.subscribed_at.strftime('%Y-%m-%d %H:%M:%S'),
            sub.user.username if sub.user else 'Guest',
            sub.unsubscribe_token,
        ])
    return response


@require_POST
@staff_required
def subscribers_broadcast(request):
    """Manual announcement/newsletter to all active subscribers."""
    subject = request.POST.get('subject', '').strip()
    message = request.POST.get('message', '').strip()

    if not subject or not message:
        messages.error(request, 'Subject and message are required to broadcast an announcement.')
        return redirect('manage_subscribers')

    from .services import send_subscriber_broadcast
    sent, failed = send_subscriber_broadcast(subject, message, user=request.user)
    messages.success(request, f'Announcement dispatched to {sent} active subscriber(s). Failed: {failed}.')
    return redirect('manage_subscribers')


@require_POST
@super_admin_required
def subscriber_delete(request, pk):
    from .models import NewsletterSubscriber

    sub = get_object_or_404(NewsletterSubscriber, pk=pk)
    email = sub.email
    sub.delete()
    messages.success(request, f'Subscriber "{email}" removed.')
    return redirect('manage_subscribers')
