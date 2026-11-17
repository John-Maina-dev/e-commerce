import logging
<<<<<<< HEAD
import re
from decimal import Decimal
from uuid import uuid4

from django.contrib import messages
from django.contrib.auth import authenticate, login
=======
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth import login
>>>>>>> 0eaeef0d594c7530f656b8338be122ce644eab03
from django.contrib.auth import views as auth_views
from django.contrib.auth.forms import AuthenticationForm
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.core.validators import validate_email
<<<<<<< HEAD
from django.db import IntegrityError, transaction
=======
from django.db import transaction
>>>>>>> 0eaeef0d594c7530f656b8338be122ce644eab03
from django.db.models import Case, F, Q, When
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from . import emails, mpesa, notify, services
from .decorators import login_required_view
from .forms import AddressForm, ContactForm, ProfileForm, RegistrationForm, ReviewForm, SitePasswordResetForm
<<<<<<< HEAD
from .models import (AccountAuditLog, Address, Category, MpesaTransaction, NewsletterSubscriber,
                     Order, OrderStatusHistory, Payment, Product, Review,
                     SiteSettings, UserProfile, WishlistItem)
=======
from .models import (Address, Category, MpesaTransaction, NewsletterSubscriber,
                     Order, Product, Review, SiteSettings, WishlistItem)
>>>>>>> 0eaeef0d594c7530f656b8338be122ce644eab03
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
<<<<<<< HEAD
    new_arrivals = (Product.objects.visible().select_related('category')
                    .order_by('-is_new', '-created_at')[:8])
=======
    new_arrivals = (Product.objects.visible().select_related('category').filter(is_new=True)[:8]
                    or Product.objects.visible().select_related('category')[:8])
>>>>>>> 0eaeef0d594c7530f656b8338be122ce644eab03
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
<<<<<<< HEAD
    currency = SiteSettings.get().currency
=======
>>>>>>> 0eaeef0d594c7530f656b8338be122ce644eab03
    return JsonResponse({'results': [
        {
            'id': p.pk,
            'name': p.name,
            'slug': p.slug,
            'category': p.category.name,
            'price': f'{p.effective_price:,.0f}',
<<<<<<< HEAD
            'currency': currency,
=======
            'currency': SiteSettings.get().currency,
>>>>>>> 0eaeef0d594c7530f656b8338be122ce644eab03
            'image': p.image_src or '',
            'out_of_stock': p.out_of_stock,
        } for p in results
    ]})


def product_detail(request, slug):
    product = get_object_or_404(
        Product.objects.visible().select_related('category').prefetch_related('images'), slug=slug)
    reviews = product.reviews.filter(active=True).select_related('user')
<<<<<<< HEAD
    related = services.related_products(product, limit=4)
=======
    related = (Product.objects.visible().filter(category=product.category)
               .exclude(pk=product.pk).select_related('category')[:4])
>>>>>>> 0eaeef0d594c7530f656b8338be122ce644eab03
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
<<<<<<< HEAD
    from . import recommendations
    totals = services.totals_for(request)
    cart_pids = [item['product'].id for item in totals['items']]
    recs = recommendations.get_cart_recommendations(cart_pids, limit=8)
    context = {
        **totals,
        'recommendations': recs,
    }
    return render(request, 'store/cart.html', context)
=======
    totals = services.totals_for(request)
    return render(request, 'store/cart.html', totals)
>>>>>>> 0eaeef0d594c7530f656b8338be122ce644eab03


@require_POST
def cart_add(request, pk):
    product = get_object_or_404(Product.objects.visible(), pk=pk)
    qty = request.POST.get('quantity', 1)
    try:
        qty = int(qty)
    except (TypeError, ValueError):
        qty = 1
