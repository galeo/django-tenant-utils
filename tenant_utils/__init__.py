from django.apps import apps as django_apps
from django.conf import settings
from django.contrib.auth import (
    SESSION_KEY,
    BACKEND_SESSION_KEY,
    HASH_SESSION_KEY,
    load_backend
)
from django.core.exceptions import ImproperlyConfigured
from django.utils.crypto import constant_time_compare


def get_tenant_user_model():
    """
    Return the Organization User model that is active in this project.
    """
    try:
        return django_apps.get_model(settings.TENANT_USER_MODEL,
                                     require_ready=False)
    except ValueError:
        raise ImproperlyConfigured(
            "TENANT_USER_MODEL must be of the form 'app_label.model_name'")
    except LookupError:
        raise ImproperlyConfigured(
            "TENANT_USER_MODEL refers to model '%s' that has not been installed" %
            settings.TENANT_USER_MODEL
        )


def get_public_user_model():
    """
    Return the Public User model that is active in this project.
    """
    try:
        return django_apps.get_model(settings.PUBLIC_USER_MODEL,
                                     require_ready=False)
    except ValueError:
        raise ImproperlyConfigured(
            "PUBLIC_USER_MODEL must be of the form 'app_label.model_name'")
    except LookupError:
        raise ImproperlyConfigured(
            "PUBLIC_USER_MODEL refers to model '%s' that has not been installed" %
            settings.PUBLIC_USER_MODEL
        )


def _get_tenant_user_session_key(request):
    return get_tenant_user_model()._meta.pk.to_python(request.session[SESSION_KEY])


def get_tenant_user(request):
    """
    Return the organization user model instance associated with the given request session.
    If not user is retrieved, return an instance of modified `AnonymousUser`.
    """
    from django.contrib.auth.models import AnonymousUser

    user = None
    try:
        user_id = _get_tenant_user_session_key(request)
        backend_path = request.session[BACKEND_SESSION_KEY]
    except KeyError:
        pass
    else:
        if backend_path in settings.AUTHENTICATION_BACKENDS:
            backend = load_backend(backend_path)
            user = backend.get_user(user_id)
            # Verify the session
            if hasattr(user, 'get_session_auth_hash'):
                session_hash = request.session.get(HASH_SESSION_KEY)
                session_hash_verified = session_hash and constant_time_compare(
                    session_hash,
                    user.get_session_auth_hash()
                )
                if not session_hash_verified:
                    request.session.flush()
                    user = None
    return user or AnonymousUser()
