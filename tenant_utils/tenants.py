import time

from django.db import models
from django.contrib.auth import get_user_model
from django.conf import settings
from django.utils import timezone
from django.utils.translation import ugettext_lazy as _

from django_tenants.models import TenantMixin
from django_tenants.utils import get_public_schema_name, get_tenant_model

from .signals import (
    tenant_user_added,
    tenant_user_removed
)
from .utils import schema_required, get_permissions_model
from .exceptions import InactiveError, ExistsError, DeleteError


class TenantBase(TenantMixin):
    """
    Contains global data and settings for the tenant model.
    """
    slug = models.SlugField(_('Tenant URL Name'), blank=True)

    # The owner of the tenant. Only they can delete it.
    # This can be changed, but it can't be blank.
    # There should always be an owner.
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    created = models.DateTimeField()
    modified = models.DateTimeField(blank=True)

    # Schema will be automatically created and synced when it is saved
    auto_create_schema = True

    # Schema will be automatically deleted when related tenant is deleted
    auto_drop_schema = True

    def save(self, *args, **kwargs):
        if not self.pk:
            self.created = timezone.now()
        self.modified = timezone.now()

        super(TenantBase, self).save(*args, **kwargs)

    def delete(self, force_drop=False):
        if force_drop:
            super(TenantBase, self).delete(force_drop=True)
        else:
            raise DeleteError("Not supported -- delete_tenant() should be used.")

    @schema_required
    def add_user(self, user_obj, is_superuser=False, is_staff=False):
        # User already is linked here
        if self.users.filter(id=user_obj.id).exists():
            raise ExistsError("User already added to tenant: %s" % user_obj)

        # User not linked to this tenant, so we need to create tenant permissions
        user_tenant_perms = get_permissions_model().objects.create(
            user=user_obj,
            is_staff=is_staff,
            is_superuser=is_superuser
        )
        # Link user to tenant
        user_obj.tenant_set.add(self)

        tenant_user_added.send(sender=self.__class__, user=user_obj, tenant=self)

    @schema_required
    def remove_user(self, user_obj):
        # Test that user is already in the tenant
        self.users.get(id=user_obj.id)

        if not user_obj.is_active:
            raise InactiveError("User specified is not an active user: %s" % user_obj)

        # Dont allow removing an owner from a tenant. This must be done
        # Through delete tenant or transfer_ownership
        if user_obj.id == self.owner.id:
            raise DeleteError("Cannot remove owner from tenant: %s" % self.owner)

        user_tenant_perms = user_obj.tenant_permissions

        # Remove all current groups from user..
        groups = user_tenant_perms.groups
        groups.clear()

        # Unlink from tenant
        get_permissions_model().objects.filter(id=user_tenant_perms.id).delete()
        user_obj.tenant_set.remove(self)

        tenant_user_removed.send(sender=self.__class__, user=user_obj, tenant=self)

    def delete_tenant(self):
        """
        We don't actually delete the tenant out of the database, but we associate them
        with a the public schema user and change their url to reflect their delete
        datetime and previous owner
        The caller should verify that the user deleting the tenant owns the tenant.
        """
        # Prevent public tenant schema from being deleted
        if self.schema_name == get_public_schema_name():
            raise ValueError("Cannot delete public tenant schema")

        for user_obj in self.users.all():
            # Don't delete owner at this point
            if user_obj.id == self.owner.id:
                continue
            self.remove_user(user_obj)

        # Seconds since epoch, time() returns a float, so we convert to
        # an int first to truncate the decimal portion
        time_string = str(int(time.time()))
        new_url = "{}-{}-{}".format(
            time_string,
            str(self.owner.id),
            self.domain_url
        )
        self.domain_url = new_url
        # The schema generated each time (even with same url slug) will be unique.
        # So we do not have to worry about a conflict with that

        # Set the owner to the system user (public schema owner)
        public_tenant = get_tenant_model().objects.get(schema_name=get_public_schema_name())

        old_owner = self.owner

        # Transfer ownership to system
        self.transfer_ownership(public_tenant.owner)

        # Remove old owner as a user if the owner still exists after the transfer
        if self.users.filter(id=user_obj.id).exists():
            self.remove_user(old_owner)

    @schema_required
    def transfer_ownership(self, new_owner):
        old_owner = self.owner

        # Remove current owner superuser status but retain any assigned role(s)
        old_owner_tenant_perms = old_owner.tenant_permissions
        old_owner_tenant_perms.is_superuser = False
        old_owner_tenant_perms.save()

        self.owner = new_owner

        # If original has no permissions left, remove user from tenant
        if not old_owner_tenant_perms.groups.exists():
            self.remove_user(old_owner)

        try:
            # Set new user as superuser in this tenant if user already exists
            user = self.users.get(id=new_owner.id)
            user_tenant_perms = user.tenant_permissions
            user_tenant_perms.is_superuser = True
            user_tenant_perms.save()
        except get_user_model().DoesNotExist:
            # New user is not a part of the system, add them as a user..
            self.add_user(new_owner, is_superuser=True)

        self.save()

    class Meta:
        abstract = True


class TenantUserMixin(models.Model):
    users = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        verbose_name=_('users'),
        blank=True,
        help_text=_('The users that belongs to this tenant.'),
        related_name="tenant_set"
    )

    class Meta:
        abstract = True
