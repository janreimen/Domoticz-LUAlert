"""Poll scheduling, the error policy, what reaches the log, and that a failing feed never clears an alert."""
import threading
import time
import unittest
from datetime import timedelta

import domoticz_stub as dz
from cap_samples import NOW, cap_xml, reference
from helpers import make_stack, start_feed
from lu_alert.controller import start_thread
from lu_alert.constants import (
    CREATE_RETRY_SECONDS, MAX_BACKOFF, UNIT_ACTIVE, UNIT_CRITICAL, UNIT_FEED_INFO, UNIT_HIGHEST,
    UNIT_STATUS,
)


def fresh_alert(identifier, **kw):
    """An alert in force at the (fixed) wall clock of the controller tests."""
    kw.setdefault("sent", NOW - timedelta(minutes=5))
    return cap_xml(identifier, **kw)


class ControllerCase(unittest.TestCase):
    def setUp(self):
        self.fake, self.context = start_feed(self)
        self.make()

    def make(self, **kw):
        kw.setdefault("ssl_context", self.context)
        self.controller, self.feed, self.devices, self.clock, self.wall = make_stack(self.fake, **kw)

    def errors(self):
        return dz.messages("error")

    def logs(self):
        return dz.messages("log")

    def value(self, unit):
        return dz.Devices[unit].nValue, dz.Devices[unit].sValue

    def start(self):
        """Start the controller and let the heartbeat pick up the result of the first poll, as Domoticz does."""
        self.controller.start()
        self.controller.on_heartbeat()

    def next_poll(self):
        """Let the clocks run to the next poll: one heartbeat starts it, the next one picks up the result."""
        delta = self.controller.next_poll_at - self.clock() + 0.1
        self.clock.advance(delta)
        self.wall.advance(delta)
        self.controller.on_heartbeat()
        self.controller.on_heartbeat()


