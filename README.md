# django-tenant-utils

django-tenant-utils is a Django app that enables global user accounts with
per-tenant permissions in multi-tenant environments and also supply some useful utilities.
It is based on [django-tenant-users](https://github.com/Corvia/django-tenant-users) and
[django-multi-tenant-users](https://github.com/bitsick/django-multi-tenant-users)
and tries to offer the best flexibility.

CAUTION: This is pre-alpha software, you may not want to use it in production environment.

## Prerequisites

django-tenant-utils is compatible with Django 2.0 and above. Python 3.5+ is supported.
It is assumed that this app will be used alongside
[django-tenants](https://github.com/tomturner/django-tenants).

## Installation

django-tenant-utils is not yet available on PyPI. You could install it directly from GitHub.

``` shell
$ pip install git+https://github.com/galeo/django-tenant-utils
```

## License

MIT License
