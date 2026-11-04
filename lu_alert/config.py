"""Plugin settings, parsed and validated from the Domoticz ``Parameters`` dict and the plugin-local ``.env``.

Hardware-page fields (see the manifest in plugin.py):

    Address   latitude;longitude of your home for the location filter; empty = the location set in Domoticz
    Username  allergens to watch for (comma separated; the field is not a user name here, it is shown as "Allergens")
    Mode1     minimum severity: Unknown (all) | Information | Minor | Moderate | Severe | Extreme
    Mode2     language of the alert texts: en | de | fr | lb
    Mode3     update interval in seconds
    Mode4     location filter: 0 Off | 1 Flag local alerts | 2 Only local alerts
    Mode5     watchlist keywords (comma separated)
    Mode6     debug level: 0 Off | 1 Basic | 2 Verbose | 3 Debug

Technical settings live in ``.env`` beside plugin.py (see ``.env.sample``); the process environment overrides it.
"""
import difflib
import os
import re
from typing import Any, Dict, List, Mapping, NamedTuple, Optional, Tuple
from urllib.parse import urlsplit

from .constants import (
    DATASET_URL, DEFAULT_ALERT_DEVICES, DEFAULT_INTERVAL, DEFAULT_LANGUAGE, DEFAULT_MAX_RESOURCES, DEFAULT_STALE_DAYS,
    DEFAULT_TEST_LEVELS, HTTP_TIMEOUT, LANGUAGES, LOCATION_FLAG, LOCATION_NAMES, LOCATION_OFF, LOCATION_ONLY,
    MAX_ALERT_DEVICES, MAX_INTERVAL, MIN_INTERVAL, MIN_SEVERITY_CHOICES, REFRESH_SECONDS,
)
from .util import clamp, safe_int, split_list

CAP_CATEGORIES = ("Geo", "Met", "Safety", "Security", "Rescue", "Fire", "Health", "Env", "Transport", "Infra",
                  "CBRNE", "Other")
_LEGACY_DEBUG = {"normal": 0, "false": 0, "off": 0, "true": 3, "debug": 3}


class SettingsError(ValueError):
    """Raised for an invalid configuration: the plugin does not start."""


class Settings:
    def __init__(self, interval: int = DEFAULT_INTERVAL, min_severity: str = MIN_SEVERITY_CHOICES[0],
                 language: str = DEFAULT_LANGUAGE, location_mode: int = LOCATION_OFF,
                 location: Optional[Tuple[float, float]] = None, keywords: Tuple[str, ...] = (),
                 allergens: Tuple[str, ...] = (), debug: int = 0, dataset_url: str = DATASET_URL,
                 max_resources: int = DEFAULT_MAX_RESOURCES, http_timeout: int = HTTP_TIMEOUT,
                 alert_devices: int = DEFAULT_ALERT_DEVICES, refresh_interval: int = REFRESH_SECONDS,
                 stale_days: int = DEFAULT_STALE_DAYS, show_test: bool = False,
                 test_levels: Tuple[str, ...] = DEFAULT_TEST_LEVELS, ignore_categories: Tuple[str, ...] = (),
                 allowed_hosts: Tuple[str, ...] = (), env_file: Optional[str] = None, notes: Optional[List[str]] = None,
                 warnings: Optional[List[str]] = None) -> None:
        self.interval = interval
        self.min_severity = min_severity
        self.language = language
        self.location_mode = location_mode
        self.location = location
        self.keywords = tuple(keywords)
        self.allergens = tuple(allergens)
        self.debug = debug
        self.dataset_url = dataset_url
        self.max_resources = max_resources
        self.http_timeout = http_timeout
        self.alert_devices = alert_devices
        self.refresh_interval = refresh_interval
        self.stale_days = stale_days
        self.show_test = show_test
        self.test_levels = tuple(level.lower() for level in test_levels)
        self.ignore_categories = tuple(c.lower() for c in ignore_categories)
        self.allowed_hosts = tuple(allowed_hosts)       # extra hosts alert files may be fetched from (.env)
        self.env_file = env_file                        # the .env that was read; None = built-in defaults
        self.notes = list(notes or [])                  # things worth a log line at start-up (corrections made)
        self.warnings = list(warnings or [])            # problems in .env that did not stop the plugin

    @classmethod
    def from_parameters(cls, params: Mapping[str, Any], domoticz_settings: Optional[Mapping[str, Any]] = None,
                        env_path: Optional[str] = None) -> "Settings":
        def get(name: str, default: str = "") -> str:
            value = params.get(name, default)
            return default if value is None else str(value).strip()

        notes: List[str] = []
        env = load_env(env_path)

        interval = DEFAULT_INTERVAL
        interval_text = get("Mode3")
        if interval_text:
            number = safe_int(interval_text)
            if number is None:
                raise SettingsError("Update interval must be a number of seconds, got %r" % interval_text)
            interval = clamp(number, MIN_INTERVAL, MAX_INTERVAL)
            if interval != number:
                notes.append("Update interval %d s is outside %d-%d s, using %d s"
                             % (number, MIN_INTERVAL, MAX_INTERVAL, interval))

        min_severity = parse_min_severity(get("Mode1"))
        language = parse_language(get("Mode2"), notes)

        location_mode = parse_location_mode(get("Mode4"))
        location = parse_location(get("Address"))
        if location is None and get("Address"):
            raise SettingsError("The home location must be 'latitude;longitude' (for example 49.6116;6.1319), got %r"
                                % get("Address"))
        if location is None and location_mode != LOCATION_OFF:
            location = parse_location(str((domoticz_settings or {}).get("Location", "")))
            if location is not None:
                notes.append("Using the location set in Domoticz for the location filter")   # never the numbers
        if location is None and location_mode != LOCATION_OFF:
            notes.append("The location filter is '%s' but no location is known (fill in the Address field or set the "
                         "location in Domoticz); the location filter is off" % LOCATION_NAMES[location_mode])
            location_mode = LOCATION_OFF

        s = cls(interval=interval, min_severity=min_severity, language=language, location_mode=location_mode,
                location=location, keywords=tuple(split_list(get("Mode5"))), allergens=tuple(split_list(get("Username"))),
                debug=parse_debug(get("Mode6")), env_file=env.path, notes=notes, warnings=list(env.warnings))
        _apply_env(s, env.values)
        return s