class StartTests(ControllerCase):
    def test_start_creates_the_devices_polls_and_connects(self):
        self.fake.add("a", cap_xml("a"))
        self.start()
        self.assertEqual(self.errors(), [])
        self.assertEqual(len(dz.Devices), 18)
        self.assertEqual(self.value(UNIT_ACTIVE), (0, "1"))
        self.assertEqual(self.value(UNIT_STATUS), (1, "On"))
        self.assertEqual(self.value(UNIT_CRITICAL), (1, "On"))
        self.assertIn("Connected to the LU-Alert feed: 1 alert files, 1 message(s) read", self.logs())
        self.assertTrue(any(t.startswith("Active alert: [Severe] Storm warning") for t in self.logs()))
        self.assertIn("Instruction: Stay indoors.", self.logs())
        self.assertTrue(self.value(UNIT_FEED_INFO)[1].startswith("OK 12:"))
        self.assertTrue(self.value(UNIT_FEED_INFO)[1].endswith(": 1 files (1 new), 1 active"))

    def test_no_alerts(self):
        self.start()
        self.assertIn("No active LU-Alert alerts", self.logs())
        self.assertEqual(self.value(UNIT_HIGHEST), (1, "No active alerts"))
        self.assertEqual(self.errors(), [])

    def test_the_poll_does_not_touch_domoticz_from_its_thread(self):
        names = []
        real = dz.Log

        def spy(text):
            names.append(threading.current_thread().name)
            real(text)
        dz.Log = spy
        self.addCleanup(setattr, dz, "Log", real)
        self.make(spawn=start_thread)
        self.controller.start()
        deadline = time.time() + 5
        while self.controller.polling and time.time() < deadline:
            self.controller.on_heartbeat()
            time.sleep(0.02)
        self.assertFalse(self.controller.polling)
        self.assertEqual(set(names), {threading.current_thread().name})
        self.controller.stop()

    def test_polling_follows_the_interval_not_the_heartbeat(self):
        self.start()
        sent = len(self.fake.requests)
        self.clock.advance(299)
        self.controller.on_heartbeat()
        self.assertEqual(len(self.fake.requests), sent)
        self.clock.advance(2)
        self.controller.on_heartbeat()
        self.assertEqual(len(self.fake.requests), sent + 1)             # only the description: no file is new

    def test_a_new_alert_is_announced_once_and_its_end_too(self):
        self.start()
        self.fake.add("a", cap_xml("a", sent=NOW, expires=NOW + timedelta(minutes=30)), modified="2026-11-02T12:00:00")
        self.next_poll()
        self.assertEqual(len([t for t in self.logs() if t.startswith("New alert:")]), 1)
        self.assertEqual(self.value(UNIT_ACTIVE), (0, "1"))
        self.next_poll()
        self.assertEqual(len([t for t in self.logs() if t.startswith("New alert:")]), 1)
        self.wall.advance(31 * 60)                                        # its end time passes between two polls
        self.controller.on_heartbeat()
        self.assertEqual(self.value(UNIT_ACTIVE), (0, "0"))
        self.assertEqual(len([t for t in self.logs() if t.startswith("Alert ended:")]), 1)

    def test_a_cancel_ends_the_alert(self):
        self.fake.add("a", cap_xml("a", sent=NOW - timedelta(hours=1)))
        self.start()
        self.assertEqual(self.value(UNIT_ACTIVE)[1], "1")
        self.fake.add("c", cap_xml("c", sent=NOW, msg_type="Cancel", references=reference("a", NOW - timedelta(hours=1))),
                      modified="2026-11-02T12:00:00")
        self.next_poll()
        self.assertEqual(self.value(UNIT_ACTIVE)[1], "0")
        self.assertTrue(any(t.startswith("Alert ended:") for t in self.logs()))

    def test_a_test_message_is_named_once_in_the_log_and_never_shown(self):
        self.fake.add("t", fresh_alert("t", level="D", headline="Monthly siren test"))
        self.start()
        self.assertEqual(self.value(UNIT_ACTIVE), (0, "0"))
        told = [t for t in self.logs() if t.startswith("Test message ignored")]
        self.assertEqual(told, ["Test message ignored (D): Monthly siren test"])
        self.next_poll()
        self.assertEqual(len([t for t in self.logs() if t.startswith("Test message ignored")]), 1)

    def test_a_level_the_plugin_does_not_know_is_named_once_in_the_log(self):
        self.fake.add("a", fresh_alert("a", level="ALERT_LVL_9", severity="Moderate"))
        self.start()
        self.assertEqual(self.value(UNIT_ACTIVE), (0, "1"))                  # still shown, by its CAP severity
        told = [t for t in self.logs() if t.startswith("Unknown LU-Alert level")]
        self.assertEqual(len(told), 1)
        self.assertIn("'ALERT_LVL_9'", told[0])
        self.next_poll()
        self.assertEqual(len([t for t in self.logs() if t.startswith("Unknown LU-Alert level")]), 1)

    def test_the_description_goes_to_the_verbose_log_only(self):
        self.make(level=2)
        self.fake.add("a", cap_xml("a"))
        self.start()
        self.assertTrue(any("Description: Strong winds expected. Gusts up to 110 km/h." in t for t in dz.messages("debug")))
        self.assertFalse(any("Strong winds" in t for t in self.logs()))

    def test_devices_domoticz_refused_at_start_appear_later(self):
        dz.accept_new_devices = False
        self.start()
        self.assertEqual(len([t for t in self.errors() if t.startswith("Domoticz did not create")]), 1)
        self.assertEqual(dz.create_attempts, [1])
        self.assertIn("Connected to the LU-Alert feed: 0 alert files, 0 message(s) read", self.logs())
        dz.accept_new_devices = True
        self.fake.add("a", cap_xml("a"))
        self.assertGreaterEqual(self.controller.settings.interval, 60)
        self.clock.advance(CREATE_RETRY_SECONDS)             # Domoticz is asked again after five minutes at the earliest
        self.next_poll()
        self.assertEqual(len(dz.Devices), 18)
        self.assertEqual(self.value(UNIT_ACTIVE), (0, "1"))


