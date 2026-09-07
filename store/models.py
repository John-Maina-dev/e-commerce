from datetime import timedelta
from decimal import Decimal, ROUND_UP

from django.conf import settings
from django.contrib.auth.models import User
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone
from django.utils.text import slugify

MONEY = {'max_digits': 12, 'decimal_places': 2}


class Category(models.Model):
    name = models.CharField(max_length=120, unique=True)
    slug = models.SlugField(unique=True, blank=True)
    description = models.TextField(blank=True)
    image = models.ImageField(upload_to='categories/', blank=True, null=True)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name

    class Meta:
        verbose_name_plural = 'Categories'
        ordering = ['name']


class ProductQuerySet(models.QuerySet):
    """Queryset for the storefront. The database is the single source of truth:
    a product is only visible when active, not hidden and not archived."""

    def visible(self):
        return self.filter(active=True, hidden=False, is_archived=False)

    def in_stock(self):
        return self.filter(stock__gt=0)


class Product(models.Model):
    STATUS_HEALTHY = 'healthy'
    STATUS_LOW = 'low'
    STATUS_OUT = 'out'

    objects = ProductQuerySet.as_manager()

    name = models.CharField(max_length=220)
    slug = models.SlugField(unique=True, blank=True)
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name='products')
    brand = models.CharField(max_length=120, blank=True)
    sku = models.CharField(max_length=80, unique=True)
    barcode = models.CharField(max_length=64, blank=True, null=True, unique=True,
                               help_text='Barcode/EAN for POS scanning. Leave blank to omit.')
    cost_price = models.DecimalField(**MONEY, default=Decimal('0.00'),
                                     help_text='Unit cost of the product, used for margin/COGS reporting.')
    short_description = models.CharField(max_length=300, blank=True)
    description = models.TextField(blank=True)
    price = models.DecimalField(**MONEY)
    sale_price = models.DecimalField(**MONEY, null=True, blank=True)
    old_price = models.DecimalField(**MONEY, null=True, blank=True)
    stock = models.PositiveIntegerField(default=0)
    low_stock_threshold = models.PositiveIntegerField(default=5)
    desired_stock_level = models.PositiveIntegerField(default=10)
    sales_count = models.PositiveIntegerField(default=0, editable=False,
                                              help_text='Net units sold across all channels (kept in sync automatically).')
    active = models.BooleanField(default=True)
    hidden = models.BooleanField(default=False)
    is_archived = models.BooleanField(default=False)
    featured = models.BooleanField(default=False)
    is_new = models.BooleanField(default=False)
    is_bestseller = models.BooleanField(default=False)
    image = models.ImageField(upload_to='products/', blank=True, null=True)
    image_url = models.URLField(blank=True)
    rating = models.DecimalField(max_digits=3, decimal_places=1, default=Decimal('0.0'),
                                 validators=[MinValueValidator(0), MaxValueValidator(5)])
    reviews_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        if not self.barcode:
            # Never store empty strings: the barcode column is unique and must
            # only hold real barcodes (multiple NULLs are allowed).
            self.barcode = None
        if not self.slug:
            base = slugify(self.name) or 'product'
            slug = base
            n = 1
            while Product.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                n += 1
                slug = f'{base}-{n}'
            self.slug = slug
        if not self.short_description and self.description:
            self.short_description = self.description[:297]
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name

    @property
    def effective_price(self):
        return self.sale_price if self.sale_price is not None else self.price

    @property
    def has_discount(self):
        return self.sale_price is not None and self.sale_price < self.price

    @property
    def discount_percent(self):
        if self.has_discount and self.price:
            return int(round((self.price - self.sale_price) / self.price * 100))
        return 0

    @property
    def image_src(self):
        return self.image.url if self.image else self.image_url

    @property
    def stock_status(self):
        if self.stock <= 0:
            return self.STATUS_OUT
        if self.stock <= self.low_stock_threshold:
            return self.STATUS_LOW
        return self.STATUS_HEALTHY

    @property
    def out_of_stock(self):
        return self.stock <= 0

    @property
    def is_visible(self):
        return self.active and not self.hidden and not self.is_archived

    @property
    def low_stock(self):
        return 0 < self.stock <= self.low_stock_threshold

    @property
    def needs_restock(self):
        return self.stock <= self.low_stock_threshold

    @property
    def recommended_restock_qty(self):
        predicted = self.sales_based_restock_recommendation
        if predicted is not None:
            return predicted
        return max(0, self.desired_stock_level - self.stock)

    @property
    def restock_recommendation_source(self):
        """Where the restock recommendation comes from: 'sales' when enough
        historical sales exist, otherwise 'desired' (the admin's target)."""
        return 'sales' if self.sales_based_restock_recommendation is not None else 'desired'

    @property
    def sales_based_restock_recommendation(self):
        """Predictive restock qty from recent sales, or None when there is not
        enough historical data (we never fake intelligence from sparse data)."""
        s = SiteSettings.get()
        lookback = max(int(s.restock_lookback_days or 30), 1)
        since = timezone.now() - timedelta(days=lookback)
        items = self.order_items.filter(order__created_at__gte=since,
                                        order__status__in=Order.PAID_STATUSES)
        distinct_orders = items.values('order_id').distinct().count()
        total_units = items.aggregate(u=models.Sum('quantity'))['u'] or 0
        if distinct_orders < max(int(s.restock_min_sales_orders or 0), 1) or total_units <= 0:
            return None
        lead_time = max(int(s.restock_lead_time_days or 0), 1)
        daily_rate = Decimal(total_units) / Decimal(lookback)
        projected = daily_rate * Decimal(lead_time)
        rounded = int(projected.to_integral_value(rounding=ROUND_UP))
        return max(0, rounded - self.stock)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['active', 'featured']),
            models.Index(fields=['active', 'hidden', 'is_archived']),
            models.Index(fields=['active', 'hidden', 'is_archived', '-created_at']),
            models.Index(fields=['brand']),
            models.Index(fields=['stock']),
        ]


