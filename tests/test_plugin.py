"""The real plugin.py (manifest, glue, callbacks) against the fake feed, with a Domoticz stub."""
import ast
import importlib
import os
import re
import sys
import time
import unittest
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from unittest import mock

import domoticz_stub as dz
import helpers
from cap_samples import CITY, HOME, cap_xml
from helpers import ROOT, start_feed
from lu_alert import __version__
from lu_alert.config import KNOWN_KEYS, Settings
from lu_alert.constants import UNIT_ACTIVE, UNIT_ALERT_FIRST, UNIT_CRITICAL, UNIT_LOCAL, UNIT_STATUS

RESERVED = {"Parameters", "Devices", "Images", "Settings"}          # injected into plugin.py by Domoticz
PARAMETER_FIELDS = {"Mode1", "Mode2", "Mode3", "Mode4", "Mode5", "Mode6", "Address", "Username"}


def source():
    with open(os.path.join(ROOT, "plugin.py"), encoding="utf-8") as fh:
        return fh.read()


def fresh(identifier, **kw):
    """An alert in force right now: the plugin runs on the real clock, the fixtures of the other tests on a fixed one."""
    now = datetime.now(timezone.utc)
    kw.setdefault("sent", now - timedelta(minutes=5))
    kw.setdefault("expires", now + timedelta(hours=1))
    return cap_xml(identifier, **kw)


def manifest():
    return ET.fromstring(source().split('"""')[1].strip())


