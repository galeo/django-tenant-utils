from django.conf import settings
from django.contrib import auth
from django.contrib.auth.middleware import AuthenticationMiddleware
from django.utils.functional import SimpleLazyObject

from django_tenants.utils import get_public_schema_name

from . import get_tenant_user


def get_user(request):
    if not hasattr(request, '_cached_user'):
        if request.tenant.schema_name == get_public_schema_name():
            request._cached_user = auth.get_user(request)
        else:
            request._cached_user = get_tenant_user(request)
    return request._cached_user


class TenantAuthenticationMiddleware(AuthenticationMiddleware):
    def process_request(self, request):
        assert hasattr(request, 'session'), (
            "The tenant authentication middleware requires session middleware "
            "to be installed. Edit your MIDDLEWARE%s setting to insert "
            "'django.contrib.sessions.middleware.SessionMiddleware' before "
            "'TenantAuthenticationMiddleware'."
        ) % ("_CLASSES" if settings.MIDDLEWARE is None else "")
        request.user = SimpleLazyObject(lambda: get_user(request))
