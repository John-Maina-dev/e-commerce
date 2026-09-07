"""Point-of-Sale interface views (staff area).

The cashier UI lives at /manage/pos/. Every money-affecting decision is made
here on the server via store.pos — the browser only describes intent.
"""
import json
import logging
from uuid import uuid4

from django.contrib import messages
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST

from . import pos, services
from .decorators import has_role, staff_required
from .models import Order, PosSession, SiteSettings
from .views import _can_view_order

logger = logging.getLogger('store')


# --------------------------------------------------------------------------- #
# Terminal
# --------------------------------------------------------------------------- #

@staff_required
def pos_terminal(request):
    session = PosSession.objects.filter(user=request.user,
                                        status=PosSession.STATUS_OPEN).first()
    context = {
        'session': session,
        'mpesa_ready': SiteSettings.get().mpesa_complete,
        'can_discount': has_role(request.user, 'Manager', 'Admin'),
    }
    return render(request, 'manage/pos.html', context)


@require_POST
@staff_required
def pos_session_open(request):
    try:
        from decimal import Decimal
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
        from decimal import Decimal, InvalidOperation
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
# JSON APIs used by the terminal
# --------------------------------------------------------------------------- #

@require_GET
@staff_required
def pos_search(request):
    results = pos.search_products(request.GET.get('q', ''))
    return JsonResponse({'results': [pos.serialize_product(p) for p in results]})


@require_POST
@staff_required
def pos_checkout(request):
    try:
        payload = json.loads(request.body or '{}')
        items = payload.get('items') or []
        method = str(payload.get('payment_method') or '').lower()
        discount = payload.get('discount') or 0
        cash = payload.get('cash_received')
        order, created = pos.create_pos_sale(
            user=request.user,
            items_payload=items,
            payment_method=method,
            discount=discount,
            cash_received=cash,
            phone=str(payload.get('phone') or ''),
            customer_name=str(payload.get('customer_name') or ''),
            token=str(payload.get('token') or ''),
            discount_authorised=has_role(request.user, 'Manager', 'Admin'),
        )
    except PermissionError as e:
        return JsonResponse({'ok': False, 'error': str(e)}, status=403)
    except ValueError as e:
        return JsonResponse({'ok': False, 'error': str(e)}, status=400)
    except Exception:
        logger.exception('POS checkout failed')
        return JsonResponse({'ok': False, 'error': 'The sale could not be completed.'},
                            status=500)

    state = pos.serialize_order_status(order)
    state['receipt_url'] = reverse('receipt', args=[order.number])
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
    state['pending_mpesa'] = order.payment_status in ('pending', 'processing')
    return JsonResponse(state)


# --------------------------------------------------------------------------- #
# Receipt (shared by POS + online orders)
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