class InventoryAlert(models.Model):
    TYPE_LOW = 'low'
    TYPE_OUT = 'out'
    TYPE_CHOICES = [(TYPE_LOW, 'Low stock'), (TYPE_OUT, 'Out of stock')]

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='inventory_alerts')
    alert_type = models.CharField(max_length=10, choices=TYPE_CHOICES, default=TYPE_LOW)
    message = models.CharField(max_length=300, blank=True, default='')
    stock_at_alert = models.PositiveIntegerField(default=0)
    is_resolved = models.BooleanField(default=False)
    resolved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['is_resolved', '-created_at']
        indexes = [models.Index(fields=['is_resolved', 'alert_type'])]
        verbose_name = 'Inventory alert'
        verbose_name_plural = 'Inventory alerts'

    def __str__(self):
        return f'{self.get_alert_type_display()} · {self.product.name}'


class InventoryChange(models.Model):
    ACTION_CHOICES = [
        ('create', 'Created'),
        ('sale', 'Sold'),
        ('restock', 'Restocked'),
        ('adjust', 'Adjusted'),
        ('release', 'Stock released'),
        ('return', 'Customer return'),
        ('threshold', 'Threshold changed'),
        ('desired', 'Desired level changed'),
    ]

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='inventory_changes')
    action = models.CharField(max_length=20, choices=ACTION_CHOICES, default='adjust')
    old_qty = models.PositiveIntegerField(null=True, blank=True)
    new_qty = models.PositiveIntegerField(null=True, blank=True)
    change = models.IntegerField(default=0)
    note = models.CharField(max_length=300, blank=True, default='')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [models.Index(fields=['product', '-created_at'])]

    def __str__(self):
        return f'{self.product.name} · {self.get_action_display()}'


