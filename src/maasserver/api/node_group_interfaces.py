# Copyright 2014 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""API handlers: `NodeGroupInterface`."""

from __future__ import (
    absolute_import,
    print_function,
    unicode_literals,
    )

str = None

__metaclass__ = type
__all__ = [
    'NodeGroupInterfaceHandler',
    'NodeGroupInterfacesHandler',
    ]


from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404
from maasserver.api.node_groups import check_nodegroup_access
from maasserver.api.support import (
    operation,
    OperationsHandler,
    )
from maasserver.api.utils import get_mandatory_param
from maasserver.forms import (
    NodeGroupInterfaceForeignDHCPForm,
    NodeGroupInterfaceForm,
    )
from maasserver.models import (
    NodeGroup,
    NodeGroupInterface,
    )
from piston.utils import rc


DISPLAYED_NODEGROUPINTERFACE_FIELDS = (
    'name',
    'ip',
    'management',
    'interface',
    'subnet_mask',
    'broadcast_ip',
    'ip_range_low',
    'ip_range_high',
    'static_ip_range_low',
    'static_ip_range_high',
    )


class NodeGroupInterfacesHandler(OperationsHandler):
    """Manage the collection of all the NodeGroupInterfaces in this MAAS.

    A NodeGroupInterface is a network interface attached to a cluster
    controller, with its network properties.
    """
    api_doc_section_name = "Nodegroup interfaces"

    create = read = update = delete = None
    fields = DISPLAYED_NODEGROUPINTERFACE_FIELDS

    @operation(idempotent=True)
    def list(self, request, uuid):
        """List of NodeGroupInterfaces of a NodeGroup."""
        nodegroup = get_object_or_404(NodeGroup, uuid=uuid)
        if not request.user.is_superuser:
            check_nodegroup_access(request, nodegroup)
        return NodeGroupInterface.objects.filter(nodegroup=nodegroup)

    @operation(idempotent=False)
    def new(self, request, uuid):
        """Create a new NodeGroupInterface for this NodeGroup.

        :param name: Name for the interface.  Must be unique within this
            cluster.  Only letters, digits, dashes, and colons are allowed.
        :param ip: Static IP of the interface.
        :type ip: unicode (IP Address)
        :param interface: Name of the network interface that connects the
            cluster controller to this network.
        :type interface: unicode
        :param management: The service(s) MAAS should manage on this interface.
        :type management: Vocabulary `NODEGROUPINTERFACE_MANAGEMENT`
        :param subnet_mask: Subnet mask, e.g. 255.0.0.0.
        :type subnet_mask: unicode (IP Address)
        :param broadcast_ip: Broadcast address for this subnet.
        :type broadcast_ip: unicode (IP Address)
        :param router_ip: Address of default gateway.
        :type router_ip: unicode (IP Address)
        :param ip_range_low: Lowest dynamic IP address to assign to clients.
        :type ip_range_low: unicode (IP Address)
        :param ip_range_high: Highest dynamic IP address to assign to clients.
        :type ip_range_high: unicode (IP Address)
        :param static_ip_range_low: Lowest static IP address to assign to
            clients.
        :type static_ip_range_low: unicode (IP Address)
        :param static_ip_range_high: Highest static IP address to assign to
            clients.
        :type static_ip_range_high: unicode (IP Address)
        """
        nodegroup = get_object_or_404(NodeGroup, uuid=uuid)
        if not request.user.is_superuser:
            check_nodegroup_access(request, nodegroup)
        instance = NodeGroupInterface(nodegroup=nodegroup)
        form = NodeGroupInterfaceForm(request.data, instance=instance)
        if form.is_valid():
            return form.save()
        else:
            raise ValidationError(form.errors)

    @classmethod
    def resource_uri(cls, nodegroup=None):
        if nodegroup is None:
            uuid = 'uuid'
        else:
            uuid = nodegroup.uuid
        return ('nodegroupinterfaces_handler', [uuid])


