"""``python3 -m lu_alert``: the engine of the plugin without Domoticz.

Reads the live feed (or local CAP files with ``--xml``) and prints the alerts the plugin would show, with the same
filters. Use it before adding the hardware, and whenever the devices show something unexpected.

Exit status: 0 ok, 1 bad options or files, 2 the feed cannot be read.
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from typing import List, Optional

from . import __version__
from .alerts import Filters, build_snapshot, format_time
from .api import ApiError, Client
from .cap import CapError, parse_cap
from .config import Settings, SettingsError
from .constants import DATASET_URL, MIN_SEVERITY_CHOICES, SEVERITIES
from .feed import Feed
from .model import ActiveAlert


class _Parser(argparse.ArgumentParser):
    """argparse that writes to the streams ``main`` was given, and whose usage errors exit with 1.

    The status 2 belongs to 'the feed cannot be read', as documented above; argparse' own 2 would mix the two up."""

    streams: tuple = ()

    def _print_message(self, message, file=None):          # argparse hook
        if message:
            out, err = self.streams or (sys.stdout, sys.stderr)
            (out if file is sys.stdout else err).write(message)

    def error(self, message):
        self.print_usage(sys.stderr)
        self.exit(1, "%s: error: %s\n" % (self.prog, message))


def _parser(out=None, err=None) -> argparse.ArgumentParser:
    p = _Parser(prog="python3 -m lu_alert", description="Show the LU-Alert alerts the plugin would show.")
    p.streams = (out or sys.stdout, err or sys.stderr)
    p.add_argument("--xml", nargs="+", metavar="FILE", help="read CAP files from disk instead of the live feed")
    p.add_argument("--min-severity", default="Unknown", choices=MIN_SEVERITY_CHOICES, help="default: all alerts")
    p.add_argument("--language", default="en", help="en, de, fr or lb (default en)")
    p.add_argument("--location", metavar="LAT;LON", default="", help="your home, for the local-alert test")
    p.add_argument("--only-local", action="store_true", help="show only alerts whose area contains --location")
    p.add_argument("--keywords", default="", help="watchlist keywords, comma separated")
    p.add_argument("--allergens", default="", help="allergens, comma separated")
    p.add_argument("--show-test", action="store_true", help="also show test and exercise messages")
    p.add_argument("--max-resources", type=int, default=None, help="how many of the newest files to read")
    p.add_argument("--dataset-url", default=None, help="default: %s" % DATASET_URL)
    p.add_argument("--json", action="store_true", help="machine readable output")
    p.add_argument("--version", action="version", version="lu_alert " + __version__)
    return p


def _row(alert: ActiveAlert) -> dict:
    iso = lambda moment: moment.isoformat() if moment else None  # noqa: E731
    return {"identifier": alert.identifier, "severity": alert.severity, "level": alert.level_code,
            "headline": alert.headline, "description": alert.description, "instruction": alert.instruction,
            "event": alert.event, "language": alert.language, "categories": list(alert.categories),
            "sent": iso(alert.sent), "expires": iso(alert.expires), "areas": list(alert.area_desc),
            "local": alert.local, "watchlist_match": alert.watch_match, "allergen_match": alert.allergen_match,
            "web": alert.web}


def main(argv: Optional[List[str]] = None, out=None, err=None) -> int:
    out = out or sys.stdout
    err = err or sys.stderr
    args = _parser(out, err).parse_args(argv)
    params = {"Mode1": args.min_severity, "Mode2": args.language, "Address": args.location,
              "Mode4": "2" if args.only_local else ("1" if args.location else "0"), "Mode5": args.keywords,
              "Username": args.allergens}
    try:
        settings = Settings.from_parameters(params)
    except SettingsError as exc:
        print("error: %s" % exc, file=err)
        return 1
    if args.show_test:
        settings.show_test = True
    if args.max_resources:
        settings.max_resources = args.max_resources
    if args.dataset_url:
        settings.dataset_url = args.dataset_url
    for warning in settings.warnings + settings.notes:
        print("note: %s" % warning, file=err)

    cap_alerts = []
    summary = ""
    if args.xml:
        for path in args.xml:
            try:
                with open(path, "rb") as fh:
                    cap_alerts.extend(parse_cap(fh.read()))
            except (OSError, CapError) as exc:
                print("error: %s: %s" % (path, exc), file=err)
                return 1
        summary = "%d file(s) read" % len(args.xml)
    else:
        feed = Feed(Client(settings.dataset_url, settings.http_timeout, allowed_hosts=settings.allowed_hosts),
                    settings.max_resources)
        try:
            result = feed.refresh()
        except ApiError as exc:
            print("error: the LU-Alert feed cannot be read: %s" % exc, file=err)
            return 2
        cap_alerts = result.cap_alerts
        summary = "%d alert files listed, %d read now" % (result.listed, result.fetched)
        if result.failed or result.unreadable:
            print("note: %d file(s) not readable now, %d not valid CAP%s" % (
                result.failed, result.unreadable, (" (e.g. %s)" % result.errors[0]) if result.errors else ""), file=err)

    snapshot = build_snapshot(cap_alerts, datetime.now(timezone.utc), Filters.from_settings(settings))
    if args.json:
        json.dump({"alerts": [_row(a) for a in snapshot.alerts], "counts": snapshot.counts, "dropped": snapshot.dropped,
                   "ignored_tests": [{"identifier": i, "level": lv, "headline": h} for i, lv, h in snapshot.ignored_tests],
                   "unknown_levels": list(snapshot.unknown_levels)},
                  out, indent=2, ensure_ascii=False)
        out.write("\n")
        return 0
    if not snapshot.alerts:
        print("No active alerts (%s)." % summary, file=out)
    for alert in snapshot.alerts:
        print("[%s] %s  (level %s, until %s)" % (alert.severity, alert.headline, alert.level_code or "-",
                                                  format_time(alert.expires) or "no end given"), file=out)
        if alert.area_desc:
            print("    area: %s%s" % (", ".join(alert.area_desc),
                                      "" if alert.local is None else ("   <- your location" if alert.local else "")), file=out)
        if alert.instruction:
            print("    instruction: %s" % alert.instruction, file=out)
        if alert.watch_match or alert.allergen_match:
            print("    matches your %s" % " and ".join(n for n, f in (("watchlist", alert.watch_match),
                                                                      ("allergens", alert.allergen_match)) if f), file=out)
    counts = ", ".join("%s %d" % (s, snapshot.counts[s]) for s in SEVERITIES if snapshot.counts[s])
    print("\n%d active alert(s)%s; %s." % (snapshot.total, " (%s)" % counts if counts else "", summary), file=out)
    if snapshot.dropped:
        print("Left out: %s." % ", ".join("%s %d" % (why, n) for why, n in sorted(snapshot.dropped.items())), file=out)
    if snapshot.unknown_levels:
        print("Unknown level(s): %s. The CAP severity of those messages is used; please report them." %
              ", ".join(snapshot.unknown_levels), file=out)
    return 0