# -- hardware fields ------------------------------------------------------------------------------------------
def parse_debug(text: str) -> int:
    text = str(text).strip().lower()
    if text in _LEGACY_DEBUG:
        return _LEGACY_DEBUG[text]
    return clamp(safe_int(text, 0) or 0, 0, 3)


def parse_min_severity(text: str) -> str:
    text = str(text).strip().lower()
    for choice in MIN_SEVERITY_CHOICES:
        if text == choice.lower():
            return choice
    if text in ("", "all"):
        return MIN_SEVERITY_CHOICES[0]
    raise SettingsError("Minimum severity must be one of %s, got %r" % (", ".join(MIN_SEVERITY_CHOICES), text))


def parse_language(text: str, notes: List[str]) -> str:
    text = str(text).strip().lower()[:2]
    if not text:
        return DEFAULT_LANGUAGE
    if text in LANGUAGES:
        return text
    notes.append("Language %r is not one of %s, using %s" % (text, ", ".join(LANGUAGES), DEFAULT_LANGUAGE))
    return DEFAULT_LANGUAGE


def parse_location_mode(text: str) -> int:
    text = str(text).strip().lower()
    if text in ("", "0", "off"):
        return LOCATION_OFF
    if text in ("1", "flag"):
        return LOCATION_FLAG
    if text in ("2", "only"):
        return LOCATION_ONLY
    raise SettingsError("Location filter must be 0 (Off), 1 (Flag local alerts) or 2 (Only local alerts), got %r" % text)


def parse_location(text: str) -> Optional[Tuple[float, float]]:
    """'49.6116;6.1319' (also with a comma, with a decimal comma not) -> (49.6116, 6.1319); None when it is no location."""
    parts = [p for p in re.split(r"[;\s]+|,\s+|,(?=-?\d+\.)", str(text).strip()) if p]
    if len(parts) != 2:
        return None
    try:
        lat, lon = float(parts[0]), float(parts[1])
    except ValueError:
        return None
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0) or lat != lat or lon != lon:
        return None
    return lat, lon


# -- .env -----------------------------------------------------------------------------------------------------
class _Spec(NamedTuple):
    attr: str
    kind: str                     # "int" | "bool" | "url" | "list"
    low: int = 0
    high: int = 0


# env key -> where it goes. The names carry the prefix LU_, so that no other program's variable of the same name
# can change the plugin.
ENV_SPECS: Dict[str, _Spec] = {
    "LU_DATASET_URL": _Spec("dataset_url", "url"),
    "LU_MAX_RESOURCES": _Spec("max_resources", "int", 10, 500),
    "LU_HTTP_TIMEOUT": _Spec("http_timeout", "int", 3, 60),
    "LU_ALERT_DEVICES": _Spec("alert_devices", "int", 1, MAX_ALERT_DEVICES),
    "LU_REFRESH_INTERVAL": _Spec("refresh_interval", "int", 30, 86400),
    "LU_STALE_DAYS": _Spec("stale_days", "int", 1, 365),
    "LU_SHOW_TEST_ALERTS": _Spec("show_test", "bool"),
    "LU_TEST_LEVELS": _Spec("test_levels", "list"),
    "LU_IGNORE_CATEGORIES": _Spec("ignore_categories", "list"),
    "LU_ALLOWED_HOSTS": _Spec("allowed_hosts", "list"),
}
KNOWN_KEYS = tuple(ENV_SPECS)

_HOST = re.compile(r"^\.?[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)*$")
_ASSIGN = re.compile(r"^(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$")
_TRUE = ("1", "true", "yes", "on")
_FALSE = ("0", "false", "no", "off", "")


