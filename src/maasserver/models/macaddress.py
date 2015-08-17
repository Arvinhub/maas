# Copyright 2012-2015 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""MACAddress model and friends."""

from __future__ import (
    absolute_import,
    print_function,
    unicode_literals,
    )

str = None

__metaclass__ = type
__all__ = [
    'find_cluster_interface_responsible_for_ip',
    'MACAddress',
    ]

from operator import attrgetter
import re

from django.db.models import (
    ForeignKey,
    ManyToManyField,
    SET_NULL,
)
from maasserver import DefaultMeta
from maasserver.enum import (
    INTERFACE_TYPE,
    IPADDRESS_TYPE,
)
from maasserver.exceptions import (
    StaticIPAddressConflict,
    StaticIPAddressUnavailable,
)
from maasserver.fields import (
    MAC,
    MACAddressField,
)
from maasserver.models.cleansave import CleanSave
from maasserver.models.macipaddresslink import MACStaticIPAddressLink
from maasserver.models.network import Network
from maasserver.models.nodegroup import NodeGroup
from maasserver.models.nodegroupinterface import (
    NodeGroupInterface,
    raise_if_address_inside_dynamic_range,
)
from maasserver.models.staticipaddress import StaticIPAddress
from maasserver.models.timestampedmodel import TimestampedModel
from maasserver.utils import get_one
from netaddr import (
    IPAddress,
    IPRange,
)
from provisioningserver.logger import get_maas_logger


mac_re = re.compile(r'^([0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}$')
maaslog = get_maas_logger("macaddress")


def find_cluster_interface_responsible_for_ip(cluster_interfaces, ip_address):
    """Pick the cluster interface whose network contains `ip_address`.

    :param cluster_interfaces: An iterable of `NodeGroupInterface`.
    :param ip_address: An `IPAddress`.
    :return: The cluster interface from `cluster_interfaces` whose subnet
        contains `ip_address`, or `None`.
    """
    for interface in cluster_interfaces:
        if interface.network is not None and ip_address in interface.network:
            return interface
    return None


def update_mac_cluster_interfaces(ip, mac, cluster):
    """Calculate and store which interface a MAC is attached to."""
    # Create a `leases` dict with only one lease: this is so we can re-use
    # update_macs_cluster_interfaces() which is designed to deal with multiple
    # leases.
    leases = {ip: mac}
    update_macs_cluster_interfaces(leases, cluster)


def update_macs_cluster_interfaces(leases, cluster):
    """Calculate and store which interface a set of MACs are attached to."""
    interface_ranges = {}
    # Only consider configured interfaces.
    interfaces = (
        cluster.nodegroupinterface_set
        .exclude(ip_range_low__isnull=True)
        .exclude(ip_range_high__isnull=True)
    )
    # Pre-calculate a dict of interface ranges, keyed by cluster
    # interface.
    for interface in interfaces:
        ip_range = IPRange(
            interface.ip_range_low, interface.ip_range_high)
        if interface.static_ip_range_low and interface.static_ip_range_high:
            static_range = IPRange(
                interface.static_ip_range_low, interface.static_ip_range_high)
        else:
            static_range = []
        interface_ranges[interface] = (ip_range, static_range)

    for ip, mac in leases.viewitems():
        # Look through the interface ranges to see if any match the passed
        # IP address.
        try:
            mac_address = MACAddress.objects.get(mac_address=mac)
        except MACAddress.DoesNotExist:
            # Silently ignore MAC addresses that we don't know about.
            continue

        for interface, (ip_range, static_range) in interface_ranges.items():
            ipaddress = IPAddress(ip)
            # Set the cluster interface only if it's new/changed.
            # This is only an optimisation to prevent repeated logging.
            changed = mac_address.cluster_interface != interface
            if not changed:
                continue
            in_range = ipaddress in ip_range or ipaddress in static_range
            if not in_range:
                continue
            mac_address.cluster_interface = interface
            mac_address.save()
            maaslog.info(
                "%s %s linked to cluster interface %s",
                mac_address.node.hostname, mac_address, interface.name)

            # Locate the Network to which this MAC belongs and link it.
            ipnetwork = interface.network
            if ipnetwork is not None:
                try:
                    network = Network.objects.get(ip=ipnetwork.ip.format())
                except Network.DoesNotExist:
                    pass
                else:
                    network.macaddress_set.add(mac_address)


