import logging
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth import views as auth_views
from django.contrib.auth.forms import AuthenticationForm
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.core.validators import validate_email
from django.db import transaction
from django.db.models import Case, F, Q, When
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from . import emails, mpesa, notify, services
from .decorators import login_required_view
from .forms import AddressForm, ContactForm, ProfileForm, RegistrationForm, ReviewForm, SitePasswordResetForm
from .models import (Address, Category, MpesaTransaction, NewsletterSubscriber,
                     Order, Product, Review, SiteSettings, WishlistItem)
from .tokens import site_token_generator

logger = logging.getLogger('store')

ZERO = Decimal('0.00')


# --------------------------------------------------------------------------- #
# Password reset (Django's secure mechanism, site-configurable timeout)
# --------------------------------------------------------------------------- #

class StorePasswordResetView(auth_views.PasswordResetView):
    template_name = 'account/password_reset.html'
    email_template_name = 'account/password_reset_email.html'
    subject_template_name = 'account/password_reset_subject.txt'
    success_url = '/account/password-reset/done/'
    form_class = SitePasswordResetForm
    token_generator = site_token_generator

    @property
    def extra_email_context(self):
        return {'site_settings': SiteSettings.get()}


class StorePasswordResetConfirmView(auth_views.PasswordResetConfirmView):
    template_name = 'account/password_reset_confirm.html'
    success_url = '/account/reset/done/'
    token_generator = site_token_generator


# --------------------------------------------------------------------------- #
# Storefront
# --------------------------------------------------------------------------- #

def home(request):
    settings = SiteSettings.get()
    categories = Category.objects.filter(active=True)[:6]
    new_arrivals = (Product.objects.visible().select_related('category').filter(is_new=True)[:8]
                    or Product.objects.visible().select_related('category')[:8])
    best_sellers = Product.objects.visible().select_related('category').filter(is_bestseller=True)[:8]
    featured = Product.objects.visible().select_related('category').filter(featured=True)[:8]
    testimonials = Review.objects.filter(active=True).select_related('product', 'user')[:6]
    return render(request, 'store/home.html', {
        'categories': categories,
        'new_arrivals': new_arrivals,
        'best_sellers': best_sellers,
        'featured': featured,
        'testimonials': testimonials,
    })


def catalogue(request):
    qs = Product.objects.visible().select_related('category')
    q = request.GET.get('q', '').strip()
    category_slug = request.GET.get('category', '')
    sort = request.GET.get('sort', '')

    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(sku__icontains=q) | Q(description__icontains=q)
                       | Q(brand__icontains=q) | Q(category__name__icontains=q))
    if category_slug:
        qs = qs.filter(category__slug=category_slug)

    qs = qs.annotate(effective=Case(When(sale_price__isnull=False, then=F('sale_price')), default=F('price')))
    sort_map = {
        'price_asc': ('effective',),
        'price_desc': ('-effective',),
        'name': ('name',),
        'rating': ('-rating',),
        'bestseller': ('-is_bestseller', '-sales_count', '-created_at'),
        'newest': ('-created_at',),
    }
    ordering = sort_map.get(sort) or ('-created_at',)
    qs = qs.order_by(*ordering)

    paginator = Paginator(qs, 12)
    page = paginator.get_page(request.GET.get('page'))

    categories = Category.objects.filter(active=True)
    return render(request, 'store/catalogue.html', {
        'page': page,
        'categories': categories,
        'q': q,
        'active_category': category_slug,
        'sort': sort,
    })


def search_suggestions(request):
    """JSON autocomplete feed for the header search box. Database-backed so new
    products appear immediately (no cache)."""
    q = request.GET.get('q', '').strip()
    if len(q) < 2:
        return JsonResponse({'results': []})
    results = (Product.objects.visible().select_related('category')
               .filter(Q(name__icontains=q) | Q(sku__icontains=q) | Q(brand__icontains=q)
                       | Q(category__name__icontains=q))
               .order_by('-is_bestseller', '-created_at')[:6])
    return JsonResponse({'results': [
        {
            'id': p.pk,
            'name': p.name,
            'slug': p.slug,
            'category': p.category.name,
            'price': f'{p.effective_price:,.0f}',
            'currency': SiteSettings.get().currency,
            'image': p.image_src or '',
            'out_of_stock': p.out_of_stock,
        } for p in results
    ]})