<<<<<<< HEAD

    is_ajax = (request.headers.get('x-requested-with') == 'XMLHttpRequest' or
               'application/json' in request.headers.get('accept', ''))

    if product.stock <= 0:
        msg = f'{product.name} is out of stock.'
        if is_ajax:
            return JsonResponse({'ok': False, 'error': msg}, status=400)
        messages.error(request, msg)
    elif qty > product.stock:
        msg = f'Only {product.stock} units of {product.name} are available.'
        if is_ajax:
            return JsonResponse({'ok': False, 'error': msg}, status=400)
        messages.error(request, msg)
    else:
        services.add_to_cart(request, product, qty)
        msg = f'{product.name} added to cart.'
        if is_ajax:
            totals = services.totals_for(request)
            return JsonResponse({
                'ok': True,
                'message': msg,
                'cart_count': services.cart_count(request),
                'subtotal': str(totals['subtotal']),
                'total': str(totals['total']),
                'tax': str(totals['tax']),
            })
        messages.success(request, msg)
=======
    if product.stock <= 0:
        messages.error(request, f'{product.name} is out of stock.')
    elif qty > product.stock:
        messages.error(request, f'Only {product.stock} units of {product.name} are available.')
    else:
        services.add_to_cart(request, product, qty)
        messages.success(request, f'{product.name} added to cart.')
>>>>>>> 0eaeef0d594c7530f656b8338be122ce644eab03
    return redirect(services.safe_next(request, 'cart'))


@require_POST
def cart_update(request, pk):
    product = get_object_or_404(Product, pk=pk)
    qty = request.POST.get('quantity', 1)
    try:
        qty = int(qty)
    except (TypeError, ValueError):
        qty = 1
<<<<<<< HEAD

    is_ajax = (request.headers.get('x-requested-with') == 'XMLHttpRequest' or
               'application/json' in request.headers.get('accept', ''))

=======
>>>>>>> 0eaeef0d594c7530f656b8338be122ce644eab03
    if qty <= 0:
        services.remove_from_cart(request, pk)
    else:
        services.set_cart_qty(request, product, qty)
        messages.success(request, 'Cart updated.')
<<<<<<< HEAD

    if is_ajax:
        totals = services.totals_for(request)
        return JsonResponse({
            'ok': True,
            'cart_count': services.cart_count(request),
            'subtotal': str(totals['subtotal']),
            'total': str(totals['total']),
            'tax': str(totals['tax']),
        })
=======
>>>>>>> 0eaeef0d594c7530f656b8338be122ce644eab03
    return redirect('cart')


@require_POST
def cart_remove(request, pk):
    services.remove_from_cart(request, pk)
    messages.success(request, 'Item removed from cart.')
<<<<<<< HEAD
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        totals = services.totals_for(request)
        return JsonResponse({
            'ok': True,
            'cart_count': services.cart_count(request),
            'subtotal': str(totals['subtotal']),
            'total': str(totals['total']),
        })
    return redirect('cart')


@require_POST
def cart_clear(request):
    services.clear_cart(request)
    messages.success(request, 'Your cart has been cleared.')
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return JsonResponse({'ok': True, 'cart_count': 0})
=======
>>>>>>> 0eaeef0d594c7530f656b8338be122ce644eab03
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


<<<<<<< HEAD
# --------------------------------------------------------------------------- #
# Checkout
# --------------------------------------------------------------------------- #

def _checkout_token(request):
    """Return the per-session idempotency token for the checkout form.

    A fresh token is minted the first time a customer reaches the checkout
    page and reused until the order is successfully placed (so a double-click
    or a back/refresh of the form cannot create a second order). The token is
    sent as a hidden field and verified server-side against any order already
    carrying it; it is rotated after a successful placement so a follow-up
    checkout gets its own fresh key.
    """
    token = request.session.get('checkout_token')
    if not token:
        token = uuid4().hex
        request.session['checkout_token'] = token
        request.session.modified = True
    return token


=======
>>>>>>> 0eaeef0d594c7530f656b8338be122ce644eab03
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
<<<<<<< HEAD
        'checkout_token': _checkout_token(request),
