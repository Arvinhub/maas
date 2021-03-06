#!/usr/bin/env python3
# Copyright 2017 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Snap management commands."""

__all__ = [
    'cmd_config',
    'cmd_init',
    'cmd_migrate',
    'cmd_status',
    ]

import argparse
from collections import OrderedDict
from contextlib import contextmanager
import grp
import os
import pwd
import random
import shutil
import signal
import string
import subprocess
import sys
import threading
import time

from maascli.command import Command
import netifaces
import tempita
import yaml


OPERATION_MODES = """\
available modes:
    all         - full MAAS installation includes database, region
                  controller, and rack controller.
    region+rack - region controller connected to external database
                  and rack controller.
    region      - only region controller connected to external
                  database.
    rack        - only rack controller connected to an external
                  region.
    none        - not configured\
"""

ARGUMENTS = OrderedDict([
    ('mode', {
        'choices': ['all', 'region+rack', 'region', 'rack', 'none'],
        'help': (
            'Set the mode of the MAAS snap (all, region+rack, region, '
            'rack, or none).'),
    }),
    ('maas-url', {
        'help': (
            'URL that MAAS should use for communicate from the nodes to '
            'MAAS and other controllers of MAAS.'),
    }),
    ('database-host', {
        'help': (
            'Hostname or IP address that should be used to communicate to '
            'the database. Only used when in \'region+rack\' or '
            '\'region\' mode.'),
    }),
    ('database-name', {
        'help': (
            'Database name for MAAS to use. Only used when in '
            '\'region+rack\' or \'region\' mode.'),
    }),
    ('database-user', {
        'help': (
            'Database username to authenticate to the database. Only used '
            'when in \'region+rack\' or \'region\' mode.'),
    }),
    ('database-pass', {
        'help': (
            'Database password to authenticate to the database. Only used '
            'when in \'region+rack\' or \'region\' mode.'),
    }),
    ('secret', {
        'help': (
            'Secret token required for the rack controller to talk '
            'to the region controller(s). Only used when in \'rack\' mode.'),
    }),
])


def print_msg(msg, newline=True):
    """Print a message to stdout.

    Flushes the message to ensure its written immediately.
    """
    print(msg, end=('\n' if newline else ''), flush=True)


def get_default_gateway_ip():
    """Return the default gateway IP."""
    gateways = netifaces.gateways()
    if 'default' in gateways:
        defaults = gateways['default']
        if netifaces.AF_INET in defaults and defaults[netifaces.AF_INET]:
            return defaults[netifaces.AF_INET][0]
        elif netifaces.AF_INET6 in defaults and defaults[netifaces.AF_INET6]:
            return defaults[netifaces.AF_INET6][0]


def get_default_url():
    """Return the best default URL for MAAS."""
    gateway_ip = get_default_gateway_ip()
    if not gateway_ip:
        gateway_ip = 'localhost'
    return 'http://%s:5240/MAAS' % gateway_ip


def get_mode_filepath():
    """Return the path to the 'snap_mode' file."""
    return os.path.join(os.environ['SNAP_COMMON'], 'snap_mode')


def get_current_mode():
    """Gets the current mode of the snap."""
    filepath = get_mode_filepath()
    if os.path.exists(filepath):
        with open(get_mode_filepath(), "r") as fp:
            return fp.read().strip()
    else:
        return "none"


def set_current_mode(mode):
    """Set the current mode of the snap."""
    with open(get_mode_filepath(), "w") as fp:
        fp.write(mode.strip())