def product_detail(request, slug):
    product = get_object_or_404(
        Product.objects.visible().select_related('category').prefetch_related('images'), slug=slug)
    reviews = product.reviews.filter(active=True).select_related('user')
    related = (Product.objects.visible().filter(category=product.category)
               .exclude(pk=product.pk).select_related('category')[:4])
    form = ReviewForm()
    if request.method == 'POST' and request.user.is_authenticated:
        form = ReviewForm(request.POST)
        if form.is_valid():
            already = product.reviews.filter(user=request.user).exists()
            if already:
                messages.error(request, 'You have already reviewed this product.')
            else:
                review = form.save(commit=False)
                review.product = product
                review.user = request.user
                review.verified_purchase = product.order_items.filter(
                    order__user=request.user, order__status__in=Order.PAID_STATUSES).exists()
                review.save()
                services.recompute_product_rating(product)
                notify.new_review(review)
                messages.success(request, 'Thank you for your review. It will appear once approved.')
                return redirect('product_detail', slug=product.slug)
    in_wishlist = request.user.is_authenticated and product.wishlisted_by.filter(user=request.user).exists()
    user_has_reviewed = request.user.is_authenticated and product.reviews.filter(user=request.user).exists()
    return render(request, 'store/product.html', {
        'product': product,
        'reviews': reviews,
        'related': related,
        'form': form,
        'in_wishlist': in_wishlist,
        'user_has_reviewed': user_has_reviewed,
    })


def cart(request):
    totals = services.totals_for(request)
    return render(request, 'store/cart.html', totals)


@require_POST
def cart_add(request, pk):
    product = get_object_or_404(Product.objects.visible(), pk=pk)
    qty = request.POST.get('quantity', 1)
    try:
        qty = int(qty)
    except (TypeError, ValueError):
        qty = 1
    if product.stock <= 0:
        messages.error(request, f'{product.name} is out of stock.')
    elif qty > product.stock:
        messages.error(request, f'Only {product.stock} units of {product.name} are available.')
    else:
        services.add_to_cart(request, product, qty)
        messages.success(request, f'{product.name} added to cart.')
    return redirect(services.safe_next(request, 'cart'))


@require_POST
def cart_update(request, pk):
    product = get_object_or_404(Product, pk=pk)
    qty = request.POST.get('quantity', 1)
    try:
        qty = int(qty)
    except (TypeError, ValueError):
        qty = 1
    if qty <= 0:
        services.remove_from_cart(request, pk)
    else:
        services.set_cart_qty(request, product, qty)
        messages.success(request, 'Cart updated.')
    return redirect('cart')


@require_POST
def cart_remove(request, pk):
    services.remove_from_cart(request, pk)
    messages.success(request, 'Item removed from cart.')
    return redirect('cart')


@require_POST
def cart_apply_coupon(request):
    code = request.POST.get('code', '').strip().upper()
    coupon, err = services.validate_coupon(request, code)
    if coupon:
        services.set_coupon(request, code)
        messages.success(request, f'Coupon {code} applied.')
    else:
        messages.error(request, err or 'Invalid coupon.')
    return redirect('cart')


@require_POST
def cart_remove_coupon(request):
    services.clear_coupon(request)
    messages.success(request, 'Coupon removed.')
    return redirect('cart')


@login_required_view
def wishlist(request):
    items = request.user.wishlist_items.select_related('product', 'product__category')
    return render(request, 'store/wishlist.html', {'items': items})