class MACAddress(CleanSave, TimestampedModel):
    """A `MACAddress` represents a `MAC address`_ attached to a :class:`Node`.

    :ivar mac_address: The MAC address.
    :ivar node: The :class:`Node` related to this `MACAddress`.
    :ivar networks: The networks related to this `MACAddress`.

    .. _MAC address: http://en.wikipedia.org/wiki/MAC_address
    """
    mac_address = MACAddressField(unique=True)
    node = ForeignKey('Node', editable=False, null=True, blank=True)

    networks = ManyToManyField('maasserver.Network', blank=True)

    ip_addresses = ManyToManyField(
        'maasserver.StaticIPAddress',
        through='maasserver.MACStaticIPAddressLink', blank=True)

    # Will be set only once we know on which cluster interface this MAC
    # is connected, normally after the first DHCPLease appears.
    cluster_interface = ForeignKey(
        'NodeGroupInterface', editable=False, blank=True, null=True,
        default=None, on_delete=SET_NULL)

    # future columns: tags, nic_name, metadata, bonding info

    class Meta(DefaultMeta):
        verbose_name = "MAC address"
        verbose_name_plural = "MAC addresses"
        ordering = ('created', )

    def __unicode__(self):
        address = self.mac_address
        if isinstance(address, MAC):
            address = address.get_raw()
        if isinstance(address, bytes):
            address = address.decode('utf-8')
        return address

    def unique_error_message(self, model_class, unique_check):
        if unique_check == ('mac_address',):
            return "This MAC address is already registered."
        return super(
            MACAddress, self).unique_error_message(model_class, unique_check)

    def get_networks(self):
        """Return networks to which this MAC is connected, sorted by name."""
        # Sort in python not using `order_by` so another query will not
        # be made if the networks where prefetched.
        return sorted(self.networks.all(), key=attrgetter('name'))

    def get_cluster_interfaces(self):
        """Return all cluster interfaces to which this MAC connects.

        This is at least its `cluster_interface`, if it is set.  But if so,
        there may also be an IPv6 cluster interface attached to the same
        network interface.
        """
        # XXX jtv 2014-08-18 bug=1358130: cluster_interface should probably be
        # an m:n relationship.  Andres came up with a simpler scheme for the
        # short term: "for IPv6, use whatever network interface on the cluster
        # also manages the node's IPv4 address."
        cluster_interface = self.get_cluster_interface()
        if cluster_interface is None:
            return []
        else:
            return NodeGroupInterface.objects.filter(
                nodegroup=cluster_interface.nodegroup,
                interface=cluster_interface.interface)

    def _map_allocated_addresses(self, cluster_interfaces):
        """Gather already allocated static IP addresses for this MAC.

        :param cluster_interfaces: Iterable of `NodeGroupInterface` where we
            may have allocated addresses.
        :return: A dict mapping each of the cluster interfaces to the MAC's
            `StaticIPAddress` on that interface (which may be `None`).
        """
        allocations = {
            interface: None
            for interface in cluster_interfaces
            }
        for sip in self.ip_addresses.all():
            interface = find_cluster_interface_responsible_for_ip(
                cluster_interfaces, IPAddress(sip.ip))
            if interface is not None:
                allocations[interface] = sip
        return allocations

    def _allocate_static_address(self, cluster_interface, alloc_type,
                                 requested_address=None, user=None):
        """Allocate a `StaticIPAddress` for this MAC."""
        # Avoid circular imports.
        from maasserver.models import (
            MACStaticIPAddressLink,
            StaticIPAddress,
            )

        new_sip = StaticIPAddress.objects.allocate_new(
            cluster_interface.network,
            cluster_interface.static_ip_range_low,
            cluster_interface.static_ip_range_high,
            cluster_interface.ip_range_low,
            cluster_interface.ip_range_high,
            alloc_type, requested_address=requested_address,
            user=user)
        MACStaticIPAddressLink(mac_address=self, ip_address=new_sip).save()
        return new_sip

    def get_cluster_interface(self):
        """Return the cluster interface for this MAC.

        For an installable node, this is the cluster interface referenced by
        self.cluster_interface (populated during commissioning).
        For an non-installable node, if self.cluster_interface is not
        explicitly specified, we fall back to the cluster interface of the
        parent's PXE MAC for the primary interface.
        """
        if self.cluster_interface is not None:
            return self.cluster_interface
        elif not self.node.installable and self.node.parent is not None:
            # As a backstop measure: if the node is non-installable, has
            # a parent and the primary MAC has no defined cluster interface:
            # use the cluster interface of the parent's PXE MAC.
            if self == self.node.get_primary_mac():
                return self.node.parent.get_pxe_mac().cluster_interface
        return None

    def get_attached_clusters_with_static_ranges(self):
        """Returns a list of cluster interfaces attached to this MAC address,
        where each cluster interface has a defined static range.
        """
        return [
            interface
            for interface in self.get_cluster_interfaces()
            if interface.get_static_ip_range()
            ]

    def _get_hostname_log_prefix(self):
        """Returns a string that represents the hostname for this MAC address,
        suitable for prepending to a log statement.
        """
        if self.node is not None:
            hostname_string = "%s: " % self.node.hostname
        else:
            hostname_string = ""
        return hostname_string

    def claim_static_ips(
            self, alloc_type=IPADDRESS_TYPE.AUTO, requested_address=None,
            fabric=None, user=None, update_host_maps=True):
        """Shim to call claim_static_ips on the Interface object related
        to this MAC.
        """
        from maasserver.models import PhysicalInterface
        interface = get_one(PhysicalInterface.objects.filter(mac=self))
        return interface.claim_static_ips(
            alloc_type, requested_address, fabric, user, update_host_maps)

    def _get_device_cluster_or_default(self):
        """Returns a cluster interface for this MAC, first by checking for a
        direct link, then by checking the parent node,
        (via get_cluster_interface()) and finally by getting the default,
        if all else fails.
        """
        cluster_interface = self.get_cluster_interface()
        if cluster_interface is not None:
            return cluster_interface.nodegroup
        else:
            return NodeGroup.objects.ensure_master()

    def update_related_dns_zones(self):
        """Updates DNS for the cluster related to this MAC."""
        # Prevent circular imports
        from maasserver.dns import config as dns_config
        dns_config.dns_update_zones([self._get_device_cluster_or_default()])

    def _get_dhcp_managed_clusters(self, fabric=None):
        """Returns the DHCP-managed clusters relevant to the specified fabric.

        :param fabric: The fabric whose DHCP-managed clusters to update.
        """
        if fabric is not None:
            raise NotImplementedError("Fabrics are not yet supported.")

        return [
            cluster
            for cluster in NodeGroup.objects.all()
            if cluster.manages_dhcp()
            ]

    def set_static_ip(
            self, requested_address, user, fabric=None, update_host_maps=True):
        """Assign a static (sticky) IP address to this MAC.

        This is meant to be called on a device's MAC address: the IP address
        can be anything. Only if the MAC is linked to a network will this
        method enforce that the IP address if part of the referenced network.

        Calls update_host_maps() on the related Node in order to update
        any DHCP mappings.

        :param requested_address: IP address to claim.  Must not be in
            the dynamic range of any cluster interface.
        :param user: User who will be given ownership of the created
            `StaticIPAddress`.
        :return: A :class:`StaticIPAddress`. If an IP address was
            already allocated, the function will return it rather than allocate
            a new one.
        :raises: StaticIPAddressForbidden if the requested_address is in a
            dynamic range.
        :raises: StaticIPAddressConflict if the MAC is connected to a cluster
            interface and the requested_address is not in the cluster's
            network.
        :raises: StaticIPAddressUnavailable if the requested_address is already
            allocated.
        """
        if fabric is not None:
            raise NotImplementedError("Fabrics are not yet supported.")

        # If this MAC is linked to a cluster interface, make sure the
        # requested_address is part of the cluster interface's network.
        cluster_interface = self.get_cluster_interface()
        if cluster_interface is not None:
            if IPAddress(requested_address) not in cluster_interface.network:
                raise StaticIPAddressConflict(
                    "Requested IP address %s is not in the network of the "
                    "related cluster interface." %
                    requested_address)

        # Raise a StaticIPAddressForbidden exception if the requested_address
        # is in a dynamic range.
        raise_if_address_inside_dynamic_range(requested_address, fabric)

        # Allocate IP if it isn't allocated already.
        if cluster_interface is None:
            maaslog.warning("set_static_ip called without a cluster_interface")
            subnet = None
        else:
            subnet = cluster_interface.subnet
        static_ip, created = StaticIPAddress.objects.get_or_create(
            ip=requested_address,
            defaults={
                'alloc_type': IPADDRESS_TYPE.STICKY,
                'user': user,
                'subnet': subnet,
            })
        if created:
            MACStaticIPAddressLink(
                mac_address=self, ip_address=static_ip).save()
        else:
            if static_ip.alloc_type != IPADDRESS_TYPE.STICKY:
                raise StaticIPAddressUnavailable(
                    "Requested IP address %s is already allocated "
                    "(with a different type)." %
                    requested_address)
            try:
                static_ip.macaddress_set.get(mac_address=self.mac_address)
            except MACAddress.DoesNotExist:
                raise StaticIPAddressUnavailable(
                    "Requested IP address %s is already allocated "
                    "to a different MAC address." %
                    requested_address)

        if update_host_maps:
            # XXX:fabric We need to restrict this to cluster interfaces in the
            # appropriate fabric!
            if cluster_interface is not None:
                relevant_clusters = [cluster_interface.nodegroup]
            else:
                relevant_clusters = self._get_dhcp_managed_clusters(fabric)

            mac_address = MAC(self.mac_address)
            ip_mapping = [(static_ip.ip, mac_address.get_raw())]

            self.node.update_host_maps(
                ip_mapping, nodegroups=relevant_clusters)
            self.update_related_dns_zones()

        return static_ip