=======
>>>>>>> 0eaeef0d594c7530f656b8338be122ce644eab03
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
<<<<<<< HEAD

    # Idempotency: the hidden token (minted per checkout page load) lets us
    # recognise a retried submission — double-click, back/refresh — and return
    # the already-placed order instead of creating a duplicate.
    checkout_token = (request.POST.get('checkout_token', '') or '').strip()
    if checkout_token:
        existing = Order.objects.filter(checkout_token=checkout_token).first()
        if existing:
            messages.info(request, f'Order {existing.number} was already placed.')
            return redirect('order_detail', number=existing.number)

    try:
        order = services.create_order_from_cart(
            request, data, payment_method, totals, checkout_token=checkout_token or None)
    except IntegrityError:
        # A concurrent request won the race to use this idempotency token.
        if checkout_token:
            existing = Order.objects.filter(checkout_token=checkout_token).first()
            if existing:
                messages.info(request, f'Order {existing.number} was already placed.')
                return redirect('order_detail', number=existing.number)
        raise
=======
    try:
        order = services.create_order_from_cart(request, data, payment_method, totals)
>>>>>>> 0eaeef0d594c7530f656b8338be122ce644eab03
    except ValueError as e:
        messages.error(request, str(e))
        return redirect('cart')

<<<<<<< HEAD
    # Rotate the idempotency token so the next checkout starts fresh and can
    # never replay this one (the previous token is now bound to the order).
    request.session['checkout_token'] = uuid4().hex
    request.session.modified = True

=======
>>>>>>> 0eaeef0d594c7530f656b8338be122ce644eab03
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
<<<<<<< HEAD
                payment.reference = tx.merchant_request_id or tx.transaction_id
                payment.save(update_fields=['status', 'transaction_id', 'reference', 'updated_at'])
            order.payment_status = 'processing'
            order.save(update_fields=['payment_status', 'updated_at'])
            messages.success(request, 'M-Pesa prompt sent. Check your phone and enter your M-Pesa PIN.')
        except RuntimeError as e:
            # Never throw the order (and the customer's basket) away because
            # the prompt could not be started. Keep the order and let the
            # customer recover.
            reason = mpesa.customer_message_for(e)
            _record_payment_start_failure(order, str(e))
            if _manual_fallback_ready(e):
                # Daraja refused the prompt before it could reach a phone, so
                # the customer can safely pay the same amount straight to the
                # store's PayBill/Till and submit the confirmation code.
                messages.info(
                    request,
                    'We could not send the automatic M-Pesa prompt, so your '
                    'order is saved. You can pay directly to our M-Pesa '
                    'PayBill/Till below and enter the confirmation code.')
                return redirect('mpesa_manual', number=order.number)
            messages.error(
                request,
                f'We could not send the M-Pesa prompt: {reason} '
                'Your order has been saved — retry the payment or switch to '
                'pay on delivery from the order page.')
            return redirect('order_detail', number=order.number)
=======
                payment.reference = tx.transaction_id
                payment.save(update_fields=['status', 'transaction_id', 'reference', 'updated_at'])
            messages.success(request, 'M-Pesa prompt sent to your phone. Complete the payment and your order will update automatically.')
        except RuntimeError as e:
            _cancel_order(order, 'M-Pesa payment could not be started: {}'.format(e))
            messages.error(request, str(e))
            return redirect('cart')
>>>>>>> 0eaeef0d594c7530f656b8338be122ce644eab03
    else:
        messages.success(request, f'Order {order.number} placed. We will contact you to arrange payment and delivery.')

    return redirect('order_detail', number=order.number)