class NodeGroupInterfaceHandler(OperationsHandler):
    """Manage a NodeGroupInterface.

    A NodeGroupInterface is identified by the uuid for its NodeGroup, and
    the name of the network interface it represents: "eth0" for example.
    """
    api_doc_section_name = "Nodegroup interface"

    create = delete = None
    fields = DISPLAYED_NODEGROUPINTERFACE_FIELDS

    def get_interface(self, request, uuid, name):
        """Return the :class:`NodeGroupInterface` indicated by the request.

        Will check for not-found errors, as well as the user's permission to
        perform the request's operation on the nodegroup.
        """
        nodegroup = get_object_or_404(NodeGroup, uuid=uuid)
        if not request.user.is_superuser:
            check_nodegroup_access(request, nodegroup)
        nodegroupinterface = get_object_or_404(
            NodeGroupInterface, nodegroup=nodegroup, name=name)
        return nodegroupinterface

    def read(self, request, uuid, name):
        """List of NodeGroupInterfaces of a NodeGroup."""
        return self.get_interface(request, uuid, name)

    def update(self, request, uuid, name):
        """Update a specific NodeGroupInterface.

        :param name: Identifying name for the cluster interface.
        :param ip: Static IP of the interface.
        :type ip: unicode (IP Address)
        :param interface: Network interface.
        :type interface: unicode
        :param management: The service(s) MAAS should manage on this interface.
        :type management: Vocabulary `NODEGROUPINTERFACE_MANAGEMENT`
        :param subnet_mask: Subnet mask, e.g. 255.0.0.0.
        :type subnet_mask: unicode (IP Address)
        :param broadcast_ip: Broadcast address for this subnet.
        :type broadcast_ip: unicode (IP Address)
        :param router_ip: Address of default gateway.
        :type router_ip: unicode (IP Address)
        :param ip_range_low: Lowest dynamic IP address to assign to clients.
        :type ip_range_low: unicode (IP Address)
        :param ip_range_high: Highest dynamic IP address to assign to clients.
        :type ip_range_high: unicode (IP Address)
        :param static_ip_range_low: Lowest static IP address to assign to
            clients.
        :type static_ip_range_low: unicode (IP Address)
        :param static_ip_range_high: Highest static IP address to assign to
            clients.
        :type static_ip_range_high: unicode (IP Address)
        """
        nodegroupinterface = self.get_interface(request, uuid, name)
        form = NodeGroupInterfaceForm(
            request.data, instance=nodegroupinterface)
        if form.is_valid():
            return form.save()
        else:
            raise ValidationError(form.errors)

    def delete(self, request, uuid, name):
        """Delete a specific NodeGroupInterface."""
        nodegroupinterface = self.get_interface(request, uuid, name)
        nodegroupinterface.delete()
        return rc.DELETED

    @operation(idempotent=False)
    def report_foreign_dhcp(self, request, uuid, name):
        """Report the result of a probe for foreign DHCP servers.

        Cluster controllers probe for DHCP servers not managed by MAAS, and
        call this method to report their findings.

        :param foreign_dhcp_ip: New value for the foreign DHCP server found
            during the last probe.  Leave blank if none were found.
        """
        foreign_dhcp_ip = get_mandatory_param(request.data, 'foreign_dhcp_ip')
        nodegroupinterface = self.get_interface(request, uuid, name)

        form = NodeGroupInterfaceForeignDHCPForm(
            {'foreign_dhcp_ip': foreign_dhcp_ip}, instance=nodegroupinterface)
        if not form.is_valid():
            raise ValidationError(form.errors)
        else:
            return form.save()

    @classmethod
    def resource_uri(cls, nodegroup=None, interface=None):
        if nodegroup is None:
            uuid = 'uuid'
        else:
            uuid = nodegroup.uuid
        if interface is None:
            interface_name = 'name'
        else:
            interface_name = interface.name
        return ('nodegroupinterface_handler', [uuid, interface_name])
