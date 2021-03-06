# Copyright 2012-2016 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for the maastftp Twisted plugin."""

__all__ = []

from functools import partial
import json
import os
import random
import re
from socket import (
    AF_INET,
    AF_INET6,
)
from unittest.mock import (
    ANY,
    Mock,
    sentinel,
)

from maastesting.factory import factory
from maastesting.matchers import (
    MockCalledOnceWith,
    MockNotCalled,
)
from maastesting.testcase import (
    MAASTestCase,
    MAASTwistedRunTest,
)
from maastesting.twisted import TwistedLoggerFixture
from netaddr import IPNetwork
from netaddr.ip import (
    IPV4_LINK_LOCAL,
    IPV6_LINK_LOCAL,
)
from provisioningserver.boot import BytesReader
from provisioningserver.boot.pxe import PXEBootMethod
from provisioningserver.boot.tests.test_pxe import compose_config_path
from provisioningserver.events import EVENT_TYPES
from provisioningserver.rackdservices import tftp as tftp_module
from provisioningserver.rackdservices.tftp import (
    get_boot_image,
    log_request,
    Port,
    TFTPBackend,
    TFTPService,
    UDPServer,
)
from provisioningserver.rpc.exceptions import BootConfigNoResponse
from provisioningserver.rpc.region import GetBootConfig
from provisioningserver.testing.boot_images import (
    make_boot_image_params,
    make_image,
)
from provisioningserver.testing.config import ClusterConfigurationFixture
from provisioningserver.tests.test_kernel_opts import make_kernel_parameters
from testtools import ExpectedException
from testtools.matchers import (
    AfterPreprocessing,
    AllMatch,
    Equals,
    HasLength,
    IsInstance,
    MatchesAll,
    MatchesStructure,
)
from tftp.backend import IReader
from tftp.errors import (
    BackendError,
    FileNotFound,
)
from tftp.protocol import TFTP
from twisted.application import internet
from twisted.application.service import MultiService
from twisted.internet import reactor
from twisted.internet.address import (
    IPv4Address,
    IPv6Address,
)
from twisted.internet.defer import (
    fail,
    inlineCallbacks,
    succeed,
)
from twisted.internet.protocol import Protocol
from twisted.internet.task import Clock
from twisted.python import context
from zope.interface.verify import verifyObject


class TestGetBootImage(MAASTestCase):
    """Tests for `get_boot_image`."""

    def make_boot_image(self, params, purpose, subarch=None, subarches=None):
        image = make_image(params, purpose)
        if subarch is not None:
            image["subarchitecture"] = subarch
        if subarches is not None:
            image["supported_subarches"] = subarches
        return image

    def make_all_boot_images(
            self, return_purpose, subarch=None, subarches=None):
        params = make_boot_image_params()
        images = []
        return_image = None
        all_purposes = ["commissioning", "xinstall", "install"]
        for purpose in all_purposes:
            image = self.make_boot_image(
                params, purpose, subarch=subarch, subarches=subarches)
            if purpose == return_purpose:
                return_image = image
            images.append(image)
        return images, return_image

    def patch_list_boot_images(self, images):
        self.patch(tftp_module, "list_boot_images").return_value = images

    def get_params_from_boot_image(self, image):
        return {
            "osystem": image["osystem"],
            "release": image["release"],
            "arch": image["architecture"],
            "subarch": image["subarchitecture"],
            "purpose": image["purpose"],
        }

    def test_returns_commissioning_image_for_enlist(self):
        images, expected_image = self.make_all_boot_images("commissioning")
        self.patch_list_boot_images(images)
        params = self.get_params_from_boot_image(expected_image)
        params["purpose"] = "enlist"
        self.assertEquals(expected_image, get_boot_image(params))

    def test_returns_commissioning_image_for_commissioning(self):
        images, expected_image = self.make_all_boot_images("commissioning")
        self.patch_list_boot_images(images)
        params = self.get_params_from_boot_image(expected_image)
        self.assertEquals(expected_image, get_boot_image(params))

    def test_returns_xinstall_image_for_xinstall(self):
        images, expected_image = self.make_all_boot_images("xinstall")
        self.patch_list_boot_images(images)
        params = self.get_params_from_boot_image(expected_image)
        self.assertEquals(expected_image, get_boot_image(params))

    def test_returns_install_image_for_install(self):
        images, expected_image = self.make_all_boot_images("install")
        self.patch_list_boot_images(images)
        params = self.get_params_from_boot_image(expected_image)
        self.assertEquals(expected_image, get_boot_image(params))

    def test_returns_image_by_its_supported_subarches(self):
        subarch = factory.make_name("hwe")
        other_subarches = [
            factory.make_name("hwe")
            for _ in range(3)
        ]
        subarches = ",".join(other_subarches + [subarch])
        images, expected_image = self.make_all_boot_images(
            "commissioning", subarch="generic", subarches=subarches)
        self.patch_list_boot_images(images)
        params = self.get_params_from_boot_image(expected_image)
        params["subarch"] = subarch
        self.assertEquals(expected_image, get_boot_image(params))

    def test_returns_None_if_missing_image(self):
        images, _ = self.make_all_boot_images(None)
        self.patch_list_boot_images(images)
        self.assertIsNone(get_boot_image({
            "osystem": factory.make_name("os"),
            "release": factory.make_name("release"),
            "arch": factory.make_name("arch"),
            "subarch": factory.make_name("subarch"),
            "purpose": factory.make_name("purpose"),
        }))


