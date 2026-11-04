"""Poll scheduling, error policy, logging of new and ended alerts. Knows neither Domoticz nor HTTP details.

A poll (one request for the dataset description plus the new alert files) runs in a background thread, so the Domoticz
plugin thread never waits for the network: it starts a poll when one is due, and on every heartbeat it picks up the
result of a finished one. The thread never touches Domoticz and never logs: what it has to say travels in its result.

Error policy:

    * every problem is logged ONCE as an error, repeats go to the verbose log, and recovery is logged once
    * after a failed poll the next attempt waits longer (backoff, capped)
    * the "LU-Alert Status" switch follows the feed: On while polls succeed, Off while they fail
    * a failed poll NEVER clears the alerts: the devices keep showing the last known alerts (they still end when
      their end time passes), and the "Feed Info" text says that the feed is not reachable
    * files that cannot be read are reported once, with how many; the other files are used
"""
import queue
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, NamedTuple, Optional

from .alerts import Filters, build_snapshot, summary_line
from .api import ApiError
from .constants import MAX_BACKOFF, STOP_TIMEOUT, UNIT_STATUS
from .feed import FeedResult
from .model import ActiveAlert, CapAlert, Snapshot
from .util import shorten


class PollResult(NamedTuple):
    feed: Optional[FeedResult] = None
    error: Optional[ApiError] = None


def start_thread(target: Callable[[], None]) -> threading.Thread:
    thread = threading.Thread(target=target, name="LUAlert-poll", daemon=True)
    thread.start()
    return thread


