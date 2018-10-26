"""Defines multi-tenant authorization functionality."""
from django.contrib.auth import get_user_model
from django.contrib.auth.models import UserManager
from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.validators import UnicodeUsernameValidator
from django.core.mail import send_mail
from django.db import models, connection
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from django_tenants.utils import get_public_schema_name, get_tenant_model

from .permissions import TenantPermissionsDelegator
from .signals import tenant_user_created, tenant_user_deleted
from .exceptions import SchemaError, ExistsError, DeleteError, InactiveError


class UserProfileManager(BaseUserManager):
    def _create_user(self, email, password, is_staff, is_superuser, is_verified, **extra_fields):
        # Do some schema validation to protect against calling create user from inside
        # a tenant. Must create public tenant permissions during user creation. This
        # happens during assign role. This function cannot be used until a public
        # schema already exists
        UserModel = get_user_model()

        if connection.get_schema() != get_public_schema_name():
            raise SchemaError("Schema must be public for UserProfileManager user creation.")

        if not email:
            raise ValueError("Users must have an email address.")

        # If no password is submitted, just assign a random one to lock down
        # the account a little bit.
        if not password:
            password = self.make_random_password(length=30)

        email = self.normalize_email(email)

        profile = UserModel.objects.filter(email=email).first()
        if profile and profile.is_active:
            raise ExistsError("User already exists!")

        # Profile might exist but not be active. If a profile does exist
        # all previous history logs will still be associated with the user,
        # but will not be accessible because the user won't be linked to
        # any tenants from the user's previous membership. There are two
        # exceptions to this. 1) The user gets re-invited to a tenant it
        # previously had access to (this is good thing IMO). 2) The public
        # schema if they had previous activity associated would be available
        if not profile:
            profile = UserModel(email=email, is_verified=is_verified, **extra_fields)

        profile.email = email
        profile.is_active = True
        profile.is_verified = is_verified
        profile.set_password(password)
        profile.save()

        # Get public tenant tenant and link the user (no perms)
        public_tenant = get_tenant_model().objects.get(
            schema_name=get_public_schema_name())
        public_tenant.add_user(profile)

        # Public tenant permissions object was created when we assigned a
        # role to the user above, if we are a staff/superuser we set it here
        if is_staff or is_superuser:
            user_tenant = profile.tenant_permissions
            user_tenant.is_staff = is_staff
            user_tenant.is_superuser = is_superuser
            user_tenant.save()

        tenant_user_created.send(sender=self.__class__, user=profile)

        return profile

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

        # This includes the linked public tenant 'tenant'. It will delete the
        # Tenant permissions and unlink when user is deleted
        for tenant in user_obj.tenants.all():
            # If user owns the tenant, we call delete on the tenant
            # which will delete the user from the tenant as well
            if tenant.owner.id == user_obj.id:
                # Delete tenant will handle any other linked users to that tenant
                tenant.delete_tenant()
            else:
                # Unlink user from all roles in any tenant it doesn't own
                tenant.remove_user(user_obj)

        # Set is_active, don't actually delete the object
        user_obj.is_active = False
        user_obj.save()

        tenant_user_deleted.send(sender=self.__class__, user=user_obj)


class AbstractUserMixin(models.Model):
    """Provides the functionality of Django's `AbstractUser`.

    This class is a verbatim copy of `django.contrib.auth.models.AbstractUser`,
    with the notable exception that it does not inherit from `AbstractBaseUser`
    and `PermissionsMixin`, and thus does not tighly couple authentication and
    authorization. It may be combined with `tenant_utils.UserProfile` to
    provide all the functionality of Django's `AbstractUser` in a multi-tenant
    environment.
    """
    username_validator = UnicodeUsernameValidator()

    username = models.CharField(
        _('username'),
        max_length=150,
        unique=True,
        help_text=_('Required. 150 characters or fewer. '
                    'Letters, digits and @/./+/-/_ only.'),
        validators=[username_validator],
        error_messages={
            'unique': _("A user with that username already exists."),
        },
    )
    first_name = models.CharField(_('first name'), max_length=30, blank=True)
    last_name = models.CharField(_('last name'), max_length=150, blank=True)
    email = models.EmailField(_('email address'), blank=True)

    is_active = models.BooleanField(
        _('active'),
        default=True,
        help_text=_(
            'Designates whether this user should be treated as active. '
            'Unselect this instead of deleting accounts.'
        ),
    )

    # Tracks whether the user's email has been verified
    is_verified = models.BooleanField(_('verified'), default=False)

    date_joined = models.DateTimeField(_('date joined'), default=timezone.now)

    objects = UserManager()

    EMAIL_FIELD = 'email'
    USERNAME_FIELD = 'username'
    REQUIRED_FIELDS = ['email']

    class Meta:
        verbose_name = _('user')
        verbose_name_plural = _('users')
        abstract = True

    def clean(self):
        super().clean()
        self.email = self.__class__.objects.normalize_email(self.email)

    def has_verified_email(self):
        return self.is_verified is True

    def __unicode__(self):
        return self.email

    def get_full_name(self):
        """
        Return the first_name plus the last_name, with a space in between.
        """
        full_name = '%s %s' % (self.first_name, self.last_name)
        return full_name.strip()

    def get_short_name(self):
        """Return the short name for the user."""
        return self.first_name

    def email_user(self, subject, message, from_email=None, **kwargs):
        """Send an email to this user."""
        send_mail(subject, message, from_email, [self.email], **kwargs)


class UserProfile(AbstractBaseUser, AbstractUserMixin, TenantPermissionsDelegator):
    """An abstract Django user class."""

    class Meta:
        abstract = True