def render_supervisord(mode):
    """Render the 'supervisord.conf' based on the mode."""
    conf_vars = {
        'postgresql': False,
        'regiond': False,
        'rackd': False,
    }
    if mode == 'all':
        conf_vars['postgresql'] = True
    if mode in ['all', 'region+rack', 'region']:
        conf_vars['regiond'] = True
    if mode in ['all', 'region+rack', 'rack']:
        conf_vars['rackd'] = True
    template = tempita.Template.from_filename(
        os.path.join(
            os.environ['SNAP'], 'usr', 'share', 'maas',
            'supervisord.conf.template'), encoding="UTF-8")
    rendered = template.substitute(conf_vars)
    conf_path = os.path.join(
        os.environ['SNAP_DATA'], 'supervisord', 'supervisord.conf')
    with open(conf_path, 'w') as fp:
        fp.write(rendered)


def get_supervisord_pid():
    """Get the running supervisord pid."""
    pid_path = os.path.join(
        os.environ['SNAP_DATA'], 'supervisord', 'supervisord.pid')
    if os.path.exists(pid_path):
        with open(pid_path, 'r') as fp:
            return int(fp.read().strip())
    else:
        return None


def sighup_supervisord():
    """Cause supervisord to stop all processes, reload configuration, and
    start all processes."""
    pid = get_supervisord_pid()
    if pid is None:
        return

    os.kill(pid, signal.SIGHUP)
    # Wait for supervisord to be running successfully.
    time.sleep(0.5)
    while True:
        process = subprocess.Popen([
            os.path.join(
                os.environ['SNAP'], 'bin', 'run-supervisorctl'),
            'status'], stdout=subprocess.PIPE)
        process.wait()
        output = process.stdout.read().decode('utf-8')
        # Error message is printed until supervisord is running correctly.
        if 'error:' in output:
            time.sleep(1)
        else:
            break


def get_config_data():
    """Return the configuration data from `regiond.conf`."""
    regiond_conf_path = os.path.join(os.environ['SNAP_DATA'], 'regiond.conf')
    if os.path.exists(regiond_conf_path):
        with open(regiond_conf_path, 'r') as fp:
            data = yaml.safe_load(fp)
        if data is None:
            data = {}
        return data
    else:
        return {}


def get_config_value(config_name):
    """Return the configuration value for `config_name`."""
    # We always read from regiond.conf. As the database options only exists
    # in that file and maas_url will always be the same in rackd.conf.
    config_data = get_config_data()
    return config_data.get(config_name, None)


def print_config_value(config_name, hidden=False):
    """Print the configuration value to stdout."""
    if hidden:
        print_msg("%s=(hidden)" % config_name)
    else:
        config_value = get_config_value(config_name)
        print_msg("%s=%s" % (config_name, config_value))


def write_config_data(config_data, config_file):
    """Write the configuration data to `regiond.conf`."""
    regiond_conf_path = os.path.join(os.environ['SNAP_DATA'], config_file)
    with open(regiond_conf_path, 'w') as fp:
        fp.write(yaml.safe_dump(config_data, default_flow_style=False))


def update_config_value(config_name, config_value):
    """Update the configuration to new value."""
    config_data = get_config_data()
    if config_value is None:
        config_data.pop(config_name, None)
    else:
        config_data[config_name] = config_value
    write_config_data(config_data, 'regiond.conf')
    # maas_url also gets set in rackd.conf.
    if config_name == 'maas_url':
        if config_value is None:
            config_data = {}
        else:
            config_data = {
                'maas_url': config_value
            }
        write_config_data(config_data, 'rackd.conf')


def get_rpc_secret():
    """Get the current RPC secret."""
    secret = None
    secret_path = os.path.join(
        os.environ['SNAP_DATA'], 'var', 'lib', 'maas', 'secret')
    if os.path.exists(secret_path):
        with open(secret_path, 'r') as fp:
            secret = fp.read().strip()
    if secret:
        return secret
    else:
        return None


def set_rpc_secret(secret):
    """Write/delete the RPC secret."""
    secret_path = os.path.join(
        os.environ['SNAP_DATA'], 'var', 'lib', 'maas', 'secret')
    if secret:
        # Write the secret.
        with open(secret_path, 'w') as fp:
            fp.write(secret)
    else:
        # Delete the secret.
        if os.path.exists(secret_path):
            os.remove(secret_path)