class FailureTests(ControllerCase):
    def test_a_failure_is_one_error_then_quiet_and_recovery_is_announced(self):
        self.fake.add("a", cap_xml("a"))
        self.start()
        self.fake.fail.extend([("status", 503)] * 3)
        for delay in (300, 600, 1200):
            self.next_poll()
            self.assertEqual(round(self.controller.next_poll_at - self.clock()), delay)
        self.assertEqual(len(self.errors()), 1, self.errors())
        self.assertIn("LU-Alert feed poll failed: dataset description: HTTP 503", self.errors()[0])
        self.assertEqual(self.value(UNIT_STATUS), (0, "Off"))
        self.next_poll()
        self.assertEqual(self.value(UNIT_STATUS), (1, "On"))
        self.assertIn("The LU-Alert feed answers again", self.logs())
        self.assertEqual((self.controller.failures, len(self.errors())), (0, 1))

    def test_the_wait_grows_and_is_capped(self):
        self.start()
        self.fake.stop()
        delays = []
        for _ in range(6):
            self.next_poll()
            delays.append(round(self.controller.next_poll_at - self.clock()))
        self.assertEqual(delays, [300, 600, 1200, 1800, 1800, 1800])
        self.assertEqual(max(delays), MAX_BACKOFF)
        self.assertEqual(len(self.errors()), 1)

    def test_a_failing_feed_never_clears_the_alerts_and_says_so(self):
        self.fake.add("a", cap_xml("a"))
        self.start()
        self.fake.fail.append(("drop",))
        self.next_poll()
        self.assertEqual(self.value(UNIT_ACTIVE), (0, "1"))
        self.assertEqual(self.value(UNIT_CRITICAL), (1, "On"))
        self.assertEqual(self.value(UNIT_STATUS), (0, "Off"))
        self.assertIn("Feed not reachable since", self.value(UNIT_FEED_INFO)[1])
        self.assertIn("last known alerts", self.value(UNIT_FEED_INFO)[1])

    def test_an_alert_still_ends_at_its_end_time_while_the_feed_is_down(self):
        self.fake.add("a", cap_xml("a", expires=NOW + timedelta(minutes=10)))
        self.start()
        self.fake.stop()
        self.next_poll()
        self.assertEqual(self.value(UNIT_ACTIVE), (0, "1"))
        self.wall.advance(20 * 60)
        self.controller.on_heartbeat()
        self.assertEqual(self.value(UNIT_ACTIVE), (0, "0"))
        self.assertEqual(self.value(UNIT_STATUS), (0, "Off"))

    def test_unreachable_at_start_still_creates_the_devices(self):
        self.fake.stop()
        self.start()
        self.assertEqual(len(dz.Devices), 18)
        self.assertEqual(self.value(UNIT_STATUS), (0, "Off"))
        self.assertEqual(len(self.errors()), 1)

    def test_a_certificate_problem_names_the_cause_once(self):
        self.make(ssl_context=None)                         # the system's CAs do not know the test CA
        self.start()
        self.assertEqual(len(self.errors()), 1)
        self.assertIn("certificate of the server is not trusted", self.errors()[0])

    def test_a_different_problem_is_a_new_error(self):
        self.start()
        self.fake.fail.append(("status", 503))
        self.next_poll()
        self.fake.fail.append(("garbage",))
        self.next_poll()
        self.assertEqual(len(self.errors()), 2)

    def test_files_that_cannot_be_read_are_reported_once_and_the_rest_is_used(self):
        self.fake.add("a", cap_xml("a"))
        self.fake.add("junk", "no xml", modified="2026-11-02T11:00:00")
        self.start()
        self.assertEqual(self.value(UNIT_ACTIVE), (0, "1"))
        reports = [t for t in self.errors() if "alert file(s) are not valid CAP" in t]
        self.assertEqual(len(reports), 1)
        self.next_poll()
        self.assertEqual(len([t for t in self.errors() if "alert file(s) are not valid CAP" in t]), 1)
        self.fake.remove("junk")
        self.next_poll()
        self.assertIn("No alert file is unreadable any more", self.logs())

    def test_a_partial_read_is_shown_as_partial_and_recovers(self):
        self.fake.add("a", cap_xml("a", headline="one"))
        self.fake.add("b", cap_xml("b", headline="two"), modified="2026-11-02T11:00:00")
        self.fake.fail.extend([("ok",), ("status", 500)])
        self.start()
        self.assertTrue(self.value(UNIT_FEED_INFO)[1].startswith("Partial"))
        self.assertTrue(any("Could not read 1 of 2 alert files" in t for t in self.errors()))
        self.next_poll()
        self.assertTrue(self.value(UNIT_FEED_INFO)[1].startswith("OK"))
        self.assertIn("All alert files can be read again", self.logs())
        self.assertEqual(self.value(UNIT_ACTIVE), (0, "2"))

    def test_an_unexpected_exception_is_one_error_not_a_crash(self):
        def boom(should_stop):
            raise RuntimeError("boom")
        self.controller.feed.refresh = boom
        self.start()
        self.assertEqual(len(self.errors()), 1)
        self.assertIn("RuntimeError: boom", self.errors()[0])
        self.assertGreater(self.controller.next_poll_at, self.clock())          # no retry storm