@require_POST
@login_required_view
def wishlist_toggle(request, pk):
    product = get_object_or_404(Product.objects.visible(), pk=pk)
    obj, created = WishlistItem.objects.get_or_create(user=request.user, product=product)
    if not created:
        obj.delete()
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return JsonResponse({'in_wishlist': created, 'count': request.user.wishlist_items.count()})
    messages.success(request, f'{product.name} {"added to" if created else "removed from"} wishlist.')
    return redirect(services.safe_next(request, 'wishlist'))


@require_POST
@login_required_view
def wishlist_move_to_cart(request, pk):
    item = get_object_or_404(WishlistItem, pk=pk, user=request.user)
    product = item.product
    if product.stock:
        services.add_to_cart(request, product, 1)
        item.delete()
        messages.success(request, f'{product.name} moved to your cart.')
    else:
        messages.error(request, f'{product.name} is out of stock.')
    return redirect('wishlist')


def checkout(request):
    if request.method == 'POST':
        return _process_checkout(request)
    totals = services.totals_for(request)
    if not totals['items']:
        messages.info(request, 'Your cart is empty.')
        return redirect('cart')
    settings = SiteSettings.get()
    initial = {'customer_name': '', 'phone': '', 'email': ''}
    if request.user.is_authenticated:
        initial = {
            'customer_name': request.user.get_full_name() or request.user.username,
            'phone': '',
            'email': request.user.email,
        }
        default_addr = request.user.addresses.filter(is_default=True).first() or request.user.addresses.first()
        if default_addr:
            initial.update({
                'customer_name': default_addr.full_name,
                'phone': default_addr.phone,
                'address_line1': default_addr.line1,
                'city': default_addr.city,
                'county': default_addr.county,
            })
    addresses = request.user.addresses.all() if request.user.is_authenticated else Address.objects.none()
    return render(request, 'store/checkout.html', {
        **totals,
        'addresses': addresses,
        'initial': initial,
        'mpesa_available': settings.mpesa_enabled,
    })


def _process_checkout(request):
    totals = services.totals_for(request)
    if not totals['items']:
        messages.error(request, 'Your cart is empty.')
        return redirect('cart')

    settings = SiteSettings.get()
    customer_name = request.POST.get('customer_name', '').strip()
    phone = request.POST.get('phone', '').strip()
    email = request.POST.get('email', '').strip()
    address_line1 = request.POST.get('address_line1', '').strip()
    city = request.POST.get('city', '').strip()
    county = request.POST.get('county', '').strip()
    payment_method = request.POST.get('payment_method', 'cod')

    if not customer_name or not phone:
        messages.error(request, 'Please provide your full name and phone number.')
        return redirect('checkout')
    if payment_method not in ('mpesa', 'cod'):
        payment_method = 'cod'
    if payment_method == 'mpesa' and not settings.mpesa_enabled:
        messages.error(request, 'M-Pesa is not available. Choose manual payment.')
        return redirect('checkout')

    data = {
        'customer_name': customer_name,
        'phone': phone,
        'email': email,
        'address_line1': address_line1,
        'city': city,
        'county': county,
    }
    try:
        order = services.create_order_from_cart(request, data, payment_method, totals)
    except ValueError as e:
        messages.error(request, str(e))
        return redirect('cart')

    if not request.user.is_authenticated:
        guest_orders = request.session.setdefault('guest_orders', [])
        if order.number not in guest_orders:
            guest_orders.append(order.number)
        request.session.modified = True

    notify.order_placed(order)

    if payment_method == 'mpesa':
        try:
            tx, resp = mpesa.stk_push(order, phone)
            payment = order.payments.first()
            if payment:
                payment.status = 'processing'
                payment.transaction_id = tx.checkout_request_id
                payment.reference = tx.transaction_id
                payment.save(update_fields=['status', 'transaction_id', 'reference', 'updated_at'])
            messages.success(request, 'M-Pesa prompt sent to your phone. Complete the payment and your order will update automatically.')
        except RuntimeError as e:
            _cancel_order(order, 'M-Pesa payment could not be started: {}'.format(e))
            messages.error(request, str(e))
            return redirect('cart')
    else:
        messages.success(request, f'Order {order.number} placed. We will contact you to arrange payment and delivery.')

    return redirect('order_detail', number=order.number)


