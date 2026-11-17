"""Point-of-Sale service layer.

Everything here runs on the SAME products, stock and inventory pipeline as
the online store — there is no separate POS inventory. Prices always come
from the database; a total sent from the browser is never trusted.
"""
import logging
from decimal import Decimal, ROUND_HALF_UP

<<<<<<< HEAD
from django.contrib.auth.models import User
from django.db import close_old_connections, models, transaction
from django.db.models import Count, Q, Sum
from django.db.models.functions import Coalesce

from . import mpesa, services
from .models import (Category, Notification, Order, OrderItem, OrderStatusHistory,
                     Payment, PosSession, Product, SiteSettings)
=======
from django.db import close_old_connections, models, transaction
from django.db.models import Count, Q, Sum

from . import mpesa, services
from .models import (Notification, Order, OrderItem, OrderStatusHistory, Payment,
                     PosSession, Product, SiteSettings)
>>>>>>> 0eaeef0d594c7530f656b8338be122ce644eab03

logger = logging.getLogger('store')

CENT = Decimal('0.01')
ZERO = Decimal('0.00')

# POS payment options -> (Order.payment_method, Payment.method)
PAYMENT_METHODS = {
    'cash': ('cod', 'manual'),
    'mpesa': ('mpesa', 'mpesa'),
    'card': ('card', 'card'),
<<<<<<< HEAD
    'bank': ('bank', 'bank'),
    'split': ('split', 'manual'),
=======
>>>>>>> 0eaeef0d594c7530f656b8338be122ce644eab03
    'other': ('cod', 'manual'),
}


def money(value):
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


# --------------------------------------------------------------------------- #
# Search / scan
# --------------------------------------------------------------------------- #

<<<<<<< HEAD
def lookup_barcode(code):
    """Find a single product by exact barcode or SKU.

    Used by hardware barcode scanners to immediately identify and add an
    item to the till without intermediate search results.
    """
    q = (code or '').strip()
    if not q:
        return None
    qs = Product.objects.visible().select_related('category')
    return qs.filter(Q(barcode__iexact=q) | Q(sku__iexact=q)).first()


def search_products(query, limit=16):
    """Products matching name, partial name, SKU, barcode, brand, category, or description.
=======
def search_products(query, limit=12):
    """Products matching a name / SKU / barcode fragment.