class CommandTests(ControllerCase):
    def test_a_command_for_one_of_our_devices_is_refused_and_confirmed(self):
        self.start()
        self.controller.on_command(UNIT_CRITICAL, "On", 0)
        self.assertTrue(any("cannot be switched" in t and "Critical Alert Active" in t for t in self.logs()))
        self.assertTrue(dz.Devices[UNIT_CRITICAL].update_calls[-1]["SuppressTriggers"])

    def test_the_status_switch_says_what_it_shows(self):
        self.start()
        self.controller.on_command(UNIT_STATUS, "Off", 0)
        self.assertTrue(any("shows whether the feed answers" in t for t in self.logs()))

    def test_a_command_for_a_foreign_unit(self):
        self.start()
        self.controller.on_command(99, "On", 0)
        self.assertTrue(any("Unit 99 is not a LU-Alert device" in t for t in self.logs()))


class StopTests(ControllerCase):
    def test_stop_without_a_poll(self):
        self.start()
        self.controller.stop()
        self.controller.stop()                               # twice is harmless

    def test_stop_waits_for_the_thread_and_a_late_result_is_dropped(self):
        release = threading.Event()
        real = self.controller.feed.refresh

        def slow(should_stop):
            release.wait(5)
            return real(should_stop)
        self.controller.feed.refresh = slow
        self.make_threaded()
        self.controller.start()
        self.assertTrue(self.controller.polling)
        threading.Timer(0.2, release.set).start()
        self.controller.stop()
        self.assertFalse(self.controller.polling)
        self.controller.on_heartbeat()
        self.assertEqual(self.errors(), [])

    def make_threaded(self):
        self.controller.spawn = start_thread

    def test_a_poll_that_will_not_end_is_abandoned_with_an_error(self):
        import lu_alert.controller as module
        release = threading.Event()
        self.addCleanup(release.set)
        self.controller.feed.refresh = lambda should_stop: release.wait(10)
        self.make_threaded()
        original = module.STOP_TIMEOUT
        module.STOP_TIMEOUT = 0.1
        self.addCleanup(setattr, module, "STOP_TIMEOUT", original)
        self.controller.start()
        self.controller.stop()
        self.assertTrue(any("did not end within" in t for t in self.errors()))


if __name__ == "__main__":
    unittest.main()
