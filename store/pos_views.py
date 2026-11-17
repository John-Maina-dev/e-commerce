"""Point-of-Sale interface views (staff area).

The cashier UI lives at /manage/pos/. Every money-affecting decision is made
here on the server via store.pos — the browser only describes intent.
"""
import json
import logging
from decimal import Decimal
import re
from uuid import uuid4

from django.contrib import messages
from django.contrib.auth.models import User
from django.db.models import Avg, Count, Q, Sum
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify
from django.views.decorators.http import require_GET, require_POST

from . import pos, services
from .decorators import has_role, staff_required
from .models import Order, OrderItem, Payment, PosSession, SiteSettings, UserProfile
from .views import _can_view_order

logger = logging.getLogger('store')


# --------------------------------------------------------------------------- #
# Terminal & Sessions
# --------------------------------------------------------------------------- #

@staff_required
def pos_terminal(request):
    session = PosSession.objects.filter(user=request.user,
                                        status=PosSession.STATUS_OPEN).first()
    settings = SiteSettings.get()
    context = {
        'session': session,
        'mpesa_ready': settings.mpesa_complete,
        'can_discount': has_role(request.user, 'Manager', 'Admin'),
        'tax_enabled': settings.tax_enabled,
        'tax_rate': str(settings.tax_rate),
    }
    return render(request, 'manage/pos.html', context)


@require_POST
@staff_required
def pos_session_open(request):
    try:
        opening = Decimal(request.POST.get('opening_cash') or '0')
    except Exception:
        opening = Decimal('0')
    session, created = pos.open_session(request.user, opening)
    if created:
        messages.success(request, 'Shift opened. The till is ready.')
    else:
        messages.info(request, 'You already have an open shift.')
    return redirect('pos_terminal')


@require_POST
@staff_required
def pos_session_close(request):
    session = PosSession.objects.filter(user=request.user,
                                        status=PosSession.STATUS_OPEN).first()
    if not session:
        messages.info(request, 'You have no open shift.')
        return redirect('pos_terminal')
    report = pos.session_report(session)
    if request.POST.get('confirm'):
        from decimal import InvalidOperation
        try:
            counted = Decimal(request.POST.get('closing_cash') or '0')
        except InvalidOperation:
            messages.error(request, 'Enter the counted cash amount.')
            return render(request, 'manage/pos_session_close.html',
                          {'session': session, 'report': report})
        pos.close_session(session, counted, notes=request.POST.get('notes', ''))
        logger.info('POS shift %s closed by %s', session.pk, request.user.username)
        messages.success(request, 'Shift closed and reconciled.')
        return redirect('pos_terminal')
    return render(request, 'manage/pos_session_close.html',
                  {'session': session, 'report': report})


# --------------------------------------------------------------------------- #
# Hardware Barcode Scanner & Search APIs
# --------------------------------------------------------------------------- #

@require_GET
@staff_required
def pos_barcode_scan(request):
    """Instant lookup of product by exact barcode or SKU for hardware scanners."""
    code = request.GET.get('code', '').strip()
    if not code:
        return JsonResponse({'ok': False, 'error': 'No barcode or SKU provided.'}, status=400)
    product = pos.lookup_barcode(code)
    if not product:
        return JsonResponse({'ok': False, 'error': f'Product with barcode/SKU "{code}" was not found.'}, status=404)
    return JsonResponse({'ok': True, 'product': pos.serialize_product(product)})


@require_GET
@staff_required
def pos_search(request):
    results = pos.search_products(request.GET.get('q', ''))
    return JsonResponse({'results': [pos.serialize_product(p) for p in results]})


@require_GET
@staff_required
def pos_catalogue(request):
    """Product grid + category chips + sorting for the supermarket-style terminal."""
    products = pos.catalogue_products(
        query=request.GET.get('q', ''),
        category=request.GET.get('category', ''),
        sort=request.GET.get('sort', ''),
    )
    return JsonResponse({
        'products': [pos.serialize_product(p) for p in products],
        'categories': [{'name': c.name, 'slug': c.slug}
                       for c in pos.active_categories()],
    })


