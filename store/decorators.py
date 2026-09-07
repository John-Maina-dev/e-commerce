from functools import wraps

from django.contrib.auth.decorators import login_required, user_passes_test
from django.shortcuts import redirect

# Role hierarchy used across the staff control center and the POS.
# Roles map to Django Groups so they can be assigned from the Django admin.
# A staff user who belongs to NO role group is treated as an Admin — this
# keeps every pre-existing staff account fully functional after upgrade.
ROLE_ADMIN = 'Admin'
ROLE_MANAGER = 'Manager'
ROLE_CASHIER = 'Cashier'

ROLE_LEVELS = {ROLE_CASHIER: 1, ROLE_MANAGER: 2, ROLE_ADMIN: 3}


def user_role_level(user):
    """Highest role level held by a staff user (0 when none applies)."""
    if not getattr(user, 'is_authenticated', False):
        return 0
    if not user.is_active:
        return 0
    if user.is_superuser:
        return ROLE_LEVELS[ROLE_ADMIN]
    groups = set(user.groups.values_list('name', flat=True))
    levels = [lvl for name, lvl in ROLE_LEVELS.items() if name in groups]
    if levels:
        return max(levels)
    # Legacy/backwards-compatible: ungrouped staff users keep full access.
    if user.is_staff:
        return ROLE_LEVELS[ROLE_ADMIN]
    return 0


def has_role(user, *roles):
    """True when the user holds at least one of the given roles (or higher)."""
    needed = min((ROLE_LEVELS[r] for r in roles if r in ROLE_LEVELS), default=None)
    if needed is None:
        return False
    return user_role_level(user) >= needed


def role_required(*roles):
    def test(u):
        return has_role(u, *roles)
    def decorator(view_func):
        @wraps(view_func)
        @user_passes_test(test, login_url='/account/login/')
        def _wrapped(request, *args, **kwargs):
            return view_func(request, *args, **kwargs)
        return _wrapped
    return decorator


def staff_required(view_func):
    """Any staff member (including Cashiers) may access."""
    @wraps(view_func)
    @user_passes_test(lambda u: u.is_active and u.is_staff, login_url='/account/login/')
    def _wrapped(request, *args, **kwargs):
        return view_func(request, *args, **kwargs)
    return _wrapped


def manager_required(view_func):
    """Manager or Admin only (product/stock/price-changing operations)."""
    return role_required(ROLE_MANAGER, ROLE_ADMIN)(view_func)


def login_required_view(view_func):
    @wraps(view_func)
    @login_required(login_url='/account/login/')
    def _wrapped(request, *args, **kwargs):
        return view_func(request, *args, **kwargs)
    return _wrapped