<<<<<<< HEAD
def _record_payment_start_failure(order, reason):
    """Mark the payment attempt failed without cancelling the order.

    A failed STK Push start is recoverable: the customer can retry from the
    order page (or switch to pay on delivery).
    """
    with transaction.atomic():
        payment = order.payments.first()
        if payment and payment.status != 'paid':
            payment.status = 'failed'
            payment.result_description = (reason or '')[:2000]
            payment.save(update_fields=['status', 'result_description', 'updated_at'])
        order.payment_status = 'failed'
        order.save(update_fields=['payment_status', 'updated_at'])
        OrderStatusHistory.objects.create(
            order=order, status=order.status,
            note=f'M-Pesa prompt could not be started: {reason}'[:300])
    # Send internal staff alert, but skip emailing customer since this was a system/config start failure
    notify.notify_staff(f'Payment could not be started for {order.number}', reason, category=notify.PAYMENT)


def _manual_fallback_ready(error):
    """Whether it is safe and useful to offer manual M-Pesa after a refusal.

    Requires a PayBill/Till number the customer can actually pay into. When
    the store has no shortcode configured there is nothing to show, so the
    normal saved-order message is used instead.
    """
    if not mpesa.manual_fallback_available(error):
        return False
    return bool((SiteSettings.get().mpesa_shortcode or '').strip())


def _mpesa_manual_context(order):
    s = SiteSettings.get()
    return {
        'order': order,
        'pay_shortcode': (s.mpesa_shortcode or '').strip(),
        'account_type': s.mpesa_account_type,
        'account_type_label': s.get_mpesa_account_type_display(),
        'pay_amount': mpesa.order_charge_amount(order),
        'business_name': s.mpesa_business_name or s.store_name,
        'store_phone': s.phone,
    }


def mpesa_manual(request, number):
    """Show PayBill/Till instructions when STK Push cannot be started."""
    order = get_object_or_404(Order, number=number)
    if not _can_view_order(request, order):
        messages.error(request, 'Order not found or you do not have access to it.')
        return redirect('home')
    if order.payment_method != 'mpesa':
        return redirect('order_detail', number=order.number)
    if order.payment_status == 'paid':
        messages.info(request, 'This order is already paid.')
        return redirect('order_detail', number=order.number)
    if order.status in ('cancelled', 'refunded'):
        messages.info(request, 'This order is closed and can no longer be paid.')
        return redirect('order_detail', number=order.number)
    if order.payment_status == 'processing':
        messages.info(request, 'An M-Pesa prompt is already in progress for this order.')
        return redirect('order_detail', number=order.number)

    payment = order.payments.first()
    if payment and payment.manual_code:
        messages.info(request, 'Your M-Pesa code has already been submitted for verification.')
        return redirect('order_detail', number=order.number)
    if order.payment_status == 'requires_review':
        messages.info(request, 'This payment is already being reviewed by the store.')
        return redirect('order_detail', number=order.number)

    context = _mpesa_manual_context(order)
    if not context['pay_shortcode']:
        messages.error(request, 'M-Pesa details are not configured. Please contact the store.')
        return redirect('order_detail', number=order.number)
    return render(request, 'store/mpesa_manual.html', context)


