from django.dispatch import Signal


# An existing user removed from a tenant
tenant_user_removed = Signal(providing_args=["user", "tenant"])

# An existing user added to a tenant
tenant_user_added = Signal(providing_args=["user", "tenant"])

# An existing user is connected to a tenant user
tenant_user_connected = Signal(providing_args=["user", "tenant", "tenant_user"])

# An existing user is disconnected from a tenant user
tenant_user_disconnected = Signal(providing_args=["user", "tenant", "tenant_user"])

# A new user is created
tenant_user_created = Signal(providing_args=["user"])

# An existing user is deleted
tenant_user_deleted = Signal(providing_args=["user"])
