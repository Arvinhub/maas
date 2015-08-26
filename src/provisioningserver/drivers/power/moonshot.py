# Copyright 2015 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Moonshot IPMI Power Driver."""

from __future__ import (
    absolute_import,
    print_function,
    unicode_literals,
    )

str = None

__metaclass__ = type
__all__ = []


from provisioningserver.drivers.power import (
    PowerActionError,
    PowerDriver,
    PowerFatalError,
)
from provisioningserver.utils.shell import (
    call_and_check,
    ExternalProcessError,
)


class MoonshotIPMIPowerDriver(PowerDriver):

    name = 'moonshot'
    description = "Moonshot IPMI Power Driver."
    settings = []

    def _issue_ipmitool_command(
            self, power_change, power_hwaddress=None, power_address=None,
            power_user=None, power_pass=None, ipmitool=None, **extra):
        command = (
            ipmitool, '-I', 'lanplus', '-H', power_address, '-U', power_user,
            '-P', power_pass, power_hwaddress, 'power', power_change
        )
        try:
            output = call_and_check(command)
        except ExternalProcessError as e:
            raise PowerFatalError(
                "Failed to power %s %s: %s" % (
                    power_change, power_hwaddress, e.output_as_unicode))
        else:
            if 'on' in output:
                return 'on'
            elif 'off' in output:
                return 'off'
            else:
                raise PowerActionError(
                    "Got unknown power state from ipmipower: %s" % output)

    def power_on(self, system_id, **kwargs):
        self._issue_ipmitool_command('on', **kwargs)

    def power_off(self, system_id, **kwargs):
        self._issue_ipmitool_command('off', **kwargs)

    def power_query(self, system_id, **kwargs):
        return self._issue_ipmitool_command('status', **kwargs)
