# Reeves Boutique — Django E-Commerce

This package is the Django conversion and modernization of the uploaded Reeves Boutique project.

## Included
- Django + SQLite development setup
- Original 56 product catalogue preserved as `store/legacy_products.json`
- Product/category management through Django Admin
- Custom modern store management dashboard
- Low-stock/restock detection using per-product thresholds
- SMTP configuration UI and live test-email button
- M-Pesa Daraja STK Push configuration UI
- M-Pesa callback endpoint with transaction/order status updates
- Cart and checkout
- Order and inventory management
- Responsive modern storefront
- Media uploads and branding settings
- Customer accounts: register, login, wishlist, addresses, order history
- Staff management UI (control center) with analytics and system health
- 264 automated tests across models, services, views, checkout and M-Pesa callbacks

## Project root

This project runs directly from `C:\Users\ADMIN\OneDrive\Desktop\e-comerce`.
`manage.py`, the `.venv`, `config/`, `store/`, `templates/`, `static/`, and
`media/` all live at that root, so there is no nested `reeves_boutique_django`
folder to `cd` into.

## Quick start (Windows PowerShell)
```powershell
cd C:\Users\ADMIN\OneDrive\Desktop\e-comerce
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
python manage.py migrate
python manage.py seed_store
python manage.py createsuperuser
python manage.py runserver
```

If you have just pulled the repository for the first time, run the full sequence
above. On subsequent runs, once the virtual environment is active, just run:

```powershell
python manage.py migrate
python manage.py runserver
```

Open `http://127.0.0.1:8000/`.

Management dashboard: `/manage/` (staff only).
Advanced Django admin: `/django-admin/`.

## Running tests
```powershell
python manage.py test store
```

Tests run against a throwaway test database and do not require real SMTP or
M-Pesa credentials (external calls are short-circuited in the test environment).

## URLs
| Area | Path |
| --- | --- |
| Storefront | `/`, `/products/`, `/product/<slug>/`, `/cart/`, `/checkout/`, `/wishlist/` |
| Accounts | `/account/…` (login, register, dashboard, orders, addresses, password) |
| Control center | `/manage/` (staff only) |
| Payments | `/payments/mpesa/…` (STK push request + callback) |
| SEO | `/sitemap.xml`, `/robots.txt` |
| Admin | `/django-admin/` |

## SMTP
Sign in as a staff user and open **Manage → Settings**. Configure the SMTP host, port, username, password, TLS and From email, save, then use **Test SMTP**. The custom Django email backend reads the saved configuration, so Django email flows can use the UI settings without hardcoding credentials.

For Gmail, use an App Password rather than your normal Gmail password when 2-Step Verification is enabled.

If the in-app SMTP settings are left disabled, Django falls back to the `EMAIL_*` values in `.env`.

## M-Pesa STK Push
Open **Manage → Settings → M-Pesa Daraja STK Push**. Select Sandbox or Production and enter the Daraja credentials. The callback URL must be publicly reachable over HTTPS in production and should point to:

`/payments/mpesa/callback/`

The checkout uses server-side Daraja OAuth and STK Push requests. Safaricom's callback updates the transaction and order to `paid` only after a successful callback result.

Do not put live credentials in source control. Use HTTPS in production.

## Inventory intelligence
Each product has `stock` and `low_stock_threshold`. The management dashboard automatically lists active products at or below the threshold. Admins can edit stock/thresholds and add products through **Manage products** or Django Admin.

## Production
Set `DEBUG=False`, configure `ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS`, use PostgreSQL for production, configure HTTPS, run `collectstatic`, and store secrets in environment variables or a secure secrets manager.