>>>>>>> 0eaeef0d594c7530f656b8338be122ce644eab03

    Exact SKU or barcode hits come first so a hardware scanner (which types
    the full code and presses Enter) lands on exactly one product.
    """
    q = (query or '').strip()
    if not q:
        return []
<<<<<<< HEAD
    qs = Product.objects.visible().select_related('category')
    exact = qs.filter(Q(barcode__iexact=q) | Q(sku__iexact=q))
    if exact.exists():
        exact_list = list(exact[:limit])
        if len(exact_list) >= limit:
            return exact_list
        remaining = limit - len(exact_list)
        fuzzy = qs.filter(
            Q(name__icontains=q) | Q(sku__icontains=q) | Q(barcode__icontains=q)
            | Q(brand__icontains=q) | Q(category__name__icontains=q)
            | Q(short_description__icontains=q) | Q(description__icontains=q)
        ).exclude(pk__in=[p.pk for p in exact_list]).order_by('name')[:remaining]
        return exact_list + list(fuzzy)

    return list(qs.filter(
        Q(name__icontains=q) | Q(sku__icontains=q) | Q(barcode__icontains=q)
        | Q(brand__icontains=q) | Q(category__name__icontains=q)
        | Q(short_description__icontains=q) | Q(description__icontains=q)
    ).order_by('name')[:limit])


def catalogue_products(query='', category='', sort='', limit=60):
    """Browseable product grid for the supermarket-style till with sorting and filtering.

    Only products the storefront considers visible can be sold.
    """
    qs = Product.objects.visible().select_related('category')
    q = (query or '').strip()
    if q:
        qs = qs.filter(
            Q(name__icontains=q) | Q(sku__icontains=q) | Q(barcode__icontains=q)
            | Q(brand__icontains=q) | Q(category__name__icontains=q)
            | Q(short_description__icontains=q) | Q(description__icontains=q)
        )
    if category:
        qs = qs.filter(category__slug=category)

    # Sorting options
    if sort == 'price_asc':
        qs = qs.annotate(eff_price=Coalesce('sale_price', 'price')).order_by('eff_price')
    elif sort == 'price_desc':
        qs = qs.annotate(eff_price=Coalesce('sale_price', 'price')).order_by('-eff_price')
    elif sort == 'newest':
        qs = qs.order_by('-created_at')
    elif sort == 'popular':
        qs = qs.order_by('-sales_count', '-reviews_count', '-rating')
    elif sort == 'bestselling':
        qs = qs.order_by('-is_bestseller', '-sales_count')
    else:
        qs = qs.order_by('name')

    return list(qs[:max(1, min(int(limit or 60), 120))])


def active_categories():
    return list(Category.objects.filter(active=True).order_by('name'))


=======
    qs = Product.objects.select_related('category')
    exact = qs.filter(Q(barcode__iexact=q) | Q(sku__iexact=q))
    if exact.exists():
        return list(exact[:limit])
    return list(qs.filter(
        Q(name__icontains=q) | Q(sku__icontains=q) | Q(barcode__icontains=q) | Q(brand__icontains=q)
    ).order_by('name')[:limit])


>>>>>>> 0eaeef0d594c7530f656b8338be122ce644eab03
def serialize_product(p):
    return {
        'id': p.pk,
        'name': p.name,
        'sku': p.sku,
        'barcode': p.barcode or '',
        'price': str(p.effective_price),
<<<<<<< HEAD
        'regular_price': str(p.price),
        'sale_price': str(p.sale_price) if p.sale_price is not None else None,
        'has_discount': p.has_discount,
        'discount_percent': p.discount_percent,
        'stock': p.stock,
        'stock_status': p.stock_status,
        'stock_status_display': 'In Stock' if p.stock_status == p.STATUS_HEALTHY else ('Low Stock' if p.stock_status == p.STATUS_LOW else 'Out of Stock'),
        'image': p.image_src or '',
        'category': p.category.name if p.category_id else '',
        'category_slug': p.category.slug if p.category_id else '',
        'brand': p.brand or '',
        'out_of_stock': p.out_of_stock,
        'low_stock': p.low_stock,
=======
        'stock': p.stock,
        'image': p.image_src or '',
        'category': p.category.name if p.category_id else '',
        'out_of_stock': p.out_of_stock,
>>>>>>> 0eaeef0d594c7530f656b8338be122ce644eab03
    }


# --------------------------------------------------------------------------- #
# Server-side pricing (the browser's numbers are ignored)
# --------------------------------------------------------------------------- #

def quote_lines(payload):
    """Turn [{id, quantity}] into validated lines.

    Raises ValueError with a customer-appropriate message when a product is
    unknown or short of stock. Live stock is re-checked under row locks in
    create_pos_sale; this first pass catches obvious errors early.
    """
    if not isinstance(payload, list) or not payload:
        raise ValueError('The sale has no items.')
    lines = []
    by_id = {}
    for entry in payload:
        try:
            pid = int(entry.get('id'))
            qty = int(entry.get('quantity'))
        except (TypeError, ValueError, AttributeError):
            raise ValueError('Invalid item payload.')
        if qty < 1:
            raise ValueError('Quantity must be at least 1.')
        if pid in by_id:
            by_id[pid]['quantity'] += qty
            continue
        product = Product.objects.filter(pk=pid).first()
        if not product:
            raise ValueError('A product in this sale no longer exists.')
        line = {'product': product, 'quantity': qty}
        by_id[pid] = line
        lines.append(line)
    return lines


def price_lines(lines):
    """Attach DB unit prices and totals; returns subtotal."""
    subtotal = ZERO
    for line in lines:
        p = line['product']
        line['unit_price'] = p.effective_price
        line['total'] = money(p.effective_price * line['quantity'])
        subtotal += line['total']
    return money(subtotal)


# --------------------------------------------------------------------------- #
# Checkout
# --------------------------------------------------------------------------- #

@transaction.atomic
def create_pos_sale(*, user, items_payload, payment_method, discount=None,
<<<<<<< HEAD
                    cash_received=None, phone='', customer_name='', customer_id=None,
                    token=None, discount_authorised=False, bank_reference='',
                    card_reference='', tenders_payload=None):
    """Create and (where applicable) immediately settle an in-store sale.

    Cash / card / bank / other -> settled synchronously; stock leaves the shared
                                  inventory inside this transaction.
    M-Pesa                      -> STK Push fires after commit; the order stays
                                   pending until Safaricom's callback confirms it
                                   (stock deducts at that point, never before).
    Split                       -> Multi-tender payment (e.g. Cash + M-Pesa).
                                   If M-Pesa is part of the split, STK push fires
                                   and order completes on callback. If only synchronous
                                   tenders (Cash, Card, Bank), settles immediately.