@require_POST
def mpesa_manual_submit(request, number):
    """Accept the customer's M-Pesa confirmation code for staff verification."""
    order = get_object_or_404(Order, number=number)
    if not _can_view_order(request, order):
        messages.error(request, 'Order not found or you do not have access to it.')
        return redirect('home')
    if order.payment_method != 'mpesa':
        return redirect('order_detail', number=order.number)
    if order.payment_status == 'paid':
        messages.info(request, 'This order is already paid.')
        return redirect('order_detail', number=order.number)
    if order.status in ('cancelled', 'refunded'):
        messages.info(request, 'This order is closed and can no longer be paid.')
        return redirect('order_detail', number=order.number)
    if order.payment_status == 'processing':
        messages.info(request, 'An M-Pesa prompt is already in progress for this order.')
        return redirect('order_detail', number=order.number)

    payment = order.payments.first() or services.get_or_create_payment(order, 'mpesa')
    if payment.manual_code:
        messages.info(request, 'Your M-Pesa code has already been submitted. '
                               'The store will verify it shortly.')
        return redirect('order_detail', number=order.number)

    # Safaricom confirmation codes are 10 letters/digits (e.g. QGH4X8Y2Z1).
    code = re.sub(r'\s+', '', request.POST.get('code', '')).upper()
    if not re.fullmatch(r'[A-Z0-9]{10}', code):
        messages.error(request, 'Enter the 10-character M-Pesa confirmation code '
                                'from the SMS (for example QGH4X8Y2Z1).')
        return redirect('mpesa_manual', number=order.number)

    # A code proves one payment only. Refuse a code already claimed on another
    # payment so the same transfer cannot be presented twice.
    if Payment.objects.filter(manual_code=code).exclude(pk=payment.pk).exists():
        messages.error(request, 'That M-Pesa code has already been used. '
                                'Please check the SMS and enter the correct code.')
        return redirect('mpesa_manual', number=order.number)

    with transaction.atomic():
        payment.manual_code = code
        payment.manual_submitted_at = timezone.now()
        payment.status = 'requires_review'
        payment.reference = code
        payment.result_description = (
            f'Manual M-Pesa payment — customer submitted code {code}; '
            'awaiting staff verification against the M-Pesa statement.')
        payment.action_note = 'Manual M-Pesa payment awaiting verification'
        payment.save(update_fields=['manual_code', 'manual_submitted_at', 'status',
                                    'reference', 'result_description', 'action_note',
                                    'updated_at'])
        order.payment_status = 'requires_review'
        order.save(update_fields=['payment_status', 'updated_at'])
        OrderStatusHistory.objects.create(
            order=order, status=order.status,
            note=f'Customer submitted M-Pesa code {code} for verification')

    notify.payment_requires_review(
        order, f'Customer submitted M-Pesa code {code} for {order.total}. '
               'Match it to the M-Pesa statement before approving.')
    messages.success(request, 'Thanks — we received your M-Pesa code. '
                              'The store will verify it and confirm your order shortly.')
    return redirect('order_detail', number=order.number)


@require_POST
def order_retry_payment(request, number):
    """Let a customer retry an M-Pesa prompt or switch to pay on delivery.

    Only the order owner (or a guest with the order in their session, or
    staff) can use this, and only while the order is still unpaid.
    """
    order = get_object_or_404(Order, number=number)
    if not _can_view_order(request, order):
        messages.error(request, 'Order not found or you do not have access to it.')
        return redirect('home')
    if order.payment_status == 'paid':
        messages.info(request, 'This order is already paid.')
        return redirect('order_detail', number=order.number)
    if order.payment_status == 'processing':
        messages.info(request, 'An M-Pesa prompt is already in progress for this order.')
        return redirect('order_detail', number=order.number)
    if order.status in ('cancelled', 'refunded'):
        messages.info(request, 'This order is closed and can no longer be paid.')
        return redirect('order_detail', number=order.number)

    action = (request.POST.get('action') or 'mpesa').strip().lower()
    actor = request.user if request.user.is_authenticated else None

    if action == 'cod':
        with transaction.atomic():
            order.payment_method = 'cod'
            order.payment_status = 'pending'
            order.save(update_fields=['payment_method', 'payment_status', 'updated_at'])
            payment = order.payments.first()
            if payment:
                payment.method = 'manual'
                payment.status = 'pending'
                payment.result_description = ''
                payment.action_note = 'Customer switched to pay on delivery'
                payment.save(update_fields=['method', 'status', 'result_description',
                                            'action_note', 'updated_at'])
            OrderStatusHistory.objects.create(
                order=order, status=order.status,
                note='Customer switched to pay on delivery', created_by=actor)
        messages.success(request, 'Payment method updated. You will pay on delivery.')
        return redirect('order_detail', number=order.number)

    # Retry M-Pesa.
    settings = SiteSettings.get()
    if not settings.mpesa_enabled:
        messages.error(request, 'M-Pesa is not available right now. Please choose pay on delivery.')
        return redirect('order_detail', number=order.number)

    phone = (request.POST.get('phone') or order.phone or '').strip()
    if not phone:
        messages.error(request, 'Enter the M-Pesa phone number.')
        return redirect('order_detail', number=order.number)

    try:
        tx, _resp = mpesa.stk_push(order, phone)
    except RuntimeError as e:
        reason = mpesa.customer_message_for(e)
        _record_payment_start_failure(order, reason)
        if _manual_fallback_ready(e):
            messages.info(
                request,
                'We could not send the automatic M-Pesa prompt. You can pay '
                'directly to our M-Pesa PayBill/Till below and enter the '
                'confirmation code.')
            return redirect('mpesa_manual', number=order.number)
        messages.error(request, f'We could not send the M-Pesa prompt: {reason}')
        return redirect('order_detail', number=order.number)

    with transaction.atomic():
        order.payment_method = 'mpesa'
        order.payment_status = 'processing'
        order.phone = phone
        order.save(update_fields=['payment_method', 'payment_status', 'phone', 'updated_at'])
        payment = order.payments.first() or services.get_or_create_payment(order, 'mpesa')
        payment.method = 'mpesa'
        payment.status = 'processing'
        payment.phone = phone
        payment.transaction_id = tx.checkout_request_id
        payment.reference = tx.transaction_id
        payment.result_description = ''
        payment.save(update_fields=['method', 'status', 'phone', 'transaction_id',
                                    'reference', 'result_description', 'updated_at'])
        OrderStatusHistory.objects.create(
            order=order, status=order.status,
            note='M-Pesa prompt re-sent', created_by=actor)
    messages.success(request, 'M-Pesa prompt sent. Enter your PIN on your phone to complete payment.')
    return redirect('order_detail', number=order.number)


