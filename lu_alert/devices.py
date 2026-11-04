"""The only module that talks to the Domoticz device API.

It is handed the ``Domoticz`` module and a callable returning the current ``Devices`` dict (Domoticz replaces that
dict before every callback, so it is never kept), and turns a ``Snapshot`` into devices:

    * the fixed devices (units 1-10 and 21-25) and one "Alert n" device per configured alert slot (units 11-20),
      created when missing - also later, when Domoticz did not accept new devices at first ("Accept new Hardware
      Devices" is off); a counter that has no unit label gets one
    * every device is created "in use" (Used=1), so nothing has to be added by hand under Setup > Devices
    * values are written when they change, and every REFRESH_SECONDS even when they did not, so the "last seen" time
      stays fresh and Domoticz' sensor time-out never marks a quiet sensor as dead
    * a name or a visibility you set in Domoticz is never touched; the plugin only writes values

All devices are read-only: a command sent to one is answered by writing its real value back.
"""
import time
from typing import Any, Callable, Dict, Optional

from .alerts import summary_line
from .constants import (
    ALERT_GREEN, ALERT_GREY, ALERT_SLOTS, CREATE_RETRY_SECONDS, EXTREME, FIXED_DEVICES, KIND_ALERT, KIND_COUNT,
    KIND_TEXT, MAX_TEXT, REFRESH_SECONDS, SEVERE, SEVERITY_ALERT_LEVEL, SEVERITY_COUNT_UNITS,
    SUBTYPE_CUSTOM, SWITCHTYPE_ONOFF, TEXT_NO_ALERT, TEXT_UNUSED, TYPENAME_ALERT, TYPENAME_COUNT, TYPENAME_SWITCH,
    TYPENAME_TEXT, UNIT_ACTIVE, UNIT_ALERT_FIRST, UNIT_ALERT_LAST, UNIT_ALLERGEN, UNIT_CRITICAL, UNIT_EXTREME,
    UNIT_FEED_INFO, UNIT_HIGHEST, UNIT_LOCAL, UNIT_SEVERE, UNIT_STATUS, UNIT_WATCHLIST, Device,
)
from .model import Snapshot
from .util import shorten

TEXT_NO_ALERTS = "No active alerts"


def _custom_unit(options_text: str) -> str:
    """The unit of a Custom Sensor: Domoticz keeps it as "<axis>;<unit>" in the device options."""
    return options_text.partition(";")[2].strip()