def ensure_physical_interfaces_created():
    """Utility function to create a PhysicalInterface for every MACAddress
    in the database that is not associated with any Interface."""
    # Circular imports
    from maasserver.models import (
        Interface,
        Subnet,
        VLAN,
    )
    # Go through each MAC that does not have an associated interface.
    macs = MACAddress.objects.find_macs_having_no_interface()
    previous_node = -1
    index = 0
    for mac in macs:
        current_node = mac.node_id
        # Note: this code assumes that the query is ordered by node_id.
        if current_node != previous_node or current_node is None:
            index = 0
        else:
            index += 1
        # Create a "dummy" interface. (this is a 'legacy' MACAddress)
        iface = Interface(
            mac=mac, type=INTERFACE_TYPE.PHYSICAL,
            name='eth' + unicode(index),
            vlan=VLAN.objects.get_default_vlan()
        )
        iface.save()
        previous_node = current_node

        # Determine the Subnet that this MAC resides on, and link up any
        # related StaticIPAddresses.
        ngi = mac.cluster_interface
        if ngi is not None and ngi.subnet is not None:
            # Known cluster interface subnet.
            subnet = ngi.subnet
            for ip in mac.ip_addresses.all():
                if unicode(ip.ip) in subnet.cidr:
                    ip.subnet = subnet
                    ip.save()
                    # Since we found the Subnet, adjust the new Interface's
                    # VLAN, too.
                    _update_interface_with_subnet_vlan(iface, subnet)
                else:
                    maaslog.warning(
                        "IP address [%s] (associated with MAC [%s]) is not "
                        "within expected cluster interface subnet [%s]." %
                        (unicode(ip.ip), unicode(mac),
                         unicode(subnet.get_cidr())))
        else:
            for ip in mac.ip_addresses.all():
                # The Subnet isn't on a known cluster interface. Expand the
                # search.
                # XXX:fabric (could be a subnet that occurs in >1 fabric)
                for subnet in Subnet.objects.get_subnets_with_ip(ip.ip):
                    break
                else:
                    subnet = None
                if subnet is not None:
                    ip.subnet = subnet
                    ip.save()
                    _update_interface_with_subnet_vlan(iface, subnet)
                else:
                    maaslog.warning(
                        "A subnet known to MAAS matching IP address [%s] "
                        "(associated with MAC [%s]) could not be found." %
                        (unicode(ip.ip), unicode(mac)))


def _update_interface_with_subnet_vlan(iface, subnet):
    """Utility function to update an interface's VLAN to match a corresponding
    Subnet's VLAN.
    """
    if iface.vlan_id != subnet.vlan_id and subnet.vlan_id != 0:
        iface.vlan = subnet.vlan
        iface.save()