class ProductImage(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='images')
    image = models.ImageField(upload_to='products/')
    alt = models.CharField(max_length=200, blank=True)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['order', 'id']

    def __str__(self):
        return f'{self.product.name} image #{self.id}'


class Review(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='reviews')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    name = models.CharField(max_length=120, blank=True)
    rating = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)])
    comment = models.TextField()
    verified_purchase = models.BooleanField(default=False)
    active = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.rating}★ review for {self.product.name}'


class WishlistItem(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='wishlist_items')
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='wishlisted_by')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'product')
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.user} → {self.product.name}'


class Coupon(models.Model):
    PERCENT = 'percent'
    FIXED = 'fixed'

    TYPE_CHOICES = [(PERCENT, 'Percentage'), (FIXED, 'Fixed amount')]

    code = models.CharField(max_length=40, unique=True)
    discount_type = models.CharField(max_length=10, choices=TYPE_CHOICES, default=PERCENT)
    value = models.DecimalField(**MONEY)
    min_order_amount = models.DecimalField(**MONEY, default=Decimal('0.00'))
    max_uses = models.PositiveIntegerField(default=0)
    used_count = models.PositiveIntegerField(default=0)
    per_user_limit = models.PositiveIntegerField(default=0)
    valid_from = models.DateTimeField(null=True, blank=True)
    valid_until = models.DateTimeField(null=True, blank=True)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.code

    def discount_for(self, subtotal):
        if self.discount_type == self.FIXED:
            return min(self.value, subtotal)
        return (subtotal * self.value / Decimal('100')).quantize(Decimal('0.01'))

    @property
    def is_valid(self):
        if not self.active:
            return False
        now = timezone.now()
        if self.valid_from and now < self.valid_from:
            return False
        if self.valid_until and now > self.valid_until:
            return False
        if self.max_uses and self.used_count >= self.max_uses:
            return False
        return True


class CouponUsage(models.Model):
    coupon = models.ForeignKey(Coupon, on_delete=models.CASCADE, related_name='usages')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    order = models.ForeignKey('Order', on_delete=models.CASCADE)
    used_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('coupon', 'order')

    def __str__(self):
        return f'{self.coupon.code} used'


class Address(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='addresses')
    full_name = models.CharField(max_length=160)
    phone = models.CharField(max_length=30)
    line1 = models.CharField(max_length=200)
    line2 = models.CharField(max_length=200, blank=True)
    city = models.CharField(max_length=120)
    county = models.CharField(max_length=120, blank=True)
    postal_code = models.CharField(max_length=20, blank=True)
    is_default = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = 'Addresses'
        ordering = ['-is_default', '-created_at']

    def __str__(self):
        return f'{self.full_name} — {self.line1}, {self.city}'


class PosSession(models.Model):
    """An open/closed shift at the physical till.

    In-store orders (Order.sales_channel = 'pos') are linked to a session so
    the cashier's sales and payments can be reconciled per shift. The opening
    cash float and closing cash count let staff verify the till balances.
    """
    STATUS_OPEN = 'open'
    STATUS_CLOSED = 'closed'
    STATUS_CHOICES = [(STATUS_OPEN, 'Open'), (STATUS_CLOSED, 'Closed')]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name='pos_sessions',
                             help_text='Cashier who opened this shift.')
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_OPEN)
    opening_cash = models.DecimalField(**MONEY, default=Decimal('0.00'),
                                       help_text='Cash float at the start of the shift.')
    closing_cash = models.DecimalField(**MONEY, null=True, blank=True,
                                       help_text='Cash physically counted at the end of the shift.')
    notes = models.TextField(blank=True, default='')
    opened_at = models.DateTimeField(auto_now_add=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-opened_at']
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['user', 'status']),
        ]

    def __str__(self):
        return f'POS session #{self.pk} · {self.user.get_full_name() or self.user.username}'

    @property
    def is_open(self):
        return self.status == self.STATUS_OPEN

    @property
    def orders_count(self):
        return self.orders.count()

    @property
    def sales_total(self):
        total = (self.orders.filter(payment_status='paid')
                            .aggregate(t=models.Sum('total'))['t'])
        return total or Decimal('0.00')


