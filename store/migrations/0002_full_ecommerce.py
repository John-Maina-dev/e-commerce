import django.core.validators
import django.db.models.deletion
import django.utils.timezone
from decimal import Decimal
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [('store', '0001_initial')]

    operations = [
        # ------------------------------------------------------------------ #
        # Category
        # ------------------------------------------------------------------ #
        migrations.AddField(
            model_name='category',
            name='description',
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name='category',
            name='created_at',
            field=models.DateTimeField(auto_now_add=True, default=django.utils.timezone.now),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='category',
            name='updated_at',
            field=models.DateTimeField(auto_now=True, default=django.utils.timezone.now),
            preserve_default=False,
        ),
        migrations.AlterModelOptions(
            name='category',
            options={'ordering': ['name'], 'verbose_name_plural': 'Categories'},
        ),

        # ------------------------------------------------------------------ #
        # Product
        # ------------------------------------------------------------------ #
        migrations.AddField(
            model_name='product',
            name='brand',
            field=models.CharField(blank=True, max_length=120),
        ),
        migrations.AddField(
            model_name='product',
            name='short_description',
            field=models.CharField(blank=True, max_length=300),
        ),
        migrations.AddField(
            model_name='product',
            name='sale_price',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True),
        ),
        migrations.AddField(
            model_name='product',
            name='desired_stock_level',
            field=models.PositiveIntegerField(default=10),
        ),
        migrations.AddField(
            model_name='product',
            name='is_new',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='product',
            name='is_bestseller',
            field=models.BooleanField(default=False),
        ),
        migrations.AlterField(
            model_name='product',
            name='rating',
            field=models.DecimalField(decimal_places=1, default=Decimal('0.0'), max_digits=3,
                                       validators=[django.core.validators.MinValueValidator(0),
                                                   django.core.validators.MaxValueValidator(5)]),
        ),
        migrations.AlterModelOptions(
            name='product',
            options={'ordering': ['-created_at']},
        ),
        migrations.AddIndex(
            model_name='product',
            index=models.Index(fields=['active', 'featured'], name='store_prod_active_49c3d6_idx'),
        ),
        migrations.AddIndex(
            model_name='product',
            index=models.Index(fields=['stock'], name='store_prod_stock_5b3f22_idx'),
        ),

        # ------------------------------------------------------------------ #
        # SiteSettings
        # ------------------------------------------------------------------ #
        migrations.RemoveField(model_name='sitesettings', name='smtp_tls'),
        migrations.RemoveField(model_name='sitesettings', name='from_email'),
        migrations.AddField(
            model_name='sitesettings',
            name='smtp_use_tls',
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name='sitesettings',
            name='smtp_use_ssl',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='sitesettings',
            name='smtp_from_email',
            field=models.EmailField(blank=True, default='', max_length=254),
        ),
        migrations.AddField(
            model_name='sitesettings',
            name='smtp_sender_name',
            field=models.CharField(blank=True, default='Reeves Boutique', max_length=160),
        ),
        migrations.AddField(
            model_name='sitesettings',
            name='tagline',
            field=models.CharField(default='Modern fashion, thoughtfully selected.', max_length=200),
        ),
        migrations.AddField(
            model_name='sitesettings',
            name='description',
            field=models.TextField(blank=True, default=''),
        ),
        migrations.AddField(
            model_name='sitesettings',
            name='favicon',
            field=models.ImageField(blank=True, null=True, upload_to='branding/'),
        ),
        migrations.AddField(
            model_name='sitesettings',
            name='banner',
            field=models.ImageField(blank=True, null=True, upload_to='branding/'),
        ),
        migrations.AddField(
            model_name='sitesettings',
            name='announcement',
            field=models.CharField(blank=True, default='', max_length=240),
        ),
        migrations.AddField(
            model_name='sitesettings',
            name='phone',
            field=models.CharField(blank=True, default='', max_length=30),
        ),
        migrations.AddField(
            model_name='sitesettings',
            name='contact_email',
            field=models.EmailField(blank=True, default='', max_length=254),
        ),
        migrations.AddField(
            model_name='sitesettings',
            name='address',
            field=models.CharField(blank=True, default='', max_length=300),
        ),
        migrations.AddField(
            model_name='sitesettings',
            name='footer_text',
            field=models.CharField(blank=True, default='', max_length=300),
        ),
        migrations.AddField(
            model_name='sitesettings',
            name='hero_title',
            field=models.CharField(default='Style that speaks for itself.', max_length=120),
        ),
        migrations.AddField(
            model_name='sitesettings',
            name='hero_subtitle',
            field=models.CharField(default='Discover modern fashion and accessories from Reeves Boutique.', max_length=300),
        ),
        migrations.AddField(
            model_name='sitesettings',
            name='social_facebook',
            field=models.URLField(blank=True, default=''),
        ),
        migrations.AddField(
            model_name='sitesettings',
            name='social_instagram',
            field=models.URLField(blank=True, default=''),
        ),
        migrations.AddField(
            model_name='sitesettings',
            name='social_twitter',
            field=models.URLField(blank=True, default=''),
        ),
        migrations.AddField(
            model_name='sitesettings',
            name='social_whatsapp',
            field=models.CharField(blank=True, default='', max_length=30),
        ),
        migrations.AddField(
            model_name='sitesettings',
            name='desired_stock_level',
            field=models.PositiveIntegerField(default=10),
        ),
        migrations.AddField(
            model_name='sitesettings',
            name='shipping_enabled',
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name='sitesettings',
            name='flat_rate',
            field=models.DecimalField(decimal_places=2, default=Decimal('150.00'), max_digits=12),
        ),
        migrations.AddField(
            model_name='sitesettings',
            name='free_shipping_threshold',
            field=models.DecimalField(decimal_places=2, default=Decimal('5000.00'), max_digits=12),
        ),
        migrations.AddField(
            model_name='sitesettings',
            name='tax_enabled',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='sitesettings',
            name='tax_rate',
            field=models.DecimalField(decimal_places=2, default=Decimal('16.00'), max_digits=12),
        ),
        migrations.AlterModelOptions(
            name='sitesettings',
            options={'verbose_name': 'Site settings', 'verbose_name_plural': 'Site settings'},
        ),

        # ------------------------------------------------------------------ #
        # Order
        # ------------------------------------------------------------------ #
        migrations.RemoveField(model_name='order', name='address'),
        migrations.AddField(
            model_name='order',
            name='user',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                                    related_name='orders', to='auth.user'),
        ),
        migrations.AddField(
            model_name='order',
            name='address_line1',
            field=models.CharField(blank=True, default='', max_length=200),
        ),
        migrations.AddField(
            model_name='order',
            name='city',
            field=models.CharField(blank=True, default='', max_length=120),
        ),
        migrations.AddField(
            model_name='order',
            name='county',
            field=models.CharField(blank=True, default='', max_length=120),
        ),
        migrations.AddField(
            model_name='order',
            name='subtotal',
            field=models.DecimalField(decimal_places=2, default=Decimal('0.00'), max_digits=12),
        ),
        migrations.AddField(
            model_name='order',
            name='discount',
            field=models.DecimalField(decimal_places=2, default=Decimal('0.00'), max_digits=12),
        ),
        migrations.AddField(
            model_name='order',
            name='shipping',
            field=models.DecimalField(decimal_places=2, default=Decimal('0.00'), max_digits=12),
        ),
        migrations.AddField(
            model_name='order',
            name='tax',
            field=models.DecimalField(decimal_places=2, default=Decimal('0.00'), max_digits=12),
        ),
        migrations.AddField(
            model_name='order',
            name='payment_status',
            field=models.CharField(choices=[('pending', 'Pending'), ('success', 'Success'),
                                            ('failed', 'Failed'), ('cancelled', 'Cancelled'),
                                            ('refunded', 'Refunded')], default='pending', max_length=20),
        ),
        migrations.AddField(
            model_name='order',
            name='payment_method',
            field=models.CharField(choices=[('mpesa', 'M-Pesa STK Push'), ('cod', 'Cash / manual payment')],
                                   default='cod', max_length=10),
        ),
        migrations.AddField(
            model_name='order',
            name='stock_released',
            field=models.BooleanField(default=False),
        ),
        migrations.AlterField(
            model_name='order',
            name='status',
            field=models.CharField(choices=[('pending', 'Pending'), ('confirmed', 'Confirmed'),
                                            ('processing', 'Processing'), ('shipped', 'Shipped'),
                                            ('delivered', 'Delivered'), ('cancelled', 'Cancelled'),
                                            ('refunded', 'Refunded')], default='pending', max_length=20),
        ),
        migrations.AlterModelOptions(
            name='order',
            options={'ordering': ['-created_at']},
        ),
        migrations.AddIndex(
            model_name='order',
            index=models.Index(fields=['status'], name='store_order_status_6a7f3b_idx'),
        ),
        migrations.AddIndex(
            model_name='order',
            index=models.Index(fields=['payment_status'], name='store_order_payment_1c9d2e_idx'),
        ),
        migrations.AddIndex(
            model_name='order',
            index=models.Index(fields=['number'], name='store_order_number_b8f6a1_idx'),
        ),

        # ------------------------------------------------------------------ #
        # OrderItem
        # ------------------------------------------------------------------ #
        migrations.AddField(
            model_name='orderitem',
            name='product_sku',
            field=models.CharField(blank=True, default='', max_length=80),
        ),
        migrations.AddField(
            model_name='orderitem',
            name='subtotal',
            field=models.DecimalField(decimal_places=2, default=Decimal('0.00'), max_digits=12),
        ),
        migrations.AlterField(
            model_name='orderitem',
            name='product',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                                    related_name='order_items', to='store.product'),
        ),

        # ------------------------------------------------------------------ #
        # MpesaTransaction
        # ------------------------------------------------------------------ #
        migrations.AddField(
            model_name='mpesatransaction',
            name='merchant_request_id',
            field=models.CharField(blank=True, default='', max_length=120),
        ),
        migrations.AddField(
            model_name='mpesatransaction',
            name='result_code',
            field=models.CharField(blank=True, default='', max_length=20),
        ),
        migrations.AddField(
            model_name='mpesatransaction',
            name='transaction_date',
            field=models.CharField(blank=True, default='', max_length=40),
        ),
        migrations.AlterField(
            model_name='mpesatransaction',
            name='order',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                                    related_name='mpesa_transactions', to='store.order'),
        ),
        migrations.AddIndex(
            model_name='mpesatransaction',
            index=models.Index(fields=['checkout_request_id'], name='store_mpesa_checkout_4f8a92_idx'),
        ),

        # ------------------------------------------------------------------ #
        # New models
        # ------------------------------------------------------------------ #
        migrations.CreateModel(
            name='ProductImage',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('image', models.ImageField(upload_to='products/')),
                ('alt', models.CharField(blank=True, max_length=200)),
                ('order', models.PositiveIntegerField(default=0)),
                ('product', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                                              related_name='images', to='store.product')),
            ],
            options={'ordering': ['order', 'id']},
        ),
        migrations.CreateModel(
            name='Review',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(blank=True, max_length=120)),
                ('rating', models.PositiveSmallIntegerField(validators=[django.core.validators.MinValueValidator(1),
                                                                        django.core.validators.MaxValueValidator(5)])),
                ('comment', models.TextField()),
                ('verified_purchase', models.BooleanField(default=False)),
                ('active', models.BooleanField(default=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('product', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                                              related_name='reviews', to='store.product')),
                ('user', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                                           to='auth.user')),
            ],
            options={'ordering': ['-created_at']},
        ),
        migrations.CreateModel(
            name='WishlistItem',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('product', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                                              related_name='wishlisted_by', to='store.product')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                                           related_name='wishlist_items', to='auth.user')),
            ],
            options={'ordering': ['-created_at'], 'unique_together': {('user', 'product')}},
        ),
        migrations.CreateModel(
            name='Coupon',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('code', models.CharField(max_length=40, unique=True)),
                ('discount_type', models.CharField(choices=[('percent', 'Percentage'), ('fixed', 'Fixed amount')],
                                                   default='percent', max_length=10)),
                ('value', models.DecimalField(decimal_places=2, max_digits=12)),
                ('min_order_amount', models.DecimalField(decimal_places=2, default=Decimal('0.00'), max_digits=12)),
                ('max_uses', models.PositiveIntegerField(default=0)),
                ('used_count', models.PositiveIntegerField(default=0)),
                ('per_user_limit', models.PositiveIntegerField(default=0)),
                ('valid_from', models.DateTimeField(blank=True, null=True)),
                ('valid_until', models.DateTimeField(blank=True, null=True)),
                ('active', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
            ],
        ),
        migrations.CreateModel(
            name='CouponUsage',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('used_at', models.DateTimeField(auto_now_add=True)),
                ('coupon', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                                             related_name='usages', to='store.coupon')),
                ('user', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                                           to='auth.user')),
                ('order', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='store.order')),
            ],
            options={'unique_together': {('coupon', 'order')}},
        ),
        migrations.AddField(
            model_name='order',
            name='coupon',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to='store.coupon'),
        ),
        migrations.CreateModel(
            name='Address',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('full_name', models.CharField(max_length=160)),
                ('phone', models.CharField(max_length=30)),
                ('line1', models.CharField(max_length=200)),
                ('line2', models.CharField(blank=True, max_length=200)),
                ('city', models.CharField(max_length=120)),
                ('county', models.CharField(blank=True, max_length=120)),
                ('postal_code', models.CharField(blank=True, max_length=20)),
                ('is_default', models.BooleanField(default=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                                           related_name='addresses', to='auth.user')),
            ],
            options={'ordering': ['-is_default', '-created_at'], 'verbose_name_plural': 'Addresses'},
        ),
        migrations.CreateModel(
            name='OrderStatusHistory',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('status', models.CharField(choices=[('pending', 'Pending'), ('confirmed', 'Confirmed'),
                                                     ('processing', 'Processing'), ('shipped', 'Shipped'),
                                                     ('delivered', 'Delivered'), ('cancelled', 'Cancelled'),
                                                     ('refunded', 'Refunded')], max_length=20)),
                ('note', models.CharField(blank=True, max_length=300)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                                                 to='auth.user')),
                ('order', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                                            related_name='status_history', to='store.order')),
            ],
            options={'ordering': ['created_at']},
        ),
        migrations.CreateModel(
            name='Payment',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('method', models.CharField(choices=[('mpesa', 'M-Pesa'), ('manual', 'Manual')],
                                            default='mpesa', max_length=10)),
                ('reference', models.CharField(blank=True, max_length=120)),
                ('amount', models.DecimalField(decimal_places=2, max_digits=12)),
                ('status', models.CharField(choices=[('pending', 'Pending'), ('success', 'Success'),
                                                     ('failed', 'Failed'), ('cancelled', 'Cancelled'),
                                                     ('refunded', 'Refunded')], default='pending', max_length=10)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('order', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                                            related_name='payments', to='store.order')),
            ],
        ),
        migrations.CreateModel(
            name='ContactMessage',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=160)),
                ('email', models.EmailField(max_length=254)),
                ('subject', models.CharField(blank=True, max_length=200)),
                ('message', models.TextField()),
                ('handled', models.BooleanField(default=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
            ],
            options={'ordering': ['-created_at']},
        ),
        migrations.CreateModel(
            name='Notification',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.CharField(max_length=200)),
                ('message', models.TextField(blank=True)),
                ('for_staff', models.BooleanField(default=True)),
                ('read', models.BooleanField(default=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
            ],
            options={'ordering': ['-created_at']},
        ),
    ]