def _cancel_order(order, note='Cancelled by system'):
    with transaction.atomic():
        services.release_stock(order)
        order.record_status('cancelled', note=note)
        order.payment_status = 'failed'
        order.save(update_fields=['payment_status', 'updated_at'])
        payment = order.payments.first()
        if payment and payment.status != 'paid':
            payment.status = 'failed'
            payment.result_description = note
            payment.save(update_fields=['status', 'result_description', 'updated_at'])
    notify.payment_failed(order, note, cancelled=True)


def order_detail(request, number):
    order = get_object_or_404(Order, number=number)
    if not _can_view_order(request, order):
        messages.error(request, 'Order not found or you do not have access to it.')
        return redirect('home')
    return render(request, 'store/order.html', {'order': order})


def _can_view_order(request, order):
    if request.user.is_staff:
        return True
    if request.user.is_authenticated and order.user_id == request.user.id:
        return True
    return number_in_session(request, order.number)


def number_in_session(request, number):
    return number in (request.session.get('guest_orders') or [])


@require_POST
def newsletter(request):
    email = request.POST.get('email', '').strip()
    try:
        validate_email(email)
    except ValidationError:
        messages.error(request, 'Please enter a valid email address.')
        return redirect(services.safe_next(request, 'home'))
    if email:
        NewsletterSubscriber.objects.get_or_create(email=email)
        messages.success(request, 'You are subscribed to our newsletter.')
    return redirect(services.safe_next(request, 'home'))


def contact(request):
    form = ContactForm()
    if request.method == 'POST':
        form = ContactForm(request.POST)
        if form.is_valid():
            contact = form.save()
            emails.contact_confirmation(contact)
            messages.success(request, 'Message sent. We will get back to you shortly.')
            return redirect('contact')
    return render(request, 'store/contact.html', {'form': form})


# --------------------------------------------------------------------------- #
# Customer account
# --------------------------------------------------------------------------- #

def register(request):
    if request.user.is_authenticated:
        return redirect('account')
    form = RegistrationForm()
    if request.method == 'POST':
        form = RegistrationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            notify.new_customer(user)
            messages.success(request, f'Welcome, {user.username}! Your account is ready.')
            return redirect('account')
    return render(request, 'account/register.html', {'form': form})


def login_view(request):
    if request.user.is_authenticated:
        return redirect('account')
    form = AuthenticationForm()
    if request.method == 'POST':
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            logger.info('User logged in: %s', user.username)
            return redirect(services.safe_next(request, 'account'))
    return render(request, 'account/login.html', {'form': form})


@login_required_view
def account(request):
    recent_orders = request.user.orders.order_by('-created_at')[:5]
    return render(request, 'account/dashboard.html', {
        'recent_orders': recent_orders,
        'address_count': request.user.addresses.count(),
        'wishlist_count': request.user.wishlist_items.count(),
        'order_count': request.user.orders.count(),
    })


@login_required_view
def account_orders(request):
    orders = request.user.orders.all()
    return render(request, 'account/orders.html', {'orders': orders})


@login_required_view
def account_order_detail(request, number):
    order = get_object_or_404(Order, number=number, user=request.user)
    return render(request, 'account/order_detail.html', {'order': order})


@login_required_view
def account_profile(request):
    form = ProfileForm(instance=request.user)
    if request.method == 'POST':
        form = ProfileForm(request.POST, instance=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, 'Profile updated.')
            return redirect('account_profile')
    return render(request, 'account/profile.html', {'form': form})


@login_required_view
def account_addresses(request):
    return render(request, 'account/addresses.html', {'addresses': request.user.addresses.all()})


