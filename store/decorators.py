from functools import wraps

<<<<<<< HEAD
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect

# Role hierarchy used across the system, staff control center, and POS.
ROLE_SUPER_ADMIN = 'Super Admin'
ROLE_ADMIN = 'Admin'
ROLE_MANAGER = 'Manager'
ROLE_CASHIER = 'Cashier'
ROLE_CUSTOMER = 'Customer'

ROLE_LEVELS = {
    ROLE_CUSTOMER: 0,
    ROLE_CASHIER: 1,
    ROLE_MANAGER: 2,
    ROLE_ADMIN: 3,
    ROLE_SUPER_ADMIN: 4,
}


def user_role_level(user):
    """Highest role level held by a user (0 when none applies or not approved)."""
=======
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
>>>>>>> 0eaeef0d594c7530f656b8338be122ce644eab03
    if not getattr(user, 'is_authenticated', False):
        return 0
    if not user.is_active:
        return 0
<<<<<<< HEAD

    # UserProfile takes precedence
    profile = getattr(user, 'profile', None)
    if profile:
        if profile.status != 'approved':
            return 0
        if profile.role == 'super_admin' or user.is_superuser:
            return ROLE_LEVELS[ROLE_SUPER_ADMIN]
        if profile.role == 'admin':
            return ROLE_LEVELS[ROLE_ADMIN]
        if profile.role == 'cashier':
            return ROLE_LEVELS[ROLE_CASHIER]
        if profile.role == 'customer':
            return ROLE_LEVELS[ROLE_CUSTOMER]

    if user.is_superuser:
        return ROLE_LEVELS[ROLE_SUPER_ADMIN]

=======
    if user.is_superuser:
        return ROLE_LEVELS[ROLE_ADMIN]
>>>>>>> 0eaeef0d594c7530f656b8338be122ce644eab03
    groups = set(user.groups.values_list('name', flat=True))
    levels = [lvl for name, lvl in ROLE_LEVELS.items() if name in groups]
    if levels:
        return max(levels)
<<<<<<< HEAD

    # Legacy/backwards-compatible: ungrouped staff users keep Admin access.
=======
    # Legacy/backwards-compatible: ungrouped staff users keep full access.
>>>>>>> 0eaeef0d594c7530f656b8338be122ce644eab03
    if user.is_staff:
        return ROLE_LEVELS[ROLE_ADMIN]
    return 0


def has_role(user, *roles):
    """True when the user holds at least one of the given roles (or higher)."""
<<<<<<< HEAD
    normalized = []
    for r in roles:
        r_str = str(r).lower().replace('_', ' ')
        if r_str in ('super admin', 'superadmin'):
            normalized.append(ROLE_LEVELS[ROLE_SUPER_ADMIN])
        elif r_str == 'admin':
            normalized.append(ROLE_LEVELS[ROLE_ADMIN])
        elif r_str == 'manager':
            normalized.append(ROLE_LEVELS[ROLE_MANAGER])
        elif r_str == 'cashier':
            normalized.append(ROLE_LEVELS[ROLE_CASHIER])
        elif r in ROLE_LEVELS:
            normalized.append(ROLE_LEVELS[r])

    needed = min(normalized, default=None)
=======
    needed = min((ROLE_LEVELS[r] for r in roles if r in ROLE_LEVELS), default=None)
>>>>>>> 0eaeef0d594c7530f656b8338be122ce644eab03
    if needed is None:
        return False
    return user_role_level(user) >= needed


def role_required(*roles):
<<<<<<< HEAD
    """Require minimum role level. Unauthenticated users are redirected to login;
    authenticated users without the required role receive 403 Forbidden."""
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect(f'/account/login/?next={request.path}')
            if not has_role(request.user, *roles):
                raise PermissionDenied('You do not have permission to access this resource.')
=======
    def test(u):
        return has_role(u, *roles)
    def decorator(view_func):
        @wraps(view_func)
        @user_passes_test(test, login_url='/account/login/')
        def _wrapped(request, *args, **kwargs):
>>>>>>> 0eaeef0d594c7530f656b8338be122ce644eab03
            return view_func(request, *args, **kwargs)
        return _wrapped
    return decorator


<<<<<<< HEAD
def super_admin_required(view_func):
    """Strictly Super Admin only (e.g. account approvals, payment settings, audit logs)."""
    return role_required(ROLE_SUPER_ADMIN)(view_func)


def admin_required(view_func):
    """Admin or Super Admin (product, inventory, order, and standard operations)."""
    return role_required(ROLE_ADMIN, ROLE_SUPER_ADMIN)(view_func)


def manager_required(view_func):
    """Manager, Admin, or Super Admin."""
    return role_required(ROLE_MANAGER, ROLE_ADMIN, ROLE_SUPER_ADMIN)(view_func)


def staff_required(view_func):
    """Any approved staff member (Cashier, Manager, Admin, Super Admin)."""
    return role_required(ROLE_CASHIER, ROLE_MANAGER, ROLE_ADMIN, ROLE_SUPER_ADMIN)(view_func)


def cashier_required(view_func):
    """Any staff member who can run the till."""
    return staff_required(view_func)
=======
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
>>>>>>> 0eaeef0d594c7530f656b8338be122ce644eab03


def login_required_view(view_func):
    @wraps(view_func)
    @login_required(login_url='/account/login/')
    def _wrapped(request, *args, **kwargs):
<<<<<<< HEAD
        profile = getattr(request.user, 'profile', None)
        if profile and profile.status != 'approved':
            from django.contrib.auth import logout
            logout(request)
            return redirect('/account/login/')
=======
>>>>>>> 0eaeef0d594c7530f656b8338be122ce644eab03
        return view_func(request, *args, **kwargs)
    return _wrapped