=======
                    cash_received=None, phone='', customer_name='', token=None,
                    discount_authorised=False):
    """Create and (where applicable) immediately settle an in-store sale.

    Cash / card / other -> settled synchronously; stock leaves the shared
                          inventory inside this transaction.
    M-Pesa              -> STK Push fires after commit; the order stays
                           pending until Safaricom's callback confirms it
                           (stock deducts at that point, never before).
>>>>>>> 0eaeef0d594c7530f656b8338be122ce644eab03

    Idempotent on `token`: a retried request can never double-sell.
    """
    discount = money(discount or ZERO)
    if discount < 0:
        raise ValueError('Discount cannot be negative.')

    # Idempotency: same token -> return the sale created by the first request.
    token = (token or '').strip()
    if token:
        existing = Order.objects.filter(pos_token=token).first()
        if existing:
            return existing, False

    lines = quote_lines(items_payload)

    # Re-check live stock per line while holding row locks.
    for line in lines:
        p = Product.objects.select_for_update().get(pk=line['product'].pk)
        if p.stock < line['quantity']:
            raise ValueError(f'Not enough stock for {p.name}. Available: {p.stock}.')

    subtotal = price_lines(lines)
    if discount > subtotal:
        discount = subtotal
    if discount > 0 and not discount_authorised:
        raise PermissionError('Only managers can apply discounts.')
<<<<<<< HEAD

    # Calculate tax based on SiteSettings
    settings = SiteSettings.get()
    taxable_amount = max(ZERO, subtotal - discount)
    tax = settings.tax_for(taxable_amount) if settings.tax_enabled else ZERO
    total = money(taxable_amount + tax)
=======
    total = money(subtotal - discount)
>>>>>>> 0eaeef0d594c7530f656b8338be122ce644eab03

    if payment_method not in PAYMENT_METHODS:
        raise ValueError('Unknown payment method.')
    order_method, pay_method = PAYMENT_METHODS[payment_method]
    if payment_method == 'mpesa' and not (phone or '').strip():
        raise ValueError('A customer phone number is required for M-Pesa.')

<<<<<<< HEAD
    # Associate customer if specified
    customer_user = None
    if customer_id:
        customer_user = User.objects.filter(pk=customer_id).first()
        if customer_user and not customer_name:
            customer_name = customer_user.get_full_name() or customer_user.username
        if customer_user and not phone and hasattr(customer_user, 'profile'):
            phone = getattr(customer_user.profile, 'phone', '')