def print_config(
        parsable=False, show_database_password=False, show_secret=False):
    """Print the config output."""
    current_mode = get_current_mode()
    if parsable:
        print_msg('mode=%s' % current_mode)
    else:
        print_msg('Mode: %s' % current_mode)
    if current_mode != 'none':
        if not parsable:
            print_msg('Settings:')
        print_config_value('maas_url')
        if current_mode in ['region+rack', 'region']:
            print_config_value('database_host')
            print_config_value('database_name')
            print_config_value('database_user')
            print_config_value(
                'database_pass', hidden=(not show_database_password))
        if current_mode == 'rack':
            secret = "(hidden)"
            if show_secret:
                secret = get_rpc_secret()
            print_msg('secret=%s' % secret)


def drop_privileges():
    """Drop privileges to 'nobody:nogroup'."""
    running_uid = pwd.getpwnam('nobody').pw_uid
    running_gid = grp.getgrnam('nogroup').gr_gid
    os.setgroups([])
    os.setgid(running_gid)
    os.setuid(running_uid)


def run_with_drop_privileges(cmd, *args, **kwargs):
    """Runs `cmd` in child process with lower privileges."""
    pid = os.fork()
    if pid == 0:
        drop_privileges()
        cmd(*args, **kwargs)
        sys.exit(0)
    else:
        os.waitpid(pid, 0)


def run_sql(sql):
    """Run sql command through `psql`."""
    subprocess.check_output([
        os.path.join(os.environ['SNAP'], 'bin', 'psql'),
        '-h', os.path.join(os.environ['SNAP_COMMON'], 'db'),
        '-d', 'postgres', '-U', 'postgres', '-c', sql],
        stderr=subprocess.STDOUT)


def wait_for_postgresql(timeout=60):
    """Wait for postgresql to be running."""
    end_time = time.time() + timeout
    while True:
        try:
            run_sql('SELECT now();')
        except subprocess.CalledProcessError:
            if time.time() > end_time:
                raise TimeoutError(
                    "Unable to connect to postgresql after %s seconds." % (
                        timeout))
            else:
                time.sleep(1)
        else:
            break


def start_postgres():
    """Start postgresql."""
    subprocess.check_output([
        os.path.join(os.environ['SNAP'], 'bin', 'pg_ctl'),
        'start', '-w', '-D', os.path.join(os.environ['SNAP_COMMON'], 'db'),
        '-l', os.path.join(os.environ['SNAP_COMMON'], 'log', 'postgresql.log'),
        '-o', '-k "%s" -h ""' % os.path.join(os.environ['SNAP_COMMON'], 'db')],
        stderr=subprocess.STDOUT)
    wait_for_postgresql()


def stop_postgres():
    """Stop postgresql."""
    subprocess.check_output([
        os.path.join(os.environ['SNAP'], 'bin', 'pg_ctl'),
        'stop', '-w', '-D', os.path.join(os.environ['SNAP_COMMON'], 'db')],
        stderr=subprocess.STDOUT)


@contextmanager
def with_postgresql():
    """Start or stop postgresql."""
    start_postgres()
    yield
    stop_postgres()


def create_db(config):
    """Create the database and user."""
    run_sql("CREATE USER %s WITH PASSWORD '%s';" % (
        config['database_user'], config['database_pass']))
    run_sql("CREATE DATABASE %s;" % config['database_name'])
    run_sql("GRANT ALL PRIVILEGES ON DATABASE %s to %s;" % (
        config['database_name'], config['database_user']))