class PluginCase(unittest.TestCase):
    def setUp(self):
        self.fake, self.context = start_feed(self)
        # the plugin builds its own SSL context from the system's certificates: the test CA goes there
        ca = helpers.certs.get()[1]
        env = {k: v for k, v in os.environ.items() if k not in KNOWN_KEYS}
        env.update(SSL_CERT_FILE=ca, LU_DATASET_URL=self.fake.dataset_url)
        patcher = mock.patch.dict(os.environ, env, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.saved = sys.modules.get("Domoticz")
        sys.modules["Domoticz"] = dz
        self.addCleanup(self.restore)
        self.plugins = []

    def restore(self):
        for plugin in self.plugins:
            plugin.onStop()
        if self.saved is None:
            sys.modules.pop("Domoticz", None)
        else:
            sys.modules["Domoticz"] = self.saved

    def load(self, settings=None, **params):
        dz.reset()
        sys.modules.pop("plugin", None)
        plugin = importlib.import_module("plugin")
        plugin.Parameters = {"Mode1": "Unknown", "Mode2": "en", "Mode3": "300", "Mode4": "0", "Address": "", "Mode5": "",
                             "Username": "", "Mode6": "0"}
        plugin.Parameters.update(params)
        plugin.Devices = dz.Devices
        plugin.Settings = {"Language": "en", "Location": ""} if settings is None else settings    # injected by Domoticz
        plugin.Images = {}
        self.plugins.append(plugin)
        return plugin

    def beat_until(self, plugin, done, seconds=5):
        deadline = time.time() + seconds
        while time.time() < deadline:
            plugin.onHeartbeat()
            if done():
                return
            time.sleep(0.02)
        self.fail("the poll did not finish")

    def errors(self):
        return dz.messages("error")

    def value(self, unit):
        return dz.Devices[unit].nValue, dz.Devices[unit].sValue


class CallbackTests(PluginCase):
    def test_start_shows_the_alerts_and_stop_ends_the_thread(self):
        self.fake.add("a", fresh("a"))
        plugin = self.load()
        plugin.onStart()
        self.assertEqual(self.errors(), [])
        self.assertEqual(len(dz.Devices), 18)
        self.assertIn(("heartbeat", 10), dz.logs)
        self.assertTrue(any("LU-Alert Luxembourg %s starting" % __version__ in t for t in dz.messages("log")))
        self.beat_until(plugin, lambda: self.value(UNIT_STATUS)[0] == 1)
        self.assertEqual(self.value(UNIT_ACTIVE)[1], "1")
        plugin.onStop()
        self.assertFalse(plugin._plugin.controller)
        self.assertTrue(any("stopped" in t for t in dz.messages("log")))

    def test_the_description_is_in_the_alert_devices_unless_the_env_says_no(self):
        self.fake.add("a", fresh("a", description="Reason: a pesticide. Bulk sale in: Colruyt"))
        for setting, expected in (("1", True), ("0", False)):
            plugin = self.load()
            with mock.patch.dict(os.environ, {"LU_DEVICE_DESCRIPTION": setting}):
                plugin.onStart()
            self.beat_until(plugin, lambda: self.value(UNIT_ALERT_FIRST)[1].startswith("[Severe]"))
            self.assertEqual("Bulk sale in: Colruyt" in self.value(UNIT_ALERT_FIRST)[1], expected, setting)
            self.assertEqual(self.errors(), [])
            plugin.onStop()
            dz.reset()

    def test_devices_are_named_after_the_hardware_like_domoticz_does(self):
        plugin = self.load(Name="LU-Alert")
        dz.hardware_name = "LU-Alert"
        plugin.onStart()
        self.assertEqual(dz.Devices[UNIT_ACTIVE].Name, "LU-Alert - Active Alerts")
        self.assertEqual(self.errors(), [])

    def test_commands_go_through_the_callback_and_change_nothing(self):
        plugin = self.load()
        plugin.onStart()
        plugin.onCommand(UNIT_CRITICAL, "On", 0, "")
        self.assertTrue(any("cannot be switched" in t for t in dz.messages("log")))
        self.assertEqual(self.errors(), [])

    def test_a_bad_configuration_is_reported_and_the_plugin_stays_idle(self):
        plugin = self.load(Mode3="often")
        plugin.onStart()
        self.assertTrue(any("Configuration error: Update interval must be a number" in t for t in self.errors()))
        plugin.onHeartbeat()
        plugin.onCommand(UNIT_CRITICAL, "Off", 0, "")
        plugin.onStop()
        self.assertTrue(any("did not start" in t for t in self.errors()))
        self.assertEqual(dz.Devices, {})
        self.assertEqual(self.fake.requests, [])

    def test_a_bad_env_value_is_a_configuration_error_too(self):
        plugin = self.load()
        with mock.patch.dict(os.environ, {"LU_DATASET_URL": "http://data.public.lu/x"}):
            plugin.onStart()
        self.assertTrue(any("LU_DATASET_URL must start with https://" in t for t in self.errors()))
        self.assertEqual(dz.Devices, {})

    def test_an_unreachable_feed_is_one_error_and_the_devices_exist(self):
        self.fake.stop()
        plugin = self.load()
        plugin.onStart()
        self.beat_until(plugin, lambda: self.value(UNIT_STATUS)[1] == "Off" and len(self.errors()) > 0)
        self.assertEqual(len(self.errors()), 1)
        self.assertEqual(len(dz.Devices), 18)
        plugin.onHeartbeat()
        self.assertEqual(len(self.errors()), 1)

    def test_an_unexpected_exception_does_not_escape_a_callback(self):
        plugin = self.load()
        plugin.onStart()

        def boom(*args):
            raise RuntimeError("boom")
        plugin._plugin.controller.on_heartbeat = boom
        plugin._plugin.controller.on_command = boom
        plugin.onHeartbeat()
        plugin.onCommand(UNIT_CRITICAL, "Off", 0, "")
        self.assertEqual(len([t for t in self.errors() if "RuntimeError: boom" in t]), 2)

    def test_an_exception_at_start_up_leaves_the_plugin_idle(self):
        plugin = self.load()
        with mock.patch("lu_alert.controller.Controller.start", side_effect=RuntimeError("boom")):
            plugin.onStart()
        self.assertTrue(any("Unexpected error in start-up: RuntimeError: boom" in t for t in self.errors()))
        self.assertIsNone(plugin._plugin.controller)

    def test_debug_levels_wire_up_domoticz_debugging(self):
        plugin = self.load(Mode6="3")
        plugin.onStart()
        self.assertIn(("debugging", 1), dz.logs)
        self.assertTrue(any(t.startswith("[BASIC]") for t in dz.messages("debug")))
        plugin = self.load(Mode6="0")
        plugin.onStart()
        self.assertNotIn(("debugging", 1), dz.logs)
        self.assertEqual(dz.messages("debug"), [])

    def test_corrections_are_logged_and_the_plugin_starts(self):
        plugin = self.load(Mode3="5", Mode2="es")
        plugin.onStart()
        text = " ".join(dz.messages("log"))
        self.assertIn("using 60 s", text)
        self.assertIn("using en", text)
        self.assertEqual(self.errors(), [])

    def test_unknown_env_keys_are_logged_as_warnings(self):
        path = os.path.join(ROOT, ".env")
        self.assertFalse(os.path.exists(path), "a .env in the repository would change the tests")
        plugin = self.load()
        plugin.onStart()
        self.assertFalse(any("Configuration warning" in t for t in dz.messages("log")))


class PrivacyTests(PluginCase):
    def test_the_home_location_never_reaches_the_log(self):
        self.fake.add("a", fresh("a", polygon=CITY))
        plugin = self.load({"Language": "en", "Location": "%s;%s" % HOME}, Mode4="1", Mode6="3")
        plugin.onStart()
        self.beat_until(plugin, lambda: self.value(UNIT_STATUS)[0] == 1)
        text = dz.all_text()
        self.assertGreater(len(text), 500)
        for fragment in ("49.6116", "6.1319", "49.61;"):
            self.assertNotIn(fragment, text)

    def test_an_address_of_your_own_is_masked_too(self):
        plugin = self.load(Mode4="1", Address="49.5001;6.0002", Mode6="3")
        plugin.onStart()
        plugin._plugin.log.Log("the user lives at 49.5001;6.0002 really")
        self.assertNotIn("49.5001", dz.all_text())
        self.assertIn("<masked>", dz.all_text())

    def test_a_proxy_password_is_masked(self):
        plugin = self.load()
        with mock.patch.dict(os.environ, {"HTTPS_PROXY": "http://user:hunter22@proxy:3128"}):
            plugin.onStart()
        plugin._plugin.log.Error("request via http://user:hunter22@proxy:3128 failed")
        self.assertNotIn("hunter22", dz.all_text())

    def test_the_local_alert_flag_works_without_the_numbers_in_the_log(self):
        self.fake.add("a", fresh("a", polygon=CITY))
        plugin = self.load({"Language": "en", "Location": "%s;%s" % HOME}, Mode4="1")
        plugin.onStart()
        self.beat_until(plugin, lambda: self.value(UNIT_STATUS)[0] == 1)
        self.assertEqual(self.value(UNIT_LOCAL)[0], 1)
        self.assertTrue(any("Using the location set in Domoticz" in t for t in dz.messages("log")))


class ManifestTests(unittest.TestCase):
    def test_the_manifest_keeps_the_key_and_the_version(self):
        root = manifest()
        self.assertEqual(root.get("key"), "LUAlert")                  # Domoticz stores the hardware by this key
        self.assertEqual(root.get("version"), __version__)
        self.assertRegex(root.get("version"), r"^\d+\.\d+\.\d+$")

    def test_the_parameter_fields(self):
        fields = [p.get("field") for p in manifest().iter("param")]
        self.assertEqual(sorted(fields), sorted(PARAMETER_FIELDS))
        self.assertEqual(len(fields), len(set(fields)))

    def test_every_option_of_the_hardware_page_is_accepted_by_the_settings(self):
        base = {"Mode3": "300"}
        for param in manifest().iter("param"):
            for option in param.iter("option"):
                params = dict(base, **{param.get("field"): option.get("value")})
                if param.get("field") == "Mode4" and option.get("value") != "0":
                    params["Address"] = "49.6;6.1"
                Settings.from_parameters(params, env_path=os.path.join(ROOT, "no-such.env"))

    def test_the_defaults_of_the_page_are_the_defaults_of_the_code(self):
        defaults = {}
        for param in manifest().iter("param"):
            chosen = [o.get("value") for o in param.iter("option") if o.get("default") == "true"]
            defaults[param.get("field")] = chosen[0] if chosen else param.get("default", "")
        settings = Settings.from_parameters(defaults, env_path=os.path.join(ROOT, "no-such.env"))
        plain = Settings()
        for attribute in ("interval", "min_severity", "language", "location_mode", "location", "debug"):
            self.assertEqual(getattr(settings, attribute), getattr(plain, attribute), attribute)

    def test_the_description_names_no_other_plugin(self):
        text = source().split('"""')[1].lower()
        for word in ("pi-hole", "pihole", "synology", "skoda", "openaq", "home assistant integration lu-alert by koosoli"):
            if word == "home assistant integration lu-alert by koosoli":
                self.assertIn(word, text)           # the credit stays
            else:
                self.assertNotIn(word, text)

    def test_plugin_py_never_binds_a_name_domoticz_injects(self):
        tree = ast.parse(source())
        bound = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                bound |= {(a.asname or a.name).split(".")[0] for a in node.names}
            elif isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                bound.add(node.name)
            elif isinstance(node, ast.Assign):
                bound |= {t.id for t in node.targets if isinstance(t, ast.Name)}
        self.assertEqual(bound & RESERVED, set(), "plugin.py would be shadowed by Domoticz' injected globals")

    def test_only_plugin_py_imports_domoticz(self):
        package = os.path.join(ROOT, "lu_alert")
        for name in sorted(os.listdir(package)):
            if name.endswith(".py"):
                with open(os.path.join(package, name), encoding="utf-8") as fh:
                    self.assertIsNone(re.search(r"^\s*(import|from)\s+Domoticz\b", fh.read(), re.M), name)

    def test_the_callbacks_domoticz_calls_exist(self):
        tree = ast.parse(source())
        top = {n.name: [a.arg for a in n.args.args] for n in tree.body if isinstance(n, ast.FunctionDef)}
        self.assertEqual(top["onCommand"], ["Unit", "Command", "Level", "Hue"])      # Domoticz calls it positionally
        for name in ("onStart", "onStop", "onHeartbeat"):
            self.assertIn(name, top)

    def test_the_standard_library_is_all_that_is_needed(self):
        stdlib = set(sys.stdlib_module_names) if hasattr(sys, "stdlib_module_names") else None
        files = [os.path.join(ROOT, "lu_alert", n) for n in sorted(os.listdir(os.path.join(ROOT, "lu_alert")))
                 if n.endswith(".py")]
        files.append(os.path.join(ROOT, "plugin.py"))
        for path in files:
            with open(path, encoding="utf-8") as fh:
                tree = ast.parse(fh.read())
            for node in ast.walk(tree):
                modules = []
                if isinstance(node, ast.Import):
                    modules = [a.name.split(".")[0] for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.level == 0:
                    modules = [node.module.split(".")[0]]
                for module in modules:
                    if module in ("Domoticz", "lu_alert"):
                        continue
                    if stdlib is not None:
                        self.assertIn(module, stdlib, "%s imports the third-party module %s" % (path, module))


if __name__ == "__main__":
    unittest.main()
