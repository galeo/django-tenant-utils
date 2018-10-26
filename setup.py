import os
from setuptools import setup

def read(filename):
    return open(os.path.join(os.path.dirname(__file__), filename)).read()


setup(
    name='django-tenant-utils',
    version='0.1.0',
    license='MIT License',

    description='A django app to extend django-tenants to incorporate global users',
    long_description=read('README.md'),
    author='Yuwei Tian',
    author_email='ibluefocus@gmail.com',
    url='https://github.com/galeo/django-tenant-utils',

    packages=['tenant_utils'],
    include_package_data=True,
    install_requires=[
        'Django >= 1.11'
    ],

    keywords='django tenants django-tenants',
    classifiers=[
        'Environment :: Web Environment',
        'Framework :: Django',
        'Framework :: Django :: 1.11',
        'Framework :: Django :: 2.0',
        'Framework :: Django :: 2.1',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: MIT License',
        'Operation System :: OS Independent',
        'Programming Language :: Python',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.5',
        'Programming Language :: Python :: 3.6',
        'Programming Language :: Python :: 3.7',
        'Topic :: Internet :: WWW/HTTP',
        'Topic :: Internet :: WWW/HTTP :: Dynamic Content',
    ]
)
