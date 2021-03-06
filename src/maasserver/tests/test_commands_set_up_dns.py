# Copyright 2012-2015 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for the get_named_conf command."""

__all__ = []


import os

from django.core.management import call_command
from maasserver.testing.testcase import MAASServerTestCase
from maastesting.factory import factory
from provisioningserver.dns.config import (
    MAAS_NAMED_CONF_NAME,
    MAAS_RNDC_CONF_NAME,
)
from provisioningserver.dns.testing import patch_dns_config_path
from testtools.matchers import (
    AllMatch,
    FileContains,
    FileExists,
)


class TestSetUpDNSCommand(MAASServerTestCase):

    def test_set_up_dns_writes_configuration(self):
        dns_conf_dir = self.make_dir()
        patch_dns_config_path(self, dns_conf_dir)
        call_command('set_up_dns')
        named_config = os.path.join(dns_conf_dir, MAAS_NAMED_CONF_NAME)
        rndc_conf_path = os.path.join(dns_conf_dir, MAAS_RNDC_CONF_NAME)
        self.assertThat([rndc_conf_path, named_config], AllMatch(FileExists()))

    def test_set_up_dns_does_not_overwrite_config(self):
        dns_conf_dir = self.make_dir()
        patch_dns_config_path(self, dns_conf_dir)
        random_content = factory.make_string()
        factory.make_file(
            location=dns_conf_dir, name=MAAS_NAMED_CONF_NAME,
            contents=random_content)
        call_command('set_up_dns', no_clobber=True)
        self.assertThat(
            os.path.join(dns_conf_dir, MAAS_NAMED_CONF_NAME),
            FileContains(random_content))
