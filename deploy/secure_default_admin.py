# Runs inside `pretix shell` on every container start (see entrypoint.sh).
#
# pretix's first migration creates the superuser admin@localhost with the
# password "admin". On a public server anyone could log in with it before the
# real admin does. This script only touches that account while it still has
# the default password:
#   - PRETIX_ADMIN_EMAIL and PRETIX_ADMIN_PASSWORD set: the account gets this
#     address and password.
#   - otherwise: the account is deactivated.
# Once the password has been changed the script does nothing.
import os

from pretix.base.models import User

DEFAULT_EMAIL = "admin@localhost"
DEFAULT_PASSWORD = "admin"
MIN_PASSWORD_LENGTH = 12

email = os.environ.get("PRETIX_ADMIN_EMAIL", "").strip()
password = os.environ.get("PRETIX_ADMIN_PASSWORD", "")
default_admin = User.objects.filter(email=DEFAULT_EMAIL).first()

if default_admin is None or not default_admin.check_password(DEFAULT_PASSWORD):
    print("[pretix-deploy] Kein Standard-Admin mit Standard-Passwort vorhanden, nichts zu tun")
elif email and len(password) >= MIN_PASSWORD_LENGTH:
    if User.objects.filter(email__iexact=email).exclude(pk=default_admin.pk).exists():
        default_admin.is_active = False
        default_admin.save()
        print("[pretix-deploy] PRETIX_ADMIN_EMAIL ist schon vergeben, Standard-Admin deaktiviert")
    else:
        default_admin.email = email
        default_admin.set_password(password)
        default_admin.needs_password_change = False
        default_admin.is_active = True
        default_admin.save()
        print("[pretix-deploy] Standard-Admin ersetzt (Adresse aus PRETIX_ADMIN_EMAIL)")
else:
    default_admin.is_active = False
    default_admin.save()
    print(
        "[pretix-deploy] Standard-Admin deaktiviert: PRETIX_ADMIN_EMAIL und "
        f"PRETIX_ADMIN_PASSWORD (mindestens {MIN_PASSWORD_LENGTH} Zeichen) setzen und neu starten"
    )
