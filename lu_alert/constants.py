"""The device model, the severity tables and the timings of the plugin.

Unit numbers never change once released: they keep existing devices (and their history, scenes, scripts and
schedules) intact when upgrading.
"""
from typing import NamedTuple, Tuple

from . import __version__

PLUGIN_KEY = "LUAlert"
PLUGIN_NAME = "LU-Alert Luxembourg"
PLUGIN_URL = "https://github.com/janreimen/Domoticz-LUAlert"
USER_AGENT = "Domoticz-LUAlert/%s (+%s)" % (__version__, PLUGIN_URL)

# The dataset "Alertes du système LU-Alert" on data.public.lu: one CAP XML file per message.
DATASET_URL = "https://data.public.lu/api/1/datasets/67aca67bcaea3ae62308114f/"

# -- timings ------------------------------------------------------------------------------------------------
HEARTBEAT_SECONDS = 10        # Domoticz caps the heartbeat at 30 s; polling is scheduled by time, not by count
DEFAULT_INTERVAL = 300        # seconds between polls
MIN_INTERVAL = 60
MAX_INTERVAL = 3600
MAX_BACKOFF = 1800            # longest wait between polls after failures
HTTP_TIMEOUT = 10             # seconds per HTTP request (.env LU_HTTP_TIMEOUT)
STOP_TIMEOUT = 12             # onStop waits this long for a running poll (a request ends at HTTP_TIMEOUT at the latest)
FETCH_WORKERS = 5             # alert files downloaded in parallel
MAX_DATASET_BYTES = 16 * 1024 * 1024    # the dataset description lists every file ever published
MAX_XML_BYTES = 2 * 1024 * 1024         # one CAP message; areas with large polygons are a few hundred kB
DEFAULT_MAX_RESOURCES = 100   # the newest files that are looked at (.env LU_MAX_RESOURCES)
DEFAULT_STALE_DAYS = 10       # a message without an end that is older than this is not shown (.env LU_STALE_DAYS)
REFRESH_SECONDS = 300         # rewrite an unchanged value this often, so Domoticz' sensor time-out never fires
CREATE_RETRY_SECONDS = 300    # after Domoticz refused to create a device, ask again no sooner than this
MAX_TEXT = 200                # Domoticz keeps the value text of a device in a VARCHAR(200) column
MAX_ALERT_DEVICES = 10
DEFAULT_ALERT_DEVICES = 3

# -- severity ---------------------------------------------------------------------------------------------
EXTREME, SEVERE, MODERATE, MINOR, INFORMATION, UNKNOWN, TEST = (
    "Extreme", "Severe", "Moderate", "Minor", "Information", "Unknown", "Test")
SEVERITIES = (EXTREME, SEVERE, MODERATE, MINOR, INFORMATION, UNKNOWN, TEST)
# Higher is more severe. Test is below everything: it is shown only when a test is asked for.
SEVERITY_RANK = {EXTREME: 4, SEVERE: 3, MODERATE: 2, MINOR: 1, INFORMATION: 0, UNKNOWN: -1, TEST: -2}
# Choices of the hardware setting "Minimum severity"
MIN_SEVERITY_CHOICES = ("Unknown", INFORMATION, MINOR, MODERATE, SEVERE, EXTREME)

# The LU-Alert level of a message, as the feed writes it (compared in lower case). The LIVE feed (looked at on
# 2026-11-04, 100 messages) uses ALERT_LVL_1 ... ALERT_LVL_4 and TEST; the other spellings come from the Home Assistant
# integration, the levels named on https://lu-alert.lu (D, N1-N3, A, I, T) and the CAP-LU profile (LU-Alert Level 1-4,
# Amber, Test, Exercise) and have not been seen in the feed.
LEVEL_TO_SEVERITY = {
    "d": EXTREME,                       # only when D is not a test level (see DEFAULT_TEST_LEVELS)
    "n1": EXTREME,                      # awareness level red
    "l1": EXTREME, "lu-alert level 1": EXTREME, "alert_lvl_1": EXTREME,
    "n2": SEVERE,                       # awareness level orange
    "l2": SEVERE, "lu-alert level 2": SEVERE, "alert_lvl_2": SEVERE,
    "a": MODERATE,                      # missing person / kidnapping (amber)
    "lu-alert amber": MODERATE,
    "n3": MINOR,                        # awareness level yellow
    "l3": MINOR, "lu-alert level 3": MINOR, "alert_lvl_3": MINOR,
    "i": INFORMATION,
    "lu-alert level 4": INFORMATION, "alert_lvl_4": INFORMATION,
    "t": TEST, "test": TEST, "lu-alert test": TEST, "lu-alert exercise": TEST,
}
# The names of the parameter that carries the level. The feed writes them with the profile prefix
# ("urn:oasis:...:profile:cap-lu:1.0:cb-eu-level"), the profile document without: the part after the last ':' counts.
LEVEL_PARAMETERS = ("cb-eu-level", "cb-lu-level")
# Levels that are treated as test messages (and so left out) unless tests are asked for. "D" is in the list because the
# Home Assistant integration this plugin follows filters it as a test level; it is also an Extreme level there, which
# is what it becomes when you take it out of LU_TEST_LEVELS. D has NOT been seen in the live feed: see the README.
# TEST is what the live feed writes for its test messages (with the CAP status Actual).
DEFAULT_TEST_LEVELS = ("T", "TEST", "D", "LU-Alert Test", "LU-Alert Exercise")
# CAP status values that are not a real alert: Test, Exercise, System and Draft are shown only when tests are shown
REAL_STATUS = "actual"

