from django import forms
from django.contrib.auth.forms import PasswordResetForm, UserCreationForm
from django.contrib.auth.models import User
from django.template import loader
from django.urls import reverse

from .models import Address, ContactMessage, Coupon, Product, Review, SiteSettings


class RegistrationForm(UserCreationForm):
    email = forms.EmailField(required=True, label='Email address')

    class Meta:
        model = User
        fields = ('username', 'first_name', 'last_name', 'email', 'password1', 'password2')

    def clean_email(self):
        email = self.cleaned_data['email'].strip().lower()
        if User.objects.filter(email=email).exists():
            raise forms.ValidationError('An account with this email already exists.')
        return email

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data['email'].strip().lower()
        user.first_name = self.cleaned_data.get('first_name', '').strip()
        user.last_name = self.cleaned_data.get('last_name', '').strip()
        if commit:
            user.save()
        return user


class SitePasswordResetForm(PasswordResetForm):
    """Django's secure reset form, but the email goes through the store's
    branded email pipeline (which respects the SMTP enable/disable toggle and
    the configured sender identity). The response is identical whether or not
    the email exists, so the form cannot be used to enumerate accounts."""

    def send_mail(self, subject_template_name, email_template_name, context,
                  from_email, to_email, html_email_template_name=None):
        from .emails import password_reset
        from .notify import password_reset_sent
        subject = loader.render_to_string(subject_template_name, context)
        subject = ''.join(subject.splitlines())
        reset_url = f"{context['protocol']}://{context['domain']}{reverse('password_reset_confirm', kwargs={'uidb64': context['uid'], 'token': context['token']})}"
        password_reset(to_email, reset_url, subject, username=context['user'].get_username())
        password_reset_sent(context['user'], to_email)