def migrate_db(capture=False):
    """Migrate the database."""
    if capture:
        process = subprocess.Popen([
            os.path.join(os.environ['SNAP'], 'bin', 'maas-region'),
            'dbupgrade'],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT)
        ret = process.wait()
        output = process.stdout.read().decode('utf-8')
        if ret != 0:
            clear_line()
            print_msg('Failed to perfom migrations:')
            print_msg(output)
            print_msg('')
            sys.exit(ret)
    else:
        subprocess.check_call([
            os.path.join(os.environ['SNAP'], 'bin', 'maas-region'),
            'dbupgrade'])


def init_db():
    """Initialize the database."""
    config_data = get_config_data()
    db_path = os.path.join(os.environ['SNAP_COMMON'], 'db')
    if os.path.exists(db_path):
        shutil.rmtree(db_path)
    os.mkdir(db_path)
    shutil.chown(db_path, user='nobody', group='nogroup')
    log_path = os.path.join(os.environ['SNAP_COMMON'], 'log', 'postgresql.log')
    if not os.path.exists(log_path):
        open(log_path, 'a').close()
    shutil.chown(log_path, user='nobody', group='nogroup')

    def _init_db():
        subprocess.check_output([
            os.path.join(os.environ['SNAP'], 'bin', 'initdb'),
            '-D', os.path.join(os.environ['SNAP_COMMON'], 'db'),
            '-U', 'postgres', '-E', 'UTF8', '--locale=C'],
            stderr=subprocess.STDOUT)
        with with_postgresql():
            create_db(config_data)
    run_with_drop_privileges(_init_db)


def clear_line():
    """Resets the current line when in a terminal."""
    if sys.stdout.isatty():
        print_msg(
            '\r' + ' ' * int(os.environ.get('COLUMNS', 0)), newline=False)


def perform_work(msg, cmd, *args, **kwargs):
    """Perform work.

    Executes the `cmd` and while its running it prints a nice message.
    """
    # When not running in a terminal, just print the message once and perform
    # the operation.
    if not sys.stdout.isatty():
        print_msg(msg)
        return cmd(*args, **kwargs)

    spinner = {
        0: '/',
        1: '-',
        2: '\\',
        3: '|',
        4: '/',
        5: '-',
        6: '\\',
        7: '|',
    }

    def _write_msg(evnt):
        idx = 0
        while not evnt.is_set():
            # Print the message with a spinner until the work is complete.
            print_msg(
                "\r[%s] %s" % (spinner[idx], msg), newline=False)
            idx += 1
            if idx == 8:
                idx = 0
            time.sleep(0.25)
        # Clear the line so previous message is not show if the next message
        # is not as long as this message.
        print_msg('\r' + ' ' * (len(msg) + 4), newline=False)

    # Spawn a thread to print the message, while performing the work in the
    # current execution thread.
    evnt = threading.Event()
    t = threading.Thread(target=_write_msg, args=(evnt,))
    t.start()
    try:
        ret = cmd(*args, **kwargs)
    finally:
        evnt.set()
        t.join()
    return ret


def read_input(prompt):
    """Reads input from stdin."""
    while True:
        try:
            data = input(prompt)
        except EOFError:
            # Ctrl-d was pressed?
            print()
            continue
        except KeyboardInterrupt:
            print()
            raise SystemExit(1)
        else:
            # The assumption is that, since Python 3 return a Unicode string
            # from input(), it has Done The Right Thing with respect to
            # character encoding.
            return data


def required_prompt(prompt, help_text=None):
    """Prompt for required input."""
    value = None
    while not value or value == "help":
        value = read_input(prompt)
        if value == "help":
            if help_text:
                print_msg(help_text)
    return value


def prompt_for_choices(prompt, choices, default=None, help_text=None):
    """Prompt requires specific choice answeres.

    If `help_text` is provided the 'help' is added as a choice.
    """
    invalid_msg = 'Invalid input, try again'
    if help_text:
        invalid_msg += " or type 'help'"
    invalid_msg += '.'
    value = None
    while True:
        value = read_input(prompt)
        if not value:
            if default:
                return default
            else:
                print_msg(invalid_msg)
                print_msg()
        elif value == 'help' and help_text:
            print_msg(help_text)
            print_msg()
        elif value not in choices:
            print_msg(invalid_msg)
            print_msg()
        else:
            return value


