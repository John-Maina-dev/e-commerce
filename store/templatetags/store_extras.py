from django import template

register = template.Library()


@register.filter
def money(value, currency='KES'):
    try:
        return f'{currency} {value:,.0f}'
    except (TypeError, ValueError):
        return f'{currency} 0'


@register.filter
def stars(value):
    """Render a star row for a rating decimal 0-5. Returns a dict for template use."""
    try:
        value = float(value)
    except (TypeError, ValueError):
        value = 0.0
    full = int(round(value))
    empty = max(0, 5 - full)
    return {'full': range(full), 'empty': range(empty), 'value': value}


@register.simple_tag(takes_context=True)
def sort_url(context, column):
    """Return a query string for a sortable table header, toggling direction
    when the same column is clicked again and preserving other filters."""
    request = context['request']
    current = request.GET.get('sort', '')
    if current == column:
        next_sort = '-' + column
    elif current == '-' + column:
        next_sort = column
    else:
        next_sort = column
    params = request.GET.copy()
    params.pop('page', None)
    params['sort'] = next_sort
    return '?' + params.urlencode()


@register.filter
def status_class(value):
    mapping = {
        'pending': 'is-pending',
        'confirmed': 'is-confirmed',
        'processing': 'is-processing',
        'shipped': 'is-shipped',
        'delivered': 'is-delivered',
        'cancelled': 'is-cancelled',
        'refunded': 'is-refunded',
        'paid': 'is-delivered',
        'processing': 'is-processing',
        'success': 'is-delivered',
        'requires_review': 'is-low',
        'completed': 'is-delivered',
        'sent': 'is-low',
        'failed': 'is-cancelled',
        'timeout': 'is-pending',
        'low': 'is-low',
        'out': 'is-out',
        'healthy': 'is-healthy',
        'restock': 'is-healthy',
        'release': 'is-confirmed',
        'create': 'is-delivered',
        'threshold': 'is-processing',
        'desired': 'is-processing',
    }
    return mapping.get(str(value), 'is-pending')
