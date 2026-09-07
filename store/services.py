import logging
from decimal import Decimal
from pathlib import Path

from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme

from . import notify
from .models import (Coupon, CouponUsage, InventoryAlert, InventoryChange,
                     Order, OrderItem, OrderStatusHistory, OrderReturn, Payment, Product, SiteSettings)

logger = logging.getLogger('store')

ZERO = Decimal('0.00')

MAX_IMAGE_UPLOAD_BYTES = 5 * 1024 * 1024
ALLOWED_IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp'}


def validate_image_upload(upload):
    """Ensure an uploaded file is a genuine image within size/type limits.

    Used for uploads that bypass a ModelForm (branding files, extra product
    gallery images). SVG/HTML uploads are rejected so a served media file can
    never become a stored-XSS vector, and Pillow verifies the bytes actually
    decode as an image rather than trusting the filename or Content-Type.
    """
    if upload.size > MAX_IMAGE_UPLOAD_BYTES:
        raise ValidationError('Image is too large (max 5 MB).')
    extension = Path(upload.name).suffix.lower()
    if extension not in ALLOWED_IMAGE_EXTENSIONS:
        raise ValidationError('Only JPG, PNG, GIF, WEBP or BMP images are allowed.')
    try:
        from io import BytesIO

        from PIL import Image
        data = upload.read(MAX_IMAGE_UPLOAD_BYTES + 1)
        Image.open(BytesIO(data)).verify()
    except Exception:
        raise ValidationError('The uploaded file is not a valid image.')
    finally:
        upload.seek(0)


def safe_next(request, default):
    """Return the caller-supplied `next` URL only when it is safe.

    Guards every `next`-param redirect against open-redirect attacks: an
    absolute URL pointing at another host (or a protocol-relative `//host`
    URL) is discarded and the trusted default is used instead.
    """
    url = request.POST.get('next', '') or request.GET.get('next', '')
    if url and url_has_allowed_host_and_scheme(url, allowed_hosts=None):
        return url
    return default


def get_cart(request):
    return request.session.get('cart', {}) or {}


def save_cart(request, cart):
    request.session['cart'] = cart
    request.session.modified = True


def cart_count(request):
    return sum(get_cart(request).values())


def cart_items(request):
    cart = get_cart(request)
    products = {str(p.id): p for p in Product.objects.filter(id__in=[int(i) for i in cart.keys()])}
    items = []
    for pid, qty in cart.items():
        p = products.get(pid)
        if not p:
            continue
        qty = max(1, int(qty))
        if p.stock < qty:
            qty = p.stock
        if qty <= 0:
            continue
        items.append({'product': p, 'quantity': qty, 'line': p.effective_price * qty})
    return items


def cart_subtotal(items):
    return sum(i['line'] for i in items) or ZERO


def add_to_cart(request, product, qty=1):
    cart = get_cart(request)
    key = str(product.id)
    current = int(cart.get(key, 0))
    cart[key] = min(current + qty, product.stock) if product.stock else 0
    save_cart(request, cart)


def set_cart_qty(request, product, qty):
    cart = get_cart(request)
    key = str(product.id)
    qty = max(1, int(qty))
    cart[key] = min(qty, product.stock) if product.stock else 0
    if cart[key] <= 0:
        cart.pop(key, None)
    save_cart(request, cart)


def remove_from_cart(request, product_id):
    cart = get_cart(request)
    cart.pop(str(product_id), None)
    save_cart(request, cart)


def clear_cart(request):
    if 'cart' in request.session:
        del request.session['cart']
        request.session.modified = True


def coupon_key(request):
    return request.session.get('coupon_code', '')


def set_coupon(request, code):
    request.session['coupon_code'] = code
    request.session.modified = True


def clear_coupon(request):
    if 'coupon_code' in request.session:
        del request.session['coupon_code']
        request.session.modified = True


def validate_coupon(request, code=None):
    code = (code or coupon_key(request)).strip().upper()
    if not code:
        return None, 'No coupon applied.'
    try:
        coupon = Coupon.objects.get(code__iexact=code)
    except Coupon.DoesNotExist:
        return None, 'Invalid coupon code.'
    if not coupon.is_valid:
        return None, 'This coupon is no longer valid.'
    subtotal = cart_subtotal(cart_items(request))
    if subtotal < coupon.min_order_amount:
        return None, f'This coupon requires a minimum order of {coupon.min_order_amount}.'
    if request.user.is_authenticated:
        usages = coupon.usages.filter(user=request.user).count()
        if coupon.per_user_limit and usages >= coupon.per_user_limit:
            return None, 'You have already used this coupon.'
    return coupon, None