def prompt_for_maas_url():
    """Prompt for the MAAS URL."""
    default_url = get_default_url()
    url = None
    while not url or url == "help":
        url = read_input("MAAS URL [default=%s]: " % default_url)
        if not url:
            url = default_url
        if url == "help":
            print_msg(
                'URL that MAAS should use for communicate from the nodes '
                'to MAAS and other controllers of MAAS.')
    return url


class SnappyCommand(Command):
    """
    Command that just prints the exception instead of the overridden
    'maas --help' output.
    """

    def __call__(self, options):
        try:
            self.handle(options)
        except Exception as exc:
            exc.always_show = True
            raise exc


class cmd_init(SnappyCommand):
    """Initialize controller."""

    def __init__(self, parser):
        super(cmd_init, self).__init__(parser)
        for argument, kwargs in ARGUMENTS.items():
            parser.add_argument('--%s' % argument, **kwargs)
        parser.add_argument(
            '--force', action='store_true',
            help=(
                "Skip confirmation questions when initialization has "
                "already been performed."))
        parser.add_argument(
            '--skip-admin', action='store_true',
            help=(
                "Skip the admin creation when initializing in 'all' mode."))
        parser.add_argument(
            '--admin-username', default=None, metavar='USERNAME',
            help="Username for the admin account.")
        parser.add_argument(
            '--admin-password', default=None, metavar='PASSWORD',
            help="Force a given admin password instead of prompting.")
        parser.add_argument(
            '--admin-email', default=None, metavar='EMAIL',
            help="Email address for the admin.")
        parser.add_argument(
            '--admin-ssh-import', default=None, metavar='LP_GH_USERNAME',
            help=(
                "Import SSH keys from Launchpad (lp:user-id) or "
                "Github (gh:user-id) for the admin."))

    def handle(self, options):
        if os.getuid() != 0:
            raise SystemExit("The 'init' command must be run by root.")

        mode = options.mode
        current_mode = get_current_mode()
        if current_mode != 'none':
            if not options.force:
                init_text = 'initialize again'
                if mode == 'none':
                    init_text = 'de-initialize'
                else:
                    print_msg('Controller has already been initialized.')
                initialize = prompt_for_choices(
                    'Are you sure you want to %s '
                    '(yes/no) [default=no]? ' % init_text,
                    ['yes', 'no'], default='no')
                if initialize == 'no':
                    sys.exit(0)

        if not mode:
            mode = prompt_for_choices(
                "Mode (%sall/region+rack/region/rack/none) [default=all]? " % (
                    '/'.join(ARGUMENTS['mode']['choices'])),
                ARGUMENTS['mode']['choices'],
                default='all', help_text=OPERATION_MODES)
        if current_mode == 'all' and mode != 'all' and not options.force:
            print_msg(
                'This will disconnect your MAAS from the running database.')
            disconnect = prompt_for_choices(
                'Are you sure you want to disconnect the database '
                '(yes/no) [default=no]? ', ['yes', 'no'], default='no')
            if disconnect == 'no':
                return 0
        elif current_mode == 'all' and mode == 'all' and not options.force:
            print_msg(
                'This will re-initialize your entire database and all '
                'current data will be lost.')
            reinit_db = prompt_for_choices(
                'Are you sure you want to re-initialize the database '
                '(yes/no) [default=no]? ', ['yes', 'no'], default='no')
            if reinit_db == 'no':
                return 0

        maas_url = options.maas_url
        if mode != 'none' and not maas_url:
            maas_url = prompt_for_maas_url()
        database_host = database_name = None
        database_user = database_pass = None
        rpc_secret = None
        if mode == 'all':
            database_host = os.path.join(os.environ['SNAP_COMMON'], 'db')
            database_name = 'maasdb'
            database_user = 'maas'
            database_pass = ''.join(
                random.choice(string.ascii_uppercase + string.digits)
                for _ in range(10))
        if mode in ['region', 'region+rack']:
            database_host = options.database_host
            if not database_host:
                database_host = required_prompt(
                    "Database host: ",
                    help_text=ARGUMENTS['database_host']['help'])
            database_name = options.database_name
            if not database_name:
                database_name = required_prompt(
                    "Database name: ",
                    help_text=ARGUMENTS['database_name']['help'])
            database_user = options.database_user
            if not database_user:
                database_user = required_prompt(
                    "Database user: ",
                    help_text=ARGUMENTS['database_user']['help'])
            database_pass = options.database_pass
            if not database_pass:
                database_pass = required_prompt(
                    "Database password: ",
                    help_text=ARGUMENTS['database_pass']['help'])
        if mode == 'rack':
            rpc_secret = options.secret
            if not rpc_secret:
                rpc_secret = required_prompt(
                    "Secret: ",
                    help_text=ARGUMENTS['secret']['help'])

        # Stop all services if in another mode.
        if current_mode != 'none':
            def stop_services():
                render_supervisord('none')
                sighup_supervisord()
            perform_work('Stopping services', stop_services)

        # Configure the settings.
        update_config_value('maas_url', maas_url)
        for name, value in [
                ('database_host', database_host),
                ('database_name', database_name),
                ('database_user', database_user),
                ('database_pass', database_pass),
                ]:
            update_config_value(name, value)
        set_rpc_secret(rpc_secret)

        # Finalize the Initialization.
        self._finalize_init(mode, options)

    def _finalize_init(self, mode, options):
        # When in 'all' mode configure the database.
        if mode == 'all':
            perform_work('Initializing database', init_db)

        # Configure mode.
        def start_services():
            render_supervisord(mode)
            set_current_mode(mode)
            sighup_supervisord()
        perform_work(
            'Starting services' if mode != 'none' else 'Stopping services',
            start_services)

        if mode == 'all':
            # When in 'all' mode configure the database and create admin user.
            perform_work('Waiting for postgresql', wait_for_postgresql)
            perform_work(
                "Performing database migrations",
                migrate_db, capture=sys.stdout.isatty())
            clear_line()
            if not options.skip_admin:
                self._create_admin_account(options)
        elif mode in ['region', 'region+rack']:
            # When in 'region' or 'region+rack' the migrations for the database
            # must be at the same level as this controller.
            perform_work(
                "Performing database migrations",
                migrate_db, capture=sys.stdout.isatty())
        else:
            clear_line()

    def _create_admin_account(self, options):
        """Create the first admin account."""
        print_create_header = (
            not options.admin_username or
            not options.admin_password or
            not options.admin_email)
        if print_create_header:
            print_msg('Create first admin account:')
        cmd = [
            os.path.join(os.environ['SNAP'], 'bin', 'maas-region'),
            'createadmin']
        if options.admin_username:
            cmd.extend(['--username', options.admin_username])
        if options.admin_password:
            cmd.extend(['--password', options.admin_password])
        if options.admin_email:
            cmd.extend(['--email', options.admin_email])
        if options.admin_ssh_import:
            cmd.extend(['--ssh-import', options.admin_ssh_import])
        subprocess.call(cmd)


