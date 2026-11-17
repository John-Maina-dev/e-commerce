from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.utils.crypto import constant_time_compare
from django.utils.http import base36_to_int

from .models import SiteSettings


class SitePasswordResetTokenGenerator(PasswordResetTokenGenerator):
    """Password-reset tokens whose expiry is configured in SiteSettings.

    Django's default generator reads settings.PASSWORD_RESET_TIMEOUT; this
    subclass reads the per-site password_reset_timeout_seconds value instead so
    admins can tune the reset-link lifetime without redeploying. Tokens are
    still generated and signed by Django's secure, hash-based scheme — the
    password hash and last_login are folded into the signature, so a used token
    is automatically invalidated.
    """

    def check_token(self, user, token):
        timeout = SiteSettings.get().password_reset_timeout_seconds
        if not (user and token):
            return False
        try:
            ts_b36, _ = token.split('-')
        except ValueError:
            return False
        try:
            ts = base36_to_int(ts_b36)
        except ValueError:
            return False
        for secret in [self.secret, *self.secret_fallbacks]:
            if constant_time_compare(self._make_token_with_timestamp(user, ts, secret), token):
                break
        else:
            return False
        if (self._num_seconds(self._now()) - ts) > timeout:
            return False
        return True


site_token_generator = SitePasswordResetTokenGenerator()