=======
>>>>>>> 0eaeef0d594c7530f656b8338be122ce644eab03
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
<<<<<<< HEAD
    is_ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.POST.get('ajax') == '1'
    email = request.POST.get('email', '').strip().lower()
    try:
        validate_email(email)
    except ValidationError:
        err_msg = 'Please enter a valid email address.'
        if is_ajax:
            return JsonResponse({'status': 'error', 'message': err_msg}, status=400)
        messages.error(request, err_msg)
        return redirect(services.safe_next(request, 'home'))

    sub, created = NewsletterSubscriber.objects.get_or_create(
        email=email,
        defaults={'active': True, 'confirmed': True}
    )

    if request.user.is_authenticated:
        sub.user = request.user

    if not created:
        if sub.active:
            msg = 'You are already subscribed to new arrival updates!'
            if is_ajax:
                return JsonResponse({'status': 'info', 'message': msg})
            messages.info(request, msg)
            return redirect(services.safe_next(request, 'home'))
        else:
            sub.active = True
            sub.confirmed = True
            sub.save()
            msg = 'Welcome back! Your subscription has been reactivated.'
    else:
        sub.save()
        msg = 'Thank you for subscribing! You will receive updates whenever new items arrive.'

    # Send welcome/confirmation email
    try:
        services.send_subscription_welcome_email(sub)
    except Exception as e:
        logger.warning('Could not send welcome email to %s: %s', email, e)

    if is_ajax:
        return JsonResponse({'status': 'ok', 'message': msg})
    messages.success(request, msg)
    return redirect(services.safe_next(request, 'home'))


def newsletter_unsubscribe(request, token):
    sub = NewsletterSubscriber.objects.filter(unsubscribe_token=token).first()
    if not sub:
        return render(request, 'account/unsubscribed.html', {
            'success': False,
            'message': 'Invalid or expired unsubscribe link.'
        })

    if request.method == 'POST' and request.POST.get('action') == 'resubscribe':
        sub.active = True
        sub.save(update_fields=['active'])
        messages.success(request, 'You have successfully resubscribed!')
        return render(request, 'account/unsubscribed.html', {
            'success': True,
            'resubscribed': True,
            'sub': sub,
            'message': f'Your subscription for {sub.email} has been restored.'
        })

    sub.active = False
    sub.save(update_fields=['active'])
    return render(request, 'account/unsubscribed.html', {
        'success': True,
        'resubscribed': False,
        'sub': sub,
        'message': f'You have been unsubscribed from Reeves Boutique updates ({sub.email}).'
    })


