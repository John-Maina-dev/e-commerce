from django.core.mail.backends.smtp import EmailBackend as DjangoSMTPBackend


class DatabaseSMTPEmailBackend(DjangoSMTPBackend):
    """Reads SMTP settings from the SiteSettings table when configured."""

    def __init__(self, *args, **kwargs):
        try:
            from .models import SiteSettings
            s = SiteSettings.objects.first()
            if s and s.smtp_enabled:
                kwargs.update(
                    host=s.smtp_host,
                    port=s.smtp_port,
                    username=s.smtp_username or None,
                    password=s.smtp_password or None,
                    use_tls=s.smtp_use_tls and not s.smtp_use_ssl,
                    use_ssl=s.smtp_use_ssl,
                )
        except Exception:
            pass
        super().__init__(*args, **kwargs)