class cmd_config(SnappyCommand):
    """View or change controller configuration."""

    # Required options based on mode.
    required_options = {
        'all': ['maas_url'],
        'region+rack': [
            'maas_url',
            'database_host',
            'database_name',
            'database_user',
            'database_pass',
            ],
        'region': [
            'maas_url',
            'database_host',
            'database_name',
            'database_user',
            'database_pass',
            ],
        'rack': [
            'maas_url',
            'secret',
            ],
        'none': [],
    }

    # Setting flags that are in .conf.
    setting_flags = (
        'maas_url',
        'database_host', 'database_name',
        'database_user', 'database_pass')

    def __init__(self, parser):
        super(cmd_config, self).__init__(parser)
        parser.add_argument(
            '--show', action='store_true',
            help=(
                "Show the current configuration. Default when no parameters "
                "are provided."))
        parser.add_argument(
            '--show-database-password', action='store_true',
            help="Show the hidden database password.")
        parser.add_argument(
            '--show-secret', action='store_true',
            help="Show the hidden secret.")
        for argument, kwargs in ARGUMENTS.items():
            parser.add_argument('--%s' % argument, **kwargs)
        parser.add_argument(
            '--force', action='store_true',
            help=(
                "Force leaving 'all' mode and cause loss of database."))
        parser.add_argument(
            '--parsable', action='store_true',
            help=(
                "Output the current configuration in a parsable format."))
        parser.add_argument(
            '--render', action='store_true', help=argparse.SUPPRESS)

    def _validate_mode(self, options):
        """Validate the parameters are correct for changing the mode."""
        if options.mode is not None:
            if options.mode != get_current_mode():
                # Changing the mode, ensure that the required parameters
                # are passed for this mode.
                missing_flags = []
                for flag in self.required_options[options.mode]:
                    if not getattr(options, flag):
                        missing_flags.append(
                            '--%s' % flag.replace('_', '-'))
                if len(missing_flags) > 0:
                    print_msg(
                        "Changing mode to '%s' requires parameters: %s" % (
                            options.mode, ', '.join(missing_flags)))
                    sys.exit(1)

    def _validate_flags(self, options, running_mode):
        """
        Validate the flags are correct for the current mode or the new mode.
        """
        invalid_flags = []
        for flag in self.setting_flags + ('secret', ):
            if (flag not in self.required_options[running_mode] and
                    getattr(options, flag)):
                invalid_flags.append('--%s' % flag.replace('_', '-'))
        if len(invalid_flags) > 0:
            print_msg(
                "Following flags are not supported in '%s' mode: %s" % (
                    running_mode, ', '.join(invalid_flags)))
            sys.exit(1)

    def handle(self, options):
        if os.getuid() != 0:
            raise SystemExit("The 'config' command must be run by root.")

        # Hidden option only called by the run-supervisord script. Renders
        # the initial supervisord.conf based on the current mode.
        if options.render:
            render_supervisord(get_current_mode())
            return

        # In config mode if --show is passed or none of the following flags
        # have been passed.
        in_config_mode = options.show
        if not in_config_mode:
            in_config_mode = not any(
                getattr(options, flag) is not None
                for flag in ('mode', 'secret') + self.setting_flags
            )

        # Config mode returns the current config of the snap.
        if in_config_mode:
            return print_config(
                options.parsable,
                options.show_database_password, options.show_secret)
        else:
            restart_required = False
            changed_to_all = False
            current_mode = get_current_mode()
            running_mode = current_mode
            if options.mode is not None:
                running_mode = options.mode

            # Validate the mode and flags.
            self._validate_mode(options)
            self._validate_flags(options, running_mode)

            # Changing the mode to from all requires --force.
            if options.mode is not None:
                if current_mode == 'all' and options.mode != 'all':
                    if not options.force:
                        print_msg(
                            "Changing mode from 'all' to '%s' will "
                            "disconnect the database and all data will "
                            "be lost. Use '--force' if your sure you want "
                            "to do this." % options.mode)
                        sys.exit(1)
                elif current_mode != 'all' and options.mode == 'all':
                    # Changing mode to all requires services to be stopped and
                    # a new database to be initialized.
                    changed_to_all = True

                    def stop_services():
                        render_supervisord('none')
                        sighup_supervisord()
                    perform_work('Stopping services', stop_services)

                    # Configure the new database settings.
                    options.database_host = os.path.join(
                        os.environ['SNAP_COMMON'], 'db')
                    options.database_name = 'maasdb'
                    options.database_user = 'maas'
                    options.database_pass = ''.join(
                        random.choice(
                            string.ascii_uppercase + string.digits)
                        for _ in range(10))
                    write_config_data({
                        'maas_url': options.maas_url,
                        'database_host': options.database_host,
                        'database_name': options.database_name,
                        'database_user': options.database_user,
                        'database_pass': options.database_pass,
                    }, 'regiond.conf')

                    # Initialize the database before starting the services.
                    perform_work('Initializing database', init_db)
                if options.mode != current_mode:
                    render_supervisord(options.mode)
                    set_current_mode(options.mode)
                    restart_required = True

            if current_mode != running_mode:
                # Update all the settings since the mode changed.
                for flag in self.setting_flags:
                    flag_value = getattr(options, flag)
                    if get_config_value(flag) != flag_value:
                        update_config_value(flag, flag_value)
                        restart_required = True
                set_rpc_secret(options.secret)
            else:
                # Only update the passed settings.
                for flag in self.setting_flags:
                    flag_value = getattr(options, flag)
                    if (flag_value is not None and
                            get_config_value(flag) != flag_value):
                        update_config_value(flag, flag_value)
                        restart_required = True
                if options.secret is not None:
                    set_rpc_secret(options.secret)

            # Restart the supervisor as its required.
            if restart_required:
                perform_work(
                    'Restarting services'
                    if running_mode != 'none' else 'Stopping services',
                    sighup_supervisord)
                clear_line()

            # Perform migrations when switching to all.
            if changed_to_all:
                perform_work('Waiting for postgresql', wait_for_postgresql)
                perform_work(
                    "Performing database migrations",
                    migrate_db, capture=sys.stdout.isatty())
                clear_line()