class Order(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('confirmed', 'Confirmed'),
        ('processing', 'Processing'),
        ('shipped', 'Shipped'),
        ('delivered', 'Delivered'),
        ('cancelled', 'Cancelled'),
        ('refunded', 'Refunded'),
    ]
    PAID_STATUSES = ['confirmed', 'processing', 'shipped', 'delivered', 'refunded']

    PAYMENT_STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('paid', 'Paid'),
        ('failed', 'Failed'),
        ('cancelled', 'Cancelled'),
        ('refunded', 'Refunded'),
        ('timeout', 'Timed out'),
        ('requires_review', 'Requires Review'),
    ]
    PAYMENT_METHOD_CHOICES = [
        ('mpesa', 'M-Pesa STK Push'),
        ('cod', 'Cash / manual payment'),
        ('card', 'Card payment'),
    ]
    SALES_CHANNEL_CHOICES = [
        ('online', 'Online store'),
        ('pos', 'Store point of sale'),
    ]
    PAYMENT_TERMINAL = ['paid', 'failed', 'cancelled', 'refunded']

    number = models.CharField(max_length=30, unique=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='orders')
    sales_channel = models.CharField(max_length=10, choices=SALES_CHANNEL_CHOICES, default='online')
    pos_token = models.CharField(max_length=64, blank=True, null=True, unique=True,
                                 help_text='Client-supplied idempotency token for POS sales so a '
                                           'retried request can never create a duplicate sale.')
    pos_payment_method = models.CharField(max_length=10, blank=True, default='',
                                          choices=[('cash', 'Cash'), ('mpesa', 'M-Pesa'),
                                                   ('card', 'Card'), ('other', 'Other')],
                                          help_text='Exact till payment option chosen by the cashier.')
    served_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                  null=True, blank=True, related_name='served_orders',
                                  help_text='Staff member who served this order at the till.')
    pos_session = models.ForeignKey('PosSession', on_delete=models.SET_NULL,
                                    null=True, blank=True, related_name='orders',
                                    help_text='POS shift during which this in-store sale was made.')
    customer_name = models.CharField(max_length=160)
    phone = models.CharField(max_length=30)
    email = models.EmailField(blank=True)
    address_line1 = models.CharField(max_length=200, blank=True, default='')
    city = models.CharField(max_length=120, blank=True, default='')
    county = models.CharField(max_length=120, blank=True, default='')
    subtotal = models.DecimalField(**MONEY, default=Decimal('0.00'))
    discount = models.DecimalField(**MONEY, default=Decimal('0.00'))
    shipping = models.DecimalField(**MONEY, default=Decimal('0.00'))
    tax = models.DecimalField(**MONEY, default=Decimal('0.00'))
    total = models.DecimalField(**MONEY)
    coupon = models.ForeignKey(Coupon, on_delete=models.SET_NULL, null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    payment_status = models.CharField(max_length=20, choices=PAYMENT_STATUS_CHOICES, default='pending')
    payment_method = models.CharField(max_length=10, choices=PAYMENT_METHOD_CHOICES, default='cod')
    stock_released = models.BooleanField(default=False)
    stock_deducted = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['payment_status']),
            models.Index(fields=['number']),
        ]

    def __str__(self):
        return self.number

    @classmethod
    def next_number(cls):
        from uuid import uuid4
        return f'RB-{timezone.now().strftime("%y%m%d")}-{uuid4().hex[:6].upper()}'

    def record_status(self, status, note='', actor=None):
        if status == self.status:
            return
        self.status = status
        self.save(update_fields=['status', 'updated_at'])
        OrderStatusHistory.objects.create(order=self, status=status, note=note, created_by=actor)

    @property
    def display_total(self):
        return self.total


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.SET_NULL, null=True, blank=True, related_name='order_items')
    product_name = models.CharField(max_length=220)
    product_sku = models.CharField(max_length=80, blank=True, default='')
    price = models.DecimalField(**MONEY)
    unit_cost = models.DecimalField(**MONEY, default=Decimal('0.00'),
                                    help_text='Product cost price at the time of sale (for COGS/margin reporting).')
    quantity = models.PositiveIntegerField(default=1)
    subtotal = models.DecimalField(**MONEY, default=Decimal('0.00'))

    def __str__(self):
        return f'{self.product_name} × {self.quantity}'

    @property
    def returned_quantity(self):
        if hasattr(self, '_returned_quantity'):
            return self._returned_quantity
        agg = self.returns.aggregate(q=models.Sum('quantity'))
        return agg['q'] or 0

    @property
    def returnable_quantity(self):
        return max(0, self.quantity - self.returned_quantity)