=======
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


>>>>>>> 0eaeef0d594c7530f656b8338be122ce644eab03
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
<<<<<<< HEAD
            user = form.save(commit=False)
            user.is_active = False  # Account remains inactive until approved by Super Admin
            user.save()
            profile, _ = UserProfile.objects.get_or_create(
                user=user,
                defaults={
                    'role': UserProfile.ROLE_CUSTOMER,
                    'status': UserProfile.STATUS_PENDING,
                }
            )
            profile.role = UserProfile.ROLE_CUSTOMER
            profile.status = UserProfile.STATUS_PENDING
            profile.save()
            AccountAuditLog.objects.create(
                target_user=user,
                target_username=user.username,
                action='register',
                note='New user registration awaiting administrator approval.',
                ip_address=request.META.get('REMOTE_ADDR'),
            )
            notify.new_registration(user)
            return render(request, 'account/pending_approval.html', {'registered_username': user.username})
    return render(request, 'account/register.html', {'form': form})


def pending_approval(request):
    return render(request, 'account/pending_approval.html')


def login_view(request):
    if request.user.is_authenticated:
        profile = getattr(request.user, 'profile', None)
        if profile and profile.role in ('super_admin', 'admin'):
            return redirect('dashboard')
        elif profile and profile.role == 'cashier':
            return redirect('pos_terminal')
        return redirect('account')

    form = AuthenticationForm()
    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '')

        # Attempt standard authentication first
        auth_user = authenticate(request, username=username, password=password)
        if auth_user is not None:
            profile = getattr(auth_user, 'profile', None)
            if profile and profile.status == UserProfile.STATUS_APPROVED:
                login(request, auth_user)
                logger.info('User logged in: %s (role: %s)', auth_user.username, profile.role)
                if profile.role in ('super_admin', 'admin'):
                    default_dest = 'dashboard'
                elif profile.role == 'cashier':
                    default_dest = 'pos_terminal'
                else:
                    default_dest = 'account'
                return redirect(services.safe_next(request, default_dest))
            else:
                messages.error(request, 'Your account is not approved to log in.')
        else:
            # Check if user exists and password is correct, but account is pending/rejected/suspended
            from django.contrib.auth import get_user_model
            UserModel = get_user_model()
            existing_user = UserModel.objects.filter(username__iexact=username).first()
            if existing_user and existing_user.check_password(password):
                profile = getattr(existing_user, 'profile', None)
                if profile and profile.status == UserProfile.STATUS_PENDING:
                    messages.warning(
                        request,
                        'Your account registration is currently pending administrator approval. '
                        'You will be able to log in as soon as an administrator approves your account.'
                    )
                elif profile and profile.status == UserProfile.STATUS_REJECTED:
                    reason = f' Reason: {profile.rejection_reason}' if profile.rejection_reason else ''
                    messages.error(
                        request,
                        f'Your account registration was rejected.{reason} Please contact support if you need assistance.'
                    )
                elif profile and profile.status == UserProfile.STATUS_SUSPENDED:
                    reason = f' Reason: {profile.suspension_reason}' if profile.suspension_reason else ''
                    messages.error(
                        request,
                        f'Your account has been suspended.{reason} Please contact an administrator.'
                    )
                else:
                    messages.error(request, 'Your account is inactive. Please contact an administrator.')
            else:
                messages.error(request, 'Invalid username or password. Please try again.')

    return render(request, 'account/login.html', {'form': form})



=======
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


