from django.contrib import admin
from django.utils.html import format_html

from .models import (Address, Category, ContactMessage, Coupon, CouponUsage, InventoryAlert,
                     InventoryChange, MpesaTransaction, NewsletterSubscriber, Notification, Order,
                     OrderItem, OrderReturn, OrderStatusHistory, Payment, PosSession, Product,
                     ProductImage, Review, SiteSettings, WishlistItem)

admin.site.site_header = 'Reeves Boutique Administration'
admin.site.site_title = 'Reeves Boutique'
admin.site.index_title = 'Store Control Center'


class ProductImageInline(admin.TabularInline):
    model = ProductImage
    extra = 1


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ('thumb', 'name', 'sku', 'barcode', 'category', 'price', 'stock', 'stock_badge',
                    'low_stock_threshold', 'featured', 'active', 'updated_at')
    list_filter = ('category', 'active', 'featured', 'is_new', 'is_bestseller')
    search_fields = ('name', 'sku', 'barcode', 'brand', 'description')
    prepopulated_fields = {'slug': ('name',)}
    list_select_related = ('category',)
    inlines = [ProductImageInline]
    readonly_fields = ('created_at', 'updated_at', 'sales_count')
    fieldsets = (
        (None, {'fields': ('name', 'slug', 'sku', 'barcode', 'category', 'brand')}),
        ('Pricing', {'fields': ('price', 'sale_price', 'old_price', 'cost_price')}),
        ('Description', {'fields': ('short_description', 'description')}),
        ('Inventory', {'fields': ('stock', 'low_stock_threshold', 'desired_stock_level', 'sales_count')}),
        ('Status', {'fields': ('active', 'featured', 'is_new', 'is_bestseller')}),
        ('Media', {'fields': ('image', 'image_url')}),
        ('Rating cache', {'fields': ('rating', 'reviews_count')}),
        ('Timestamps', {'fields': ('created_at', 'updated_at')}),
    )

    @admin.display(description='')
    def thumb(self, obj):
        if obj.image_src:
            return format_html('<img src="{}" style="height:40px;width:40px;object-fit:cover;border-radius:8px">', obj.image_src)
        return '—'

    @admin.display(description='Stock')
    def stock_badge(self, obj):
        if obj.stock <= 0:
            return format_html('<span style="color:#b91c1c;font-weight:700">Out</span>')
        if obj.stock <= obj.low_stock_threshold:
            return format_html('<span style="color:#b45309;font-weight:700">Low ({})</span>', obj.stock)
        return str(obj.stock)


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'active', 'created_at')
    list_filter = ('active',)
    search_fields = ('name',)
    prepopulated_fields = {'slug': ('name',)}


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ('number', 'customer_name', 'phone', 'sales_channel', 'total', 'status', 'payment_status', 'payment_method', 'created_at')
    list_filter = ('status', 'payment_status', 'payment_method', 'sales_channel')
    search_fields = ('number', 'customer_name', 'phone', 'email')
    readonly_fields = ('number', 'subtotal', 'discount', 'shipping', 'tax', 'total', 'created_at', 'updated_at')
    list_select_related = ('user', 'served_by')


@admin.register(PosSession)
class PosSessionAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'user', 'status', 'opening_cash', 'closing_cash', 'opened_at', 'closed_at')
    list_filter = ('status', 'user')
    search_fields = ('user__username', 'notes')
    list_select_related = ('user',)
    readonly_fields = ('opened_at', 'closed_at', 'updated_at')


@admin.register(OrderItem)
class OrderItemAdmin(admin.ModelAdmin):
    list_display = ('order', 'product_name', 'quantity', 'price', 'unit_cost', 'subtotal')
    search_fields = ('order__number', 'product_name')
    autocomplete_fields = ('product',)


@admin.register(OrderStatusHistory)
class OrderStatusHistoryAdmin(admin.ModelAdmin):
    list_display = ('order', 'status', 'note', 'created_by', 'created_at')
    list_filter = ('status',)


@admin.register(OrderReturn)
class OrderReturnAdmin(admin.ModelAdmin):
    list_display = ('order', 'item', 'quantity', 'refunded_amount', 'restocked',
                    'processed_by', 'created_at')
    list_filter = ('restocked',)
    search_fields = ('order__number', 'item__product_name', 'reason')
    readonly_fields = ('created_at',)


@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = ('product', 'user', 'rating', 'active', 'verified_purchase', 'created_at')
    list_filter = ('active', 'rating', 'verified_purchase')
    search_fields = ('product__name', 'comment', 'name')
    actions = ['approve_reviews']

    @admin.action(description='Approve selected reviews')
    def approve_reviews(self, request, queryset):
        for review in queryset:
            review.active = True
            review.save(update_fields=['active'])
        self.message_user(request, f'{queryset.count()} review(s) approved.')


@admin.register(WishlistItem)
class WishlistItemAdmin(admin.ModelAdmin):
    list_display = ('user', 'product', 'created_at')
    search_fields = ('user__username', 'product__name')


@admin.register(Coupon)
class CouponAdmin(admin.ModelAdmin):
    list_display = ('code', 'discount_type', 'value', 'min_order_amount', 'used_count', 'max_uses', 'active', 'valid_until')
    list_filter = ('active', 'discount_type')
    search_fields = ('code',)


@admin.register(CouponUsage)
class CouponUsageAdmin(admin.ModelAdmin):
    list_display = ('coupon', 'user', 'order', 'used_at')
    search_fields = ('coupon__code',)