=======
>>>>>>> 0eaeef0d594c7530f656b8338be122ce644eab03
    session = PosSession.objects.filter(user=user, status=PosSession.STATUS_OPEN).first()

    order = Order.objects.create(
        number=Order.next_number(),
<<<<<<< HEAD
        user=customer_user,
=======
        user=None,
>>>>>>> 0eaeef0d594c7530f656b8338be122ce644eab03
        sales_channel='pos',
        served_by=user,
        pos_session=session,
        pos_token=token or None,
        customer_name=customer_name.strip() or 'Walk-in customer',
        phone=(phone or '').strip(),
        subtotal=subtotal,
        discount=discount,
        shipping=ZERO,
<<<<<<< HEAD
        tax=tax,
=======
        tax=ZERO,
>>>>>>> 0eaeef0d594c7530f656b8338be122ce644eab03
        total=total,
        payment_method=order_method,
        status='pending',
        payment_status='pending',
        stock_deducted=False,
    )
    order.pos_payment_method = payment_method
    order.save(update_fields=['pos_payment_method'])
<<<<<<< HEAD

=======
>>>>>>> 0eaeef0d594c7530f656b8338be122ce644eab03
    for line in lines:
        OrderItem.objects.create(
            order=order,
            product=line['product'],
            product_name=line['product'].name,
            product_sku=line['product'].sku,
            price=line['unit_price'],
            unit_cost=line['product'].cost_price,
            quantity=line['quantity'],
            subtotal=line['total'],
        )
<<<<<<< HEAD

=======
>>>>>>> 0eaeef0d594c7530f656b8338be122ce644eab03
    OrderStatusHistory.objects.create(order=order, status='pending',
                                      note=f'POS sale · {payment_method.upper()}',
                                      created_by=user)
    Notification.create(f'POS sale {order.number}',
                        message=f'{order.customer_name} — {total}',
                        category='order', link=f'/manage/orders/{order.number}/')

<<<<<<< HEAD
    # Payment execution
    if payment_method == 'mpesa':
        Payment.objects.create(order=order, method='mpesa', amount=total,
                               status='pending', phone=(phone or '').strip())
        transaction.on_commit(lambda: _start_mpesa(order.pk, amount=total, phone=(phone or '').strip()))
        return order, True

    elif payment_method == 'cash':
=======
    if payment_method == 'mpesa':
        Payment.objects.create(order=order, method='mpesa', amount=total,
                               status='pending', phone=(phone or '').strip())
        transaction.on_commit(lambda: _start_mpesa(order.pk))
        return order, True

    # Cash / card / other: settled right now, verified manually by cashier.
    received = change = None
    if payment_method == 'cash':
>>>>>>> 0eaeef0d594c7530f656b8338be122ce644eab03
        received = money(cash_received if cash_received is not None else total)
        if received < total:
            raise ValueError(f'Cash received ({received}) is less than the total ({total}).')
        change = money(received - total)

