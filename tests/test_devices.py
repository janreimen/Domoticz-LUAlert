"""The device model: what is created, what is written when, what a command does."""
import unittest

import domoticz_stub as dz
import helpers  # noqa: F401  (puts the project on the path)
from cap_samples import CITY, HOME, NOW, cap_xml
from helpers import Clock, make_logger
from lu_alert.alerts import Filters, build_snapshot
from lu_alert.cap import parse_cap
from lu_alert.constants import (
    ALERT_SLOTS, FIXED_DEVICES, KIND_ALERT, KIND_COUNT, KIND_FLAG, KIND_TEXT, MAX_ALERT_DEVICES, MAX_TEXT, UNIT_ACTIVE,
    UNIT_ALERT_FIRST, UNIT_ALLERGEN, UNIT_COUNT_EXTREME, UNIT_COUNT_SEVERE, UNIT_CRITICAL, UNIT_EXTREME,
    UNIT_FEED_INFO, UNIT_HIGHEST, UNIT_LOCAL, UNIT_SEVERE, UNIT_STATUS, UNIT_WATCHLIST,
)
from lu_alert.devices import DeviceManager, TEXT_NO_ALERTS


def snapshot(*documents, **filters):
    alerts = [a for d in documents for a in parse_cap(d)]
    return build_snapshot(alerts, NOW, Filters(**filters))


class DeviceCase(unittest.TestCase):
    def setUp(self):
        dz.reset()
        self.clock = Clock()
        self.manager = self.make()

    def make(self, alert_devices=3, **kw):
        return DeviceManager(dz, lambda: dz.Devices, make_logger(), alert_devices, clock=self.clock, **kw)

    def errors(self):
        return dz.messages("error")

    def value(self, unit):
        return dz.Devices[unit].nValue, dz.Devices[unit].sValue


class FrozenModelTests(unittest.TestCase):
    """Unit numbers never change once released: devices, history, scenes and scripts hang on them."""

    def test_the_units_are_frozen(self):
        frozen = {1: "Active Alerts", 2: "Highest Severity", 3: "Critical Alert Active", 4: "Severe Alert Active",
                  5: "Extreme Alert Active", 6: "Local Alert Active", 7: "Watchlist Match", 8: "Allergen Match",
                  9: "LU-Alert Status", 10: "Feed Info", 21: "Extreme Alerts", 22: "Severe Alerts",
                  23: "Moderate Alerts", 24: "Minor Alerts", 25: "Information Alerts"}
        self.assertEqual({d.unit: d.name for d in FIXED_DEVICES}, frozen)
        self.assertEqual([(d.unit, d.name) for d in ALERT_SLOTS], [(10 + i, "Alert %d" % i) for i in range(1, 11)])

    def test_the_kinds_are_frozen(self):
        kinds = {d.unit: d.kind for d in FIXED_DEVICES}
        self.assertEqual(kinds[1], KIND_COUNT)
        self.assertEqual(kinds[2], KIND_ALERT)
        self.assertEqual({kinds[u] for u in range(3, 10)}, {KIND_FLAG})
        self.assertEqual(kinds[10], KIND_TEXT)
        self.assertEqual({kinds[u] for u in range(21, 26)}, {KIND_COUNT})

    def test_units_and_keys_are_unique(self):
        every = list(FIXED_DEVICES) + list(ALERT_SLOTS)
        self.assertEqual(len({d.unit for d in every}), len(every))
        self.assertEqual(len({d.key for d in every}), len(every))
        self.assertEqual(len({d.name for d in every}), len(every))