class Env(NamedTuple):
    values: Dict[str, str]
    path: Optional[str]            # the file that was read (None: no .env, built-in defaults)
    warnings: List[str]


def _clean_value(text: str) -> str:
    """The value of a KEY=VALUE line: quotes removed, a trailing ' # comment' dropped."""
    text = text.strip()
    if text[:1] in ("'", '"'):
        end = text.find(text[0], 1)
        if end != -1:
            rest = text[end + 1:].strip()
            if rest and not rest.startswith("#"):
                return text                  # text after the closing quote: keep it all, so the value is rejected
            return text[1:end]
        return text
    return re.split(r"\s+#", text, maxsplit=1)[0].strip()


def load_env(env_path: Optional[str] = None) -> Env:
    """Read the plugin-local .env; the process environment takes precedence.

    Problems that do not stop the plugin (an unknown key, a line that is not KEY=VALUE) are returned as warnings,
    because a typo in a key name would otherwise leave the default silently in force.
    """
    path = env_path or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
    values: Dict[str, str] = {}
    warnings: List[str] = []
    found = None
    if os.path.isfile(path):
        found = path
        try:
            with open(path, encoding="utf-8-sig") as fh:       # tolerate a BOM from Windows editors
                content = fh.read()
        except (OSError, UnicodeDecodeError) as exc:
            raise SettingsError("Cannot read the configuration file %s: %s" % (path, exc))
        name = os.path.basename(path)
        for lineno, raw in enumerate(content.splitlines(), 1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            match = _ASSIGN.match(line)
            if not match:
                warnings.append("%s line %d ignored: expected KEY=VALUE" % (name, lineno))
                continue
            key, value = match.group(1), _clean_value(match.group(2))
            if key not in KNOWN_KEYS:
                close = difflib.get_close_matches(key.upper(), KNOWN_KEYS, n=1, cutoff=0.6)
                warnings.append("%s line %d: unknown setting %s ignored%s" % (
                    name, lineno, key, " (did you mean %s?)" % close[0] if close else ""))
                continue
            values[key] = value
    for key in KNOWN_KEYS:
        if key in os.environ:
            values[key] = os.environ[key].strip()
    return Env(values, found, warnings)


def _apply_env(s: Settings, values: Mapping[str, str]) -> None:
    for key, spec in ENV_SPECS.items():
        raw = values.get(key)
        if raw is None or (raw == "" and spec.kind != "list"):
            continue
        if spec.kind == "int":
            value: Any = _to_int(raw, key, spec.low, spec.high)
        elif spec.kind == "bool":
            value = _to_bool(raw, key)
        elif spec.kind == "url":
            value = _to_url(raw, key)
        else:
            value = tuple(item.lower() for item in split_list(raw))
        if key == "LU_IGNORE_CATEGORIES":
            known = {c.lower() for c in CAP_CATEGORIES}
            unknown = [c for c in value if c not in known]
            if unknown:
                s.warnings.append("%s: unknown category %s ignored (known: %s)" % (key, ", ".join(unknown),
                                                                                    ", ".join(CAP_CATEGORIES)))
            value = tuple(c for c in value if c in known)
        if key == "LU_ALLOWED_HOSTS":
            bad = [h for h in value if not _HOST.match(h)]
            if bad:
                s.warnings.append("%s: %s is not a host name and was ignored" % (key, ", ".join(bad)))
            value = tuple(h.strip(".") for h in value if _HOST.match(h))
        setattr(s, spec.attr, value)


def _to_int(text: str, label: str, low: int, high: int) -> int:
    try:
        value = int(float(text))
    except (ValueError, OverflowError):                 # "abc", "nan" and "inf" alike
        raise SettingsError("%s must be a number, got %r" % (label, text))
    if not low <= value <= high:
        raise SettingsError("%s must be between %d and %d, got %d" % (label, low, high, value))
    return value


def _to_bool(text: str, label: str) -> bool:
    lowered = text.strip().lower()
    if lowered in _TRUE:
        return True
    if lowered in _FALSE:
        return False
    raise SettingsError("%s must be 0 or 1, got %r" % (label, text))


def _to_url(text: str, label: str) -> str:
    try:
        parts = urlsplit(text)
        parts.port                                      # raises ValueError for an invalid port
    except ValueError as exc:
        raise SettingsError("%s is not a valid URL: %s" % (label, exc))
    if parts.scheme.lower() != "https":
        raise SettingsError("%s must start with https://, got %r" % (label, text))
    if not parts.hostname:
        raise SettingsError("%s has no host name" % label)
    if parts.username is not None or parts.password is not None:
        raise SettingsError("%s must not contain credentials" % label)
    return text


def proxy_secrets(environ: Mapping[str, str]) -> List[str]:
    """Passwords inside proxy URLs of the environment (``http://user:pass@proxy:3128``): they must never reach the log."""
    found = []
    for name in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy"):
        try:
            password = urlsplit(environ.get(name, "")).password
        except ValueError:
            continue
        if password and password not in found:
            found.append(password)
    return found
