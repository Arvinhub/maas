# Copyright 2015-2016 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for VLAN forms."""

__all__ = []

import random

from maasserver.forms_vlan import VLANForm
from maasserver.models.vlan import DEFAULT_MTU
from maasserver.testing.factory import factory
from maasserver.testing.orm import reload_object
from maasserver.testing.testcase import MAASServerTestCase


class TestVLANForm(MAASServerTestCase):

    def test__requires_vid(self):
        fabric = factory.make_Fabric()
        form = VLANForm(fabric=fabric, data={})
        self.assertFalse(form.is_valid(), form.errors)
        self.assertEqual({
            "vid": [
                "This field is required.",
                "Vid must be between 0 and 4095.",
                ],
            }, form.errors)

    def test__creates_vlan(self):
        fabric = factory.make_Fabric()
        vlan_name = factory.make_name("vlan")
        vid = random.randint(1, 1000)
        mtu = random.randint(552, 4096)
        form = VLANForm(fabric=fabric, data={
            "name": vlan_name,
            "vid": vid,
            "mtu": mtu,
        })
        self.assertTrue(form.is_valid(), form.errors)
        vlan = form.save()
        self.assertEqual(vlan_name, vlan.name)
        self.assertEqual(vid, vlan.vid)
        self.assertEqual(fabric, vlan.fabric)
        self.assertEqual(mtu, vlan.mtu)

    def test__creates_vlan_with_default_mtu(self):
        fabric = factory.make_Fabric()
        vlan_name = factory.make_name("vlan")
        vid = random.randint(1, 1000)
        form = VLANForm(fabric=fabric, data={
            "name": vlan_name,
            "vid": vid,
        })
        self.assertTrue(form.is_valid(), form.errors)
        vlan = form.save()
        self.assertEqual(vlan_name, vlan.name)
        self.assertEqual(vid, vlan.vid)
        self.assertEqual(fabric, vlan.fabric)
        self.assertEqual(DEFAULT_MTU, vlan.mtu)

    def test__doest_require_name_vid_or_mtu_on_update(self):
        vlan = factory.make_VLAN()
        form = VLANForm(instance=vlan, data={})
        self.assertTrue(form.is_valid(), form.errors)

    def test__updates_vlan(self):
        vlan = factory.make_VLAN()
        new_name = factory.make_name("vlan")
        new_vid = random.randint(1, 1000)
        new_mtu = random.randint(552, 4096)
        form = VLANForm(instance=vlan, data={
            "name": new_name,
            "vid": new_vid,
            "mtu": new_mtu,
        })
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        self.assertEqual(new_name, reload_object(vlan).name)
        self.assertEqual(new_vid, reload_object(vlan).vid)
        self.assertEqual(new_mtu, reload_object(vlan).mtu)

    def test_update_verfies_primary_rack_is_on_vlan(self):
        vlan = factory.make_VLAN()
        rack = factory.make_RackController()
        form = VLANForm(instance=vlan, data={
            "primary_rack": rack.system_id,
        })
        self.assertFalse(form.is_valid(), form.errors)

    def test_update_sets_primary_rack(self):
        vlan = factory.make_VLAN()
        rack = factory.make_RackController(vlan=vlan)
        form = VLANForm(instance=vlan, data={
            "primary_rack": rack.system_id,
        })
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        self.assertEqual(rack, reload_object(vlan).primary_rack)

    def test_update_unsets_primary_rack(self):
        vlan = factory.make_VLAN()
        rack = factory.make_RackController(vlan=vlan)
        vlan.primary_rack = rack
        vlan.save()
        form = VLANForm(instance=vlan, data={
            "primary_rack": "",
        })
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        self.assertEqual(None, reload_object(vlan).primary_rack)

    def test_update_verfies_secondary_rack_is_on_vlan(self):
        vlan = factory.make_VLAN()
        rack = factory.make_RackController()
        form = VLANForm(instance=vlan, data={
            "secondary_rack": rack.system_id
        })
        self.assertFalse(form.is_valid(), form.errors)

    def test_update_sets_secondary_rack(self):
        vlan = factory.make_VLAN()
        rack = factory.make_RackController(vlan=vlan)
        form = VLANForm(instance=vlan, data={
            "secondary_rack": rack.system_id
        })
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        self.assertEqual(rack, reload_object(vlan).secondary_rack)

    def test_update_unsets_secondary_rack(self):
        vlan = factory.make_VLAN()
        rack = factory.make_RackController(vlan=vlan)
        vlan.secondary_rack = rack
        vlan.save()
        form = VLANForm(instance=vlan, data={
            "secondary_rack": "",
        })
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        self.assertEqual(None, reload_object(vlan).secondary_rack)

    def test_update_blank_primary_sets_to_secondary(self):
        vlan = factory.make_VLAN()
        primary_rack = factory.make_RackController(vlan=vlan)
        secondary_rack = factory.make_RackController(vlan=vlan)
        vlan.primary_rack = primary_rack
        vlan.secondary_rack = secondary_rack
        vlan.save()
        form = VLANForm(instance=reload_object(vlan), data={
            "primary_rack": "",
        })
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        vlan = reload_object(vlan)
        self.assertEqual(secondary_rack, vlan.primary_rack)
        self.assertEqual(None, vlan.secondary_rack)

    def test_update_primary_set_to_secondary_removes_secondary(self):
        vlan = factory.make_VLAN()
        primary_rack = factory.make_RackController(vlan=vlan)
        secondary_rack = factory.make_RackController(vlan=vlan)
        vlan.primary_rack = primary_rack
        vlan.secondary_rack = secondary_rack
        vlan.save()
        form = VLANForm(instance=reload_object(vlan), data={
            "primary_rack": secondary_rack.system_id,
        })
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        vlan = reload_object(vlan)
        self.assertEqual(secondary_rack, vlan.primary_rack)
        self.assertEqual(None, vlan.secondary_rack)

    def test_update_secondary_set_to_existing_primary_fails(self):
        vlan = factory.make_VLAN()
        rack = factory.make_RackController(vlan=vlan)
        vlan.primary_rack = rack
        vlan.save()
        form = VLANForm(instance=reload_object(vlan), data={
            "secondary_rack": rack.system_id,
        })
        self.assertFalse(form.is_valid())

    def test_update_setting_both_racks_to_same_fails(self):
        vlan = factory.make_VLAN()
        rack = factory.make_RackController(vlan=vlan)
        form = VLANForm(instance=vlan, data={
            "primary_rack": rack.system_id,
            "secondary_rack": rack.system_id,
        })
        self.assertFalse(form.is_valid())

    def test_update_turns_dhcp_on(self):
        vlan = factory.make_VLAN()
        factory.make_ipv4_Subnet_with_IPRanges(vlan=vlan)
        rack = factory.make_RackController(vlan=vlan)
        vlan.primary_rack = rack
        vlan.save()
        form = VLANForm(instance=reload_object(vlan), data={
            "dhcp_on": "true",
        })
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        vlan = reload_object(vlan)
        self.assertTrue(vlan.dhcp_on)

    def test_update_validates_primary_rack_with_dhcp_on(self):
        vlan = factory.make_VLAN()
        form = VLANForm(instance=vlan, data={
            "dhcp_on": "true",
        })
        self.assertFalse(form.is_valid())

    def test_update_validates_subnet_with_dhcp_on(self):
        vlan = factory.make_VLAN()
        rack = factory.make_RackController(vlan=vlan)
        vlan.primary_rack = rack
        vlan.save()
        form = VLANForm(instance=reload_object(vlan), data={
            "dhcp_on": "true",
        })
        self.assertFalse(form.is_valid())

    def test_update_can_delete_primary_and_set_dhcp_on_with_secondary(self):
        vlan = factory.make_VLAN()
        factory.make_ipv4_Subnet_with_IPRanges(vlan=vlan)
        primary_rack = factory.make_RackController(vlan=vlan)
        secondary_rack = factory.make_RackController(vlan=vlan)
        vlan.primary_rack = primary_rack
        vlan.secondary_rack = secondary_rack
        vlan.save()
        form = VLANForm(instance=reload_object(vlan), data={
            "primary_rack": "",
            "dhcp_on": "true",
        })
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        vlan = reload_object(vlan)
        self.assertEqual(secondary_rack, vlan.primary_rack)
        self.assertEqual(None, vlan.secondary_rack)
        self.assertTrue(vlan.dhcp_on)