@login_required_view
def address_add(request):
    form = AddressForm()
    if request.method == 'POST':
        form = AddressForm(request.POST)
        if form.is_valid():
            addr = form.save(commit=False)
            addr.user = request.user
            if addr.is_default or not request.user.addresses.exists():
                request.user.addresses.update(is_default=False)
                addr.is_default = True
            addr.save()
            messages.success(request, 'Address saved.')
            return redirect('account_addresses')
    return render(request, 'account/address_form.html', {'form': form, 'title': 'Add address'})


@login_required_view
def address_edit(request, pk):
    addr = get_object_or_404(Address, pk=pk, user=request.user)
    form = AddressForm(instance=addr)
    if request.method == 'POST':
        form = AddressForm(request.POST, instance=addr)
        if form.is_valid():
            addr = form.save(commit=False)
            if addr.is_default:
                request.user.addresses.exclude(pk=addr.pk).update(is_default=False)
            addr.save()
            messages.success(request, 'Address updated.')
            return redirect('account_addresses')
    return render(request, 'account/address_form.html', {'form': form, 'title': 'Edit address'})


@require_POST
@login_required_view
def address_delete(request, pk):
    addr = get_object_or_404(Address, pk=pk, user=request.user)
    addr.delete()
    messages.success(request, 'Address deleted.')
    return redirect('account_addresses')


@login_required_view
def account_notifications(request):
    page = Paginator(request.user.notifications.all(), 25).get_page(request.GET.get('page'))
    return render(request, 'account/notifications.html', {'page': page})


@require_POST
@login_required_view
def account_notifications_clear(request):
    request.user.notifications.update(read=True)
    messages.success(request, 'Notifications marked as read.')
    return redirect('account_notifications')


# --------------------------------------------------------------------------- #
# M-Pesa callback (public, Safaricom -> us)
# --------------------------------------------------------------------------- #

@login_required_view
def order_status_json(request, number):
    """JSON endpoint for e-commerce order status polling (M-Pesa checkout).

    Returns the payment status so the browser can update without a page
    refresh, matching the POS polling experience.
    """
    order = get_object_or_404(Order, number=number)
    if not _can_view_order(request, order):
        return JsonResponse({'error': 'Not found'}, status=404)
    tx = order.mpesa_transactions.order_by('-created_at').first()
    return JsonResponse({
        'number': order.number,
        'status': order.status,
        'payment_status': order.payment_status,
        'total': str(order.total),
        'mpesa_receipt': getattr(tx, 'mpesa_receipt', '') or '',
        'result_description': (getattr(tx, 'result_description', '') or '')[:200],
    })


def error_400(request, exception=None):
    return render(request, 'errors/400.html', status=400)


def error_403(request, exception=None):
    return render(request, 'errors/403.html', status=403)


def error_404(request, exception=None):
    return render(request, 'errors/404.html', status=404)


def error_500(request, exception=None):
    if not settings.DEBUG:
        try:
            title = 'Server error'
            detail = ''
            if exception is not None:
                title = f'Server error: {type(exception).__name__}'
                detail = str(exception)[:300]
            notify.system_error(title, detail)
        except Exception:
            logger.exception('Failed to record system error notification')
    return render(request, 'errors/500.html', status=500)


# Result codes documented as "the customer cancelled the STK prompt".
_CANCELLED_RESULT_CODES = {'1031', '1032'}


