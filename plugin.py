"""
<plugin key="LUAlert" name="LU-Alert Luxembourg" author="Jan Reimen" version="0.1.1" wikilink="https://github.com/janreimen/Domoticz-LU-Alert" externallink="https://lu-alert.lu/">
    <description>
        <h2>LU-Alert Luxembourg</h2><br/>
        Shows the official <b>LU-Alert</b> warnings of the Luxembourg government as Domoticz devices: the number of
        active alerts, the highest severity as a coloured alert, one alert device per active alert, switches for
        critical alerts that you can use in notifications and scripts, and optional matches for your location, your
        keywords and your allergens. Read-only; no account and no Python packages needed.<br/><br/>
        <h3>Features</h3>
        <ul style="list-style-type:square">
            <li>Active Alerts, Highest Severity (green, yellow, orange, red) and the counts per severity</li>
            <li>Alert 1 ... Alert 10: the most severe active alerts, with severity, headline and end time</li>
            <li>Critical / Severe / Extreme Alert Active switches</li>
            <li>Local Alert Active (the alert area contains your home), Watchlist Match, Allergen Match</li>
            <li>Alerts are cancelled, replaced and ended like the feed says; test messages are left out</li>
            <li>The feed is read every few minutes in the background; a failing feed never clears the alerts</li>
        </ul>
        <h3>Configuration</h3>
        Nothing is required: the defaults show every alert in English, updated every 5 minutes. The location filter
        uses the home location of Domoticz unless you enter another latitude;longitude. More settings (the number of
        alert devices, how test messages are handled) are in the file <tt>.env</tt> beside the plugin.<br/><br/>
        <h3>Documentation</h3>
        <a href="https://github.com/janreimen/Domoticz-LU-Alert">https://github.com/janreimen/Domoticz-LU-Alert</a><br/>
        Idea and alert mapping: the Home Assistant integration LU-Alert by koosoli. Data: LU-Alert, data.public.lu.
    </description>
    <params>
        <param field="Mode1" label="Minimum severity" width="200px">
            <options>
                <option label="All alerts" value="Unknown" default="true"/>
                <option label="Information and above" value="Information"/>
                <option label="Minor and above" value="Minor"/>
                <option label="Moderate and above" value="Moderate"/>
                <option label="Severe and above" value="Severe"/>
                <option label="Extreme only" value="Extreme"/>
            </options>
        </param>
        <param field="Mode2" label="Language of the alert texts" width="200px">
            <options>
                <option label="English" value="en" default="true"/>
                <option label="Deutsch" value="de"/>
                <option label="Français" value="fr"/>
                <option label="Lëtzebuergesch" value="lb"/>
            </options>
        </param>
        <param field="Mode3" label="Update Interval (seconds)" width="75px" required="true" default="300"/>
        <param field="Mode4" label="Location filter" width="200px">
            <options>
                <option label="Off" value="0" default="true"/>
                <option label="Flag local alerts" value="1"/>
                <option label="Only local alerts" value="2"/>
            </options>
        </param>
        <param field="Address" label="Home location: latitude;longitude (empty = Domoticz location)" width="250px" required="false" default=""/>
        <param field="Mode5" label="Watchlist keywords (comma separated)" width="300px" required="false" default=""/>
        <param field="Username" label="Allergens (comma separated)" width="300px" required="false" default=""/>
        <param field="Mode6" label="Debug" width="120px">
            <options>
                <option label="Off" value="0" default="true"/>
                <option label="Basic" value="1"/>
                <option label="Verbose" value="2"/>
                <option label="Debug" value="3"/>
            </options>
        </param>
    </params>
</plugin>
"""
import os
import sys
import traceback

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import Domoticz  # noqa: E402  (provided by Domoticz)

