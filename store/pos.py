"""Point-of-Sale service layer.

Everything here runs on the SAME products, stock and inventory pipeline as
the online store — there is no separate POS inventory. Prices always come
from the database; a total sent from the browser is never trusted.
"""
import logging
from decimal import Decimal, ROUND_HALF_UP

from django.db import close_old_connections, models, transaction
from django.db.models import Count, Q, Sum

from . import mpesa, services
from .models import (Notification, Order, OrderItem, OrderStatusHistory, Payment,
                     PosSession, Product, SiteSettings)

logger = logging.getLogger('store')

CENT = Decimal('0.01')
ZERO = Decimal('0.00')

# POS payment options -> (Order.payment_method, Payment.method)
PAYMENT_METHODS = {
    'cash': ('cod', 'manual'),
    'mpesa': ('mpesa', 'mpesa'),
    'card': ('card', 'card'),
    'other': ('cod', 'manual'),
}


def money(value):
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


# --------------------------------------------------------------------------- #
# Search / scan
# --------------------------------------------------------------------------- #

def search_products(query, limit=12):
    """Products matching a name / SKU / barcode fragment.

    Exact SKU or barcode hits come first so a hardware scanner (which types
    the full code and presses Enter) lands on exactly one product.
    """
    q = (query or '').strip()
    if not q:
        return []
    qs = Product.objects.select_related('category')
    exact = qs.filter(Q(barcode__iexact=q) | Q(sku__iexact=q))
    if exact.exists():
        return list(exact[:limit])
    return list(qs.filter(
        Q(name__icontains=q) | Q(sku__icontains=q) | Q(barcode__icontains=q) | Q(brand__icontains=q)
    ).order_by('name')[:limit])


def serialize_product(p):
    return {
        'id': p.pk,
        'name': p.name,
        'sku': p.sku,
        'barcode': p.barcode or '',
        'price': str(p.effective_price),
        'stock': p.stock,
        'image': p.image_src or '',
        'category': p.category.name if p.category_id else '',
        'out_of_stock': p.out_of_stock,
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
                    cash_received=None, phone='', customer_name='', token=None,
                    discount_authorised=False):
    """Create and (where applicable) immediately settle an in-store sale.

    Cash / card / other -> settled synchronously; stock leaves the shared
                          inventory inside this transaction.
    M-Pesa              -> STK Push fires after commit; the order stays
                           pending until Safaricom's callback confirms it
                           (stock deducts at that point, never before).

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
    total = money(subtotal - discount)

    if payment_method not in PAYMENT_METHODS:
        raise ValueError('Unknown payment method.')
    order_method, pay_method = PAYMENT_METHODS[payment_method]
    if payment_method == 'mpesa' and not (phone or '').strip():
        raise ValueError('A customer phone number is required for M-Pesa.')

    session = PosSession.objects.filter(user=user, status=PosSession.STATUS_OPEN).first()

    order = Order.objects.create(
        number=Order.next_number(),
        user=None,
        sales_channel='pos',
        served_by=user,
        pos_session=session,
        pos_token=token or None,
        customer_name=customer_name.strip() or 'Walk-in customer',
        phone=(phone or '').strip(),
        subtotal=subtotal,
        discount=discount,
        shipping=ZERO,
        tax=ZERO,
        total=total,
        payment_method=order_method,
        status='pending',
        payment_status='pending',
        stock_deducted=False,
    )
    order.pos_payment_method = payment_method
    order.save(update_fields=['pos_payment_method'])
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
    OrderStatusHistory.objects.create(order=order, status='pending',
                                      note=f'POS sale · {payment_method.upper()}',
                                      created_by=user)
    Notification.create(f'POS sale {order.number}',
                        message=f'{order.customer_name} — {total}',
                        category='order', link=f'/manage/orders/{order.number}/')

    if payment_method == 'mpesa':
        Payment.objects.create(order=order, method='mpesa', amount=total,
                               status='pending', phone=(phone or '').strip())
        transaction.on_commit(lambda: _start_mpesa(order.pk))
        return order, True

    # Cash / card / other: settled right now, verified manually by cashier.
    received = change = None
    if payment_method == 'cash':
        received = money(cash_received if cash_received is not None else total)
        if received < total:
            raise ValueError(f'Cash received ({received}) is less than the total ({total}).')
        change = money(received - total)

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
    """Runs post-commit: fire the real STK push; on failure cancel the sale."""
    close_old_connections()
    order = Order.objects.filter(pk=order_pk).first()
    if not order:
        return
    try:
        tx, resp = mpesa.stk_push(order, order.phone)
        payment = get_payment(order)
        if payment:
            payment.status = 'processing'
            payment.transaction_id = tx.checkout_request_id
            payment.reference = tx.transaction_id
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
                payment.save(update_fields=['status', 'result_description', 'updated_at'])


def get_payment(order):
    return order.payments.order_by('-created_at').first()


PAYMENT_LABELS = {
    'cash': 'CASH',
    'mpesa': 'M-PESA',
    'card': 'CARD',
    'other': 'OTHER',
}


def serialize_order_status(order):
    """Compact JSON state for receipt polling / the POS confirmation panel."""
    tx = order.mpesa_transactions.order_by('-created_at').first()
    return {
        'number': order.number,
        'status': order.status,
        'payment_status': order.payment_status,
        'method_display': PAYMENT_LABELS.get(order.pos_payment_method)
                          or order.get_payment_method_display(),
        'total': str(order.total),
        'mpesa_receipt': getattr(tx, 'mpesa_receipt', '') or '',
        'result_description': (getattr(tx, 'result_description', '') or '')[:200],
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
    return {
        'orders': totals['count'],
        'total': totals['total'] or ZERO,
        'by_method': by_method,
        'expected_cash': money(expected_cash),
        'open_orders': orders.exclude(payment_status__in=('paid', 'failed', 'cancelled')).count(),
    }