# Channel blocks of CAP-LU: one <info> per language and channel. The text of the app and the website is the fullest,
# a siren block has no text for people.
CHANNEL_PARAMETER = "canal"
CHANNEL_ORDER = ("mobile-app", "website channel", "cell-broadcast", "sms", "email", "facebook")
CHANNEL_LAST = ("siren", "led-signs", "twitter")

LANGUAGES = ("en", "de", "fr", "lb")
DEFAULT_LANGUAGE = "en"
MSG_NO_ALERT = ("ack", "error")        # CAP replies, not alerts

# -- device kinds -------------------------------------------------------------------------------------------
KIND_COUNT = "count"          # Custom Sensor with a unit label, whole numbers
KIND_FLAG = "flag"            # On/Off switch that shows a state (read-only)
KIND_TEXT = "text"            # Text device (read-only)
KIND_ALERT = "alert"          # Alert device: a coloured level and a text (read-only)

# Domoticz TypeName of each kind. TypeName is the documented way to create a device.
TYPENAME_COUNT = "Custom"
TYPENAME_SWITCH = "Switch"
TYPENAME_TEXT = "Text"
TYPENAME_ALERT = "Alert"
SWITCHTYPE_ONOFF = 0
SUBTYPE_CUSTOM = 31           # what Domoticz makes of TypeName "Custom" (sTypeCustom, 0x1F in hardwaretypes.h)

# Domoticz alert levels: 0 grey, 1 green, 2 yellow, 3 orange, 4 red
ALERT_GREY, ALERT_GREEN, ALERT_YELLOW, ALERT_ORANGE, ALERT_RED = 0, 1, 2, 3, 4
SEVERITY_ALERT_LEVEL = {EXTREME: ALERT_RED, SEVERE: ALERT_RED, MODERATE: ALERT_ORANGE, MINOR: ALERT_YELLOW,
                        INFORMATION: ALERT_GREEN, UNKNOWN: ALERT_GREY, TEST: ALERT_GREY}


class Device(NamedTuple):
    unit: int
    key: str
    name: str
    kind: str
    label: str                # unit label of a Custom Sensor ("" for the others)


UNIT_ACTIVE = 1
UNIT_HIGHEST = 2
UNIT_CRITICAL = 3
UNIT_SEVERE = 4
UNIT_EXTREME = 5
UNIT_LOCAL = 6
UNIT_WATCHLIST = 7
UNIT_ALLERGEN = 8
UNIT_STATUS = 9
UNIT_FEED_INFO = 10
UNIT_ALERT_FIRST = 11         # units 11-20: "Alert 1" ... "Alert 10"
UNIT_ALERT_LAST = 20
UNIT_COUNT_EXTREME = 21
UNIT_COUNT_SEVERE = 22
UNIT_COUNT_MODERATE = 23
UNIT_COUNT_MINOR = 24
UNIT_COUNT_INFORMATION = 25

FIXED_DEVICES: Tuple[Device, ...] = (
    Device(UNIT_ACTIVE, "active", "Active Alerts", KIND_COUNT, "alerts"),
    Device(UNIT_HIGHEST, "highest", "Highest Severity", KIND_ALERT, ""),
    Device(UNIT_CRITICAL, "critical", "Critical Alert Active", KIND_FLAG, ""),
    Device(UNIT_SEVERE, "severe", "Severe Alert Active", KIND_FLAG, ""),
    Device(UNIT_EXTREME, "extreme", "Extreme Alert Active", KIND_FLAG, ""),
    Device(UNIT_LOCAL, "local", "Local Alert Active", KIND_FLAG, ""),
    Device(UNIT_WATCHLIST, "watchlist", "Watchlist Match", KIND_FLAG, ""),
    Device(UNIT_ALLERGEN, "allergen", "Allergen Match", KIND_FLAG, ""),
    Device(UNIT_STATUS, "status", "LU-Alert Status", KIND_FLAG, ""),
    Device(UNIT_FEED_INFO, "feed_info", "Feed Info", KIND_TEXT, ""),
    Device(UNIT_COUNT_EXTREME, "count_extreme", "Extreme Alerts", KIND_COUNT, "alerts"),
    Device(UNIT_COUNT_SEVERE, "count_severe", "Severe Alerts", KIND_COUNT, "alerts"),
    Device(UNIT_COUNT_MODERATE, "count_moderate", "Moderate Alerts", KIND_COUNT, "alerts"),
    Device(UNIT_COUNT_MINOR, "count_minor", "Minor Alerts", KIND_COUNT, "alerts"),
    Device(UNIT_COUNT_INFORMATION, "count_information", "Information Alerts", KIND_COUNT, "alerts"),
)

SEVERITY_COUNT_UNITS = {EXTREME: UNIT_COUNT_EXTREME, SEVERE: UNIT_COUNT_SEVERE, MODERATE: UNIT_COUNT_MODERATE,
                        MINOR: UNIT_COUNT_MINOR, INFORMATION: UNIT_COUNT_INFORMATION}


def alert_slot(index: int) -> Device:
    """The device of alert number ``index`` (1-based)."""
    return Device(UNIT_ALERT_FIRST + index - 1, "alert_%d" % index, "Alert %d" % index, KIND_ALERT, "")


ALERT_SLOTS: Tuple[Device, ...] = tuple(alert_slot(i) for i in range(1, MAX_ALERT_DEVICES + 1))

# Location filter (hardware setting "Location filter")
LOCATION_OFF, LOCATION_FLAG, LOCATION_ONLY = 0, 1, 2
LOCATION_NAMES = {LOCATION_OFF: "Off", LOCATION_FLAG: "Flag local alerts", LOCATION_ONLY: "Only local alerts"}

# Text that tells a user what the "Alert n" devices show when there is nothing to show
TEXT_NO_ALERT = "No alert"
TEXT_UNUSED = "Not in use (raise LU_ALERT_DEVICES in .env)"
