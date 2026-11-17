from django.contrib.auth import views as auth_views
from django.urls import path

from . import manage_views, pos_views, views

# --------------------------------------------------------------------------- #
# Storefront
# --------------------------------------------------------------------------- #
storefront = [
    path('', views.home, name='home'),
    path('products/', views.catalogue, name='catalogue'),
    path('search/suggestions/', views.search_suggestions, name='search_suggestions'),
    path('products/<slug:slug>/', views.product_detail, name='product_detail'),
    path('cart/', views.cart, name='cart'),
    path('cart/add/<int:pk>/', views.cart_add, name='cart_add'),
    path('cart/update/<int:pk>/', views.cart_update, name='cart_update'),
    path('cart/remove/<int:pk>/', views.cart_remove, name='cart_remove'),
    path('cart/clear/', views.cart_clear, name='cart_clear'),
    path('cart/coupon/', views.cart_apply_coupon, name='cart_apply_coupon'),
    path('cart/coupon/remove/', views.cart_remove_coupon, name='cart_remove_coupon'),
    path('checkout/', views.checkout, name='checkout'),
    path('orders/<str:number>/', views.order_detail, name='order_detail'),
    path('orders/<str:number>/pay/', views.order_retry_payment, name='order_retry_payment'),
    path('orders/<str:number>/pay/mpesa-manual/', views.mpesa_manual, name='mpesa_manual'),
    path('orders/<str:number>/pay/mpesa-manual/submit/', views.mpesa_manual_submit,
         name='mpesa_manual_submit'),
    path('orders/<str:number>/status/', views.order_status_json, name='order_status_json'),
    path('wishlist/', views.wishlist, name='wishlist'),
    path('wishlist/toggle/<int:pk>/', views.wishlist_toggle, name='wishlist_toggle'),
    path('wishlist/move/<int:pk>/', views.wishlist_move_to_cart, name='wishlist_move_to_cart'),
    path('contact/', views.contact, name='contact'),
    path('newsletter/', views.newsletter, name='newsletter'),
    path('newsletter/unsubscribe/<str:token>/', views.newsletter_unsubscribe, name='newsletter_unsubscribe'),
    path('payments/mpesa/callback/', views.mpesa_callback, name='mpesa_callback'),
    path('receipt/<str:number>/', pos_views.receipt, name='receipt'),
    path('receipt/<str:number>/pdf/', pos_views.receipt_pdf, name='receipt_pdf'),
]