class OrderStatusHistory(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='status_history')
    status = models.CharField(max_length=20, choices=Order.STATUS_CHOICES)
    note = models.CharField(max_length=300, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f'{self.order.number} → {self.status}'


class OrderReturn(models.Model):
    """A partial return against an existing sale.

    The original order and its items are never modified or deleted: a return
    is a separate record that references what came back, why, who processed
    it and how much was refunded. Stock is restored through the same audited
    inventory pipeline as every other movement.
    """
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='returns')
    item = models.ForeignKey('OrderItem', on_delete=models.CASCADE, related_name='returns')
    quantity = models.PositiveIntegerField(default=1)
    reason = models.CharField(max_length=300, blank=True, default='')
    refunded_amount = models.DecimalField(**MONEY, default=Decimal('0.00'))
    restocked = models.BooleanField(default=True,
                                    help_text='Whether the goods went back into sellable stock.')
    processed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                     null=True, blank=True, related_name='returns_processed')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Order return'
        verbose_name_plural = 'Order returns'

    def __str__(self):
        return f'Return {self.quantity} × {self.item.product_name} ({self.order.number})'


class Payment(models.Model):
    METHOD_CHOICES = [('mpesa', 'M-Pesa STK Push'), ('manual', 'Cash / manual'), ('card', 'Card payment')]
    STATUS_CHOICES = Order.PAYMENT_STATUS_CHOICES
    VERIFICATION_CHOICES = [
        ('', 'Not verified'),
        ('gateway', 'Gateway verified'),
        ('manual', 'Manually reviewed'),
    ]

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='payments')
    method = models.CharField(max_length=10, choices=METHOD_CHOICES, default='mpesa')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    reference = models.CharField(max_length=120, blank=True)
    transaction_id = models.CharField(max_length=120, blank=True)
    amount = models.DecimalField(**MONEY)
    phone = models.CharField(max_length=30, blank=True)
    result_code = models.CharField(max_length=20, blank=True, default='')
    result_description = models.TextField(blank=True)
    verification = models.CharField(max_length=20, choices=VERIFICATION_CHOICES, blank=True, default='')
    amount_paid = models.DecimalField(**MONEY, null=True, blank=True,
                                      help_text='Cash actually handed over at the till (POS cash sales).')
    change_given = models.DecimalField(**MONEY, null=True, blank=True,
                                       help_text='Change returned to the customer (POS cash sales).')
    verified_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                    null=True, blank=True, related_name='payment_actions')
    verified_at = models.DateTimeField(null=True, blank=True)
    action_note = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status', 'method']),
            models.Index(fields=['order']),
        ]

    def __str__(self):
        return f'{self.get_method_display()} {self.amount} for {self.order.number}'

    @property
    def is_gateway_verified(self):
        return self.verification == 'gateway'

    @property
    def is_manually_reviewed(self):
        return self.verification == 'manual'

    @classmethod
    def record(cls, order, method, amount, status='pending', reference=''):
        return cls.objects.create(order=order, method=method, amount=amount, status=status, reference=reference)