>>>>>>> 0eaeef0d594c7530f656b8338be122ce644eab03
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


<<<<<<< HEAD
@require_POST
@login_required_view
def account_notification_read(request, pk):
    n = get_object_or_404(request.user.notifications, pk=pk)
    n.read = True
    n.save(update_fields=['read'])
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return JsonResponse({'status': 'ok'})
    return redirect(services.safe_next(request, 'account_notifications'))


@login_required_view
def account_subscription(request):
    sub, _ = NewsletterSubscriber.objects.get_or_create(
        email=request.user.email,
        defaults={'user': request.user, 'active': True, 'confirmed': True}
    )
    if not sub.user:
        sub.user = request.user
        sub.save(update_fields=['user'])

    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'toggle':
            sub.active = not sub.active
            sub.save(update_fields=['active'])
            status_str = 'subscribed to' if sub.active else 'unsubscribed from'
            messages.success(request, f'You are now {status_str} new arrival alerts.')
        elif action == 'categories':
            cat_ids = request.POST.getlist('categories')
            if 'all' in cat_ids or not cat_ids:
                sub.all_categories = True
                sub.categories.clear()
            else:
                sub.all_categories = False
                sub.categories.set(Category.objects.filter(id__in=cat_ids))
            sub.save(update_fields=['all_categories'])
            messages.success(request, 'Your category preferences have been saved.')
        return redirect('account_subscription')

    categories = Category.objects.filter(active=True)
    return render(request, 'account/subscription.html', {
        'sub': sub,
        'categories': categories,
    })


=======
>>>>>>> 0eaeef0d594c7530f656b8338be122ce644eab03
# --------------------------------------------------------------------------- #
# M-Pesa callback (public, Safaricom -> us)
# --------------------------------------------------------------------------- #

<<<<<<< HEAD
=======
@login_required_view
>>>>>>> 0eaeef0d594c7530f656b8338be122ce644eab03
def order_status_json(request, number):
    """JSON endpoint for e-commerce order status polling (M-Pesa checkout).

    Returns the payment status so the browser can update without a page
<<<<<<< HEAD
    refresh, matching the POS polling experience. Access is gated by
    ``_can_view_order`` (same rule as ``order_detail``) so guest customers who
    can view their order — including via the session-based guest list — can
    also poll for M-Pesa confirmation.
=======
    refresh, matching the POS polling experience.
>>>>>>> 0eaeef0d594c7530f656b8338be122ce644eab03
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
<<<<<<< HEAD
@require_POST
def mpesa_callback(request):
    import json
    from decimal import InvalidOperation

    try:
        raw_body = request.body.decode('utf-8', errors='replace')
        logger.info('M-Pesa Callback received: %s', raw_body)
        data = json.loads(raw_body)
=======
def mpesa_callback(request):
    import json

    from decimal import InvalidOperation

    try:
        data = json.loads(request.body)
>>>>>>> 0eaeef0d594c7530f656b8338be122ce644eab03
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

<<<<<<< HEAD
            # The server decides whether to trust the callback. Compare the
            # gateway amount with the amount actually requested from Daraja
            # (whole shillings) rather than the raw order total, which can
            # include cents that STK Push cannot charge.
            callback_amount = meta.get('Amount')
            expected = (tx.amount or order.total).quantize(Decimal('0.01'))
=======
            # The server decides whether to trust the callback. The amount
            # charged by the gateway must match what the server calculated.
            callback_amount = meta.get('Amount')
            expected = order.total.quantize(Decimal('0.01'))
>>>>>>> 0eaeef0d594c7530f656b8338be122ce644eab03
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
<<<<<<< HEAD
        return JsonResponse({'ResultCode': 0, 'ResultDesc': 'Accepted'})
=======
        return JsonResponse({'ResultCode': 1, 'ResultDesc': 'Internal error'})
>>>>>>> 0eaeef0d594c7530f656b8338be122ce644eab03
