import os
import ssl
import sys
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [ROOT, os.path.join(ROOT, "tests"), os.path.join(ROOT, "tools")]

for _name in ("NO_PROXY", "no_proxy"):          # the fake feed runs on 127.0.0.1: never through a proxy of the machine
    os.environ[_name] = "127.0.0.1,localhost," + os.environ.get(_name, "")
os.environ["TZ"] = "UTC"                       # alert end times are shown in local time: tests run in UTC
if hasattr(time, "tzset"):
    time.tzset()

import domoticz_stub as dz  # noqa: E402
from cap_samples import NOW  # noqa: E402
from lu_alert.alerts import Filters  # noqa: E402
from lu_alert.api import Client  # noqa: E402
from lu_alert.config import Settings  # noqa: E402
from lu_alert.controller import Controller  # noqa: E402
from lu_alert.devices import DeviceManager  # noqa: E402
from lu_alert.feed import Feed  # noqa: E402
from lu_alert.logger import Logger  # noqa: E402
from fake_feed import FakeFeed  # noqa: E402,F401  (re-exported for the test modules)
import certs  # noqa: E402

NOW_TS = NOW.timestamp()


class Clock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t

    def advance(self, seconds):
        self.t += seconds


def make_logger(level=0):
    return Logger(dz, level)


def run_inline(target):
    """A 'thread' that runs at once: the tests control when a poll happens. Has the two methods the controller uses."""
    target()

    class Done:
        def is_alive(self):
            return False

        def join(self, timeout=None):
            pass
    return Done()


def make_filters(**kw):
    return Filters(**kw)


def make_stack(fake, level=0, clock=None, wall=None, spawn=run_inline, ssl_context=None, alert_devices=3, **settings_kw):
    """Client + feed + device manager + controller against a fake feed, with controllable clocks and an inline poll."""
    dz.reset()
    clock = clock or Clock()
    wall = wall or Clock(NOW_TS)
    log = make_logger(level)
    settings = Settings(dataset_url=fake.dataset_url, alert_devices=alert_devices, **settings_kw)
    client = Client(fake.dataset_url, timeout=3, ssl_context=ssl_context)
    feed = Feed(client, settings.max_resources)
    devices = DeviceManager(dz, lambda: dz.Devices, log, alert_devices, clock=clock)
    controller = Controller(settings, feed, devices, log, clock=clock, wall_clock=wall, spawn=spawn)
    return controller, feed, devices, clock, wall


def by_name(prefix):
    return [d for d in dz.Devices.values() if d.Name.startswith(prefix)]


def start_feed(testcase):
    """A fake data.public.lu on a real TLS server, and an SSL context that trusts its test CA.

    The client only talks https, so every test that reads a feed needs a certificate: openssl makes one per run."""
    if not certs.available():
        raise unittest.SkipTest("the openssl command is needed for the TLS test certificates")
    _folder, ca, _other, cert, key = certs.get()
    fake = FakeFeed().start(cert, key)
    testcase.addCleanup(fake.stop)
    return fake, ssl.create_default_context(cafile=ca)