class MpesaTransaction(models.Model):
    STATUS_CHOICES = [('sent', 'Sent'), ('completed', 'Completed'), ('failed', 'Failed'), ('timeout', 'Timed out')]

    transaction_id = models.CharField(max_length=80, unique=True)
    order = models.ForeignKey(Order, on_delete=models.SET_NULL, null=True, blank=True, related_name='mpesa_transactions')
    phone = models.CharField(max_length=30)
    amount = models.DecimalField(**MONEY)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='sent')
    checkout_request_id = models.CharField(max_length=120, blank=True)
    merchant_request_id = models.CharField(max_length=120, blank=True, default='')
    mpesa_receipt = models.CharField(max_length=80, blank=True)
    result_code = models.CharField(max_length=20, blank=True, default='')
    result_description = models.TextField(blank=True)
    transaction_date = models.CharField(max_length=40, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=['checkout_request_id'])]

    def __str__(self):
        return self.transaction_id


class NewsletterSubscriber(models.Model):
    email = models.EmailField(unique=True)
    active = models.BooleanField(default=True)
    subscribed_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.email


class ContactMessage(models.Model):
    name = models.CharField(max_length=160)
    email = models.EmailField()
    subject = models.CharField(max_length=200, blank=True)
    message = models.TextField()
    handled = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.name}: {self.subject}'


class Notification(models.Model):
    CATEGORY_CHOICES = [
        ('order', 'Order'),
        ('payment', 'Payment'),
        ('inventory', 'Inventory'),
        ('review', 'Review'),
        ('customer', 'Customer'),
        ('account', 'Account'),
        ('system', 'System'),
    ]

    title = models.CharField(max_length=200)
    message = models.TextField(blank=True)
    for_staff = models.BooleanField(default=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                             null=True, blank=True, related_name='notifications')
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, blank=True, default='')
    link = models.CharField(max_length=300, blank=True, default='')
    read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['for_staff', 'read']),
            models.Index(fields=['user', 'read']),
            models.Index(fields=['user', '-created_at']),
        ]

    def __str__(self):
        return self.title

    @classmethod
    def create(cls, title, message='', for_staff=True, user=None, category='', link=''):
        return cls.objects.create(title=title, message=message, for_staff=for_staff,
                                  user=user, category=category, link=link)