<<<<<<< HEAD
        services.mark_order_paid(
            order, method='manual', reference=f'CASH-{order.number}',
            verification='manual', verified_by=user,
            note=f'In-store cash sale by {user.get_full_name() or user.username}')
        payment = get_payment(order)
        payment.amount_paid = received
        payment.change_given = change
        payment.save(update_fields=['amount_paid', 'change_given', 'updated_at'])
        return order, True

    elif payment_method == 'card':
        ref = (card_reference or '').strip() or f'CARD-{order.number}'
        services.mark_order_paid(
            order, method='card', reference=ref,
            verification='manual', verified_by=user,
            note=f'In-store card payment ({ref}) verified by {user.get_full_name() or user.username}')
        payment = get_payment(order)
        payment.amount_paid = total
        payment.save(update_fields=['amount_paid', 'updated_at'])
        return order, True

    elif payment_method == 'bank':
        ref = (bank_reference or '').strip() or f'BANK-{order.number}'
        services.mark_order_paid(
            order, method='bank', reference=ref,
            verification='manual', verified_by=user,
            note=f'In-store bank transfer ({ref}) verified by {user.get_full_name() or user.username}')
        payment = get_payment(order)
        payment.amount_paid = total
        payment.save(update_fields=['amount_paid', 'updated_at'])
        return order, True

    elif payment_method == 'split':
        if not tenders_payload or not isinstance(tenders_payload, list):
            raise ValueError('Split payment requires tender items.')
        tender_sum = ZERO
        for t in tenders_payload:
            amt = money(t.get('amount') or 0)
            if amt <= 0:
                raise ValueError('Each split tender must have an amount greater than zero.')
            tender_sum += amt

        if tender_sum != total:
            raise ValueError(f'Total tenders ({tender_sum}) must equal the grand total ({total}).')

        has_mpesa = False
        mpesa_tender = None
        for t in tenders_payload:
            m = str(t.get('method') or '').lower()
            t_amt = money(t.get('amount') or 0)
            if m == 'cash':
                rec = money(t.get('cash_received') if t.get('cash_received') is not None else t_amt)
                if rec < t_amt:
                    raise ValueError(f'Cash received ({rec}) is less than tender amount ({t_amt}).')
                chg = money(rec - t_amt)
                Payment.objects.create(
                    order=order, method='manual', amount=t_amt,
                    amount_paid=rec, change_given=chg,
                    status='paid', verification='manual', verified_by=user,
                    reference=f'CASH-{order.number}'
                )
            elif m == 'card':
                ref = str(t.get('reference') or '').strip() or f'CARD-{order.number}'
                Payment.objects.create(
                    order=order, method='card', amount=t_amt,
                    amount_paid=t_amt,
                    status='paid', verification='manual', verified_by=user,
                    reference=ref
                )
            elif m == 'bank':
                ref = str(t.get('reference') or '').strip() or f'BANK-{order.number}'
                Payment.objects.create(
                    order=order, method='bank', amount=t_amt,
                    amount_paid=t_amt,
                    status='paid', verification='manual', verified_by=user,
                    reference=ref
                )
            elif m == 'mpesa':
                t_phone = str(t.get('phone') or phone).strip()
                if not t_phone:
                    raise ValueError('Customer phone number is required for the M-Pesa portion.')
                has_mpesa = True
                mpesa_tender = {'amount': t_amt, 'phone': t_phone}
                Payment.objects.create(
                    order=order, method='mpesa', amount=t_amt,
                    status='pending', phone=t_phone
                )
            else:
                raise ValueError(f'Unsupported split payment tender: {m}')

        if has_mpesa:
            transaction.on_commit(lambda: _start_mpesa(
                order.pk,
                amount=mpesa_tender['amount'],
                phone=mpesa_tender['phone']
            ))
            return order, True
        else:
            services.debit_stock_for_order(order)
            order.status = 'confirmed'
            order.payment_status = 'paid'
            order.save(update_fields=['status', 'payment_status', 'updated_at'])
            order.record_status('confirmed', note='POS sale · Split tenders confirmed', actor=user)
            return order, True

    else:  # other
        services.mark_order_paid(
            order, method=pay_method, reference=f'POS-{order.number}',
            verification='manual', verified_by=user,
            note=f'In-store {payment_method} sale by {user.get_full_name() or user.username}')
        return order, True


def _start_mpesa(order_pk, amount=None, phone=None):
=======
    services.mark_order_paid(
        order, method=pay_method, reference=f'POS-{order.number}',
        verification='manual', verified_by=user,
        note=f'In-store {payment_method} sale by {user.get_full_name() or user.username}')
    payment = get_payment(order)
    payment.amount_paid = received
    payment.change_given = change
    payment.save(update_fields=['amount_paid', 'change_given', 'updated_at'])
    return order, True


def _start_mpesa(order_pk):
>>>>>>> 0eaeef0d594c7530f656b8338be122ce644eab03
    """Runs post-commit: fire the real STK push; on failure cancel the sale."""
    close_old_connections()
    order = Order.objects.filter(pk=order_pk).first()
    if not order:
        return