@require_GET
@staff_required
def pos_recommendations(request):
    """Provide intelligent cross-sell product recommendations for the current till basket."""
    from . import recommendations
    raw_pids = request.GET.get('items', '').split(',')
    clean_pids = [p.strip() for p in raw_pids if p.strip()]
    recs = recommendations.get_cart_recommendations(clean_pids, limit=8)
    return JsonResponse({
        'ok': True,
        'recommendations': {
            'all': recs['you_may_also_like'],
            'you_may_also_like': recs['you_may_also_like'],
            'frequently_bought': recs['frequently_bought'],
            'complete_your_look': recs['complete_your_look'],
            'related': recs['related_products'],
            'popular': recs['popular_products'],
        }
    })


# --------------------------------------------------------------------------- #
# Customer Search & Instant Quick-Registration
# --------------------------------------------------------------------------- #

@require_GET
@staff_required
def pos_customer_search(request):
    """Search registered users and past customer orders for the POS customer selector."""
    q = request.GET.get('q', '').strip()
    customers = []
    seen = set()

    if q:
        # Search User model
        user_matches = User.objects.filter(
            Q(first_name__icontains=q) | Q(last_name__icontains=q) |
            Q(username__icontains=q) | Q(email__icontains=q) |
            Q(profile__phone__icontains=q)
        ).select_related('profile')[:15]

        for u in user_matches:
            name = u.get_full_name() or u.username
            phone = getattr(u.profile, 'phone', '') if hasattr(u, 'profile') else ''
            key = (name.lower(), phone)
            if key not in seen:
                seen.add(key)
                customers.append({
                    'id': u.pk,
                    'name': name,
                    'phone': phone,
                    'email': u.email,
                    'is_registered': True,
                })

        # Also search previous guest customers from Order
        order_matches = (Order.objects.filter(
            Q(customer_name__icontains=q) | Q(phone__icontains=q) | Q(email__icontains=q)
        ).exclude(customer_name__in=['Walk-in customer', ''])
        .values('customer_name', 'phone', 'email')
        .distinct()[:15])

        for o in order_matches:
            name = o['customer_name']
            phone = o['phone'] or ''
            key = (name.lower(), phone)
            if key not in seen:
                seen.add(key)
                customers.append({
                    'id': None,
                    'name': name,
                    'phone': phone,
                    'email': o['email'] or '',
                    'is_registered': False,
                })

    return JsonResponse({'customers': customers[:20]})


@require_POST
@staff_required
def pos_customer_create(request):
    """Create a new customer profile on the fly from the POS checkout screen without losing cart state."""
    try:
        payload = json.loads(request.body or '{}')
        name = str(payload.get('name') or '').strip()
        phone = str(payload.get('phone') or '').strip()
        email = str(payload.get('email') or '').strip().lower()

        if not name:
            return JsonResponse({'ok': False, 'error': 'Customer name is required.'}, status=400)
        if not phone:
            return JsonResponse({'ok': False, 'error': 'Customer phone number is required.'}, status=400)

        # Generate a unique username based on phone or name
        clean_phone = re.sub(r'\D', '', phone)
        base_username = f"cust_{clean_phone}" if clean_phone else (slugify(name)[:20] or 'customer')
        username = base_username
        n = 1
        while User.objects.filter(username=username).exists():
            username = f"{base_username}_{n}"
            n += 1

        parts = name.split(' ', 1)
        first_name = parts[0]
        last_name = parts[1] if len(parts) > 1 else ''

        user = User.objects.create(
            username=username,
            first_name=first_name,
            last_name=last_name,
            email=email,
            is_active=True,
            is_staff=False,
            is_superuser=False,
        )
        user.set_unusable_password()
        user.save()

        # Update or create UserProfile
        profile, _ = UserProfile.objects.get_or_create(user=user)
        profile.role = UserProfile.ROLE_CUSTOMER
        profile.status = UserProfile.STATUS_APPROVED
        profile.phone = phone
        profile.save()

        return JsonResponse({
            'ok': True,
            'customer': {
                'id': user.pk,
                'name': user.get_full_name() or user.username,
                'phone': phone,
                'email': user.email,
            }
        })
    except Exception as e:
        logger.exception('Failed to create customer in POS: %s', e)
        return JsonResponse({'ok': False, 'error': 'Could not create customer.'}, status=500)