class SiteSettings(models.Model):
    ENV_CHOICES = [('sandbox', 'Sandbox'), ('production', 'Production')]

    # Branding
    store_name = models.CharField(max_length=160, default='Reeves Boutique')
    tagline = models.CharField(max_length=200, default='Modern fashion, thoughtfully selected.')
    description = models.TextField(blank=True, default='')
    logo = models.ImageField(upload_to='branding/', blank=True, null=True)
    favicon = models.ImageField(upload_to='branding/', blank=True, null=True)
    banner = models.ImageField(upload_to='branding/', blank=True, null=True)
    announcement = models.CharField(max_length=240, blank=True, default='')
    primary_color = models.CharField(max_length=20, default='#d97706')
    currency = models.CharField(max_length=10, default='KES')
    phone = models.CharField(max_length=30, blank=True, default='')
    contact_email = models.EmailField(blank=True, default='')
    address = models.CharField(max_length=300, blank=True, default='')
    footer_text = models.CharField(max_length=300, blank=True, default='')
    hero_title = models.CharField(max_length=120, default='Style that speaks for itself.')
    hero_subtitle = models.CharField(max_length=300, default='Discover modern fashion and accessories from Reeves Boutique.')
    social_facebook = models.URLField(blank=True, default='')
    social_instagram = models.URLField(blank=True, default='')
    social_twitter = models.URLField(blank=True, default='')
    social_whatsapp = models.CharField(max_length=30, blank=True, default='')

    # Inventory
    low_stock_default = models.PositiveIntegerField(default=5)
    desired_stock_level = models.PositiveIntegerField(default=10)
    inventory_alert_email = models.EmailField(blank=True, default='')
    staff_notifications_email = models.EmailField(
        blank=True, default='',
        help_text='Admin emails for new orders, payments, reviews and system alerts.')
    restock_lookback_days = models.PositiveIntegerField(default=30)
    restock_lead_time_days = models.PositiveIntegerField(default=7)
    restock_min_sales_orders = models.PositiveIntegerField(default=2)

    # Shipping & tax
    shipping_enabled = models.BooleanField(default=True)
    flat_rate = models.DecimalField(**MONEY, default=Decimal('150.00'))
    free_shipping_threshold = models.DecimalField(**MONEY, default=Decimal('5000.00'))
    tax_enabled = models.BooleanField(default=False)
    tax_rate = models.DecimalField(**MONEY, default=Decimal('16.00'))

    # Order / payment → inventory strategy
    INVENTORY_STRATEGY_CHOICES = [
        ('hold', 'Reserve stock when the order is placed'),
        ('paid', 'Deduct stock when payment is confirmed'),
    ]
    inventory_strategy = models.CharField(max_length=20, choices=INVENTORY_STRATEGY_CHOICES, default='hold')

    # SMTP
    smtp_enabled = models.BooleanField(default=False)
    smtp_host = models.CharField(max_length=160, default='smtp.gmail.com')
    smtp_port = models.PositiveIntegerField(default=587)
    smtp_username = models.CharField(max_length=200, blank=True, default='')
    smtp_password = models.CharField(max_length=300, blank=True, default='')
    smtp_use_tls = models.BooleanField(default=True)
    smtp_use_ssl = models.BooleanField(default=False)
    smtp_from_email = models.EmailField(blank=True, default='')
    smtp_sender_name = models.CharField(max_length=160, blank=True, default='Reeves Boutique')

    # Password reset / email security
    password_reset_timeout_seconds = models.PositiveIntegerField(
        default=86400,
        help_text='How long a password-reset link stays valid, in seconds.',
    )

    # M-Pesa
    mpesa_enabled = models.BooleanField(default=False)
    mpesa_environment = models.CharField(max_length=20, choices=ENV_CHOICES, default='sandbox')
    mpesa_consumer_key = models.CharField(max_length=300, blank=True, default='')
    mpesa_consumer_secret = models.CharField(max_length=300, blank=True, default='')
    mpesa_shortcode = models.CharField(max_length=50, blank=True, default='')
    mpesa_passkey = models.CharField(max_length=300, blank=True, default='')
    mpesa_callback_url = models.URLField(blank=True, default='')
    mpesa_account_reference = models.CharField(max_length=100, default='Reeves Boutique')
    mpesa_transaction_desc = models.CharField(max_length=200, default='Payment for Reeves Boutique order')

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Site settings'
        verbose_name_plural = 'Site settings'

    def __str__(self):
        return self.store_name

    @classmethod
    def get(cls):
        obj = cls.objects.first()
        if not obj:
            obj = cls.objects.create()
        return obj

    @property
    def smtp_complete(self):
        return bool(self.smtp_enabled and self.smtp_host and self.smtp_username and self.smtp_password)

    @property
    def mpesa_complete(self):
        return bool(
            self.mpesa_enabled
            and self.mpesa_consumer_key
            and self.mpesa_consumer_secret
            and self.mpesa_shortcode
            and self.mpesa_passkey
            and self.mpesa_callback_url
        )

    def shipping_for(self, subtotal):
        if not self.shipping_enabled:
            return Decimal('0.00')
        if subtotal >= self.free_shipping_threshold:
            return Decimal('0.00')
        return self.flat_rate

    def tax_for(self, subtotal):
        if not self.tax_enabled:
            return Decimal('0.00')
        return (subtotal * self.tax_rate / Decimal('100')).quantize(Decimal('0.01'))