class DeviceManager:
    def __init__(self, domoticz: Any, get_devices: Callable[[], Dict[int, Any]], logger: Any, alert_devices: int = 3,
                 clock: Callable[[], float] = time.monotonic, refresh_seconds: int = REFRESH_SECONDS) -> None:
        self.dz = domoticz
        self.get_devices = get_devices
        self.log = logger
        self.clock = clock
        self.refresh_seconds = refresh_seconds
        self.alert_devices = alert_devices
        self.model = tuple(FIXED_DEVICES) + tuple(ALERT_SLOTS[:alert_devices])
        self._paused_until = 0.0                # Domoticz refused to create a device: no new attempt before this
        self._creation_refused = False
        self._unit_checked: set = set()         # units whose unit label was looked at since start
        self._written: Dict[int, float] = {}    # unit -> time of the last write
        self._warned: set = set()               # problems reported once

    # -- creating -------------------------------------------------------------------------------------------
    def ensure_devices(self) -> None:
        """Create the devices that are missing and give counters without a unit label their label.

        Called at start and by every poll: a device Domoticz did not accept at first appears as soon as the setting
        "Accept new Hardware Devices" is on, without restarting the hardware."""
        for spec in self.model:
            device = self.get_devices().get(spec.unit)
            if device is not None:
                self._add_missing_unit(device, spec)
                continue
            if self.clock() < self._paused_until:
                return
            self.dz.Device(**self._kwargs(spec)).Create()
            if spec.unit not in self.get_devices():
                self._creation_failed("'%s' (unit %d)" % (spec.name, spec.unit))
                return                      # the reason is the same for all of them: ask Domoticz once, not many times
            self._creation_worked()
            self.log.Basic("Created device '%s' (unit %d)" % (spec.name, spec.unit))

    def _add_missing_unit(self, device: Any, spec: Device) -> None:
        """A counter created without a unit label gets the label it should have; a label you set yourself stays."""
        if spec.kind != KIND_COUNT or not spec.label or spec.unit in self._unit_checked:
            return
        self._unit_checked.add(spec.unit)
        if getattr(device, "SubType", None) != SUBTYPE_CUSTOM:
            return                          # not a Custom Sensor any more: not ours to change
        if _custom_unit((getattr(device, "Options", None) or {}).get("Custom", "")):
            return
        try:
            device.Update(nValue=device.nValue, sValue=device.sValue, Options={"Custom": "1;%s" % spec.label},
                          SuppressTriggers=True)        # only the options: the value and its triggers stay as they are
        except Exception as exc:
            self.log.Error("Could not add the unit '%s' to '%s': %s" % (spec.label, spec.name, exc))
            return
        self.log.Log("Added the unit '%s' to '%s' (unit %d)" % (spec.label, spec.name, spec.unit))

    def _creation_failed(self, what: str) -> None:
        self._paused_until = self.clock() + CREATE_RETRY_SECONDS
        if not self._creation_refused:
            self._creation_refused = True
            self.log.Error("Domoticz did not create the device %s. If its log says that the settings prevent accepting "
                           "new devices, switch on Setup > Settings > System > 'Accept new Hardware Devices'. "
                           "The plugin asks again every %d minutes" % (what, CREATE_RETRY_SECONDS // 60))

    def _creation_worked(self) -> None:
        if self._creation_refused:
            self._creation_refused = False
            self.log.Log("Domoticz creates the LU-Alert devices now")

    @staticmethod
    def _kwargs(spec: Device) -> Dict[str, Any]:
        kwargs: Dict[str, Any] = dict(Name=spec.name, Unit=spec.unit, Used=1)
        if spec.kind == KIND_COUNT:
            kwargs.update(TypeName=TYPENAME_COUNT, Options={"Custom": "1;%s" % spec.label})
        elif spec.kind == KIND_TEXT:
            kwargs.update(TypeName=TYPENAME_TEXT)
        elif spec.kind == KIND_ALERT:
            kwargs.update(TypeName=TYPENAME_ALERT)
        else:                                   # a flag: an On/Off switch that only shows a state
            kwargs.update(TypeName=TYPENAME_SWITCH, Switchtype=SWITCHTYPE_ONOFF)
        return kwargs

    # -- showing --------------------------------------------------------------------------------------------
    def show(self, snapshot: Snapshot) -> None:
        """Write every alert device from a snapshot."""
        now = self.clock()
        counts = snapshot.counts
        top = snapshot.alerts[0] if snapshot.alerts else None
        self._write(UNIT_ACTIVE, 0, str(snapshot.total), now)
        if top is None:
            self._write(UNIT_HIGHEST, ALERT_GREEN, TEXT_NO_ALERTS, now)
        else:
            self._write(UNIT_HIGHEST, SEVERITY_ALERT_LEVEL[top.severity], summary_line(top), now)
        extreme, severe = counts.get(EXTREME, 0), counts.get(SEVERE, 0)
        self._flag(UNIT_CRITICAL, extreme + severe > 0, now)
        self._flag(UNIT_SEVERE, severe > 0, now)
        self._flag(UNIT_EXTREME, extreme > 0, now)
        self._flag(UNIT_LOCAL, any(a.local is True for a in snapshot.alerts), now)
        self._flag(UNIT_WATCHLIST, any(a.watch_match for a in snapshot.alerts), now)
        self._flag(UNIT_ALLERGEN, any(a.allergen_match for a in snapshot.alerts), now)
        for severity, unit in SEVERITY_COUNT_UNITS.items():
            self._write(unit, 0, str(counts.get(severity, 0)), now)
        for index in range(UNIT_ALERT_LAST - UNIT_ALERT_FIRST + 1):
            unit = UNIT_ALERT_FIRST + index
            if index < self.alert_devices:
                if index < len(snapshot.alerts):
                    alert = snapshot.alerts[index]
                    self._write(unit, SEVERITY_ALERT_LEVEL[alert.severity], summary_line(alert), now)
                else:
                    self._write(unit, ALERT_GREEN, TEXT_NO_ALERT, now)
            elif unit in self.get_devices():                    # a slot beyond the configured number, left from before
                self._write(unit, ALERT_GREY, TEXT_UNUSED, now)

    def set_status(self, online: bool) -> None:
        self._flag(UNIT_STATUS, online, self.clock())

    def set_feed_info(self, text: str) -> None:
        self._write(UNIT_FEED_INFO, 0, shorten(text, MAX_TEXT), self.clock())

    def _flag(self, unit: int, on: bool, now: Optional[float] = None) -> None:
        self._write(unit, 1 if on else 0, "On" if on else "Off", now)

    # -- commands -------------------------------------------------------------------------------------------
    def name_of(self, unit: int) -> str:
        device = self.get_devices().get(unit)
        return "" if device is None else str(device.Name)

    def restore(self, unit: int) -> None:
        """Put a device back to its real value after a command: all devices of this plugin are read-only."""
        device = self.get_devices().get(unit)
        if device is not None:
            device.Update(nValue=device.nValue, sValue=device.sValue, SuppressTriggers=True)

    def owns(self, unit: int) -> bool:
        return any(spec.unit == unit for spec in self.model)

    # -- writing --------------------------------------------------------------------------------------------
    def _write(self, unit: int, nvalue: int, svalue: str, now: Optional[float] = None) -> None:
        device = self.get_devices().get(unit)
        if device is None:
            if ("missing", unit) not in self._warned and not self._creation_refused:      # refused: already explained
                self._warned.add(("missing", unit))
                self.log.Error("Cannot update Domoticz unit %d: no such device. It was deleted or Domoticz did not "
                               "create it; the plugin creates it again as soon as Domoticz accepts new devices" % unit)
            return
        self._warned.discard(("missing", unit))
        svalue = shorten(svalue, MAX_TEXT)
        changed = device.nValue != nvalue or device.sValue != svalue
        stale = now is not None and now - self._written.get(unit, 0.0) >= self.refresh_seconds
        if not (changed or stale):
            return
        device.Update(nValue=nvalue, sValue=svalue)
        if now is not None:
            self._written[unit] = now
        if changed:
            self.log.Debug("Update unit %d: %d '%s'" % (unit, nvalue, svalue))
