from __future__ import unicode_literals

# TODO: Remove when support for Python 2.6 is dropped
try:
    from collections import OrderedDict
except ImportError:
    from django.utils.datastructures import SortedDict as OrderedDict
from functools import wraps
from imp import reload
import logging
import sys
# TODO: Remove when support for Python 2.6 is dropped
if sys.version_info >= (2, 7):
    from unittest import skipIf
else:
    from django.utils.unittest import skipIf

from django.contrib.auth.management.commands import createsuperuser
from django.dispatch.dispatcher import receiver
from django.test.signals import setting_changed
from django.test.testcases import TransactionTestCase
from django.utils.six.moves import input

from .. import settings
from ..models import Tenant
from ..management.commands import createtenant


logger = logging.getLogger('tenancy.tests')


def skipIfCustomTenant(test):
    """
    Skip a test if a custom tenant model is in use.
    """
    return skipIf(
        settings.TENANT_MODEL != settings.DEFAULT_TENANT_MODEL,
        'Custom tenant model in use'
    )(test)


@skipIfCustomTenant
class TenancyTestCase(TransactionTestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name='tenant')
        self.other_tenant = Tenant.objects.create(name='other_tenant')

    def tearDown(self):
        for tenant in Tenant.objects.all():
            tenant.delete()

        # Remove references to tenants to allow them and their associated
        # models to be garbage collected since unittest2 suites might keep
        # references to testcases.
        # See http://bugs.python.org/issue11798 for more details.
        del self.tenant
        del self.other_tenant


def setup_custom_tenant_user(test):
    """
    Setup Django's internal with a custom tenant user for a test or skip it
    if the current Django version has no custom user support.
    """
    @wraps(test)
    def wrapped(self, *args, **kwargs):
        with self.settings(AUTH_USER_MODEL='tenancy.TenantUser'):
            from ..settings import TENANT_AUTH_USER_MODEL
            self.assertTrue(TENANT_AUTH_USER_MODEL)
            test(self, *args, **kwargs)
    return wrapped


@receiver(setting_changed)
def reload_settings_module(signal, sender, setting, value, **kwargs):
    if setting == 'AUTH_USER_MODEL' or setting.startswith('TENANCY_'):
        logger.debug(
            "Attempt reload of settings because `%s` has changed to %r." % (
                setting, value
            )
        )
        try:
            reload(settings)
        except Exception:
            logger.exception("Failed to reload the settings module.")
        else:
            logger.debug("Successfully reloaded the settings module.")


class Replier(object):
    def __init__(self, replies):
        self.replies = OrderedDict(replies)

    def __call__(self, prompt):
        for p in self.replies:
            if prompt.startswith(p):
                return self.replies[p]
        else:
            raise ValueError("No reply defined for %s" % prompt)


class GetPass(Replier):
    def __init__(self, replier):
        self.replier = replier

    def getpass(self, prompt='Password'):
        return self.replier.__call__(prompt)


def mock_inputs(inputs):
    """
    Decorator to temporarily replace input/getpass to allow interactive
    createsuperuser.
    """
    def inner(test_func):
        @wraps(test_func)
        def wrapped(*args):
            replier = Replier(inputs)
            getpass = createsuperuser.getpass
            createsuperuser.input = replier
            createsuperuser.getpass = GetPass(replier)
            createtenant.input = replier
            try:
                test_func(*args)
            finally:
                createsuperuser.input = input
                createtenant.input = input
                createsuperuser.getpass = getpass
        return wrapped
    return inner