# Domoticz injects the globals Parameters, Devices, Images and Settings into this module (and replaces them before
# every callback). Never bind one of those names here: the injected dict would silently shadow it. The modules are
# imported under other names.
from lu_alert import __version__  # noqa: E402
from lu_alert import config as lu_config  # noqa: E402
from lu_alert.api import Client  # noqa: E402
from lu_alert.constants import HEARTBEAT_SECONDS, LOCATION_NAMES, PLUGIN_NAME  # noqa: E402
from lu_alert.controller import Controller  # noqa: E402
from lu_alert.devices import DeviceManager  # noqa: E402
from lu_alert.feed import Feed  # noqa: E402
from lu_alert.logger import LEVEL_NAMES, Logger  # noqa: E402


def _domoticz_settings():
    """The settings of Domoticz itself (its location, language, ...); empty when this Domoticz does not inject them."""
    try:
        return dict(Settings)
    except NameError:
        return {}


class BasePlugin:
    def __init__(self):
        self.controller = None          # stays None until onStart completed: every other callback then does nothing
        self.log = Logger(Domoticz)

    # -- Domoticz callbacks ------------------------------------------------------------------------------
    def onStart(self):
        self.controller = None
        self.log = log = Logger(Domoticz)
        try:
            settings = lu_config.Settings.from_parameters(Parameters, _domoticz_settings())
        except lu_config.SettingsError as exc:
            log.Error("Configuration error: %s" % exc)
            return
        log.set_level(settings.debug)
        for secret in lu_config.proxy_secrets(os.environ):
            log.add_secret(secret)
        # the home location is private: whatever happens to put it into a message, the logger masks it
        for text in (Parameters.get("Address", ""), _domoticz_settings().get("Location", "")):
            log.add_secret(str(text or "").strip())
        location = ""
        if settings.location_mode:
            location = ", location filter '%s'" % LOCATION_NAMES[settings.location_mode]
        log.Log("%s %s starting (update every %d s, minimum severity %s, language %s%s, debug level %d: %s)" % (
            PLUGIN_NAME, __version__, settings.interval, settings.min_severity, settings.language, location,
            settings.debug, LEVEL_NAMES[settings.debug]))
        for note in settings.notes:
            log.Log(note)
        for warning in settings.warnings:
            log.Log("Configuration warning: %s" % warning)
        log.Basic("Configuration file: %s" % (settings.env_file or "none (.env not found, built-in defaults)"))
        log.Basic("Dataset: %s, newest %d files, %d alert devices" % (settings.dataset_url, settings.max_resources,
                                                                      settings.alert_devices))

        client = Client(settings.dataset_url, settings.http_timeout, allowed_hosts=settings.allowed_hosts)
        feed = Feed(client, settings.max_resources)
        devices = DeviceManager(Domoticz, lambda: Devices, log, settings.alert_devices,
                                refresh_seconds=settings.refresh_interval)
        controller = Controller(settings, feed, devices, log)
        Domoticz.Heartbeat(HEARTBEAT_SECONDS)
        try:
            controller.start()
        except Exception as exc:
            self._unexpected("start-up", exc)
            return
        self.controller = controller

    def onStop(self):
        if self.controller is not None:
            try:
                self.controller.stop()
            except Exception as exc:
                self._unexpected("shutdown", exc)
            self.controller = None
        self.log.Log("LU-Alert stopped")

    def onHeartbeat(self):
        if self.controller is None:
            return
        try:
            self.controller.on_heartbeat()
        except Exception as exc:
            self._unexpected("heartbeat", exc)

    def onCommand(self, Unit, Command, Level, Hue):
        if self.controller is None:
            self.log.Error("Command for unit %s ignored: the plugin did not start, see the errors above" % Unit)
            return
        try:
            self.controller.on_command(Unit, Command, Level)
        except Exception as exc:
            self._unexpected("command for unit %s" % Unit, exc)

    # -- helpers -----------------------------------------------------------------------------------------
    def _unexpected(self, where, exc):
        self.log.Error("Unexpected error in %s: %s: %s" % (where, type(exc).__name__, exc))
        self.log.Debug(traceback.format_exc())


_plugin = BasePlugin()


def onStart():
    _plugin.onStart()


def onStop():
    _plugin.onStop()


def onHeartbeat():
    _plugin.onHeartbeat()


def onCommand(Unit, Command, Level, Hue):
    _plugin.onCommand(Unit, Command, Level, Hue)
