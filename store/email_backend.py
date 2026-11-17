<<<<<<< HEAD
import logging
from django.conf import settings
from django.core.mail.backends.smtp import EmailBackend as DjangoSMTPBackend

logger = logging.getLogger('store')


class DatabaseSMTPEmailBackend(DjangoSMTPBackend):
    """Reads SMTP settings from the SiteSettings table or settings.py/env."""
=======
from django.core.mail.backends.smtp import EmailBackend as DjangoSMTPBackend


class DatabaseSMTPEmailBackend(DjangoSMTPBackend):
    """Reads SMTP settings from the SiteSettings table when configured."""
>>>>>>> 0eaeef0d594c7530f656b8338be122ce644eab03

    def __init__(self, *args, **kwargs):
        try:
            from .models import SiteSettings
            s = SiteSettings.objects.first()
            if s and s.smtp_enabled:
<<<<<<< HEAD
                if s.smtp_host and s.smtp_username and s.smtp_password:
                    kwargs.update(
                        host=s.smtp_host.strip(),
                        port=s.smtp_port,
                        username=s.smtp_username.strip() or None,
                        password=s.smtp_password.strip() or None,
                        use_tls=s.smtp_use_tls and not s.smtp_use_ssl,
                        use_ssl=s.smtp_use_ssl,
                        timeout=getattr(settings, 'EMAIL_TIMEOUT', 15),
                    )
                elif settings.EMAIL_HOST_USER and settings.EMAIL_HOST_PASSWORD:
                    kwargs.update(
                        host=getattr(settings, 'EMAIL_HOST', 'smtp.gmail.com').strip(),
                        port=getattr(settings, 'EMAIL_PORT', 587),
                        username=settings.EMAIL_HOST_USER.strip(),
                        password=settings.EMAIL_HOST_PASSWORD.strip(),
                        use_tls=getattr(settings, 'EMAIL_USE_TLS', True) and not getattr(settings, 'EMAIL_USE_SSL', False),
                        use_ssl=getattr(settings, 'EMAIL_USE_SSL', False),
                        timeout=getattr(settings, 'EMAIL_TIMEOUT', 15),
                    )
            elif not s and settings.EMAIL_HOST_USER and settings.EMAIL_HOST_PASSWORD:
                kwargs.update(
                    host=getattr(settings, 'EMAIL_HOST', 'smtp.gmail.com').strip(),
                    port=getattr(settings, 'EMAIL_PORT', 587),
                    username=settings.EMAIL_HOST_USER.strip(),
                    password=settings.EMAIL_HOST_PASSWORD.strip(),
                    use_tls=getattr(settings, 'EMAIL_USE_TLS', True) and not getattr(settings, 'EMAIL_USE_SSL', False),
                    use_ssl=getattr(settings, 'EMAIL_USE_SSL', False),
                    timeout=getattr(settings, 'EMAIL_TIMEOUT', 15),
                )
        except Exception as e:
            logger.warning('Failed to load SMTP settings: %s', e)
        super().__init__(*args, **kwargs)

    def open(self):
        if self.connection:
            return False
        # Port 587 uses STARTTLS. Direct SSL will fail with [SSL: WRONG_VERSION_NUMBER].
        if self.port == 587 and self.use_ssl:
            logger.warning('Port 587 requires STARTTLS. Auto-adjusting use_ssl=False, use_tls=True.')
            self.use_ssl = False
            self.use_tls = True
        # Port 465 requires direct SSL wrapper. STARTTLS will cause connection timeout.
        elif self.port == 465 and self.use_tls:
            logger.warning('Port 465 requires direct SSL. Auto-adjusting use_ssl=True, use_tls=False.')
            self.use_ssl = True
            self.use_tls = False
        return super().open()
=======
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
>>>>>>> 0eaeef0d594c7530f656b8338be122ce644eab03