class TestBytesReader(MAASTestCase):
    """Tests for `BytesReader`."""

    def test_interfaces(self):
        reader = BytesReader(b"")
        self.addCleanup(reader.finish)
        verifyObject(IReader, reader)

    def test_read(self):
        data = factory.make_string(size=10).encode("ascii")
        reader = BytesReader(data)
        self.addCleanup(reader.finish)
        self.assertEqual(data[:7], reader.read(7))
        self.assertEqual(data[7:], reader.read(7))
        self.assertEqual(b"", reader.read(7))

    def test_finish(self):
        reader = BytesReader(b"1234")
        reader.finish()
        self.assertRaises(ValueError, reader.read, 1)


class TestTFTPBackend(MAASTestCase):
    """Tests for `TFTPBackend`."""

    run_tests_with = MAASTwistedRunTest.make_factory(timeout=5)

    def setUp(self):
        super(TestTFTPBackend, self).setUp()
        self.useFixture(ClusterConfigurationFixture())
        from provisioningserver import boot
        self.patch(boot, "find_mac_via_arp")
        self.patch(tftp_module, 'log_request')

    def test_init(self):
        temp_dir = self.make_dir()
        client_service = Mock()
        backend = TFTPBackend(temp_dir, client_service)
        self.assertEqual((True, False), (backend.can_read, backend.can_write))
        self.assertEqual(temp_dir, backend.base.path)
        self.assertEqual(client_service, backend.client_service)

    def get_reader(self, data):
        temp_file = self.make_file(name="example", contents=data)
        temp_dir = os.path.dirname(temp_file)
        backend = TFTPBackend(temp_dir, Mock())
        return backend.get_reader(b"example")

    @inlineCallbacks
    def test_get_reader_regular_file(self):
        # TFTPBackend.get_reader() returns a regular FilesystemReader for
        # paths not matching re_config_file.
        self.patch(tftp_module, 'get_remote_mac')
        data = factory.make_string().encode("ascii")
        reader = yield self.get_reader(data)
        self.addCleanup(reader.finish)
        self.assertEqual(len(data), reader.size)
        self.assertEqual(data, reader.read(len(data)))
        self.assertEqual(b"", reader.read(1))

    @inlineCallbacks
    def test_get_reader_handles_backslashes_in_path(self):
        self.patch(tftp_module, 'get_remote_mac')

        data = factory.make_string().encode("ascii")
        temp_dir = self.make_dir()
        subdir = factory.make_name('subdir')
        filename = factory.make_name('file')
        os.mkdir(os.path.join(temp_dir, subdir))
        factory.make_file(os.path.join(temp_dir, subdir), filename, data)

        path = ('\\%s\\%s' % (subdir, filename)).encode("ascii")
        backend = TFTPBackend(
            temp_dir, "http://nowhere.example.com/")
        reader = yield backend.get_reader(path)

        self.addCleanup(reader.finish)
        self.assertEqual(len(data), reader.size)
        self.assertEqual(data, reader.read(len(data)))
        self.assertEqual(b"", reader.read(1))

    @inlineCallbacks
    def test_get_reader_logs_node_event_with_mac_address(self):
        mac_address = factory.make_mac_address()
        self.patch(tftp_module, 'get_remote_mac').return_value = mac_address
        data = factory.make_string().encode("ascii")
        reader = yield self.get_reader(data)
        self.addCleanup(reader.finish)
        self.assertThat(
            tftp_module.log_request,
            MockCalledOnceWith(mac_address, ANY))

    @inlineCallbacks
    def test_get_reader_does_not_log_when_mac_cannot_be_found(self):
        self.patch(tftp_module, 'get_remote_mac').return_value = None
        data = factory.make_string().encode("ascii")
        reader = yield self.get_reader(data)
        self.addCleanup(reader.finish)
        self.assertThat(
            tftp_module.log_request,
            MockNotCalled())

    @inlineCallbacks
    def test_get_reader_converts_BootConfigNoResponse_to_FileNotFound(self):
        client = Mock()
        client.localIdent = factory.make_name("system_id")
        client.return_value = fail(BootConfigNoResponse())
        client_service = Mock()
        client_service.getClientNow.return_value = succeed(client)
        backend = TFTPBackend(
            self.make_dir(), client_service)

        with ExpectedException(FileNotFound):
            yield backend.get_reader(b'pxelinux.cfg/default')

    @inlineCallbacks
    def test_get_reader_converts_other_exceptions_to_tftp_error(self):
        exception_type = factory.make_exception_type()
        exception_message = factory.make_string()
        client = Mock()
        client.localIdent = factory.make_name("system_id")
        client.return_value = fail(exception_type(exception_message))
        client_service = Mock()
        client_service.getClientNow.return_value = succeed(client)
        backend = TFTPBackend(
            self.make_dir(), client_service)

        with TwistedLoggerFixture() as logger:
            with ExpectedException(BackendError, re.escape(exception_message)):
                yield backend.get_reader(b'pxelinux.cfg/default')

        # The original exception is logged.
        self.assertDocTestMatches(
            """\
            TFTP back-end failed.
            Traceback (most recent call last):
            ...
            maastesting.factory.TestException#...
            """,
            logger.output)

    @inlineCallbacks
    def _test_get_render_file(self, local, remote):
        # For paths matching PXEBootMethod.match_path, TFTPBackend.get_reader()
        # returns a Deferred that will yield a BytesReader.
        mac = factory.make_mac_address("-")
        config_path = compose_config_path(mac)
        backend = TFTPBackend(
            self.make_dir(), Mock())
        # python-tx-tftp sets up call context so that backends can discover
        # more about the environment in which they're running.
        call_context = {"local": local, "remote": remote}

        @partial(self.patch, backend, "get_boot_method_reader")
        def get_boot_method_reader(boot_method, params):
            params_json = json.dumps(params).encode("ascii")
            params_json_reader = BytesReader(params_json)
            return succeed(params_json_reader)

        reader = yield context.call(
            call_context, backend.get_reader, config_path)
        output = reader.read(10000).decode("ascii")
        # The addresses provided by python-tx-tftp in the call context are
        # passed over the wire as address:port strings.
        expected_params = {
            "mac": mac,
            "local_ip": call_context["local"][0],  # address only.
            "remote_ip": call_context["remote"][0],  # address only.
            "bios_boot_method": "pxe",
            }
        observed_params = json.loads(output)
        self.assertEqual(expected_params, observed_params)

    def test_get_render_file_with_ipv4_hosts(self):
        return self._test_get_render_file(
            local=(
                factory.make_ipv4_address(),
                factory.pick_port()),
            remote=(
                factory.make_ipv4_address(),
                factory.pick_port()),
        )

    def test_get_render_file_with_ipv6_hosts(self):
        # Some versions of Twisted have the scope and flow info in the remote
        # address tuple. See https://twistedmatrix.com/trac/ticket/6826 (the
        # address is captured by tftp.protocol.TFTP.dataReceived).
        return self._test_get_render_file(
            local=(
                factory.make_ipv6_address(),
                factory.pick_port(),
                random.randint(1, 1000),
                random.randint(1, 1000)),
            remote=(
                factory.make_ipv6_address(),
                factory.pick_port(),
                random.randint(1, 1000),
                random.randint(1, 1000)),
        )

    @inlineCallbacks
    def test_get_boot_method_reader_returns_rendered_params(self):
        # Fake configuration parameters, as discovered from the file path.
        fake_params = {"mac": factory.make_mac_address("-")}
        # Fake kernel configuration parameters, as returned from the RPC call.
        fake_kernel_params = make_kernel_parameters()
        fake_params = fake_kernel_params._asdict()

        # Stub the output of list_boot_images so the label is set in the
        # kernel parameters.
        boot_image = {
            "osystem": fake_params["osystem"],
            "release": fake_params["release"],
            "architecture": fake_params["arch"],
            "subarchitecture": fake_params["subarch"],
            "purpose": fake_params["purpose"],
            "supported_subarches": "",
            "label": fake_params["label"],
        }
        self.patch(tftp_module, "list_boot_images").return_value = [boot_image]
        del fake_params["label"]

        # Stub RPC call to return the fake configuration parameters.
        client = Mock()
        client.localIdent = factory.make_name("system_id")
        client.return_value = succeed(fake_params)
        client_service = Mock()
        client_service.getClientNow.return_value = succeed(client)

        # get_boot_method_reader() takes a dict() of parameters and returns an
        # `IReader` of a PXE configuration, rendered by
        # `PXEBootMethod.get_reader`.
        backend = TFTPBackend(
            self.make_dir(), client_service)

        # Stub get_reader to return the render parameters.
        method = PXEBootMethod()
        fake_render_result = factory.make_name("render").encode("utf-8")
        render_patch = self.patch(method, "get_reader")
        render_patch.return_value = BytesReader(fake_render_result)

        # Get the rendered configuration, which will actually be a JSON dump
        # of the render-time parameters.
        params_with_ip = dict(fake_params)
        params_with_ip['remote_ip'] = factory.make_ipv4_address()
        reader = yield backend.get_boot_method_reader(method, params_with_ip)
        self.addCleanup(reader.finish)
        self.assertIsInstance(reader, BytesReader)
        output = reader.read(10000)

        # The result has been rendered by `method.get_reader`.
        self.assertEqual(fake_render_result, output)
        self.assertThat(method.get_reader, MockCalledOnceWith(
            backend, kernel_params=fake_kernel_params, **params_with_ip))

    @inlineCallbacks
    def test_get_boot_method_reader_returns_rendered_params_for_local(self):
        # Fake configuration parameters, as discovered from the file path.
        fake_params = {"mac": factory.make_mac_address("-")}
        # Fake kernel configuration parameters, as returned from the RPC call.
        fake_kernel_params = make_kernel_parameters(
            purpose="local", label="local")
        fake_params = fake_kernel_params._asdict()
        del fake_params["label"]

        # Stub RPC call to return the fake configuration parameters.
        client = Mock()
        client.localIdent = factory.make_name("system_id")
        client.return_value = succeed(fake_params)
        client_service = Mock()
        client_service.getClientNow.return_value = succeed(client)

        # get_boot_method_reader() takes a dict() of parameters and returns an
        # `IReader` of a PXE configuration, rendered by
        # `PXEBootMethod.get_reader`.
        backend = TFTPBackend(
            self.make_dir(), client_service)

        # Stub get_reader to return the render parameters.
        method = PXEBootMethod()
        fake_render_result = factory.make_name("render").encode("utf-8")
        render_patch = self.patch(method, "get_reader")
        render_patch.return_value = BytesReader(fake_render_result)

        # Get the rendered configuration, which will actually be a JSON dump
        # of the render-time parameters.
        params_with_ip = dict(fake_params)
        params_with_ip['remote_ip'] = factory.make_ipv4_address()
        reader = yield backend.get_boot_method_reader(method, params_with_ip)
        self.addCleanup(reader.finish)
        self.assertIsInstance(reader, BytesReader)
        output = reader.read(10000)

        # The result has been rendered by `method.get_reader`.
        self.assertEqual(fake_render_result, output)
        self.assertThat(method.get_reader, MockCalledOnceWith(
            backend, kernel_params=fake_kernel_params, **params_with_ip))

    @inlineCallbacks
    def test_get_boot_method_reader_returns_no_image(self):
        # Fake configuration parameters, as discovered from the file path.
        fake_params = {"mac": factory.make_mac_address("-")}
        # Fake kernel configuration parameters, as returned from the RPC call.
        fake_kernel_params = make_kernel_parameters(label='no-such-image')
        fake_params = fake_kernel_params._asdict()

        # Stub the output of list_boot_images so no images exist.
        self.patch(tftp_module, "list_boot_images").return_value = []
        del fake_params["label"]

        # Stub RPC call to return the fake configuration parameters.
        client = Mock()
        client.localIdent = factory.make_name("system_id")
        client.return_value = succeed(fake_params)
        client_service = Mock()
        client_service.getClientNow.return_value = succeed(client)

        # get_boot_method_reader() takes a dict() of parameters and returns an
        # `IReader` of a PXE configuration, rendered by
        # `PXEBootMethod.get_reader`.
        backend = TFTPBackend(
            self.make_dir(), client_service)

        # Stub get_reader to return the render parameters.
        method = PXEBootMethod()
        fake_render_result = factory.make_name("render").encode("utf-8")
        render_patch = self.patch(method, "get_reader")
        render_patch.return_value = BytesReader(fake_render_result)

        # Get the rendered configuration, which will actually be a JSON dump
        # of the render-time parameters.
        params_with_ip = dict(fake_params)
        params_with_ip['remote_ip'] = factory.make_ipv4_address()
        reader = yield backend.get_boot_method_reader(method, params_with_ip)
        self.addCleanup(reader.finish)
        self.assertIsInstance(reader, BytesReader)
        output = reader.read(10000)

        # The result has been rendered by `method.get_reader`.
        self.assertEqual(fake_render_result, output)
        self.assertThat(method.get_reader, MockCalledOnceWith(
            backend, kernel_params=fake_kernel_params, **params_with_ip))

    @inlineCallbacks
    def test_get_boot_method_render_substitutes_armhf_in_params(self):
        # get_config_reader() should substitute "arm" for "armhf" in the
        # arch field of the parameters (mapping from pxe to maas
        # namespace).
        config_path = b"pxelinux.cfg/default-arm"
        backend = TFTPBackend(
            self.make_dir(), "http://example.com/")
        # python-tx-tftp sets up call context so that backends can discover
        # more about the environment in which they're running.
        call_context = {
            "local": (
                factory.make_ipv4_address(),
                factory.pick_port()),
            "remote": (
                factory.make_ipv4_address(),
                factory.pick_port()),
            }

        @partial(self.patch, backend, "get_boot_method_reader")
        def get_boot_method_reader(boot_method, params):
            params_json = json.dumps(params).encode("ascii")
            params_json_reader = BytesReader(params_json)
            return succeed(params_json_reader)

        reader = yield context.call(
            call_context, backend.get_reader, config_path)
        output = reader.read(10000).decode("ascii")
        observed_params = json.loads(output)
        # XXX: GavinPanella 2015-11-25 bug=1519804: get_by_pxealias() on
        # ArchitectureRegistry is not stable, so we permit either here.
        self.assertIn(observed_params["arch"], ["armhf", "arm64"])

    def test_get_kernel_params_filters_out_unnecessary_arguments(self):
        params_okay = {
            name.decode("ascii"): factory.make_name("value")
            for name, _ in GetBootConfig.arguments
        }
        params_other = {
            factory.make_name("name"): factory.make_name("value")
            for _ in range(3)
        }
        params_all = params_okay.copy()
        params_all.update(params_other)

        client = Mock()
        client.localIdent = params_okay["system_id"]
        client_service = Mock()
        client_service.getClientNow.return_value = succeed(client)

        backend = TFTPBackend(self.make_dir(), client_service)
        backend.fetcher = Mock()

        backend.get_kernel_params(params_all)

        self.assertThat(
            backend.fetcher, MockCalledOnceWith(
                client, GetBootConfig, **params_okay))