# --------------------------------------------------------------------------- #
# Checkout & Sale Completion
# --------------------------------------------------------------------------- #

@require_POST
@staff_required
def pos_checkout(request):
    try:
        payload = json.loads(request.body or '{}')
        items = payload.get('items') or []
        method = str(payload.get('payment_method') or '').lower()
        discount = payload.get('discount') or 0
        cash = payload.get('cash_received')
        customer_id = payload.get('customer_id')
        bank_reference = payload.get('bank_reference') or ''
        card_reference = payload.get('card_reference') or ''
        tenders = payload.get('tenders') or None

        order, created = pos.create_pos_sale(
            user=request.user,
            items_payload=items,
            payment_method=method,
            discount=discount,
            cash_received=cash,
            phone=str(payload.get('phone') or ''),
            customer_name=str(payload.get('customer_name') or ''),
            customer_id=customer_id,
            token=str(payload.get('token') or ''),
            discount_authorised=has_role(request.user, 'Manager', 'Admin'),
            bank_reference=bank_reference,
            card_reference=card_reference,
            tenders_payload=tenders,
        )
    except PermissionError as e:
        return JsonResponse({'ok': False, 'error': str(e)}, status=403)
    except ValueError as e:
        return JsonResponse({'ok': False, 'error': str(e)}, status=400)
    except Exception:
        logger.exception('POS checkout failed')
        return JsonResponse({'ok': False, 'error': 'The sale could not be completed.'},
                            status=500)

    # The post-commit STK Push hook may already have cancelled or failed the
    # sale (e.g. Daraja rejected the prompt). Re-read so the terminal reflects
    # the real state instead of the pre-commit instance.
    order.refresh_from_db()
    state = pos.serialize_order_status(order)
    state['receipt_url'] = reverse('receipt', args=[order.number])
    state['pdf_receipt_url'] = reverse('receipt_pdf', args=[order.number])
    state['created'] = created
    state['pending_mpesa'] = order.payment_status in ('pending', 'processing')
    return JsonResponse({'ok': True, 'sale': state})


@require_GET
@staff_required
def pos_order_state(request, number):
    order = get_object_or_404(Order.objects.prefetch_related('payments',
                                                             'mpesa_transactions'),
                               number=number)
    state = pos.serialize_order_status(order)
    state['receipt_url'] = reverse('receipt', args=[order.number])
    state['pdf_receipt_url'] = reverse('receipt_pdf', args=[order.number])
    state['pending_mpesa'] = order.payment_status in ('pending', 'processing')
    return JsonResponse(state)


# --------------------------------------------------------------------------- #
# Standalone Customer Display Screen
# --------------------------------------------------------------------------- #

@staff_required
def pos_customer_display(request):
    """Dedicated standalone customer-facing display screen for secondary monitor/tablet."""
    settings = SiteSettings.get()
    return render(request, 'manage/pos_customer_display.html', {
        'site_settings': settings,
        'store_name': settings.store_name,
        'tagline': settings.tagline,
        'currency': settings.currency or 'KES',
    })


# --------------------------------------------------------------------------- #
# POS Shift & Operations Dashboard
# --------------------------------------------------------------------------- #

