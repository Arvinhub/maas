# Copyright 2016 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""A script that configures and then logs via:

- The Twisted modern logging system.

- The Twisted modern logging systems.

- The standard library's `logging` system.

- The standard library's `warnings` system.

- Standard output.

- Standard error.

"""

import argparse
import logging
import sys
import warnings

import provisioningserver.logger
import twisted.logger
import twisted.python.log


modes = provisioningserver.logger.LoggingMode

parser = argparse.ArgumentParser()
parser.add_argument("--name", required=True)
parser.add_argument("--verbosity", type=int, required=True)
parser.add_argument(
    "--mode", type=modes.__getitem__, help=" or ".join(
        mode.name for mode in modes))
options = parser.parse_args()

# Configure logging. This is the main entry-point.
provisioningserver.logger.configure(
    verbosity=options.verbosity, mode=options.mode)

# Simulate what `twistd` does when passed `--logfile=-`.
if options.mode == modes.TWISTD:
    twisted.python.log.startLogging(sys.stdout)

# Twisted, new.
twisted.logger.Logger(options.name).debug("From `twisted.logger`.")
twisted.logger.Logger(options.name).info("From `twisted.logger`.")
twisted.logger.Logger(options.name).warn("From `twisted.logger`.")
twisted.logger.Logger(options.name).error("From `twisted.logger`.")

# Twisted, legacy.
twisted.python.log.msg("From `twisted.python.log`.", system=options.name)

# Standard library.
logging.getLogger(options.name).debug("From `logging`.")
logging.getLogger(options.name).info("From `logging`.")
logging.getLogger(options.name).warning("From `logging`.")
logging.getLogger(options.name).error("From `logging`.")

# Standard library, "maas" logger.
maaslog = provisioningserver.logger.get_maas_logger(options.name)
maaslog.debug("From `get_maas_logger`.")
maaslog.info("From `get_maas_logger`.")
maaslog.warning("From `get_maas_logger`.")
maaslog.error("From `get_maas_logger`.")

# Standard IO.
print("Printing to stdout.", file=sys.stdout, flush=True)
print("Printing to stderr.", file=sys.stderr, flush=True)

# Warnings.
warnings.formatwarning = lambda message, *_, **__: str(message)
warnings.warn("This is a warning!")

# Make sure everything is flushed.
sys.stdout.flush()
sys.stderr.flush()