# --------------------------------------------------------------------------- #
# Customer account
# --------------------------------------------------------------------------- #
account = [
    path('account/register/', views.register, name='register'),
    path('account/pending-approval/', views.pending_approval, name='pending_approval'),
    path('account/login/', views.login_view, name='login'),
    path('account/logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('account/', views.account, name='account'),
    path('account/orders/', views.account_orders, name='account_orders'),
    path('account/orders/<str:number>/', views.account_order_detail, name='account_order_detail'),
    path('account/profile/', views.account_profile, name='account_profile'),
    path('account/subscription/', views.account_subscription, name='account_subscription'),
    path('account/addresses/', views.account_addresses, name='account_addresses'),
    path('account/notifications/', views.account_notifications, name='account_notifications'),
    path('account/notifications/clear/', views.account_notifications_clear, name='account_notifications_clear'),
    path('account/notifications/<int:pk>/read/', views.account_notification_read, name='account_notification_read'),
    path('account/addresses/add/', views.address_add, name='address_add'),
    path('account/addresses/<int:pk>/edit/', views.address_edit, name='address_edit'),
    path('account/addresses/<int:pk>/delete/', views.address_delete, name='address_delete'),
    path('account/password-change/', auth_views.PasswordChangeView.as_view(
        template_name='account/password_change.html', success_url='/account/password-change/done/'),
        name='password_change'),
    path('account/password-change/done/', auth_views.PasswordChangeDoneView.as_view(
        template_name='account/password_change_done.html'), name='password_change_done'),
    path('account/password-reset/', views.StorePasswordResetView.as_view(), name='password_reset'),
    path('account/password-reset/done/', auth_views.PasswordResetDoneView.as_view(
        template_name='account/password_reset_done.html'), name='password_reset_done'),
    path('account/reset/<uidb64>/<token>/', views.StorePasswordResetConfirmView.as_view(),
         name='password_reset_confirm'),
    path('account/reset/done/', auth_views.PasswordResetCompleteView.as_view(
        template_name='account/password_reset_complete.html'), name='password_reset_complete'),
]

# --------------------------------------------------------------------------- #
# Point of sale (staff)
# --------------------------------------------------------------------------- #
pos = [
    path('manage/pos/', pos_views.pos_terminal, name='pos_terminal'),
    path('manage/pos/dashboard/', pos_views.pos_dashboard, name='pos_dashboard'),
    path('manage/pos/session/open/', pos_views.pos_session_open, name='pos_session_open'),
    path('manage/pos/session/close/', pos_views.pos_session_close, name='pos_session_close'),
    path('manage/pos/scan/', pos_views.pos_barcode_scan, name='pos_barcode_scan'),
    path('manage/pos/search/', pos_views.pos_search, name='pos_search'),
    path('manage/pos/catalogue/', pos_views.pos_catalogue, name='pos_catalogue'),
    path('manage/pos/recommendations/', pos_views.pos_recommendations, name='pos_recommendations'),
    path('manage/pos/customers/search/', pos_views.pos_customer_search, name='pos_customer_search'),
    path('manage/pos/customers/create/', pos_views.pos_customer_create, name='pos_customer_create'),
    path('manage/pos/customer-display/', pos_views.pos_customer_display, name='pos_customer_display'),
    path('manage/pos/checkout/', pos_views.pos_checkout, name='pos_checkout'),
    path('manage/pos/orders/<str:number>/state/', pos_views.pos_order_state, name='pos_order_state'),
]

# --------------------------------------------------------------------------- #
# Management (staff)
# --------------------------------------------------------------------------- #
manage = [
    path('manage/', manage_views.dashboard, name='dashboard'),
    path('manage/notifications/clear/', manage_views.notifications_clear, name='notifications_clear'),
    path('manage/notifications/', manage_views.manage_notifications, name='manage_notifications'),

    path('manage/products/', manage_views.manage_products, name='manage_products'),
    path('manage/products/add/', manage_views.product_add, name='product_add'),
    path('manage/products/bulk/', manage_views.product_bulk_action, name='product_bulk_action'),
    path('manage/products/<int:pk>/edit/', manage_views.product_edit, name='product_edit'),
    path('manage/products/<int:pk>/action/', manage_views.product_action, name='product_action'),
    path('manage/products/<int:pk>/delete/', manage_views.product_delete, name='product_delete'),

    path('manage/categories/', manage_views.manage_categories, name='manage_categories'),
    path('manage/categories/add/', manage_views.category_add, name='category_add'),
    path('manage/categories/<int:pk>/edit/', manage_views.category_edit, name='category_edit'),
    path('manage/categories/<int:pk>/delete/', manage_views.category_delete, name='category_delete'),

    path('manage/inventory/', manage_views.inventory, name='inventory'),
    path('manage/inventory/update/', manage_views.inventory_update, name='inventory_update'),
    path('manage/inventory/history/', manage_views.inventory_history, name='inventory_history'),
    path('manage/inventory/alerts/<int:pk>/resolve/', manage_views.inventory_alert_resolve, name='inventory_alert_resolve'),

    path('manage/orders/', manage_views.manage_orders, name='manage_orders'),
    path('manage/orders/<str:number>/', manage_views.manage_order_detail, name='manage_order_detail'),
    path('manage/orders/<str:number>/status/', manage_views.order_status_update, name='order_status_update'),
    path('manage/orders/<str:number>/return/', manage_views.order_return_item, name='order_return_item'),

    path('manage/customers/', manage_views.manage_customers, name='manage_customers'),
    path('manage/subscribers/', manage_views.manage_subscribers, name='manage_subscribers'),
    path('manage/subscribers/export/', manage_views.subscribers_export_csv, name='subscribers_export_csv'),
    path('manage/subscribers/broadcast/', manage_views.subscribers_broadcast, name='subscribers_broadcast'),
    path('manage/subscribers/<int:pk>/delete/', manage_views.subscriber_delete, name='subscriber_delete'),
    path('manage/accounts/', manage_views.manage_accounts, name='manage_accounts'),
    path('manage/accounts/<int:pk>/action/', manage_views.account_action, name='account_action'),
    path('manage/accounts/<int:pk>/role/', manage_views.account_role_update, name='account_role_update'),
    path('manage/accounts/<int:pk>/delete/', manage_views.account_delete, name='account_delete'),
    path('manage/accounts/audit-logs/', manage_views.account_audit_logs, name='account_audit_logs'),
    path('manage/reviews/', manage_views.manage_reviews, name='manage_reviews'),
    path('manage/reviews/<int:pk>/action/', manage_views.review_action, name='review_action'),

    path('manage/coupons/', manage_views.manage_coupons, name='manage_coupons'),
    path('manage/coupons/add/', manage_views.coupon_add, name='coupon_add'),
    path('manage/coupons/<int:pk>/edit/', manage_views.coupon_edit, name='coupon_edit'),
    path('manage/coupons/<int:pk>/delete/', manage_views.coupon_delete, name='coupon_delete'),

    path('manage/payments/', manage_views.manage_payments, name='manage_payments'),
    path('manage/payments/<int:pk>/', manage_views.manage_payment_detail, name='manage_payment_detail'),
    path('manage/payments/<int:pk>/action/', manage_views.payment_action, name='payment_action'),

    path('manage/settings/', manage_views.manage_settings, name='manage_settings'),
    path('manage/settings/email/', manage_views.manage_email_settings, name='manage_email_settings'),
    path('manage/settings/email/test/', manage_views.test_email, name='test_email'),
    path('manage/settings/payments/', manage_views.manage_payment_settings, name='manage_payment_settings'),
    path('manage/settings/payments/test/', manage_views.test_mpesa, name='test_mpesa'),
    path('manage/data/', manage_views.manage_data, name='manage_data'),
    path('manage/data/<str:data_type>/delete/', manage_views.manage_data_delete, name='manage_data_delete'),

    path('manage/analytics/', manage_views.manage_analytics, name='manage_analytics'),
    path('manage/system-health/', manage_views.system_health, name='system_health'),
]

urlpatterns = storefront + account + pos + manage