<<<<<<< HEAD
    push_phone = phone or order.phone
    try:
        tx, resp = mpesa.stk_push(order, push_phone, amount=amount)
        payment = order.payments.filter(method='mpesa').order_by('-created_at').first()
=======
    try:
        tx, resp = mpesa.stk_push(order, order.phone)
        payment = get_payment(order)
>>>>>>> 0eaeef0d594c7530f656b8338be122ce644eab03
        if payment:
            payment.status = 'processing'
            payment.transaction_id = tx.checkout_request_id
            payment.reference = tx.transaction_id
<<<<<<< HEAD
            payment.phone = push_phone
            payment.save(update_fields=['status', 'transaction_id', 'reference', 'phone', 'updated_at'])
    except RuntimeError as e:
        logger.warning('POS M-Pesa start failed for %s: %s', order.number, e)
        reason = mpesa.customer_message_for(e)
        with transaction.atomic():
            services.release_stock(order)
            order.record_status('cancelled', note=f'M-Pesa could not be started: {reason}')
            order.payment_status = 'failed'
            order.save(update_fields=['payment_status', 'updated_at'])
            payment = order.payments.filter(method='mpesa').order_by('-created_at').first()
            if payment and payment.status != 'paid':
                payment.status = 'failed'
                payment.result_description = reason[:300]
=======
            payment.save(update_fields=['status', 'transaction_id', 'reference', 'updated_at'])
    except RuntimeError as e:
        logger.warning('POS M-Pesa start failed for %s: %s', order.number, e)
        with transaction.atomic():
            services.release_stock(order)
            order.record_status('cancelled', note=f'M-Pesa could not be started: {e}')
            order.payment_status = 'failed'
            order.save(update_fields=['payment_status', 'updated_at'])
            payment = get_payment(order)
            if payment and payment.status != 'paid':
                payment.status = 'failed'
                payment.result_description = str(e)[:300]
>>>>>>> 0eaeef0d594c7530f656b8338be122ce644eab03
                payment.save(update_fields=['status', 'result_description', 'updated_at'])


def get_payment(order):
    return order.payments.order_by('-created_at').first()


PAYMENT_LABELS = {
    'cash': 'CASH',
    'mpesa': 'M-PESA',
    'card': 'CARD',
<<<<<<< HEAD
    'bank': 'BANK TRANSFER',
    'split': 'SPLIT PAYMENT',
=======
>>>>>>> 0eaeef0d594c7530f656b8338be122ce644eab03
    'other': 'OTHER',
}


def serialize_order_status(order):
    """Compact JSON state for receipt polling / the POS confirmation panel."""
    tx = order.mpesa_transactions.order_by('-created_at').first()
<<<<<<< HEAD
    payment = order.payments.order_by('-created_at').first()
    reason = ((getattr(payment, 'result_description', '') or
               getattr(tx, 'result_description', '') or '')[:200])
    change = ZERO
    for p in order.payments.all():
        if p.change_given and p.change_given > change:
            change = p.change_given
=======
>>>>>>> 0eaeef0d594c7530f656b8338be122ce644eab03
    return {
        'number': order.number,
        'status': order.status,
        'payment_status': order.payment_status,
        'method_display': PAYMENT_LABELS.get(order.pos_payment_method)
                          or order.get_payment_method_display(),
<<<<<<< HEAD
        'subtotal': str(order.subtotal),
        'discount': str(order.discount),
        'tax': str(order.tax),
        'total': str(order.total),
        'change_given': str(change),
        'customer_name': order.customer_name,
        'mpesa_receipt': getattr(tx, 'mpesa_receipt', '') or '',
        'result_description': reason,
=======
        'total': str(order.total),
        'mpesa_receipt': getattr(tx, 'mpesa_receipt', '') or '',
        'result_description': (getattr(tx, 'result_description', '') or '')[:200],
>>>>>>> 0eaeef0d594c7530f656b8338be122ce644eab03
    }