class MpesaSettingsForm(forms.Form):
    """Server-side validation for the M-Pesa Daraja configuration page.

    Secret values are never required to be re-typed: a blank secret means
    "keep the value already stored" and is only enforced when M-Pesa is
    actually enabled and no value exists yet. This mirrors the masked inputs
    in the UI, where saved secrets are shown as empty fields.
    """

    mpesa_enabled = forms.BooleanField(required=False)
    mpesa_environment = forms.ChoiceField(required=False, choices=SiteSettings.ENV_CHOICES)
    mpesa_account_type = forms.ChoiceField(required=False, choices=SiteSettings.ACCOUNT_TYPE_CHOICES)
    mpesa_business_name = forms.CharField(required=False, max_length=160)
    mpesa_shortcode = forms.CharField(required=False, max_length=50)
    mpesa_consumer_key = forms.CharField(
        required=False, max_length=300,
        widget=forms.PasswordInput(attrs={'autocomplete': 'off'}))
    mpesa_consumer_secret = forms.CharField(
        required=False, max_length=300,
        widget=forms.PasswordInput(attrs={'autocomplete': 'off'}))
    mpesa_passkey = forms.CharField(
        required=False, max_length=300,
        widget=forms.PasswordInput(attrs={'autocomplete': 'off'}))
    mpesa_callback_url = forms.URLField(required=False)
    mpesa_account_reference = forms.CharField(required=False, max_length=100)
    mpesa_transaction_desc = forms.CharField(required=False, max_length=200)
    inventory_strategy = forms.ChoiceField(
        required=False, choices=SiteSettings.INVENTORY_STRATEGY_CHOICES)

    def __init__(self, *args, instance=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance = instance

    def clean_mpesa_environment(self):
        value = self.cleaned_data.get('mpesa_environment') or ''
        if value and value not in dict(SiteSettings.ENV_CHOICES):
            raise forms.ValidationError('Select a valid environment.')
        return value

    def clean_mpesa_account_type(self):
        value = self.cleaned_data.get('mpesa_account_type') or ''
        if value and value not in dict(SiteSettings.ACCOUNT_TYPE_CHOICES):
            raise forms.ValidationError('Select PayBill or Till Number.')
        return value

    def clean_mpesa_shortcode(self):
        value = (self.cleaned_data.get('mpesa_shortcode') or '').strip()
        if value:
            if not value.isdigit():
                raise forms.ValidationError('Shortcode must contain digits only.')
            if not (5 <= len(value) <= 9):
                raise forms.ValidationError(
                    'Shortcode must be between 5 and 9 digits (e.g. 174379).')
        return value

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get('mpesa_enabled'):
            return cleaned

        s = self.instance
        for field, label in (
            ('mpesa_shortcode', 'Business shortcode'),
            ('mpesa_consumer_key', 'Consumer Key'),
            ('mpesa_consumer_secret', 'Consumer Secret'),
            ('mpesa_passkey', 'Passkey'),
        ):
            new_value = (cleaned.get(field) or '').strip()
            existing = getattr(s, field, '') if s is not None else ''
            if not new_value and not existing:
                self.add_error(field, f'{label} is required when M-Pesa is enabled.')
        return cleaned


class ProfileForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ('first_name', 'last_name', 'email')

    def clean_email(self):
        email = self.cleaned_data['email'].strip().lower()
        if User.objects.filter(email=email).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError('An account with this email already exists.')
        return email


class AddressForm(forms.ModelForm):
    class Meta:
        model = Address
        fields = ('full_name', 'phone', 'line1', 'line2', 'city', 'county', 'postal_code', 'is_default')


class ReviewForm(forms.ModelForm):
    class Meta:
        model = Review
        fields = ('rating', 'comment')
        widgets = {'rating': forms.NumberInput(attrs={'min': 1, 'max': 5, 'required': True}),
                   'comment': forms.Textarea(attrs={'rows': 4, 'required': True})}


class ContactForm(forms.ModelForm):
    class Meta:
        model = ContactMessage
        fields = ('name', 'email', 'subject', 'message')


class CouponForm(forms.ModelForm):
    class Meta:
        model = Coupon
        fields = ('code', 'discount_type', 'value', 'min_order_amount', 'max_uses',
                  'per_user_limit', 'valid_from', 'valid_until', 'active')
        widgets = {
            'valid_from': forms.DateTimeInput(attrs={'type': 'datetime-local'}),
            'valid_until': forms.DateTimeInput(attrs={'type': 'datetime-local'}),
        }


class ProductForm(forms.ModelForm):
    low_stock_threshold = forms.IntegerField(required=False, min_value=0)
    desired_stock_level = forms.IntegerField(required=False, min_value=0)
    display_order = forms.IntegerField(
        required=False, min_value=0, initial=0,
        help_text='Lower numbers appear first in storefront showcase sections (0 = default).'
    )
    cost_price = forms.DecimalField(required=False, min_value=0, max_digits=12, decimal_places=2,
                                    widget=forms.NumberInput(attrs={'step': '0.01', 'min': '0'}))

    class Meta:
        model = Product
        fields = ('name', 'sku', 'barcode', 'category', 'brand', 'short_description', 'description',
                  'price', 'sale_price', 'old_price', 'cost_price', 'stock', 'low_stock_threshold',
                  'desired_stock_level', 'active', 'hidden', 'featured', 'is_new', 'is_bestseller',
                  'showcase_hero', 'showcase_coverflow', 'display_order',
                  'image', 'image_url')
        widgets = {
            'description': forms.Textarea(attrs={'rows': 6}),
            'short_description': forms.Textarea(attrs={'rows': 2}),
            'price': forms.NumberInput(attrs={'step': '0.01', 'min': '0'}),
            'sale_price': forms.NumberInput(attrs={'step': '0.01', 'min': '0'}),
            'old_price': forms.NumberInput(attrs={'step': '0.01', 'min': '0'}),
        }

    def clean_sku(self):
        sku = self.cleaned_data['sku'].strip().upper()
        if Product.objects.filter(sku=sku).exclude(pk=self.instance.pk if self.instance else None).exists():
            raise forms.ValidationError('A product with this SKU already exists.')
        return sku

    def clean_barcode(self):
        barcode = self.cleaned_data.get('barcode') or ''
        barcode = barcode.strip()
        if barcode and Product.objects.filter(barcode=barcode).exclude(pk=self.instance.pk if self.instance else None).exists():
            raise forms.ValidationError('A product with this barcode already exists.')
        return barcode or None

    def clean_cost_price(self):
        return self.cleaned_data.get('cost_price') if self.cleaned_data.get('cost_price') is not None else 0

    def clean_low_stock_threshold(self):
        return self.cleaned_data.get('low_stock_threshold') or 5

    def clean_desired_stock_level(self):
        return self.cleaned_data.get('desired_stock_level') or 10

    def clean_display_order(self):
        val = self.cleaned_data.get('display_order')
        return val if val is not None else 0

    def clean(self):
        cleaned = super().clean()
        price = cleaned.get('price')
        sale_price = cleaned.get('sale_price')
        old_price = cleaned.get('old_price')
        if price is not None and price <= 0:
            self.add_error('price', 'Price must be greater than zero.')
        if price is not None and sale_price is not None:
            if sale_price < 0:
                self.add_error('sale_price', 'Sale price cannot be negative.')
            elif sale_price >= price:
                self.add_error('sale_price', 'Sale price must be lower than the regular price.')
        if price is not None and old_price is not None and old_price <= price:
            self.add_error('old_price', 'Compare-at price should be higher than the regular price.')

        # A published product must always have a usable picture: either an
        # uploaded file or an explicit external image URL.
        existing = self.instance if getattr(self, 'instance', None) and self.instance.pk else None
        has_existing = bool(existing and (existing.image or existing.image_url
                                          or existing.images.exists()))
        new_upload = self.files.get('image')
        gallery = [f for f in self.files.getlist('images') if f]
        url = (cleaned.get('image_url') or '').strip()
        if not has_existing and not new_upload and not gallery and not url:
            self.add_error('image', 'A product image is required. Upload a photo '
                                    '(or provide an image URL) before publishing.')
        return cleaned