class cmd_status(SnappyCommand):
    """Status of controller services."""

    def handle(self, options):
        if get_current_mode() == 'none':
            print_msg('MAAS is not configured')
            sys.exit(1)
        else:
            process = subprocess.Popen([
                os.path.join(
                    os.environ['SNAP'], 'bin', 'run-supervisorctl'),
                'status'], stdout=subprocess.PIPE)
            ret = process.wait()
            output = process.stdout.read().decode('utf-8')
            if ret == 0:
                print_msg(output, newline=False)
            else:
                if 'error:' in output:
                    print_msg(
                        'MAAS supervisor is currently restarting. '
                        'Please wait and try again.')
                    sys.exit(-1)
                else:
                    print_msg(output, newline=False)
                    sys.exit(ret)


class cmd_migrate(SnappyCommand):
    """Perform migrations on connected database."""

    def __init__(self, parser):
        super(cmd_migrate, self).__init__(parser)
        # '--configure' is only used from the 'hooks/configure' when the snap
        # is in 'all' mode. Postgresql is not running when the migrate is
        # called.
        parser.add_argument(
            '--configure', action='store_true', help=argparse.SUPPRESS)

    def handle(self, options):
        if os.getuid() != 0:
            raise SystemExit("The 'migrate' command must be run by root.")

        # Hidden parameter that is only called from the configure hook. Updates
        # the database when running in all mode.
        if options.configure:
            current_mode = get_current_mode()
            if current_mode == 'all':
                wait_for_postgresql()
                sys.exit(migrate_db())
            elif current_mode in ['region', 'region+rack']:
                sys.exit(migrate_db())
            else:
                # In 'rack' or 'none' mode, nothing to do.
                sys.exit(0)

        mode = get_current_mode()
        if mode == 'none':
            print_msg('MAAS is not configured')
            sys.exit(1)
        elif mode == 'rack':
            print_msg(
                "Mode 'rack' is not connected to a database. "
                "No migrations to perform.")
            sys.exit(1)
        else:
            sys.exit(migrate_db())
