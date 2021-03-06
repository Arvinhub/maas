# Copyright 2016 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for the region controller service."""

__all__ = []

from unittest.mock import (
    ANY,
    call,
    MagicMock,
    sentinel,
)

from crochet import wait_for
from maasserver import region_controller
from maasserver.region_controller import RegionControllerService
from maasserver.testing.factory import factory
from maasserver.testing.testcase import MAASServerTestCase
from maastesting.matchers import (
    MockCalledOnceWith,
    MockCallsMatch,
    MockNotCalled,
)
from testtools.matchers import MatchesStructure
from twisted.internet import reactor
from twisted.internet.defer import (
    fail,
    inlineCallbacks,
    succeed,
)


wait_for_reactor = wait_for(30)  # 30 seconds.


class TestRegionControllerService(MAASServerTestCase):

    def test_init_sets_properties(self):
        service = RegionControllerService(sentinel.listener)
        self.assertThat(
            service,
            MatchesStructure.byEquality(
                clock=reactor,
                processingDefer=None,
                needsDNSUpdate=False,
                postgresListener=sentinel.listener))

    @wait_for_reactor
    @inlineCallbacks
    def test_startService_registers_with_postgres_listener(self):
        listener = MagicMock()
        service = RegionControllerService(listener)
        service.startService()
        yield service.processingDefer
        self.assertThat(
            listener.register,
            MockCallsMatch(
                call("sys_dns", service.markDNSForUpdate),
                call("sys_proxy", service.markProxyForUpdate)))

    @wait_for_reactor
    @inlineCallbacks
    def test_startService_calls_markDNSForUpdate(self):
        listener = MagicMock()
        service = RegionControllerService(listener)
        mock_markDNSForUpdate = self.patch(service, "markDNSForUpdate")
        service.startService()
        yield service.processingDefer
        self.assertThat(mock_markDNSForUpdate, MockCalledOnceWith(None, None))

    @wait_for_reactor
    @inlineCallbacks
    def test_startService_calls_markProxyForUpdate(self):
        listener = MagicMock()
        service = RegionControllerService(listener)
        mock_markProxyForUpdate = self.patch(service, "markProxyForUpdate")
        service.startService()
        yield service.processingDefer
        self.assertThat(
            mock_markProxyForUpdate, MockCalledOnceWith(None, None))

    def test_stopService_calls_unregister_on_the_listener(self):
        listener = MagicMock()
        service = RegionControllerService(listener)
        service.stopService()
        self.assertThat(
            listener.unregister,
            MockCallsMatch(
                call("sys_dns", service.markDNSForUpdate),
                call("sys_proxy", service.markProxyForUpdate)))

    @wait_for_reactor
    @inlineCallbacks
    def test_stopService_handles_canceling_processing(self):
        listener = MagicMock()
        service = RegionControllerService(listener)
        service.startProcessing()
        yield service.stopService()
        self.assertIsNone(service.processingDefer)

    def test_markDNSForUpdate_sets_needsDNSUpdate_and_starts_process(self):
        listener = MagicMock()
        service = RegionControllerService(listener)
        mock_startProcessing = self.patch(service, "startProcessing")
        service.markDNSForUpdate(None, None)
        self.assertTrue(service.needsDNSUpdate)
        self.assertThat(mock_startProcessing, MockCalledOnceWith())

    def test_markProxyForUpdate_sets_needsProxyUpdate_and_starts_process(self):
        listener = MagicMock()
        service = RegionControllerService(listener)
        mock_startProcessing = self.patch(service, "startProcessing")
        service.markProxyForUpdate(None, None)
        self.assertTrue(service.needsProxyUpdate)
        self.assertThat(mock_startProcessing, MockCalledOnceWith())

    def test_startProcessing_doesnt_call_start_when_looping_call_running(self):
        service = RegionControllerService(sentinel.listener)
        mock_start = self.patch(service.processing, "start")
        service.processing.running = True
        service.startProcessing()
        self.assertThat(mock_start, MockNotCalled())

    def test_startProcessing_calls_start_when_looping_call_not_running(self):
        service = RegionControllerService(sentinel.listener)
        mock_start = self.patch(service.processing, "start")
        service.startProcessing()
        self.assertThat(
            mock_start,
            MockCalledOnceWith(0.1, now=False))

    @wait_for_reactor
    @inlineCallbacks
    def test_process_doesnt_update_zones_when_nothing_to_process(self):
        service = RegionControllerService(sentinel.listener)
        service.needsDNSUpdate = False
        mock_dns_update_all_zones = self.patch(
            region_controller, "dns_update_all_zones")
        service.startProcessing()
        yield service.processingDefer
        self.assertThat(mock_dns_update_all_zones, MockNotCalled())

    @wait_for_reactor
    @inlineCallbacks
    def test_process_doesnt_proxy_update_config_when_nothing_to_process(self):
        service = RegionControllerService(sentinel.listener)
        service.needsProxyUpdate = False
        mock_proxy_update_config = self.patch(
            region_controller, "proxy_update_config")
        service.startProcessing()
        yield service.processingDefer
        self.assertThat(mock_proxy_update_config, MockNotCalled())

    @wait_for_reactor
    @inlineCallbacks
    def test_process_stops_processing(self):
        service = RegionControllerService(sentinel.listener)
        service.needsDNSUpdate = False
        service.startProcessing()
        yield service.processingDefer
        self.assertIsNone(service.processingDefer)

    @wait_for_reactor
    @inlineCallbacks
    def test_process_updates_zones(self):
        service = RegionControllerService(sentinel.listener)
        service.needsDNSUpdate = True
        mock_dns_update_all_zones = self.patch(
            region_controller, "dns_update_all_zones")
        mock_msg = self.patch(
            region_controller.log, "msg")
        service.startProcessing()
        yield service.processingDefer
        self.assertThat(mock_dns_update_all_zones, MockCalledOnceWith())
        self.assertThat(
            mock_msg,
            MockCalledOnceWith("Successfully configured DNS."))

    @wait_for_reactor
    @inlineCallbacks
    def test_process_updates_proxy(self):
        service = RegionControllerService(sentinel.listener)
        service.needsProxyUpdate = True
        mock_proxy_update_config = self.patch(
            region_controller, "proxy_update_config")
        mock_proxy_update_config.return_value = succeed(None)
        mock_msg = self.patch(
            region_controller.log, "msg")
        service.startProcessing()
        yield service.processingDefer
        self.assertThat(
            mock_proxy_update_config, MockCalledOnceWith(reload_proxy=True))
        self.assertThat(
            mock_msg,
            MockCalledOnceWith("Successfully configured proxy."))

    @wait_for_reactor
    @inlineCallbacks
    def test_process_updates_zones_logs_failure(self):
        service = RegionControllerService(sentinel.listener)
        service.needsDNSUpdate = True
        mock_dns_update_all_zones = self.patch(
            region_controller, "dns_update_all_zones")
        mock_dns_update_all_zones.side_effect = factory.make_exception()
        mock_err = self.patch(
            region_controller.log, "err")
        service.startProcessing()
        yield service.processingDefer
        self.assertThat(mock_dns_update_all_zones, MockCalledOnceWith())
        self.assertThat(
            mock_err,
            MockCalledOnceWith(ANY, "Failed configuring DNS."))

    @wait_for_reactor
    @inlineCallbacks
    def test_process_updates_proxy_logs_failure(self):
        service = RegionControllerService(sentinel.listener)
        service.needsProxyUpdate = True
        mock_proxy_update_config = self.patch(
            region_controller, "proxy_update_config")
        mock_proxy_update_config.return_value = fail(factory.make_exception())
        mock_err = self.patch(
            region_controller.log, "err")
        service.startProcessing()
        yield service.processingDefer
        self.assertThat(
            mock_proxy_update_config, MockCalledOnceWith(reload_proxy=True))
        self.assertThat(
            mock_err,
            MockCalledOnceWith(ANY, "Failed configuring proxy."))

    @wait_for_reactor
    @inlineCallbacks
    def test_process_updates_bind_and_proxy(self):
        service = RegionControllerService(sentinel.listener)
        service.needsDNSUpdate = True
        service.needsProxyUpdate = True
        mock_dns_update_all_zones = self.patch(
            region_controller, "dns_update_all_zones")
        mock_proxy_update_config = self.patch(
            region_controller, "proxy_update_config")
        mock_proxy_update_config.return_value = succeed(None)
        service.startProcessing()
        yield service.processingDefer
        self.assertThat(
            mock_dns_update_all_zones, MockCalledOnceWith())
        self.assertThat(
            mock_proxy_update_config, MockCalledOnceWith(reload_proxy=True))