@admin.register(Address)
class AddressAdmin(admin.ModelAdmin):
    list_display = ('user', 'full_name', 'city', 'is_default')
    search_fields = ('user__username', 'full_name', 'city')


@admin.register(MpesaTransaction)
class MpesaTransactionAdmin(admin.ModelAdmin):
    list_display = ('transaction_id', 'order', 'phone', 'amount', 'status', 'checkout_request_id', 'mpesa_receipt', 'created_at')
    list_filter = ('status',)
    search_fields = ('transaction_id', 'checkout_request_id', 'mpesa_receipt', 'phone')
    readonly_fields = ('transaction_id', 'created_at', 'updated_at')


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ('order', 'method', 'status', 'verification', 'reference', 'amount',
                    'verified_by', 'created_at')
    list_filter = ('method', 'status', 'verification')
    search_fields = ('order__number', 'reference', 'transaction_id', 'phone')
    list_select_related = ('order', 'verified_by')
    readonly_fields = ('created_at', 'updated_at')
    fieldsets = (
        (None, {'fields': ('order', 'method', 'status', 'amount')}),
        ('Gateway', {'fields': ('reference', 'transaction_id', 'result_code', 'result_description')}),
        ('Verification', {'fields': ('verification', 'verified_by', 'verified_at', 'action_note')}),
        ('Contact', {'fields': ('phone',)}),
    )


@admin.register(NewsletterSubscriber)
class NewsletterSubscriberAdmin(admin.ModelAdmin):
    list_display = ('email', 'active', 'subscribed_at')
    list_filter = ('active',)


@admin.register(ContactMessage)
class ContactMessageAdmin(admin.ModelAdmin):
    list_display = ('name', 'email', 'subject', 'handled', 'created_at')
    list_filter = ('handled',)


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ('title', 'for_staff', 'read', 'created_at')
    list_filter = ('read', 'for_staff')


@admin.register(InventoryAlert)
class InventoryAlertAdmin(admin.ModelAdmin):
    list_display = ('product', 'alert_type', 'stock_at_alert', 'is_resolved', 'created_at')
    list_filter = ('alert_type', 'is_resolved')
    search_fields = ('product__name', 'product__sku')
    list_select_related = ('product',)
    readonly_fields = ('created_at', 'updated_at')


@admin.register(InventoryChange)
class InventoryChangeAdmin(admin.ModelAdmin):
    list_display = ('product', 'action', 'change', 'old_qty', 'new_qty', 'user', 'created_at')
    list_filter = ('action',)
    search_fields = ('product__name', 'product__sku', 'note')
    list_select_related = ('product', 'user')
    readonly_fields = ('created_at',)


@admin.register(SiteSettings)
class SiteSettingsAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return not SiteSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False

    # Credentials are managed through the store's Manage → Settings pages.
    # In Django admin they are shown as masked, read-only placeholders so a
    # plaintext secret is never rendered back into a page.
    def _masked(self, value):
        return '********' if value else '— not configured —'

    def smtp_password_masked(self, obj):
        return self._masked(obj.smtp_password)
    smtp_password_masked.short_description = 'SMTP password'

    def mpesa_consumer_key_masked(self, obj):
        return self._masked(obj.mpesa_consumer_key)
    mpesa_consumer_key_masked.short_description = 'M-Pesa consumer key'

    def mpesa_consumer_secret_masked(self, obj):
        return self._masked(obj.mpesa_consumer_secret)
    mpesa_consumer_secret_masked.short_description = 'M-Pesa consumer secret'

    def mpesa_passkey_masked(self, obj):
        return self._masked(obj.mpesa_passkey)
    mpesa_passkey_masked.short_description = 'M-Pesa passkey'

    readonly_fields = (
        'smtp_password_masked', 'mpesa_consumer_key_masked',
        'mpesa_consumer_secret_masked', 'mpesa_passkey_masked',
    )

    fieldsets = (
        ('Branding', {'fields': ('store_name', 'tagline', 'description', 'logo', 'favicon', 'banner',
                                 'announcement', 'primary_color', 'currency', 'phone', 'contact_email',
                                 'address', 'footer_text', 'hero_title', 'hero_subtitle',
                                 'social_facebook', 'social_instagram', 'social_twitter', 'social_whatsapp')}),
        ('Inventory defaults', {'fields': ('low_stock_default', 'desired_stock_level',
                                           'inventory_alert_email', 'restock_lookback_days',
                                           'restock_lead_time_days', 'restock_min_sales_orders')}),
        ('Shipping & tax', {'fields': ('shipping_enabled', 'flat_rate', 'free_shipping_threshold',
                                       'tax_enabled', 'tax_rate', 'inventory_strategy')}),
        ('SMTP / Email', {'fields': ('smtp_enabled', 'smtp_host', 'smtp_port', 'smtp_username',
                                     'smtp_password_masked', 'smtp_use_tls', 'smtp_use_ssl',
                                     'smtp_from_email', 'smtp_sender_name',
                                     'password_reset_timeout_seconds')}),
        ('M-Pesa STK Push', {'fields': ('mpesa_enabled', 'mpesa_environment', 'mpesa_consumer_key_masked',
                                        'mpesa_consumer_secret_masked', 'mpesa_shortcode',
                                        'mpesa_passkey_masked', 'mpesa_callback_url',
                                        'mpesa_account_reference', 'mpesa_transaction_desc')}),
    )