class TestTFTPService(MAASTestCase):

    def test_tftp_service(self):
        # A TFTP service is configured and added to the top-level service.
        interfaces = [
            factory.make_ipv4_address(),
            factory.make_ipv6_address(),
            ]
        self.patch(
            tftp_module, "get_all_interface_addresses",
            lambda: interfaces)
        example_root = self.make_dir()
        example_client_service = Mock()
        example_port = factory.pick_port()
        tftp_service = TFTPService(
            resource_root=example_root, client_service=example_client_service,
            port=example_port)
        tftp_service.updateServers()
        # The "tftp" service is a multi-service containing UDP servers for
        # each interface defined by get_all_interface_addresses().
        self.assertIsInstance(tftp_service, MultiService)
        # There's also a TimerService that updates the servers every 45s.
        self.assertThat(
            tftp_service.refresher, MatchesStructure.byEquality(
                step=45, parent=tftp_service, name="refresher",
                call=(tftp_service.updateServers, (), {}),
            ))
        expected_backend = MatchesAll(
            IsInstance(TFTPBackend),
            AfterPreprocessing(
                lambda backend: backend.base.path,
                Equals(example_root)),
            AfterPreprocessing(
                lambda backend: backend.client_service,
                Equals(example_client_service)))
        expected_protocol = MatchesAll(
            IsInstance(TFTP),
            AfterPreprocessing(
                lambda protocol: protocol.backend,
                expected_backend))
        expected_server = MatchesAll(
            IsInstance(internet.UDPServer),
            AfterPreprocessing(
                lambda service: len(service.args),
                Equals(2)),
            AfterPreprocessing(
                lambda service: service.args[0],  # port
                Equals(example_port)),
            AfterPreprocessing(
                lambda service: service.args[1],  # protocol
                expected_protocol))
        self.assertThat(
            tftp_service.getServers(),
            AllMatch(expected_server))
        # Only the interface used for each service differs.
        self.assertItemsEqual(
            [svc.kwargs for svc in tftp_service.getServers()],
            [{"interface": interface} for interface in interfaces])

    def test_tftp_service_rebinds_on_HUP(self):
        # Initial set of interfaces to bind to.
        interfaces = {"1.1.1.1", "2.2.2.2"}
        self.patch(
            tftp_module, "get_all_interface_addresses",
            lambda: interfaces)

        tftp_service = TFTPService(
            resource_root=self.make_dir(), client_service=Mock(),
            port=factory.pick_port())
        tftp_service.updateServers()

        # The child services of tftp_services are named after the
        # interface they bind to.
        self.assertEqual(interfaces, {
            server.name for server in tftp_service.getServers()
        })

        # Update the set of interfaces to bind to.
        interfaces.add("3.3.3.3")
        interfaces.remove("1.1.1.1")

        # Ask the TFTP service to update its set of servers.
        tftp_service.updateServers()

        # We're in the reactor thread but we want to move the reactor
        # forwards, hence we need to get all explicit about it.
        reactor.runUntilCurrent()

        # The interfaces now bound match the updated interfaces set.
        self.assertEqual(interfaces, {
            server.name for server in tftp_service.getServers()
        })

    def test_tftp_service_does_not_bind_to_link_local_addresses(self):
        # Initial set of interfaces to bind to.
        ipv4_test_net_3 = IPNetwork("203.0.113.0/24")  # RFC 5737
        normal_addresses = {
            factory.pick_ip_in_network(ipv4_test_net_3),
            factory.make_ipv6_address(),
        }
        link_local_addresses = {
            factory.pick_ip_in_network(IPV4_LINK_LOCAL),
            factory.pick_ip_in_network(IPV6_LINK_LOCAL),
        }
        self.patch(
            tftp_module, "get_all_interface_addresses",
            lambda: normal_addresses | link_local_addresses)

        tftp_service = TFTPService(
            resource_root=self.make_dir(), client_service=Mock(),
            port=factory.pick_port())
        tftp_service.updateServers()

        # Only the "normal" addresses have been used.
        self.assertEqual(normal_addresses, {
            server.name for server in tftp_service.getServers()
        })