class Controller:
    def __init__(self, settings: Any, feed: Any, devices: Any, logger: Any,
                 clock: Callable[[], float] = time.monotonic, wall_clock: Callable[[], float] = time.time,
                 spawn: Callable[[Callable[[], None]], Any] = start_thread) -> None:
        self.settings = settings
        self.feed = feed
        self.devices = devices
        self.log = logger
        self.clock = clock
        self.wall_clock = wall_clock
        self.spawn = spawn
        self.filters = Filters.from_settings(settings)
        self.next_poll_at = 0.0
        self.failures = 0
        self.connected = False
        self.snapshot: Optional[Snapshot] = None
        self.cap_alerts: List[CapAlert] = []
        self._thread: Any = None                        # the running poll; set and cleared on the plugin thread only
        self._results: "queue.Queue[PollResult]" = queue.Queue()
        self._halt = threading.Event()
        self._problems: Dict[str, str] = {}             # problem key -> kind of the last one logged
        self._known: Dict[str, ActiveAlert] = {}        # the alerts the log already told about
        self._tests_told: set = set()                   # identifiers of test messages the log already named
        self._levels_told: set = set()                  # level codes the log already called unknown
        self._first_snapshot = True
        self._down_since: Optional[float] = None

    # -- life cycle -----------------------------------------------------------------------------------------
    def start(self) -> None:
        self.devices.ensure_devices()
        self._begin_poll()

    def stop(self) -> None:
        self._halt.set()
        thread = self._thread
        if thread is not None:
            thread.join(STOP_TIMEOUT)
            if thread.is_alive():
                self.log.Error("A poll of the LU-Alert feed did not end within %d s; it is abandoned" % STOP_TIMEOUT)
        self._thread = None

    def on_heartbeat(self) -> None:
        self._collect()
        if self._thread is None and self.clock() >= self.next_poll_at:
            self._begin_poll()
        self._expire()

    @property
    def polling(self) -> bool:
        return self._thread is not None

    # -- polling --------------------------------------------------------------------------------------------
    def _begin_poll(self) -> None:
        self.next_poll_at = self.clock() + self.settings.interval     # an unexpected exception must not cause a retry storm
        self.log.Basic("Polling the LU-Alert feed")
        self._thread = self.spawn(self._poll_in_thread)

    def _poll_in_thread(self) -> None:
        """Runs in the background thread: reads the feed, queues ONE result, never raises, never logs."""
        try:
            result = PollResult(feed=self.feed.refresh(self._halt.is_set))
        except ApiError as exc:
            result = PollResult(error=exc)
        except Exception as exc:
            result = PollResult(error=ApiError("%s: %s" % (type(exc).__name__, exc), "unexpected"))
        self._results.put(result)

    def _collect(self) -> None:
        """Apply the results of finished polls (plugin thread)."""
        while True:
            try:
                result = self._results.get_nowait()
            except queue.Empty:
                return
            self._thread = None
            if self._halt.is_set():
                continue
            if result.error is not None:
                self._poll_failed(result.error)
            else:
                self._poll_worked(result.feed)

    def _poll_worked(self, feed: FeedResult) -> None:
        for level, text in feed.messages:
            self.log.emit(level, text)
        self.failures = 0
        self._down_since = None
        if not self.connected:
            self.connected = True
            self.log.Log("Connected to the LU-Alert feed: %d alert files, %d message(s) read" % (feed.listed,
                                                                                                    len(feed.cap_alerts)))
        self._recovered("feed", "The LU-Alert feed answers again")
        self.cap_alerts = feed.cap_alerts
        self.devices.ensure_devices()                   # devices Domoticz did not accept at first, unit labels
        self.devices.set_status(True)
        self._show(self._build())

        if feed.failed:
            self._report("files", "Could not read %d of %d alert files (%s): the alerts shown may be incomplete, the "
                         "next poll tries again" % (feed.failed, feed.listed, shorten(feed.errors[0], 150)), "failed")
        else:
            self._recovered("files", "All alert files can be read again")
        if feed.unreadable:
            self._report("unreadable", "%d alert file(s) are not valid CAP or too large and are ignored (%s)"
                         % (feed.unreadable, shorten(feed.errors[0], 150) if feed.errors else "see the verbose log"),
                         "unreadable")
        else:
            self._recovered("unreadable", "No alert file is unreadable any more")
        info = "OK %s: %d files (%d new), %d active" % (self._clock_text(), feed.listed, feed.fetched,
                                                         self.snapshot.total if self.snapshot else 0)
        if feed.failed:
            info = "Partial %s: %d of %d files not readable, %d active" % (
                self._clock_text(), feed.failed, feed.listed, self.snapshot.total if self.snapshot else 0)
        self.devices.set_feed_info(info)

    def _poll_failed(self, exc: ApiError) -> None:
        self.failures += 1
        self.connected = False
        if self._down_since is None:
            self._down_since = self.wall_clock()
        self.devices.ensure_devices()
        self.devices.set_status(False)
        self.devices.set_feed_info("Feed not reachable since %s: the alert devices show the last known alerts"
                                   % time.strftime("%H:%M", time.localtime(self._down_since)))
        self._report("feed", "LU-Alert feed poll failed: %s" % exc, exc.kind)
        interval = self.settings.interval
        delay = max(interval, min(interval * 2 ** min(self.failures - 1, 6), MAX_BACKOFF))
        self.next_poll_at = self.clock() + delay
        self.log.Basic("Failure %d, next attempt in %d s" % (self.failures, delay))

    # -- showing --------------------------------------------------------------------------------------------
    def _now(self) -> datetime:
        return datetime.fromtimestamp(self.wall_clock(), timezone.utc)

    def _clock_text(self) -> str:
        return time.strftime("%H:%M", time.localtime(self.wall_clock()))

    def _build(self) -> Snapshot:
        snapshot = build_snapshot(self.cap_alerts, self._now(), self.filters)
        self.snapshot = snapshot
        if snapshot.dropped:
            self.log.Verbose("Left out: %s" % ", ".join("%s %d" % (why, n) for why, n in sorted(snapshot.dropped.items())))
        return snapshot

    def _show(self, snapshot: Snapshot) -> None:
        self.devices.show(snapshot)
        current = {a.identifier: a for a in snapshot.alerts}
        first = self._first_snapshot
        self._first_snapshot = False
        for identifier, alert in current.items():
            if identifier not in self._known:
                self._announce("Active alert" if first else "New alert", alert)
        for identifier, alert in self._known.items():
            if identifier not in current:
                self.log.Log("Alert ended: %s" % summary_line(alert, 160))
        if first and not current:
            self.log.Log("No active LU-Alert alerts")
        self._known = current
        for level in snapshot.unknown_levels:
            if level not in self._levels_told:
                self._levels_told.add(level)
                self.log.Log("Unknown LU-Alert level '%s': the CAP severity of the message is used. Please report this "
                             "level (python3 -m lu_alert --json shows it)" % shorten(level, 40))
        for identifier, level, headline in snapshot.ignored_tests:
            if identifier not in self._tests_told:      # said once, so a real alert taken for a test is not silent
                self._tests_told.add(identifier)
                self.log.Log("Test message ignored (%s): %s" % (shorten(level or "no level", 40), shorten(headline, 120)))

    def _announce(self, what: str, alert: ActiveAlert) -> None:
        where = " (%s)" % shorten(", ".join(alert.area_desc), 80) if alert.area_desc else ""
        self.log.Log("%s: %s%s" % (what, summary_line(alert, 200), where))
        if alert.instruction:
            self.log.Log("Instruction: %s" % shorten(alert.instruction, 300))
        if alert.description:
            self.log.Verbose("Description: %s" % shorten(alert.description, 600))

    def _expire(self) -> None:
        """An alert ends when its time is up, also while the feed cannot be reached or between two polls."""
        snapshot = self.snapshot
        if snapshot is None or snapshot.next_expiry is None or self._now() < snapshot.next_expiry:
            return
        self._show(self._build())

    # -- problems -------------------------------------------------------------------------------------------
    def _report(self, key: str, message: str, kind: str) -> None:
        if self._problems.get(key) == kind:
            self.log.Verbose(message)                           # same problem as before: not an error again
            return
        self._problems[key] = kind
        self.log.Error(message)

    def _recovered(self, key: str, message: str) -> None:
        if self._problems.pop(key, None) is not None:
            self.log.Log(message)

    # -- commands -------------------------------------------------------------------------------------------
    def on_command(self, unit: int, command: Any, level: Any = None) -> None:
        name = self.devices.name_of(unit)
        self.log.Log("Command received: unit %d (%s) %s" % (unit, name or "unknown", command))
        if self.devices.owns(unit):
            what = "shows whether the feed answers" if unit == UNIT_STATUS else "only shows what the feed reports"
            self.log.Log("'%s' %s; it cannot be switched" % (name or "unit %d" % unit, what))
        else:
            self.log.Log("Unit %d is not a LU-Alert device, the command is ignored" % unit)
        self.devices.restore(unit)
