from django.contrib.auth.backends import ModelBackend

from django_tenants.utils import get_public_schema_name

from . import get_tenant_user_model


TenantUserModel = get_tenant_user_model()


class TenantModelBackend(ModelBackend):
    """
    Authenticates against settings.TENANT_USER_MODEL.
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        # When the 'public' schema is requested, just skip
        if request.tenant.schema_name == get_public_schema_name():
            return None

        if username is None:
            username = kwargs.get(TenantUserModel.USERNAME_FIELD)
        try:
            user = TenantUserModel._default_manager.get_by_natural_key(username)
        except TenantUserModel.DoesNotExist:
            # Run the default password hasher once to reduce the timing
            # difference between an existing and a non-existing user (#20760).
            TenantUserModel().set_password(password)
        else:
            if user.check_password(password) and self.user_can_authenticate(user):
                return user

    def get_user(self, user_id):
        try:
            user = TenantUserModel._default_manager.get(pk=user_id)
        except TenantUserModel.DoesNotExist:
            return None
        return user if self.user_can_authenticate(user) else None