@csrf_exempt
def mpesa_callback(request):
    import json

    from decimal import InvalidOperation

    try:
        data = json.loads(request.body)
        body = data.get('Body', {}).get('stkCallback', {})
        checkout_id = body.get('CheckoutRequestID', '')
        if not checkout_id:
            logger.warning('M-Pesa callback with no CheckoutRequestID')
            return JsonResponse({'ResultCode': 0, 'ResultDesc': 'Accepted'})

        tx = (MpesaTransaction.objects.select_related('order')
              .filter(checkout_request_id=checkout_id).first())
        if not tx:
            logger.warning('M-Pesa callback for unknown CheckoutRequestID %s', checkout_id)
            return JsonResponse({'ResultCode': 0, 'ResultDesc': 'Accepted'})

        # Idempotency: never process the same gateway callback twice.
        if tx.status in ('completed', 'failed'):
            logger.info('M-Pesa callback already processed for %s (status %s)', checkout_id, tx.status)
            return JsonResponse({'ResultCode': 0, 'ResultDesc': 'Already processed'})

        result_code = str(body.get('ResultCode', '-1'))
        result_desc = body.get('ResultDesc', '')
        tx.result_code = result_code
        tx.result_description = result_desc

        if result_code == '0':
            meta = {}
            for item in (body.get('CallbackMetadata', {}) or {}).get('Item', []):
                if 'Name' in item:
                    meta[item['Name']] = item.get('Value')
            tx.status = 'completed'
            tx.mpesa_receipt = str(meta.get('MpesaReceiptNumber', '') or '')
            tx.transaction_date = str(meta.get('TransactionDate', '') or '')
            tx.phone = tx.phone or str(meta.get('PhoneNumber', '') or '')
            tx.save()

            if not tx.order:
                logger.info('M-Pesa payment completed for %s but no order is attached', checkout_id)
                return JsonResponse({'ResultCode': 0, 'ResultDesc': 'Accepted'})
            order = tx.order

            # The server decides whether to trust the callback. The amount
            # charged by the gateway must match what the server calculated.
            callback_amount = meta.get('Amount')
            expected = order.total.quantize(Decimal('0.01'))
            amount_ok = False
            if callback_amount is not None:
                try:
                    amount_ok = Decimal(str(callback_amount)).quantize(Decimal('0.01')) == expected
                except (InvalidOperation, TypeError, ValueError):
                    amount_ok = False

            if not amount_ok or not tx.mpesa_receipt:
                with transaction.atomic():
                    payment = services.get_or_create_payment(order, 'mpesa')
                    payment.status = 'requires_review'
                    payment.result_code = result_code
                    payment.result_description = (f'Amount mismatch or missing receipt: '
                                                  f'gateway reported {callback_amount or "n/a"}, '
                                                  f'expected {expected}.')
                    payment.transaction_id = checkout_id
                    payment.save()
                order.payment_status = 'requires_review'
                order.save(update_fields=['payment_status', 'updated_at'])
                notify.payment_requires_review(
                    order,
                    f'M-Pesa callback amount {callback_amount} did not match order total {expected}. '
                    f'Do not treat this as paid until verified.')
                logger.warning('M-Pesa callback amount mismatch for order %s: got %s expected %s',
                               order.number, callback_amount, expected)
            else:
                payment = services.mark_order_paid(
                    order, method='mpesa', reference=tx.mpesa_receipt,
                    verification='gateway', transaction_id=checkout_id,
                    result_code=result_code, result_description=result_desc)
                logger.info('M-Pesa payment confirmed for %s receipt %s amount %s',
                            checkout_id, tx.mpesa_receipt, tx.amount)
                notify.payment_received(order, tx.mpesa_receipt)
        else:
            tx.status = 'failed'
            tx.save()
            logger.info('M-Pesa payment failed for %s: %s', checkout_id, result_desc)
            if tx.order:
                order = tx.order
                cancelled = result_code in _CANCELLED_RESULT_CODES
                status = 'cancelled' if cancelled else 'failed'
                services.mark_order_payment_failed(
                    order, method='mpesa', status=status, reference=tx.transaction_id,
                    result_code=result_code, result_description=result_desc,
                    note=('Cancelled by customer' if cancelled else 'Payment failed'))
                notify.payment_failed(order, result_desc, cancelled=cancelled)
        return JsonResponse({'ResultCode': 0, 'ResultDesc': 'Accepted'})
    except Exception:
        logger.exception('Error handling M-Pesa callback')
        return JsonResponse({'ResultCode': 1, 'ResultDesc': 'Internal error'})
