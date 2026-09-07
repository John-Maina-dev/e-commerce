# Reeves Boutique — Functionality Summary Report

Date: 2026-08-07
Stack: Django 5.2.17 · Python 3.14.6 · SQLite (dev) · whitenoise · requests

## 1. Status

- `manage.py check` — clean (0 issues)
- `manage.py makemigrations --check --dry-run` — no changes detected
- `manage.py test store` — **59 tests, all passing**
- `collectstatic --noinput` — works in both dev (plain storage) and production (manifest storage, 387 files post-processed)
- `seed_store` — 56 products + 7 categories seeded
- Live `runserver` smoke test — storefront, catalogue, product detail, cart, wishlist, contact, login, sitemap.xml, robots.txt all respond 200; auth-gated routes redirect correctly
- Test suite runs against a throwaway DB with no real SMTP/M-Pesa credentials

## 2. Storefront

- Home page, product catalogue with search (`?q=`), sort (bestseller / newest / price), pagination, and category filters
- Product detail page: gallery, price with discounts, stock status, rating + reviews, related products
- Cart: add/update/remove, quantity capped at stock, stock-out guard, coupon codes (percent / fixed, min order, per-user limits, usage tracking)
- Checkout: guest or account checkout, address capture, COB/M-Pesa payment methods, order summary with discount/shipping/tax
- Order confirmation page, order lookup by number, email notifications (queued when SMTP configured)
- Wishlist: toggle, move to cart
- Contact form with auto-reply email
- Newsletter subscribe
- SEO: `sitemap.xml`, `robots.txt`, canonical URLs, meta descriptions, Open Graph tags
- Dark mode toggle (localStorage) + responsive layout

## 3. Customer accounts

- Register, login, logout, password change/reset (email-based flow)
- Dashboard, order history + per-order detail, profile edit, address book (multi-address CRUD, set default)
- Wishlist tied to account
- Orders link orders to the logged-in user; guest orders reachable via number

## 4. Staff control center (`/manage/`, staff-only)

- Dashboard with KPIs (sales, orders, revenue, low-stock counts), charts, recent orders
- Products CRUD, inventory management (stock, low-stock threshold, restock flag), categories CRUD
- Orders list + detail with status workflow (pending → processing → shipped → delivered; cancel/refund with automatic stock restock guarded against double-release)
- Customers list, reviews moderation, coupons CRUD
- Payments view (transactions + M-Pesa status)
- Settings: branding (store name, logo, colors, currency), shipping/tax rules, SMTP configuration with Test SMTP button, M-Pesa Daraja STK Push configuration
- Analytics and system health pages

## 5. SMTP configuration UI

- SMTP host/port/user/password/TLS/From-email configurable via Manage → Settings, saved to DB
- Custom email backend (`store/email_backend.py`) reads the saved configuration
- Test SMTP button; `EMAIL_*` env vars used as fallback when in-app SMTP is disabled
- Transactional templates for welcome, order confirmation, payment success/failed, order status, contact (HTML + plain-text)

## 6. M-Pesa Daraja STK Push

- Server-side OAuth token + STK Push request via `requests` (sandbox/production switchable)
- Callback endpoint `/payments/mpesa/callback/` validates and updates transaction + order status to paid; idempotent (duplicate callbacks ignored)
- Failed callbacks record failure on the transaction
- Sandbox-tested only; live payments require real Daraja credentials + HTTPS reachable callback URL

## 7. Security

- `@staff_required` decorator + `login_required` on all restricted views
- CSRF enabled, content-type parsing limited, HTML-escaped output, Decimal for all money
- Production hardening settings (`SECURE_SSL_REDIRECT`, secure cookies) toggled when `DEBUG=False`
- Secrets (SMTP/M-Pesa) stored in DB settings, not in source control; `.env.example` provided
- Custom 400/403/404/500 error templates

## 8. Known limitations / notes

- Live M-Pesa and SMTP deliveries were NOT exercised against real credentials — external integration is verified via tests/mocking only
- Cart and wishlist counts are session-based (guest) / user-based (account) — no persistent cart merge between guest and account
- `store/legacy_products.json` preserves the original 56-product catalogue for re-seeding

## 9. Files of note

- `config/settings.py` — TESTING flag + environment-driven static storage backend
- `store/services.py` — cart/coupon/order/release-stock logic
- `store/mpesa.py`, `store/email_backend.py` — integrations
- `store/manage_views.py` — staff control center
- `store/tests/` — 59 tests across models/services/views
- `static/store.css` + `static/store.js` — styling and interactions
- `templates/` — storefront, account, manage, errors, email templates
