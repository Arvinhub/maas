# Copyright 2012-2015 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for the install_pxe_bootloader command."""

__all__ = []

import os.path

from maastesting.factory import factory
from maastesting.testcase import MAASTestCase
from maastesting.utils import (
    age_file,
    get_write_time,
)
from provisioningserver.boot.install_bootloader import (
    install_bootloader,
    make_destination,
)
from testtools.matchers import (
    DirExists,
    FileContains,
)


class TestInstallBootloader(MAASTestCase):

    def test_integration(self):
        loader_contents = factory.make_string()
        loader = self.make_file(contents=loader_contents)
        destination = self.make_file()
        install_bootloader(loader, destination)
        self.assertThat(destination, FileContains(loader_contents))

    def test_make_destination_creates_directory_if_not_present(self):
        tftproot = self.make_dir()
        dest = make_destination(tftproot)
        self.assertThat(dest, DirExists())

    def test_make_destination_returns_existing_directory(self):
        tftproot = self.make_dir()
        make_destination(tftproot)
        dest = make_destination(tftproot)
        self.assertThat(dest, DirExists())

    def test_install_bootloader_installs_new_bootloader(self):
        contents = factory.make_string()
        loader = self.make_file(contents=contents)
        install_dir = self.make_dir()
        dest = os.path.join(install_dir, factory.make_name('loader'))
        install_bootloader(loader, dest)
        self.assertThat(dest, FileContains(contents))

    def test_install_bootloader_replaces_bootloader_if_changed(self):
        contents = factory.make_string()
        loader = self.make_file(contents=contents)
        dest = self.make_file(contents="Old contents")
        install_bootloader(loader, dest)
        self.assertThat(dest, FileContains(contents))

    def test_install_bootloader_skips_if_unchanged(self):
        contents = factory.make_string()
        dest = self.make_file(contents=contents)
        age_file(dest, 100)
        original_write_time = get_write_time(dest)
        loader = self.make_file(contents=contents)
        install_bootloader(loader, dest)
        self.assertThat(dest, FileContains(contents))
        self.assertEqual(original_write_time, get_write_time(dest))

    def test_install_bootloader_sweeps_aside_dot_new_if_any(self):
        contents = factory.make_string()
        loader = self.make_file(contents=contents)
        dest = self.make_file(contents="Old contents")
        temp_file = '%s.new' % dest
        factory.make_file(
            os.path.dirname(temp_file), name=os.path.basename(temp_file))
        install_bootloader(loader, dest)
        self.assertThat(dest, FileContains(contents))