class CreationTests(DeviceCase):
    def test_every_device_is_created_in_use(self):
        self.manager.ensure_devices()
        self.assertEqual(sorted(dz.Devices), list(range(1, 11)) + [11, 12, 13] + list(range(21, 26)))
        self.assertEqual({d.Used for d in dz.Devices.values()}, {1})
        self.assertEqual(self.errors(), [])

    def test_the_types(self):
        self.manager.ensure_devices()
        self.assertEqual(dz.Devices[UNIT_ACTIVE].TypeName, "Custom")
        self.assertEqual(dz.Devices[UNIT_ACTIVE].Options, {"Custom": "1;alerts"})
        self.assertEqual(dz.Devices[UNIT_HIGHEST].TypeName, "Alert")
        self.assertEqual(dz.Devices[UNIT_CRITICAL].TypeName, "Switch")
        self.assertEqual(dz.Devices[UNIT_STATUS].kw["Switchtype"], 0)
        self.assertEqual(dz.Devices[UNIT_FEED_INFO].TypeName, "Text")
        self.assertEqual(dz.Devices[UNIT_ALERT_FIRST].TypeName, "Alert")

    def test_the_number_of_alert_devices(self):
        for count in (1, 5, MAX_ALERT_DEVICES):
            dz.reset()
            self.make(count).ensure_devices()
            self.assertEqual([u for u in dz.Devices if 11 <= u <= 20], list(range(11, 11 + count)))

    def test_a_second_call_creates_nothing(self):
        self.manager.ensure_devices()
        attempts = len(dz.create_attempts)
        self.manager.ensure_devices()
        self.assertEqual(len(dz.create_attempts), attempts)

    def test_a_device_that_was_deleted_is_created_again(self):
        self.manager.ensure_devices()
        dz.Devices[UNIT_LOCAL].Delete()
        self.manager.ensure_devices()
        self.assertIn(UNIT_LOCAL, dz.Devices)

    def test_when_domoticz_refuses_the_reason_is_given_once_and_asked_again_later(self):
        dz.accept_new_devices = False
        self.manager.ensure_devices()
        self.manager.ensure_devices()
        self.assertEqual(dz.create_attempts, [1])                       # one refusal, not eighteen
        ours = [t for t in self.errors() if t.startswith("Domoticz did not create")]
        self.assertEqual(len(ours), 1)
        self.assertIn("Accept new Hardware Devices", ours[0])
        self.clock.advance(301)
        dz.accept_new_devices = True
        self.manager.ensure_devices()
        self.assertEqual(len(dz.Devices), 18)
        self.assertTrue(any("creates the LU-Alert devices now" in t for t in dz.messages("log")))

    def test_a_counter_without_a_unit_gets_one_but_a_label_of_your_own_stays(self):
        self.manager.ensure_devices()
        dz.Devices[UNIT_ACTIVE].Options = {"Custom": "1;"}
        dz.Devices[UNIT_COUNT_EXTREME].Options = {"Custom": "1;warnings"}
        fresh = self.make()
        fresh.ensure_devices()
        self.assertEqual(dz.Devices[UNIT_ACTIVE].Options, {"Custom": "1;alerts"})
        self.assertEqual(dz.Devices[UNIT_COUNT_EXTREME].Options, {"Custom": "1;warnings"})
        self.assertTrue(dz.Devices[UNIT_ACTIVE].update_calls[-1]["SuppressTriggers"])    # the value was not rewritten

    def test_a_device_a_user_renamed_keeps_its_name(self):
        self.manager.ensure_devices()
        dz.Devices[UNIT_ACTIVE].Name = "Storms"
        self.manager.show(snapshot(cap_xml("a")))
        self.manager.ensure_devices()
        self.assertEqual(dz.Devices[UNIT_ACTIVE].Name, "Storms")
        self.assertEqual({c["Name"] for c in dz.Devices[UNIT_ACTIVE].update_calls}, {None})


class ShowTests(DeviceCase):
    def setUp(self):
        super().setUp()
        self.manager.ensure_devices()

    def test_nothing_active(self):
        self.manager.show(snapshot())
        self.assertEqual(self.value(UNIT_ACTIVE), (0, "0"))
        self.assertEqual(self.value(UNIT_HIGHEST), (1, TEXT_NO_ALERTS))
        for unit in (UNIT_CRITICAL, UNIT_SEVERE, UNIT_EXTREME, UNIT_LOCAL, UNIT_WATCHLIST, UNIT_ALLERGEN):
            self.assertEqual(self.value(unit), (0, "Off"), unit)
        for unit in range(UNIT_ALERT_FIRST, UNIT_ALERT_FIRST + 3):
            self.assertEqual(self.value(unit), (1, "No alert"))
        self.assertEqual([self.value(u)[1] for u in range(21, 26)], ["0"] * 5)

    def test_a_severe_alert(self):
        self.manager.show(snapshot(cap_xml("a")))
        self.assertEqual(self.value(UNIT_ACTIVE), (0, "1"))
        self.assertEqual(self.value(UNIT_HIGHEST), (4, "[Severe] Storm warning for the whole country - until 2026-11-02 14:00"))
        self.assertEqual([self.value(u)[1] for u in (UNIT_CRITICAL, UNIT_SEVERE, UNIT_EXTREME)], ["On", "On", "Off"])
        self.assertEqual(self.value(UNIT_COUNT_SEVERE), (0, "1"))
        self.assertEqual(self.value(UNIT_COUNT_EXTREME), (0, "0"))
        self.assertEqual(self.value(UNIT_ALERT_FIRST)[0], 4)
        self.assertEqual(self.value(UNIT_ALERT_FIRST + 1), (1, "No alert"))

    def test_the_colours(self):
        for level, colour in (("N1", 4), ("N2", 4), ("A", 3), ("N3", 2), ("I", 1)):
            self.manager.show(snapshot(cap_xml("a", level=level)))
            self.assertEqual(self.value(UNIT_HIGHEST)[0], colour, level)
        self.manager.show(snapshot(cap_xml("a", with_level=False, severity="Bogus")))
        self.assertEqual(self.value(UNIT_HIGHEST)[0], 0)

    def test_the_alert_devices_list_the_most_severe_first_and_the_rest_is_not_shown(self):
        documents = [cap_xml("s%d" % i, level="N3", headline="Minor %d" % i, sent=NOW.replace(minute=i)) for i in range(5)]
        documents.append(cap_xml("big", level="N1", headline="Extreme one"))
        self.manager.show(snapshot(*documents))
        self.assertEqual(self.value(UNIT_ACTIVE)[1], "6")
        self.assertTrue(dz.Devices[UNIT_ALERT_FIRST].sValue.startswith("[Extreme] Extreme one"))
        self.assertEqual([dz.Devices[u].sValue[:8] for u in (12, 13)], ["[Minor] ", "[Minor] "])
        self.assertEqual(self.value(UNIT_COUNT_EXTREME)[1], "1")

    def test_a_slot_beyond_the_configured_number_that_exists_from_before_is_greyed_out(self):
        dz.reset()
        self.make(5).ensure_devices()
        small = self.make(2)
        small.show(snapshot(cap_xml("a")))
        self.assertEqual(self.value(UNIT_ALERT_FIRST + 3), (0, "Not in use (raise LU_ALERT_DEVICES in .env)"))
        self.assertEqual(self.value(UNIT_ALERT_FIRST + 1), (1, "No alert"))

    def test_the_flags_for_location_watchlist_and_allergens(self):
        document = cap_xml("a", polygon=CITY, description="Contains peanuts.")
        self.manager.show(snapshot(document, location_mode=1, location=HOME, keywords=("storm",), allergens=("peanuts",)))
        self.assertEqual([self.value(u)[1] for u in (UNIT_LOCAL, UNIT_WATCHLIST, UNIT_ALLERGEN)], ["On"] * 3)
        self.manager.show(snapshot(document))
        self.assertEqual([self.value(u)[1] for u in (UNIT_LOCAL, UNIT_WATCHLIST, UNIT_ALLERGEN)], ["Off"] * 3)

    def test_a_text_is_cut_to_what_domoticz_can_keep(self):
        self.manager.show(snapshot(cap_xml("a", headline="x" * 500)))
        self.assertLessEqual(len(dz.Devices[UNIT_HIGHEST].sValue), MAX_TEXT)
        self.manager.set_feed_info("y" * 500)
        self.assertLessEqual(len(dz.Devices[UNIT_FEED_INFO].sValue), MAX_TEXT)

    def test_the_status_switch_and_the_feed_info(self):
        self.manager.set_status(True)
        self.manager.set_feed_info("OK 12:00: 3 files")
        self.assertEqual(self.value(UNIT_STATUS), (1, "On"))
        self.assertEqual(self.value(UNIT_FEED_INFO), (0, "OK 12:00: 3 files"))
        self.manager.set_status(False)
        self.assertEqual(self.value(UNIT_STATUS), (0, "Off"))