def totals_for(request, coupon=None):
    items = cart_items(request)
    subtotal = cart_subtotal(items)
    settings = SiteSettings.get()
    discount = ZERO
    if coupon is None:
        coupon, err = validate_coupon(request)
    if coupon:
        discount = coupon.discount_for(subtotal)
    shipping = settings.shipping_for(subtotal)
    tax = settings.tax_for(subtotal)
    total = subtotal - discount + shipping + tax
    return {
        'items': items,
        'subtotal': subtotal,
        'discount': discount,
        'shipping': shipping,
        'tax': tax,
        'total': total,
        'coupon': coupon,
    }


@transaction.atomic
def create_order_from_cart(request, data, payment_method, totals):
    from uuid import uuid4

    settings = SiteSettings.get()
    user = request.user if request.user.is_authenticated else None
    hold_stock = settings.inventory_strategy == 'hold'
    order = Order.objects.create(
        number=Order.next_number(),
        user=user,
        customer_name=data.get('customer_name', ''),
        phone=data.get('phone', ''),
        email=data.get('email', ''),
        address_line1=data.get('address_line1', ''),
        city=data.get('city', ''),
        county=data.get('county', ''),
        subtotal=totals['subtotal'],
        discount=totals['discount'],
        shipping=totals['shipping'],
        tax=totals['tax'],
        total=totals['total'],
        coupon=totals.get('coupon'),
        payment_method=payment_method,
        status='pending',
        payment_status='pending',
        stock_deducted=hold_stock,
    )
    for item in totals['items']:
        p = Product.objects.select_for_update().get(pk=item['product'].pk)
        if p.stock < item['quantity']:
            raise ValueError(f'Not enough stock for {p.name}. Available: {p.stock}.')
        if hold_stock:
            old_stock = p.stock
            p.stock -= item['quantity']
            p.sales_count += item['quantity']
            p.save(update_fields=['stock', 'sales_count', 'updated_at'])
            record_inventory_change(p, 'sale', old_qty=old_stock, new_qty=p.stock,
                                    note=f'Sale · order {order.number}')
            evaluate_product_stock(p)
        OrderItem.objects.create(
            order=order,
            product=p,
            product_name=p.name,
            product_sku=p.sku,
            price=item['product'].effective_price,
            unit_cost=p.cost_price,
            quantity=item['quantity'],
            subtotal=item['line'],
        )
    Payment.objects.create(
        order=order,
        method='mpesa' if payment_method == 'mpesa' else 'manual',
        amount=order.total,
        status='pending',
        phone=data.get('phone', ''),
    )
    OrderStatusHistory.objects.create(order=order, status='pending', note='Order placed')
    coupon = totals.get('coupon')
    if coupon:
        coupon.used_count += 1
        coupon.save(update_fields=['used_count'])
        CouponUsage.objects.create(coupon=coupon, user=user, order=order)
    clear_cart(request)
    clear_coupon(request)
    return order


@transaction.atomic
def release_stock(order):
    if order.stock_released:
        return 0
    if not order.stock_deducted:
        # Nothing was ever deducted (e.g. 'deduct on payment' strategy and the
        # order was never paid) — there is nothing to restore.
        order.stock_released = True
        order.save(update_fields=['stock_released', 'updated_at'])
        return 0
    restored = 0
    for item in order.items.all():
        if item.product:
            old_stock = item.product.stock
            item.product.stock += item.quantity
            item.product.sales_count = max(0, item.product.sales_count - item.quantity)
            item.product.save(update_fields=['stock', 'sales_count', 'updated_at'])
            record_inventory_change(item.product, 'release', old_qty=old_stock, new_qty=item.product.stock,
                                    note=f'Released · order {order.number} cancelled/refunded')
            evaluate_product_stock(item.product)
            restored += item.quantity
    if restored:
        order.stock_released = True
        order.stock_deducted = False
        order.save(update_fields=['stock_released', 'stock_deducted', 'updated_at'])
        logger.info('Restored %s units of stock for cancelled/refunded order %s', restored, order.number)
    return restored


# --------------------------------------------------------------------------- #
# Payments
# --------------------------------------------------------------------------- #

def payment_method_for(order):
    return 'mpesa' if order.payment_method == 'mpesa' else 'manual'


