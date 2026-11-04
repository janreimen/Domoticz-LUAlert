"""Settings: the hardware page, the .env file, and what a wrong value does."""
import os
import tempfile
import unittest
from unittest import mock

import helpers  # noqa: F401
from lu_alert.config import (
    ENV_SPECS, KNOWN_KEYS, Settings, SettingsError, load_env, parse_debug, parse_location, parse_location_mode,
    parse_min_severity, proxy_secrets,
)
from lu_alert.constants import DATASET_URL, LOCATION_FLAG, LOCATION_OFF, LOCATION_ONLY


class EnvCase(unittest.TestCase):
    """A test with its own folder for the .env file and no LU_ variable from the environment of the machine."""

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = os.path.join(folder.name, ".env")
        clean = {k: v for k, v in os.environ.items() if k not in KNOWN_KEYS}
        patcher = mock.patch.dict(os.environ, clean, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def write(self, text, encoding="utf-8"):
        with open(self.path, "w", encoding=encoding) as fh:
            fh.write(text)

    def settings(self, params=None, domoticz=None):
        return Settings.from_parameters(params or {}, domoticz, env_path=self.path)


class HardwareFieldTests(EnvCase):
    def test_defaults(self):
        s = self.settings()
        self.assertEqual((s.interval, s.min_severity, s.language, s.location_mode, s.location, s.debug),
                         (300, "Unknown", "en", LOCATION_OFF, None, 0))
        self.assertEqual((s.keywords, s.allergens, s.dataset_url, s.max_resources, s.alert_devices),
                         ((), (), DATASET_URL, 100, 3))
        self.assertEqual((s.stale_days, s.show_test, s.ignore_categories, s.allowed_hosts), (10, False, (), ()))
        self.assertEqual(s.test_levels, ("t", "d", "lu-alert test", "lu-alert exercise"))
        self.assertIsNone(s.env_file)
        self.assertEqual((s.notes, s.warnings), ([], []))

    def test_every_field(self):
        s = self.settings({"Mode1": "Severe", "Mode2": "DE", "Mode3": "120", "Mode4": "1", "Address": "49.6;6.1",
                           "Mode5": "storm, flood", "Username": "peanuts; milk", "Mode6": "2"})
        self.assertEqual((s.min_severity, s.language, s.interval, s.location_mode, s.location, s.debug),
                         ("Severe", "de", 120, LOCATION_FLAG, (49.6, 6.1), 2))
        self.assertEqual((s.keywords, s.allergens), (("storm", "flood"), ("peanuts", "milk")))

    def test_the_interval_is_clamped_and_says_so(self):
        s = self.settings({"Mode3": "5"})
        self.assertEqual(s.interval, 60)
        self.assertIn("5 s is outside 60-3600 s, using 60 s", s.notes[0])
        self.assertEqual(self.settings({"Mode3": "99999"}).interval, 3600)
        self.assertEqual(self.settings({"Mode3": "  "}).interval, 300)

    def test_an_interval_that_is_no_number_stops_the_plugin(self):
        with self.assertRaisesRegex(SettingsError, "Update interval must be a number"):
            self.settings({"Mode3": "often"})

    def test_the_minimum_severity(self):
        self.assertEqual(parse_min_severity("severe"), "Severe")
        self.assertEqual(parse_min_severity(""), "Unknown")
        self.assertEqual(parse_min_severity("ALL"), "Unknown")
        with self.assertRaisesRegex(SettingsError, "Minimum severity must be one of"):
            parse_min_severity("loud")

    def test_the_language_falls_back_with_a_note(self):
        s = self.settings({"Mode2": "es"})
        self.assertEqual(s.language, "en")
        self.assertIn("Language 'es' is not one of en, de, fr, lb", s.notes[0])
        self.assertEqual(self.settings({"Mode2": "lb"}).language, "lb")
        self.assertEqual(self.settings({"Mode2": "fr-LU"}).language, "fr")
        self.assertEqual(self.settings({"Mode2": ""}).notes, [])

    def test_the_debug_level(self):
        self.assertEqual([parse_debug(t) for t in ("0", "1", "2", "3", "9", "-1", "abc", "")], [0, 1, 2, 3, 3, 0, 0, 0])
        self.assertEqual([parse_debug(t) for t in ("true", "False", "debug", "Normal")], [3, 0, 3, 0])

    def test_the_location_modes(self):
        self.assertEqual([parse_location_mode(t) for t in ("", "0", "off", "1", "flag", "2", "only")],
                         [LOCATION_OFF, LOCATION_OFF, LOCATION_OFF, LOCATION_FLAG, LOCATION_FLAG, LOCATION_ONLY,
                          LOCATION_ONLY])
        with self.assertRaisesRegex(SettingsError, "Location filter must be 0"):
            parse_location_mode("3")

    def test_locations(self):
        self.assertEqual(parse_location("49.6116;6.1319"), (49.6116, 6.1319))
        self.assertEqual(parse_location(" 49.6116 , 6.1319 "), (49.6116, 6.1319))
        self.assertEqual(parse_location("49.6116,6.1319"), (49.6116, 6.1319))
        self.assertEqual(parse_location("-33.9 151.2"), (-33.9, 151.2))
        for bad in ("", "49.6", "49.6;6.1;3", "north;east", "91;0", "0;181", "nan;1"):
            self.assertIsNone(parse_location(bad), bad)

    def test_a_home_location_that_is_wrong_stops_the_plugin_without_repeating_it_in_a_note(self):
        with self.assertRaisesRegex(SettingsError, "latitude;longitude"):
            self.settings({"Address": "somewhere", "Mode4": "1"})

    def test_the_domoticz_location_is_used_and_its_numbers_are_not_logged(self):
        s = self.settings({"Mode4": "1"}, {"Location": "49.6116;6.1319"})
        self.assertEqual((s.location_mode, s.location), (LOCATION_FLAG, (49.6116, 6.1319)))
        self.assertEqual(s.notes, ["Using the location set in Domoticz for the location filter"])
        self.assertNotIn("49.61", " ".join(s.notes))

    def test_the_address_field_beats_the_domoticz_location(self):
        s = self.settings({"Mode4": "2", "Address": "49.5;6.0"}, {"Location": "49.6116;6.1319"})
        self.assertEqual(s.location, (49.5, 6.0))
        self.assertEqual(s.notes, [])

    def test_a_filter_without_a_location_switches_itself_off_and_says_so(self):
        s = self.settings({"Mode4": "2"})
        self.assertEqual((s.location_mode, s.location), (LOCATION_OFF, None))
        self.assertIn("no location is known", s.notes[0])
        self.assertIn("Only local alerts", s.notes[0])

    def test_without_the_filter_the_location_is_not_needed(self):
        self.assertEqual(self.settings({}, {"Location": "49.6116;6.1319"}).location, None)

    def test_a_number_in_the_wrong_shape_does_not_break_the_parse(self):
        self.assertEqual(self.settings({"Mode3": None, "Mode1": None}).interval, 300)


class EnvFileTests(EnvCase):
    def test_every_key_is_applied(self):
        self.write("""
# a comment
LU_DATASET_URL=https://data.example.lu/api/1/datasets/abc/
LU_MAX_RESOURCES=50
LU_HTTP_TIMEOUT=20
LU_ALERT_DEVICES=5
LU_REFRESH_INTERVAL=600
LU_STALE_DAYS=3
LU_SHOW_TEST_ALERTS=1
LU_TEST_LEVELS=T, Probe
LU_IGNORE_CATEGORIES=Met, Fire
LU_ALLOWED_HOSTS=files.example.lu
""")
        s = self.settings()
        self.assertEqual((s.dataset_url, s.max_resources, s.http_timeout, s.alert_devices, s.refresh_interval, s.stale_days),
                         ("https://data.example.lu/api/1/datasets/abc/", 50, 20, 5, 600, 3))
        self.assertEqual((s.show_test, s.test_levels, s.ignore_categories, s.allowed_hosts),
                         (True, ("t", "probe"), ("met", "fire"), ("files.example.lu",)))
        self.assertEqual(s.env_file, self.path)
        self.assertEqual(s.warnings, [])

    def test_every_key_in_the_table_is_documented_in_the_sample(self):
        with open(os.path.join(helpers.ROOT, ".env.sample"), encoding="utf-8") as fh:
            sample = fh.read()
        for key in ENV_SPECS:
            self.assertIn(key + "=", sample, key)

    def test_quotes_comments_export_and_spaces(self):
        self.write('export LU_MAX_RESOURCES = "40"  # the newest\n'
                   "LU_STALE_DAYS='7'\n"
                   "LU_SHOW_TEST_ALERTS = yes # on\n"
                   "LU_TEST_LEVELS=\"T\"\n")
        s = self.settings()
        self.assertEqual((s.max_resources, s.stale_days, s.show_test, s.test_levels), (40, 7, True, ("t",)))

    def test_a_byte_order_mark_is_tolerated(self):
        self.write("LU_MAX_RESOURCES=30\n", encoding="utf-8-sig")
        self.assertEqual(self.settings().max_resources, 30)

    def test_the_process_environment_beats_the_file(self):
        self.write("LU_MAX_RESOURCES=30\n")
        with mock.patch.dict(os.environ, {"LU_MAX_RESOURCES": "60"}):
            self.assertEqual(self.settings().max_resources, 60)

    def test_an_unknown_key_is_reported_with_a_suggestion(self):
        self.write("LU_MAX_RESOURCE=30\nWHATEVER=1\nthis is no assignment\n")
        s = self.settings()
        self.assertEqual(s.max_resources, 100)
        self.assertEqual(len(s.warnings), 3)
        self.assertIn("unknown setting LU_MAX_RESOURCE ignored (did you mean LU_MAX_RESOURCES?)", s.warnings[0])
        self.assertIn("unknown setting WHATEVER ignored", s.warnings[1])
        self.assertNotIn("did you mean", s.warnings[1])
        self.assertIn("line 3 ignored: expected KEY=VALUE", s.warnings[2])

    def test_values_that_are_wrong_stop_the_plugin_with_the_key_in_the_message(self):
        cases = {
            "LU_MAX_RESOURCES=5": "LU_MAX_RESOURCES must be between 10 and 500, got 5",
            "LU_MAX_RESOURCES=lots": "LU_MAX_RESOURCES must be a number",
            "LU_MAX_RESOURCES=inf": "LU_MAX_RESOURCES must be a number",
            "LU_ALERT_DEVICES=11": "LU_ALERT_DEVICES must be between 1 and 10",
            "LU_ALERT_DEVICES=0": "LU_ALERT_DEVICES must be between 1 and 10",
            "LU_SHOW_TEST_ALERTS=maybe": "LU_SHOW_TEST_ALERTS must be 0 or 1",
            "LU_DATASET_URL=http://data.public.lu/x": "LU_DATASET_URL must start with https://",
            "LU_DATASET_URL=ftp://data.public.lu/x": "LU_DATASET_URL must start with https://",
            "LU_DATASET_URL=https:///x": "LU_DATASET_URL has no host name",
            "LU_DATASET_URL=https://user:pw@data.public.lu/x": "must not contain credentials",
            "LU_DATASET_URL=https://data.public.lu:abc/x": "not a valid URL",
        }
        for line, message in cases.items():
            self.write(line + "\n")
            with self.assertRaisesRegex(SettingsError, message, msg=line):
                self.settings()

    def test_a_quoted_value_with_text_after_it_is_rejected_not_guessed(self):
        self.write('LU_MAX_RESOURCES="40" 50\n')
        with self.assertRaises(SettingsError):
            self.settings()

    def test_an_empty_value_keeps_the_default_except_for_lists(self):
        self.write("LU_MAX_RESOURCES=\nLU_SHOW_TEST_ALERTS=\nLU_TEST_LEVELS=\n")
        s = self.settings()
        self.assertEqual((s.max_resources, s.show_test, s.test_levels), (100, False, ()))   # an empty list means: none

    def test_unknown_categories_are_dropped_with_a_warning(self):
        self.write("LU_IGNORE_CATEGORIES=met, weather, FIRE\n")
        s = self.settings()
        self.assertEqual(s.ignore_categories, ("met", "fire"))
        self.assertIn("unknown category weather ignored", s.warnings[0])

    def test_allowed_hosts_are_checked_for_being_host_names(self):
        self.write("LU_ALLOWED_HOSTS=files.example.lu, .cdn.example.lu, https://evil.example/x, 10.0.0.5, bad host\n")
        s = self.settings()
        self.assertEqual(s.allowed_hosts, ("files.example.lu", "cdn.example.lu", "10.0.0.5"))
        self.assertIn("not a host name and was ignored", s.warnings[0])
        self.assertIn("https://evil.example/x", s.warnings[0])

    def test_a_file_that_cannot_be_read_stops_the_plugin(self):
        with open(self.path, "wb") as fh:
            fh.write(b"\xff\xfe\x00LU_X=1\xc3\x28")
        with self.assertRaisesRegex(SettingsError, "Cannot read the configuration file"):
            self.settings()

    def test_load_env_without_a_file(self):
        env = load_env(self.path)
        self.assertEqual((env.values, env.path, env.warnings), ({}, None, []))


class ProxySecretTests(unittest.TestCase):
    def test_passwords_in_proxy_urls(self):
        found = proxy_secrets({"HTTPS_PROXY": "http://user:s3cret@proxy:3128", "http_proxy": "http://u:s3cret@proxy:3128",
                               "ALL_PROXY": "socks5://u:other@h:1080", "NO_PROXY": "localhost"})
        self.assertEqual(found, ["s3cret", "other"])
        self.assertEqual(proxy_secrets({"HTTPS_PROXY": "http://proxy:3128"}), [])
        self.assertEqual(proxy_secrets({"HTTPS_PROXY": "http://u:p@[bad"}), [])
        self.assertEqual(proxy_secrets({}), [])


if __name__ == "__main__":
    unittest.main()