class WriteTests(DeviceCase):
    def setUp(self):
        super().setUp()
        self.manager.ensure_devices()

    def test_an_unchanged_value_is_not_written_again_until_it_is_old(self):
        self.manager.show(snapshot())
        updates = dz.Devices[UNIT_ACTIVE].updates
        self.manager.show(snapshot())
        self.assertEqual(dz.Devices[UNIT_ACTIVE].updates, updates)
        self.clock.advance(301)                                  # the time-out of Domoticz' sensors never fires
        self.manager.show(snapshot())
        self.assertEqual(dz.Devices[UNIT_ACTIVE].updates, updates + 1)

    def test_a_change_is_written_at_once(self):
        self.manager.show(snapshot())
        self.manager.show(snapshot(cap_xml("a")))
        self.assertEqual(self.value(UNIT_ACTIVE), (0, "1"))

    def test_a_missing_device_is_reported_once(self):
        dz.Devices[UNIT_LOCAL].Delete()
        self.manager.show(snapshot())
        self.manager.show(snapshot(cap_xml("a")))
        missing = [t for t in self.errors() if "Cannot update Domoticz unit %d" % UNIT_LOCAL in t]
        self.assertEqual(len(missing), 1)
        self.assertIn("no such device", missing[0])

    def test_nothing_is_reported_as_missing_while_domoticz_refuses_new_devices(self):
        dz.reset()
        dz.accept_new_devices = False
        manager = self.make()
        manager.ensure_devices()
        manager.show(snapshot())
        self.assertEqual([t for t in self.errors() if "Cannot update" in t], [])


class CommandTests(DeviceCase):
    def setUp(self):
        super().setUp()
        self.manager.ensure_devices()
        self.manager.show(snapshot(cap_xml("a")))

    def test_ownership_and_names(self):
        self.assertTrue(self.manager.owns(UNIT_CRITICAL))
        self.assertTrue(self.manager.owns(UNIT_ALERT_FIRST))
        self.assertFalse(self.manager.owns(UNIT_ALERT_FIRST + 5))      # a slot that is not configured
        self.assertFalse(self.manager.owns(99))
        self.assertEqual(self.manager.name_of(UNIT_CRITICAL), "Critical Alert Active")
        self.assertEqual(self.manager.name_of(99), "")

    def test_restore_confirms_the_real_value_without_a_trigger(self):
        device = dz.Devices[UNIT_CRITICAL]
        before = (device.nValue, device.sValue)
        self.manager.restore(UNIT_CRITICAL)
        self.assertTrue(device.update_calls[-1]["SuppressTriggers"])      # no trigger, no event, no notification
        self.assertEqual((device.nValue, device.sValue), before)
        self.manager.restore(99)                                # an unknown unit is harmless


if __name__ == "__main__":
    unittest.main()