# --------------------------------------------------------------------------- #
# Sessions & reporting
# --------------------------------------------------------------------------- #

def open_session(user, opening_cash=ZERO):
    session = PosSession.objects.filter(user=user, status=PosSession.STATUS_OPEN).first()
    if session:
        return session, False
    session = PosSession.objects.create(user=user, opening_cash=money(opening_cash))
    Notification.create(f'{user.get_full_name() or user.username} opened a POS shift',
                        category='system')
    return session, True


def close_session(session, closing_cash, notes=''):
    from django.utils import timezone
    session.closing_cash = money(closing_cash)
    session.notes = (notes or '')[:2000]
    session.status = PosSession.STATUS_CLOSED
    session.closed_at = timezone.now()
    session.save(update_fields=['closing_cash', 'notes', 'status', 'closed_at', 'updated_at'])
    return session


def session_report(session):
<<<<<<< HEAD
    """Cash-up figures for one shift — computed from real orders and payments."""
    orders = session.orders.all()
    paid = orders.filter(payment_status='paid')
    totals = paid.aggregate(count=Count('id'), total=Sum('total'))

    cash_total = ZERO
    mpesa_total = ZERO
    card_total = ZERO
    bank_total = ZERO

    # Look up all paid payments belonging to paid orders in this session
    session_payments = Payment.objects.filter(order__in=paid, status='paid')
    for p in session_payments:
        if p.method == 'manual':
            cash_total += p.amount
        elif p.method == 'mpesa':
            mpesa_total += p.amount
        elif p.method == 'card':
            card_total += p.amount
        elif p.method == 'bank':
            bank_total += p.amount

    if not session_payments.exists() and paid.exists():
        for label, om in (('cash', 'cod'), ('mpesa', 'mpesa'), ('card', 'card'), ('bank', 'bank')):
            sub = paid.filter(payment_method=om).aggregate(t=Sum('total'))['t'] or ZERO
            if label == 'cash': cash_total += sub
            elif label == 'mpesa': mpesa_total += sub
            elif label == 'card': card_total += sub
            elif label == 'bank': bank_total += sub

    by_method = {
        'cash': {
            'count': paid.filter(Q(payment_method='cod') | Q(payment_method='split', payments__method='manual')).distinct().count(),
            'total': money(cash_total)
        },
        'mpesa': {
            'count': paid.filter(Q(payment_method='mpesa') | Q(payment_method='split', payments__method='mpesa')).distinct().count(),
            'total': money(mpesa_total)
        },
        'card': {
            'count': paid.filter(Q(payment_method='card') | Q(payment_method='split', payments__method='card')).distinct().count(),
            'total': money(card_total)
        },
        'bank': {
            'count': paid.filter(Q(payment_method='bank') | Q(payment_method='split', payments__method='bank')).distinct().count(),
            'total': money(bank_total)
        },
    }
    expected_cash = session.opening_cash + cash_total
=======
    """Cash-up figures for one shift — computed from real orders only."""
    orders = session.orders.all()
    paid = orders.filter(payment_status='paid')
    totals = paid.aggregate(count=Count('id'), total=Sum('total'))
    by_method = {}
    for label, om in (('cash', 'cod'), ('mpesa', 'mpesa'), ('card', 'card')):
        qs = paid.filter(payment_method=om)
        agg = qs.aggregate(count=Count('id'), total=Sum('total'))
        by_method[label] = {'count': agg['count'], 'total': agg['total'] or ZERO}
    expected_cash = session.opening_cash + by_method['cash']['total']
>>>>>>> 0eaeef0d594c7530f656b8338be122ce644eab03
    return {
        'orders': totals['count'],
        'total': totals['total'] or ZERO,
        'by_method': by_method,
        'expected_cash': money(expected_cash),
        'open_orders': orders.exclude(payment_status__in=('paid', 'failed', 'cancelled')).count(),
    }