class DummyProtocol(Protocol):
    def doStop(self):
        pass


class TestPort(MAASTestCase):
    """Tests for :py:class:`Port`."""

    run_tests_with = MAASTwistedRunTest.make_factory(timeout=5)

    def test_getHost_works_with_IPv4_address(self):
        port = Port(0, DummyProtocol(), "127.0.0.1")
        port.addressFamily = AF_INET
        port.startListening()
        self.addCleanup(port.stopListening)
        self.assertEqual(
            IPv4Address('UDP', '127.0.0.1', port._realPortNumber),
            port.getHost())

    def test_getHost_works_with_IPv6_address(self):
        port = Port(0, DummyProtocol(), "::1")
        port.addressFamily = AF_INET6
        port.startListening()
        self.addCleanup(port.stopListening)
        self.assertEqual(
            IPv6Address('UDP', '::1', port._realPortNumber),
            port.getHost())


class TestUDPServer(MAASTestCase):

    run_tests_with = MAASTwistedRunTest.make_factory(timeout=5)

    def test__getPort_calls__listenUDP_with_args_from_constructor(self):
        server = UDPServer(sentinel.foo, bar=sentinel.bar)
        _listenUDP = self.patch(server, "_listenUDP")
        _listenUDP.return_value = sentinel.port
        self.assertEqual(sentinel.port, server._getPort())
        self.assertThat(_listenUDP, MockCalledOnceWith(
            sentinel.foo, bar=sentinel.bar))

    def test__listenUDP_with_IPv4_address(self):
        server = UDPServer(0, DummyProtocol(), "127.0.0.1")
        port = server._getPort()
        self.addCleanup(port.stopListening)
        self.assertEqual(AF_INET, port.addressFamily)

    def test__listenUDP_with_IPv6_address(self):
        server = UDPServer(0, DummyProtocol(), "::1")
        port = server._getPort()
        self.addCleanup(port.stopListening)
        self.assertEqual(AF_INET6, port.addressFamily)


