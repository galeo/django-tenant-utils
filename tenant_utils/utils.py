"""Defines utility functions for multi tenant user environments."""
from django.apps import apps
from django.conf import settings
from django.db import connection, transaction
from django.contrib.auth import get_user_model
from django.utils.translation import ugettext_lazy as _
from django.core.exceptions import ImproperlyConfigured

from django_tenants.utils import (
    schema_context,
    get_tenant_model,
    get_tenant_domain_model,
    get_public_schema_name
)

from .exceptions import ExistsError


def get_tenant_schema_session_key():
    return getattr(settings, 'TENANT_SCHEMA_SESSION_KEY',
                   '_tenant_schema_name')


def get_permissions_model():
    try:
        model_name = settings.TENANT_USERS_PERMISSIONS_MODEL
        return apps.get_model(model_name, require_ready=False)
    except AttributeError:
        raise ImproperlyConfigured(
            _('TENANT_USERS_PERMISSIONS_MODEL '
              'must be defined in settings.')
        )
    except LookupError:
        raise ImproperlyConfigured(
            _('Failed to import the model specified in '
              'settings.TENANT_USERS_PERMISSIONS_MODEL.')
        )


def schema_required(func):
    def inner(self, *args, **options):
        tenant_schema = self.schema_name
        # Save current schema and restore it when we're done
        saved_schema = connection.get_schema()
        # Set schema to this tenants schema to start building permissions in that tenant
        connection.set_schema(tenant_schema)
        try:
            result = func(self, *args, **options)
        finally:
            # Even if an exception is raised we need to reset our schema state
            connection.set_schema(saved_schema)
        return result
    return inner


@transaction.atomic
def add_user(user=None, tenant=None, **kwargs):
    user.tenants.add(tenant)
    with schema_context(tenant.schema_name):
        try:
            PermissionsModel = get_permissions_model()
            permissions = PermissionsModel.objects.get(user_id=user.id)
        except PermissionsModel.DoesNotExist:
            permissions = PermissionsModel(user=user, **kwargs)
            permissions.save()


@transaction.atomic
def remove_user(user=None, tenant=None):
    user.tenants.remove(tenant)
    with schema_context(tenant.schema_name):
        PermissionsModel = get_permissions_model()
        permissions = PermissionsModel.objects.filter(user_id=user.id).first()
        if permissions:
            permissions.delete()


def get_current_tenant():
    current_schema = connection.get_schema()
    TenantModel = get_tenant_model()
    tenant = TenantModel.objects.get(schema_name=current_schema)
    return tenant


@transaction.atomic
def create_public_tenant(domain_url, owner_email, username, **owner_extra):
    UserModel = get_user_model()
    TenantModel = get_tenant_model()
    public_schema_name = get_public_schema_name()

    if TenantModel.objects.filter(schema_name=public_schema_name).first():
        raise ExistsError("Public tenant already exists.")

    # Create public tenant user. This user doesn't go through object manager
    # create_user function because public tenant does not exist yet
    profile = UserModel.objects.create(
        email=owner_email,
        username=username,
        is_active=True,
        **owner_extra
    )
    profile.set_unusable_password()
    profile.save()

    # Create public tenant
    public_tenant = TenantModel.objects.create(
        schema_name=public_schema_name,
        name='Public Tenant',
        owner=profile
    )

    # Add one or more domains for the tenant
    get_tenant_domain_model().objects.create(
        domain=domain_url,
        tenant=public_tenant,
        is_primary=True
    )


def fix_tenant_urls(domain_url):
    """
    Helper function to update the domain urls on all tenants
    Useful for domain changes in development
    """
    TenantModel = get_tenant_model()
    public_schema_name = get_public_schema_name()

    tenants = TenantModel.objects.all()
    for tenant in tenants:
        if tenant.schema_name == public_schema_name:
            tenant.domain_url = domain_url
        else:
            # Assume the URL is wrong, parse out the subdomain
            # and glue it back to the domain URL configured
            slug = tenant.domain_url.split('.')[0]
            new_url = "{}.{}".format(slug, domain_url)
            tenant.domain_url = new_url
        tenant.save()
