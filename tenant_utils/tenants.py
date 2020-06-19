import time

from django.db import models, transaction
from django.conf import settings
from django.utils import timezone
from django.utils.translation import ugettext_lazy as _

from django_tenants.models import TenantMixin
from django_tenants.utils import get_public_schema_name, get_tenant_model

from . import get_tenant_user_model
from .signals import (
    tenant_user_added,
    tenant_user_removed,
    tenant_user_connected,
    tenant_user_disconnected
)
from .utils import schema_required
from .exceptions import InactiveError, ExistsError, DeleteError, SchemaError


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

    def delete(self, force_drop=False, *args, **kwargs):
        if force_drop:
            super().delete(force_drop, *args, **kwargs)
        else:
            raise DeleteError("Not supported -- delete_tenant() should be used.")

    def _link_to_tenant_user(self, user_obj, tenant_user):
        """
        Link the public user to the tenant user.
        """
        fields = self.__class__.users.field.remote_field.through_fields + (
            'organization_user',)
        self.__class__.users.through._default_manager.create(
            **dict(zip(fields, (self, user_obj, tenant_user.pk))))

    def _unlink_from_tenant(self, user_obj):
        """
        Unlink the public user from the tenant.
        """
        fields = self.__class__.users.field.remote_field.through_fields
        self.__class__.users.through._default_manager.filter(
            **dict(zip(fields, (self, user_obj)))).delete()

    def _check_user_exists(self, user_obj):
        """
        Check if the public user already linked here.
        """
        # User already connected to a tenant user
        if self.users.filter(id=user_obj.id).exists():
            raise ExistsError("User already added to tenant: %s" % user_obj)

        # User already linked to a user inside the tenant, due to dirty data
        linked_tenant_user = get_tenant_user_model().objects.filter(
            supervisor_id=user_obj.id).first()
        if linked_tenant_user:
            raise ExistsError(
                "User already linked to a user inside the tenant: {}".format(
                    linked_tenant_user))

    @schema_required
    @transaction.atomic
    def connect_user(self, user_obj, tenant_user):
        """
        Connect a public user to a tenant user.
        """
        if self.schema_name == get_public_schema_name():
            raise SchemaError(
                "It's not allowed to connect a public user to a public user."
                "Make sure the current tenant {} is not the "
                "public tenant.".format(self))

        self._check_user_exists(user_obj)

        # The tenant user already linked to a public user
        if tenant_user.supervisor is not None:
            raise ExistsError(
                "The tenant user already linked to public user: {}".format(
                    tenant_user.supervisor))

        tenant_user.supervisor = user_obj
        tenant_user.save(update_fields=['supervisor'])

        # Link user to tenant
        fields = self.__class__.users.field.remote_field.through_fields + (
            'organization_user',)
        self.__class__.users.through._default_manager.create(
            **dict(zip(fields, (self, user_obj, tenant_user.pk))))

        tenant_user_connected.send(sender=self.__class__,
                                   user=user_obj,
                                   tenant=self,
                                   tenant_user=tenant_user)

    @schema_required
    @transaction.atomic
    def disconnect_user(self, user_obj, tenant_user):
        """
        Disconnect a public user from the tenant user.
        """
        if self.schema_name == get_public_schema_name():
            raise SchemaError(
                "Make sure the current tenant {} is not "
                "the public tenant.".format(self))

        disconnected = False
        # Test that user is already disconnected from the tenant user
        if self.users.filter(id=user_obj.id).exists() or \
           get_tenant_user_model().objects.filter(
               supervisor=user_obj.id).exists():
            disconnected = True

        # Don't allow disconnecting an owner from a tenant
        if user_obj.id == self.owner.id:
            raise DeleteError(
                "Cannot disconnect owner from tenant: {}".format(self.owner))

        tenant_user.supervisor = None
        tenant_user.save(update_fields=['supervisor'])

        self._unlink_from_tenant(user_obj)

        if disconnected:
            tenant_user_disconnected.send(sender=self.__class__,
                                          user=user_obj,
                                          tenant=self,
                                          tenant_user=tenant_user)

    @schema_required
    @transaction.atomic
    def add_user(self, user_obj, is_superuser=False, is_staff=False):
        """
        Create a user inside the tenant and set its supervisor to the public user.
        """
        if self.schema_name == get_public_schema_name():
            raise SchemaError(
                "It's not allowed to add a public user to the public tenant."
                "Make sure the current tenant {} is not the "
                "public tenant.".format(self))

        self._check_user_exists(user_obj)

        # Create a user in the tenant with generated username and email
        # And link it to the public user
        time_string = str(int(time.time()))
        tenant_user = get_tenant_user_model().objects.create(
            email='{}_{}'.format(user_obj.email, time_string),
            username='{}_{}'.format(user_obj.username, time_string),
            supervisor=user_obj,
            is_superuser=is_superuser, is_staff=is_staff,
            is_verified=True)

        # Link user to tenant
        self._link_to_tenant_user(user_obj, tenant_user)

        tenant_user_added.send(sender=self.__class__, user=user_obj, tenant=self)

    @schema_required
    @transaction.atomic
    def remove_user(self, user_obj, soft_remove=True):
        """
        Remove the related public user from the tenant.

        If `soft_remove` is set to False, then cleanup the permissions of the tenant
        user and set its `is_active` status to False.
        """
        if self.schema_name == get_public_schema_name():
            raise SchemaError(
                "It's not allowed to remove a public user from the public tenant."
                "Make sure the current tenant {} is not the public tenant.".format(self)
            )

        deleted = False
        # Test that user is already in the tenant
        if self.users.filter(id=user_obj.id).exists() or \
           get_tenant_user_model().objects.filter(supervisor=user_obj.id).exists():
            deleted = True

        # Don't allow removing an owner from a tenant
        # This must be done through delete tenant or transfer_ownership
        if user_obj.id == self.owner.id:
            raise DeleteError("Cannot remove owner from tenant: %s" % self.owner)

        tenant_user = get_tenant_user_model().objects.filter(
            supervisor=user_obj.id).first()
        if tenant_user:
            # Set supervisor of the tenant user to NULL
            tenant_user.supervisor = None
            if not soft_remove:
                # Remove all current groups from user
                tenant_user.user_permissions.clear()
                # Remove permissions
                tenant_user.groups.clear()
                # Set the status of this tenant user to inactive
                tenant_user.is_active = False
            tenant_user.save()

        self._unlink_from_tenant(user_obj)

        if deleted:
            tenant_user_removed.send(sender=self.__class__, user=user_obj, tenant=self)

    def delete_tenant(self):
        """
        We don't actually delete the tenant out of the database, but we associate them
        with a the public schema user and change their url to reflect their delete
        datetime and previous owner.

        The caller should verify that the user deleting the tenant owns the tenant.
        """
        # Prevent public tenant schema from being deleted
        if self.schema_name == get_public_schema_name():
            raise ValueError("Cannot delete public tenant schema")

        for user_obj in self.users.all():
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

        # Transfer ownership to system
        self.transfer_ownership(public_tenant.owner)

    @transaction.atomic
    def transfer_ownership(self, new_owner):
        old_owner = self.owner
        self.owner = new_owner
        self.save(update_fields=['owner'])
        self.remove_user(old_owner, soft_remove=False)
        self.add_user(new_owner, is_superuser=True)

    class Meta:
        abstract = True


class TenantUserMixin(models.Model):
    users = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        verbose_name=_('users'),
        blank=True,
        help_text=_('The users that belongs to this tenant.'),
        related_name="tenants"
    )

    class Meta:
        abstract = True