def get_or_create_payment(order, method=None, amount=None):
    method = method or payment_method_for(order)
    payment = order.payments.filter(method=method).first()
    if not payment:
        payment = Payment.objects.create(order=order, method=method,
                                         amount=amount or order.total,
                                         status='pending', phone=order.phone)
    return payment


@transaction.atomic
def debit_stock_for_order(order):
    """Deduct stock for an order's items exactly once.

    Under the 'hold' strategy the stock was already deducted at order creation
    (so this is a no-op). Under the 'paid' strategy this is called when the
    payment is confirmed, and raises ValueError if stock is now insufficient.

    POS sales always follow deduct-on-paid semantics: a till sale only becomes
    an Order when money changes hands (or a pending M-Pesa prompt confirms),
    so stock leaves the shared inventory at that moment regardless of the
    online-store strategy.
    """
    if order.stock_deducted:
        return 0
    settings = SiteSettings.get()
    if settings.inventory_strategy == 'hold' and order.sales_channel != 'pos':
        order.stock_deducted = True
        order.save(update_fields=['stock_deducted', 'updated_at'])
        return 0
    deducted = 0
    for item in order.items.select_related('product').all():
        if not item.product:
            continue
        p = Product.objects.select_for_update().get(pk=item.product.pk)
        if p.stock < item.quantity:
            raise ValueError(f'Not enough stock for {p.name}. Available: {p.stock}.')
        old_stock = p.stock
        p.stock -= item.quantity
        p.sales_count += item.quantity
        p.save(update_fields=['stock', 'sales_count', 'updated_at'])
        record_inventory_change(p, 'sale', old_qty=old_stock, new_qty=p.stock,
                                note=f'Sale · order {order.number} (payment confirmed)')
        evaluate_product_stock(p)
        deducted += item.quantity
    if deducted:
        order.stock_deducted = True
        order.save(update_fields=['stock_deducted', 'updated_at'])
    return deducted


@transaction.atomic
def mark_order_paid(order, *, method=None, reference, verification,
                    transaction_id='', result_code='', result_description='',
                    verified_by=None, note=''):
    """Record a successful payment and advance the order.

    Only gateway callbacks (verification='gateway') or staff manual approval
    (verification='manual') may call this — a customer can never self-confirm
    their own payment. Stock is deducted per the configured inventory strategy.
    """
    payment = get_or_create_payment(order, method)
    payment.status = 'paid'
    payment.reference = reference or payment.reference
    payment.transaction_id = transaction_id or payment.reference
    payment.result_code = result_code
    payment.result_description = result_description
    payment.verification = verification
    if verification == 'manual':
        payment.verified_by = verified_by
        payment.verified_at = timezone.now()
        if note:
            payment.action_note = note
    payment.save()

    order.payment_status = 'paid'
    order.save(update_fields=['payment_status', 'updated_at'])
    if order.status in ('pending', 'processing'):
        who = f'{verified_by.get_full_name() or verified_by.username}' if verified_by else 'Safaricom'
        order.record_status('confirmed', note=f'Payment confirmed ({who})')

    try:
        debit_stock_for_order(order)
    except ValueError as e:
        payment.action_note = (payment.action_note + ' ' if payment.action_note else '') + str(e)
        payment.save(update_fields=['action_note', 'updated_at'])
        notify.fulfillment_blocked(order, str(e))
    return payment


@transaction.atomic
def mark_order_payment_failed(order, *, method=None, status='failed', reference='',
                              result_code='', result_description='', verified_by=None,
                              note='', cancel_order=True):
    """Record a failed/cancelled payment. Optionally cancels the order and
    releases any deducted stock."""
    payment = get_or_create_payment(order, method)
    payment.status = status
    if reference:
        payment.reference = reference
    payment.result_code = result_code
    payment.result_description = result_description
    if verified_by:
        payment.verified_by = verified_by
        payment.verified_at = timezone.now()
    if note:
        payment.action_note = note
    payment.save()

    order.payment_status = status
    order.save(update_fields=['payment_status', 'updated_at'])
    if cancel_order and order.status in ('pending', 'processing', 'confirmed'):
        release_stock(order)
        order.record_status('cancelled', note=note or 'Payment not received')
    return payment


# --------------------------------------------------------------------------- #
# Inventory alerts & history
# --------------------------------------------------------------------------- #

def record_inventory_change(product, action, old_qty=None, new_qty=None, note='', user=None):
    change = 0
    if isinstance(old_qty, int) and isinstance(new_qty, int):
        change = new_qty - old_qty
    return InventoryChange.objects.create(
        product=product, action=action, old_qty=old_qty, new_qty=new_qty,
        change=change, note=note, user=user)


