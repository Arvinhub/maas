# Copyright 2012-2016 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Configuration abstractions for the MAAS CLI."""

__all__ = [
    "ProfileConfig",
    ]

from contextlib import (
    closing,
    contextmanager,
)
import json
import os
from os.path import expanduser
import sqlite3

from maascli import utils


class ProfileConfig:
    """Store profile configurations in an sqlite3 database."""

    def __init__(self, database):
        self.database = database
        with self.cursor() as cursor:
            cursor.execute(
                "CREATE TABLE IF NOT EXISTS profiles "
                "(id INTEGER PRIMARY KEY,"
                " name TEXT NOT NULL UNIQUE,"
                " data BLOB)")

    def cursor(self):
        return closing(self.database.cursor())

    def __iter__(self):
        with self.cursor() as cursor:
            results = cursor.execute(
                "SELECT name FROM profiles").fetchall()
        return (name for (name,) in results)

    def __getitem__(self, name):
        with self.cursor() as cursor:
            data = cursor.execute(
                "SELECT data FROM profiles"
                " WHERE name = ?", (name,)).fetchone()
        if data is None:
            raise KeyError(name)
        else:
            return json.loads(data[0])

    def __setitem__(self, name, data):
        with self.cursor() as cursor:
            cursor.execute(
                "INSERT OR REPLACE INTO profiles (name, data) "
                "VALUES (?, ?)", (name, json.dumps(data)))

    def __delitem__(self, name):
        with self.cursor() as cursor:
            cursor.execute(
                "DELETE FROM profiles"
                " WHERE name = ?", (name,))

    @classmethod
    def create_database(cls, dbpath):
        # Initialise the database file with restrictive permissions.
        os.close(os.open(dbpath, os.O_CREAT | os.O_APPEND, 0o600))

    @classmethod
    @contextmanager
    def open(cls, dbpath=expanduser("~/.maascli.db")):
        """Load a profiles database.

        Called without arguments this will open (and create) a database in the
        user's home directory.

        **Note** that this returns a context manager which will close the
        database on exit, saving if the exit is clean.
        """
        # As the effective UID and GID of the user invoking `sudo` (if any)...
        try:
            with utils.sudo_gid(), utils.sudo_uid():
                cls.create_database(dbpath)
        except PermissionError:
            # Creating the database might fail if $HOME is set to the current
            # effective UID's $HOME, but we have permission to change the UID
            # to one without permission to access $HOME. So try again without
            # changing the GID/UID.
            cls.create_database(dbpath)

        database = sqlite3.connect(dbpath)
        try:
            yield cls(database)
        except:
            raise
        else:
            database.commit()
        finally:
            database.close()
