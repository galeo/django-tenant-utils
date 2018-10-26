from django.contrib.auth.backends import ModelBackend as DjangoModelBackend
from django.contrib.auth.models import Permission

from django_tenants.utils import get_public_schema_name

from . import get_tenant_user_model
from .utils import get_permissions_model


TenantUserModel = get_tenant_user_model()


class ModelBackend(DjangoModelBackend):
    """
    Authenticates against settings.AUTH_USER_MODEL.

    This class overrides `_get_group_permissions` to find permissions based on
    the user's per-tenant `settings.TENANT_USERS_PERMISSIONS_MODEL` instance's
    group memberships instead of the user's direct group memberships.
    """
    def _get_group_permissions(self, user_obj):
        """
        Returns a set of permission strings the user `user_obj` has from the
        groups they belong to through their
        `settings.TENANT_USERS_PERMISSIONS_MODEL` instance.
        """
        PermissionsModel = get_permissions_model()
        groups_field = PermissionsModel._meta.get_field('groups')
        groups_query = 'group__%s' % groups_field.related_query_name()
        return Permission.objects.filter(**{groups_query: user_obj})


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
