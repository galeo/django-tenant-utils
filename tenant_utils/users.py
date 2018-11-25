"""Defines multi-tenant authorization functionality."""
from django.contrib.auth import get_user_model
from django.contrib.auth.base_user import BaseUserManager
from django.db import connection

from django_tenants.utils import get_public_schema_name, get_tenant_model

from .signals import tenant_user_created, tenant_user_deleted
from .exceptions import SchemaError, ExistsError, DeleteError, InactiveError


class UserManager(BaseUserManager):
    def _create_user(self, email, password, is_staff, is_superuser, is_verified, **extra_fields):
        # Do some schema validation to protect against calling create user from inside
        # a tenant. Must create public tenant permissions during user creation. This
        # happens during assign role. This function cannot be used until a public
        # schema already exists
        UserModel = get_user_model()

        if connection.get_schema() != get_public_schema_name():
            raise SchemaError("Schema must be public for UserManager user creation.")

        if not email:
            raise ValueError("Users must have an email address.")
        email = self.normalize_email(email)

        # If no password is submitted, just assign a random one to lock down
        # the account a little bit.
        if not password:
            password = self.make_random_password(length=30)

        user = UserModel.objects.filter(email=email).first()
        if user and user.is_active:
            raise ExistsError("User already exists!")

        # User might exist but not be active. If a user does exist
        # all previous history logs will still be associated with the user,
        # but will not be accessible because the user won't be linked to
        # any tenants from the user's previous membership. There are two
        # exceptions to this. 1) The user gets re-invited to a tenant it
        # previously had access to (this is good thing IMO). 2) The public
        # schema if they had previous activity associated would be available
        if not user:
            user = UserModel(email=email, is_verified=is_verified, **extra_fields)

        user.email = email
        user.is_active = True
        user.is_verified = is_verified
        user.set_password(password)
        user.save()

        # Public tenant permissions object was created when we assigned a
        # role to the user above, if we are a staff/superuser we set it here
        if is_staff or is_superuser:
            user.is_staff = is_staff
            user.is_superuser = is_superuser
            user.save()

        tenant_user_created.send(sender=self.__class__, user=user)

        return user

    def create_user(self, email=None, password=None, is_staff=False, **extra_fields):
        return self._create_user(email, password, is_staff, False, False, **extra_fields)

    def create_superuser(self, password, email=None, **extra_fields):
        return self._create_user(email, password, True, True, True, **extra_fields)

    def delete_user(self, user_obj):
        if not user_obj.is_active:
            raise InactiveError("User specified is not an active user!")

        # Check to make sure we don't try to delete the public tenant owner
        # that would be bad...
        public_tenant = get_tenant_model().objects.get(schema_name=get_public_schema_name())
        if user_obj.id == public_tenant.owner.id:
            raise DeleteError("Cannot delete the public tenant owner!")

        # Delete the tenant permissions and unlink when user is deleted
        for tenant in user_obj.tenants.all():
            # If user owns the tenant, we call delete on the tenant
            # which will delete the user from the tenant as well
            if tenant.owner.id == user_obj.id:
                # Delete tenant will handle any other linked users to that tenant
                tenant.delete_tenant()
            else:
                # Unlink user from all roles in any tenant it doesn't own
                tenant.remove_user(user_obj, soft_remove=False)

        # Set is_active, don't actually delete the object
        user_obj.is_active = False
        user_obj.save()

        tenant_user_deleted.send(sender=self.__class__, user=user_obj)