class TestLogRequest(MAASTestCase):
    """Tests for `log_request`."""

    def test__defers_log_call_later(self):
        clock = Clock()
        log_request(sentinel.macaddr, sentinel.filename, clock)
        self.expectThat(clock.calls, HasLength(1))
        [call] = clock.calls
        self.expectThat(call.getTime(), Equals(0.0))

    def test__sends_event_later(self):
        send_event = self.patch(tftp_module, "send_node_event_mac_address")
        clock = Clock()
        log_request(sentinel.macaddr, sentinel.filename, clock)
        self.assertThat(send_event, MockNotCalled())
        clock.advance(0.0)
        self.assertThat(send_event, MockCalledOnceWith(
            mac_address=sentinel.macaddr, description=sentinel.filename,
            event_type=EVENT_TYPES.NODE_TFTP_REQUEST))

    def test__logs_to_server_log(self):
        self.patch(tftp_module, "send_node_event_mac_address")
        clock = Clock()
        mac_address = factory.make_mac_address()
        file_name = factory.make_name("file")
        with TwistedLoggerFixture() as logger:
            log_request(mac_address, file_name, clock)
            clock.advance(0.0)  # Don't leave anything in the reactor.
        self.assertThat(logger.output, Equals(
            "%s requested by %s" % (file_name, mac_address)))

    def test__logs_when_sending_event_errors(self):
        send_event = self.patch(tftp_module, "send_node_event_mac_address")
        send_event.side_effect = factory.make_exception()
        clock = Clock()
        log_request(sentinel.macaddr, sentinel.filename, clock)
        self.assertThat(send_event, MockNotCalled())
        with TwistedLoggerFixture() as logger:
            clock.advance(0.0)
        self.assertDocTestMatches(
            """\
            Logging TFTP request failed.
            Traceback (most recent call last):
            ...
            maastesting.factory.TestException#...
            """,
            logger.output)
