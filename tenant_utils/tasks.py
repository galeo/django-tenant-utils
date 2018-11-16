import time

from django.conf import settings
from django.contrib.auth import get_user_model

from django_tenants.utils import (
    get_public_schema_name,
    get_tenant_model, get_tenant_domain_model,
    schema_context
)

from . import get_tenant_user_model
from .exceptions import InactiveError, ExistsError


def provision_tenant(tenant_name, tenant_slug, user_email, is_staff=False):
    """
    Create a tenant with default roles and permissions

    Returns:
    The Fully Qualified Domain Name(FQDN) for the tenant.
    """
    tenant = None

    UserModel = get_user_model()
    TenantModel = get_tenant_model()

    user = UserModel.objects.get(email=user_email)
    if not user.is_active:
        raise InactiveError("Inactive user passed to provision tenant")

    tenant_domain = '{}.{}'.format(tenant_slug, settings.TENANT_USERS_DOMAIN)

    if get_tenant_domain_model().objects.filter(domain=tenant_domain).first():
        raise ExistsError("Tenant URL already exists.")

    time_string = str(int(time.time()))
    # Must be valid postgres schema characters see:
    # https://www.postgresql.org/docs/9.2/static/sql-syntax-lexical.html#SQL-SYNTAX-IDENTIFIERS
    # We generate unique schema names each time so we can keep tenants around without
    # taking up url/schema namespace.
    schema_name = '{}_{}'.format(tenant_slug, time_string)
    domain = None

    # noinspection PyBroadException
    try:
        # Wrap it in public schema context so schema consistency is maintained
        # if any error occurs
        with schema_context(get_public_schema_name()):
            tenant = TenantModel.objects.create(name=tenant_name,
                                                slug=tenant_slug,
                                                schema_name=schema_name,
                                                owner=user)

            # Add one or more domains for the tenant
            domain = get_tenant_domain_model().objects.create(domain=tenant_domain,
                                                              tenant=tenant,
                                                              is_primary=True)
            # Add user as a superuser inside the tenant
            # tenant.add_user(user, is_superuser=True, is_staff=is_staff)
    except:
        if domain is not None:
            domain.delete()
        if tenant is not None:
            # Flag is set to auto-drop the schema for the tenant
            tenant.delete(True)
        raise

    return tenant


def create_tenant_user(tenant_slug,
                       email, password,
                       is_verified=False,
                       is_staff=False, is_superuser=False,
                       related_user_email=None,
                       **user_extra):
    """
    Create user for a specified tenant.
    """
    PublicUserModel = get_user_model()
    TenantUserModel = get_tenant_user_model()
    TenantModel = get_tenant_model()
    public_schema_name = get_public_schema_name()

    tenant = TenantModel.objects.filter(slug=tenant_slug).first()
    if not tenant:
        raise ExistsError("Tenant not exists.")

    public_profile = None
    if related_user_email:
        with schema_context(public_schema_name):
            public_profile = PublicUserModel.objects.filter(
                email=related_user_email).first()
            if not public_profile:
                raise ExistsError("Related public user not exists.")

    profile = None
    with schema_context(tenant.schema_name):
        profile = TenantUserModel.objects.filter(email=email).first()
        if profile and profile.is_active:
            raise ExistsError("User already exists!")

        if not profile:
            profile = TenantUserModel.objects.create(
                email=email, **user_extra
            )
        profile.is_active = True
        profile.is_staff = is_staff
        profile.is_superuser = is_superuser
        profile.is_verified = is_verified
        profile.set_password(password)
        if public_profile:
            profile.supervisor = public_profile
        profile.save()
    return profile