def build_alert_message(product, alert_type):
    if alert_type == InventoryAlert.TYPE_OUT:
        return f'{product.name} is out of stock and cannot be sold. Restock to avoid losing sales.'
    return f'{product.name} has only {product.stock} left (threshold {product.low_stock_threshold}). Restock soon.'


def evaluate_product_stock(product, user=None):
    """Recompute a product's open alerts after a stock change.

    Creates an InventoryAlert (low stock / out of stock) the first time a
    product crosses its threshold, resolves alerts when stock recovers, and
    sends an email to the configured admin address when a new alert is raised.

    Returns the list of newly created alerts.
    """
    stock = product.stock or 0
    threshold = product.low_stock_threshold or 0
    if stock <= 0:
        status = Product.STATUS_OUT
        alert_type = InventoryAlert.TYPE_OUT
    elif stock <= threshold:
        status = Product.STATUS_LOW
        alert_type = InventoryAlert.TYPE_LOW
    else:
        status = Product.STATUS_HEALTHY

    # Back to healthy: close every open alert for this product.
    if status == Product.STATUS_HEALTHY:
        InventoryAlert.objects.filter(product=product, is_resolved=False).update(
            is_resolved=True, resolved_at=timezone.now())
        return []

    # A product can only be in one state at a time — close the other type.
    other_type = InventoryAlert.TYPE_LOW if alert_type == InventoryAlert.TYPE_OUT else InventoryAlert.TYPE_OUT
    InventoryAlert.objects.filter(product=product, alert_type=other_type, is_resolved=False).update(
        is_resolved=True, resolved_at=timezone.now())

    new_alerts = []
    alert = InventoryAlert.objects.filter(product=product, alert_type=alert_type, is_resolved=False).first()
    if alert:
        alert.stock_at_alert = stock
        alert.message = build_alert_message(product, alert_type)
        alert.save(update_fields=['stock_at_alert', 'message', 'updated_at'])
    else:
        alert = InventoryAlert.objects.create(
            product=product, alert_type=alert_type, stock_at_alert=stock,
            message=build_alert_message(product, alert_type))
        new_alerts.append(alert)
        notify.inventory_alert(alert)
        if user:
            logger.info('Inventory alert raised for %s (%s) by %s', product.name, alert_type, user.username)
    return new_alerts


def recompute_product_rating(product):
    from django.db.models import Avg, Count
    from decimal import Decimal, ROUND_HALF_UP

    agg = product.reviews.filter(active=True).aggregate(r=Avg('rating'), c=Count('id'))
    if agg['c']:
        product.rating = (agg['r'] or Decimal('0')).quantize(Decimal('0.1'), rounding=ROUND_HALF_UP)
        product.reviews_count = agg['c']
    else:
        product.rating = Decimal('0.0')
        product.reviews_count = 0
    product.save(update_fields=['rating', 'reviews_count', 'updated_at'])


# --------------------------------------------------------------------------- #
# Returns
# --------------------------------------------------------------------------- #

@transaction.atomic
def process_return(order, item, quantity, reason='', restock=True, user=None):
    """Record a partial return against an existing sale.

    The original order is never altered or deleted. Stock flows back through
    the audited InventoryChange pipeline only when `restock` is true (damaged
    goods may be returned without re-entering sellable stock). The refunded
    amount is derived from the price actually charged on the line.
    """
    quantity = int(quantity)
    already = item.returns.aggregate(q=models.Sum('quantity'))['q'] or 0
    if quantity < 1:
        raise ValueError('Return quantity must be at least 1.')
    sellable = item.quantity - already
    if quantity > sellable:
        raise ValueError(f'Only {sellable} unit(s) of {item.product_name} can still be returned.')
    refunded = (item.price * quantity).quantize(Decimal('0.01'))

    ret = OrderReturn.objects.create(
        order=order, item=item, quantity=quantity, reason=reason[:300],
        refunded_amount=refunded, restocked=restock, processed_by=user)

    if restock and item.product:
        p = Product.objects.select_for_update().get(pk=item.product.pk)
        old_stock = p.stock
        p.stock += quantity
        p.sales_count = max(0, p.sales_count - quantity)
        p.save(update_fields=['stock', 'sales_count', 'updated_at'])
        record_inventory_change(p, 'return', old_qty=old_stock, new_qty=p.stock,
                                note=f'Return · order {order.number} · {reason}'[:300], user=user)
        evaluate_product_stock(p)
    return ret
