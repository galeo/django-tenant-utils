from django.dispatch import Signal


# An existing user removed from a tenant
tenant_user_removed = Signal(providing_args=["user", "tenant"])

# An existing user added to a tenant
tenant_user_added = Signal(providing_args=["user", "tenant"])

# A new user is created
tenant_user_created = Signal(providing_args=["user"])

# An existing user is deleted
tenant_user_deleted = Signal(providing_args=["user"])