@staff_required
def pos_dashboard(request):
    """POS Operations & Shift Analytics Dashboard."""
    today = timezone.localdate()
    settings = SiteSettings.get()
    currency = settings.currency or 'KES'

    # Shift currently open for this cashier
    active_session = PosSession.objects.filter(user=request.user, status=PosSession.STATUS_OPEN).first()

    # POS orders for today
    pos_orders_today = Order.objects.filter(sales_channel='pos', created_at__date=today)
    paid_today = pos_orders_today.filter(payment_status='paid')

    today_sales = paid_today.aggregate(total=Sum('total'))['total'] or Decimal('0.00')
    today_count = paid_today.count()
    avg_basket = (today_sales / today_count) if today_count > 0 else Decimal('0.00')

    # Payment Breakdown today (including split payment tenders)
    cash_today = Decimal('0.00')
    mpesa_today = Decimal('0.00')
    card_today = Decimal('0.00')
    bank_today = Decimal('0.00')

    today_payments = Payment.objects.filter(order__in=paid_today, status='paid')
    for p in today_payments:
        if p.method == 'manual':
            cash_today += p.amount
        elif p.method == 'mpesa':
            mpesa_today += p.amount
        elif p.method == 'card':
            card_today += p.amount
        elif p.method == 'bank':
            bank_today += p.amount

    if not today_payments.exists() and paid_today.exists():
        cash_today = paid_today.filter(payment_method='cod').aggregate(t=Sum('total'))['t'] or Decimal('0.00')
        mpesa_today = paid_today.filter(payment_method='mpesa').aggregate(t=Sum('total'))['t'] or Decimal('0.00')
        card_today = paid_today.filter(payment_method='card').aggregate(t=Sum('total'))['t'] or Decimal('0.00')
        bank_today = paid_today.filter(payment_method='bank').aggregate(t=Sum('total'))['t'] or Decimal('0.00')

    # Top selling items at POS today
    top_items = (OrderItem.objects.filter(order__in=paid_today)
                 .values('product_name', 'product_sku')
                 .annotate(units_sold=Sum('quantity'), revenue=Sum('subtotal'))
                 .order_by('-units_sold')[:8])

    # Recent shifts
    recent_sessions = PosSession.objects.select_related('user').order_by('-opened_at')[:10]

    context = {
        'today': today,
        'currency': currency,
        'active_session': active_session,
        'today_sales': today_sales,
        'today_count': today_count,
        'avg_basket': avg_basket,
        'cash_today': cash_today,
        'mpesa_today': mpesa_today,
        'card_today': card_today,
        'bank_today': bank_today,
        'top_items': top_items,
        'recent_sessions': recent_sessions,
        'total_pos_orders': pos_orders_today.count(),
    }
    return render(request, 'manage/pos_dashboard.html', context)


# --------------------------------------------------------------------------- #
# Receipts (HTML & PDF)
# --------------------------------------------------------------------------- #

def receipt(request, number):
    order = get_object_or_404(Order.objects.select_related('served_by', 'pos_session')
                              .prefetch_related('items', 'payments'), number=number)
    if not _can_view_order(request, order):
        messages.error(request, 'Receipt not found or you do not have access to it.')
        return redirect('home')
    payment = order.payments.order_by('-created_at').first()
    response = render(request, 'receipt.html', {
        'order': order,
        'payment': payment,
    })
    if request.GET.get('download'):
        response['Content-Disposition'] = f'attachment; filename="receipt-{order.number}.html"'
    return response


def receipt_pdf(request, number):
    """Download or stream 80mm/58mm thermal receipt PDF generated via ReportLab."""
    order = get_object_or_404(
        Order.objects.select_related('served_by', 'pos_session')
        .prefetch_related('items', 'payments', 'mpesa_transactions'),
        number=number
    )
    if not _can_view_order(request, order):
        messages.error(request, 'Receipt not found or you do not have access to it.')
        return redirect('home')

    from .receipt_pdf import generate_receipt_pdf
    size = request.GET.get('size', '80')
    if size not in ('80', '58'):
        size = '80'
    buf = generate_receipt_pdf(order, size=size)

    disposition = 'attachment' if request.GET.get('download') else 'inline'
    response = HttpResponse(buf.getvalue(), content_type='application/pdf')
    response['Content-Disposition'] = f'{disposition}; filename="receipt-{order.number}.pdf"'
    return response
