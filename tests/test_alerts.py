"""The rules that decide which alerts a person sees: cancel, replace, expire, test, severity, language, location."""
import unittest
from datetime import timedelta

import helpers  # noqa: F401
from cap_samples import CITY, ESCH, HOME, NOW, cap_xml, info_xml, reference
from lu_alert.alerts import Filters, build_snapshot, choose_info, format_time, level_code, parse_references, summary_line
from lu_alert.cap import parse_cap
from lu_alert.constants import SEVERITY_RANK


def snap(*documents, now=NOW, **filters):
    alerts = [a for document in documents for a in parse_cap(document)]
    return build_snapshot(alerts, now, Filters(**filters))


def minutes(n):
    return NOW - timedelta(minutes=n)


class SeverityTests(unittest.TestCase):
    def test_one_alert_in_force(self):
        s = snap(cap_xml("a"))
        self.assertEqual(s.total, 1)
        alert = s.alerts[0]
        self.assertEqual((alert.severity, alert.rank, alert.level_code), ("Severe", 3, "N2"))
        self.assertEqual(alert.headline, "Storm warning for the whole country")
        self.assertEqual(alert.expires, NOW + timedelta(hours=2))
        self.assertEqual(alert.area_desc, ("Luxembourg",))
        self.assertEqual(alert.categories, ("Met",))
        self.assertIsNone(alert.local)
        self.assertEqual(s.counts["Severe"], 1)
        self.assertEqual(s.next_expiry, NOW + timedelta(hours=2))

    def test_the_level_codes_of_the_feed(self):
        table = {"N1": "Extreme", "L1": "Extreme", "LU-Alert Level 1": "Extreme", "ALERT_LVL_1": "Extreme", "D": "Extreme",
                 "N2": "Severe", "L2": "Severe", "LU-Alert Level 2": "Severe", "ALERT_LVL_2": "Severe",
                 "A": "Moderate", "LU-Alert Amber": "Moderate",
                 "N3": "Minor", "L3": "Minor", "LU-Alert Level 3": "Minor", "ALERT_LVL_3": "Minor",
                 "I": "Information", "LU-Alert Level 4": "Information", "ALERT_LVL_4": "Information", "n2": "Severe"}
        for code, severity in table.items():
            self.assertEqual(snap(cap_xml("a", level=code, severity="Unknown"), test_levels=()).alerts[0].severity,
                             severity, code)

    def test_the_level_beats_the_cap_severity(self):
        self.assertEqual(snap(cap_xml("a", level="N1", severity="Minor")).alerts[0].severity, "Extreme")

    def test_an_unknown_level_falls_back_to_the_cap_severity(self):
        alert = snap(cap_xml("a", level="X9", severity="Moderate")).alerts[0]
        self.assertEqual((alert.severity, alert.level_code), ("Moderate", "X9"))

    def test_without_a_level_the_cap_severity_counts(self):
        self.assertEqual(snap(cap_xml("a", with_level=False, severity="Severe")).alerts[0].severity, "Severe")
        self.assertEqual(snap(cap_xml("a", with_level=False, severity="Bogus")).alerts[0].severity, "Unknown")

    def test_the_level_may_be_in_any_block(self):
        infos = [info_xml("en", with_level=False, severity="Minor"), info_xml("de", level="N1")]
        self.assertEqual(snap(cap_xml("a", infos=infos)).alerts[0].severity, "Extreme")
        self.assertEqual(level_code(parse_cap(cap_xml("a", infos=infos))[0].infos), "N1")

    def test_ranking_and_counts(self):
        s = snap(cap_xml("minor", level="N3", sent=minutes(10)), cap_xml("extreme", level="N1", sent=minutes(50)),
                 cap_xml("severe-new", level="N2", sent=minutes(5)), cap_xml("severe-old", level="N2", sent=minutes(60)))
        self.assertEqual([a.identifier for a in s.alerts], ["extreme", "severe-new", "severe-old", "minor"])
        self.assertEqual((s.counts["Extreme"], s.counts["Severe"], s.counts["Minor"], s.counts["Moderate"]), (1, 2, 1, 0))
        self.assertEqual(s.total, 4)

    def test_the_minimum_severity(self):
        documents = [cap_xml("e", level="N1"), cap_xml("s", level="N2"), cap_xml("m", level="A"), cap_xml("i", level="I"),
                     cap_xml("u", with_level=False, severity="Bogus")]
        self.assertEqual(snap(*documents).total, 5)
        self.assertEqual(snap(*documents, min_rank=SEVERITY_RANK["Information"]).total, 4)
        self.assertEqual([a.identifier for a in snap(*documents, min_rank=SEVERITY_RANK["Severe"]).alerts], ["e", "s"])
        self.assertEqual([a.identifier for a in snap(*documents, min_rank=SEVERITY_RANK["Extreme"]).alerts], ["e"])


class SupersedeTests(unittest.TestCase):
    def test_of_one_identifier_the_newest_counts(self):
        s = snap(cap_xml("a", sent=minutes(120), headline="old"), cap_xml("a", sent=minutes(60), headline="new"))
        self.assertEqual([a.headline for a in s.alerts], ["new"])

    def test_a_cancel_ends_the_alert_it_references_and_is_not_shown(self):
        s = snap(cap_xml("a", sent=minutes(180)),
                 cap_xml("c", sent=minutes(5), msg_type="Cancel", references=reference("a", minutes(180))))
        self.assertEqual(s.total, 0)
        self.assertEqual(s.dropped["cancelled or replaced"], 2)

    def test_an_update_replaces_the_alert_it_references(self):
        s = snap(cap_xml("a", sent=minutes(180), headline="first"),
                 cap_xml("b", sent=minutes(60), msg_type="Update", references=reference("a", minutes(180)),
                         headline="second"))
        self.assertEqual([(a.identifier, a.headline) for a in s.alerts], [("b", "second")])

    def test_a_chain_of_updates_leaves_the_last(self):
        s = snap(cap_xml("a", sent=minutes(180)),
                 cap_xml("b", sent=minutes(120), msg_type="Update", references=reference("a", minutes(180))),
                 cap_xml("c", sent=minutes(60), msg_type="Update", references=reference("b", minutes(120))))
        self.assertEqual([a.identifier for a in s.alerts], ["c"])

    def test_a_reference_to_an_older_version_does_not_end_a_newer_one(self):
        s = snap(cap_xml("a", sent=minutes(30)),
                 cap_xml("u", sent=minutes(20), msg_type="Update", references=reference("a", minutes(300))))
        self.assertEqual(sorted(a.identifier for a in s.alerts), ["a", "u"])

    def test_a_reference_without_a_time_ends_it(self):
        s = snap(cap_xml("a"), cap_xml("c", msg_type="Cancel", references="lu-alert@gouvernement.lu,a"))
        self.assertEqual(s.total, 0)

    def test_replies_are_not_alerts_and_end_nothing(self):
        s = snap(cap_xml("a", sent=minutes(60)),
                 cap_xml("ack", sent=minutes(5), msg_type="Ack", references=reference("a", minutes(60))),
                 cap_xml("err", sent=minutes(4), msg_type="Error", references=reference("a", minutes(60))))
        self.assertEqual([a.identifier for a in s.alerts], ["a"])
        self.assertEqual(s.dropped["reply"], 2)

    def test_a_message_that_references_itself_ends_nothing(self):
        s = snap(cap_xml("a", sent=minutes(60), references=reference("a", minutes(60))))
        self.assertEqual(s.total, 1)

    def test_a_message_without_an_identifier_is_ignored(self):
        self.assertEqual(snap(cap_xml("")).total, 0)

    def test_a_cancel_of_something_never_seen_is_harmless(self):
        self.assertEqual(snap(cap_xml("c", msg_type="Cancel", references=reference("zzz", minutes(5)))).total, 0)


class ExpiryTests(unittest.TestCase):
    def test_an_expired_alert_is_dropped(self):
        s = snap(cap_xml("a", expires=NOW - timedelta(minutes=1)))
        self.assertEqual(s.total, 0)
        self.assertEqual(s.dropped["expired"], 1)

    def test_the_latest_end_over_all_blocks_counts(self):
        infos = [info_xml("en", expires=NOW - timedelta(hours=1)), info_xml("de", expires=NOW + timedelta(hours=1))]
        s = snap(cap_xml("a", infos=infos))
        self.assertEqual(s.total, 1)
        self.assertEqual(s.alerts[0].expires, NOW + timedelta(hours=1))

    def test_without_an_end_the_alert_stays_for_stale_days(self):
        self.assertEqual(snap(cap_xml("a", expires=None, sent=NOW - timedelta(days=1))).alerts[0].expires, None)
        old = cap_xml("b", expires=None, sent=NOW - timedelta(days=11))
        self.assertEqual(snap(old).dropped["old and without an end"], 1)
        self.assertEqual(snap(old, stale_days=30).total, 1)

    def test_the_next_expiry_is_the_earliest_end(self):
        s = snap(cap_xml("a", expires=NOW + timedelta(hours=3)), cap_xml("b", expires=NOW + timedelta(minutes=20)),
                 cap_xml("c", expires=None))
        self.assertEqual(s.next_expiry, NOW + timedelta(minutes=20))
        self.assertIsNone(snap(cap_xml("c", expires=None)).next_expiry)

    def test_the_alert_ends_when_the_clock_passes_its_end(self):
        document = cap_xml("a", expires=NOW + timedelta(minutes=10))
        self.assertEqual(snap(document, now=NOW + timedelta(minutes=9)).total, 1)
        self.assertEqual(snap(document, now=NOW + timedelta(minutes=11)).total, 0)


class TestMessageTests(unittest.TestCase):
    def test_test_exercise_system_and_draft_are_left_out(self):
        for status in ("Test", "Exercise", "System", "Draft", "test"):
            s = snap(cap_xml("a", status=status))
            self.assertEqual((s.total, s.dropped.get("test")), (0, 1), status)
        self.assertEqual(snap(cap_xml("a", status="Actual")).total, 1)
        self.assertEqual(snap(cap_xml("a", status="")).total, 1)

    def test_the_test_levels_are_left_out(self):
        for code in ("T", "LU-Alert Test", "LU-Alert Exercise"):
            self.assertEqual(snap(cap_xml("a", level=code)).total, 0, code)

    def test_tests_can_be_shown_and_rank_last(self):
        s = snap(cap_xml("t", level="T"), cap_xml("a", level="I"), show_test=True)
        self.assertEqual([(a.identifier, a.severity) for a in s.alerts], [("a", "Information"), ("t", "Test")])
        self.assertEqual(s.counts["Test"], 1)
        self.assertEqual(snap(cap_xml("t", status="Exercise"), show_test=True).alerts[0].severity, "Test")

    def test_a_test_ignores_the_minimum_severity_when_shown(self):
        s = snap(cap_xml("t", level="T"), show_test=True, min_rank=SEVERITY_RANK["Extreme"])
        self.assertEqual(s.total, 1)

    def test_level_d_is_a_test_by_default_like_in_the_integration_this_follows(self):
        s = snap(cap_xml("a", level="D", headline="Monthly test"))
        self.assertEqual((s.total, s.dropped["test"]), (0, 1))
        self.assertEqual(s.ignored_tests, (("a", "D", "Monthly test"),))              # named in the log, not silent

    def test_the_list_of_test_levels_can_be_changed_so_that_d_is_a_real_extreme_alert(self):
        s = snap(cap_xml("a", level="D"), test_levels=("t", "lu-alert test", "lu-alert exercise"))
        self.assertEqual((s.total, s.alerts[0].severity), (1, "Extreme"))
        self.assertEqual(s.ignored_tests, ())
        self.assertEqual(snap(cap_xml("a", level="N2"), test_levels=("n2",)).total, 0)

    def test_a_test_by_status_is_named_with_its_status(self):
        self.assertEqual(snap(cap_xml("a", status="Exercise", with_level=False, headline="Drill")).ignored_tests,
                         (("a", "Exercise", "Drill"),))


class CategoryTests(unittest.TestCase):
    def test_a_category_is_ignored_only_when_all_of_them_are(self):
        document = cap_xml("a", categories=("Met",))
        self.assertEqual(snap(document, ignore_categories=("met",)).dropped["ignored category"], 1)
        self.assertEqual(snap(cap_xml("a", categories=("Met", "Safety")), ignore_categories=("met",)).total, 1)
        self.assertEqual(snap(document, ignore_categories=("fire",)).total, 1)
        self.assertEqual(snap(cap_xml("a", categories=()), ignore_categories=("met",)).total, 1)


class LanguageTests(unittest.TestCase):
    def test_the_preferred_language_then_english_then_any(self):
        document = cap_xml("a")
        self.assertEqual(snap(document, language="de").alerts[0].headline, "Sturmwarnung für das ganze Land")
        self.assertEqual(snap(document, language="fr").alerts[0].headline, "Alerte tempête pour tout le pays")
        self.assertEqual(snap(document, language="lb").alerts[0].headline, "Storm warning for the whole country")
        only_german = cap_xml("a", languages=("de",))
        self.assertEqual(snap(only_german, language="lb").alerts[0].language, "de-LU")

    def test_the_fullest_channel_is_chosen_not_the_siren(self):
        s = snap(cap_xml("a", languages=("en",), channels=("Siren", "Mobile-App")))
        self.assertEqual(s.alerts[0].headline, "Storm warning for the whole country")
        infos = [info_xml("en", channel="Cell-Broadcast", headline="cb"), info_xml("en", channel="Website channel",
                                                                                   headline="web"),
                 info_xml("en", channel="Sms", headline="sms")]
        self.assertEqual(snap(cap_xml("a", infos=infos)).alerts[0].headline, "web")

    def test_choose_info_of_nothing(self):
        self.assertIsNone(choose_info([], "en"))
        self.assertEqual(snap(cap_xml("a", infos=[])).dropped["no text"], 1)

    def test_a_missing_headline_falls_back_to_the_event(self):
        s = snap(cap_xml("a", infos=[info_xml("en", headline="", event="Flood")]))
        self.assertEqual(s.alerts[0].headline, "Flood")


class LocationTests(unittest.TestCase):
    def test_the_local_flag(self):
        flag = dict(location_mode=1, location=HOME)
        self.assertIs(snap(cap_xml("a", polygon=CITY), **flag).alerts[0].local, True)
        self.assertIs(snap(cap_xml("a", polygon=ESCH), **flag).alerts[0].local, False)
        self.assertIsNone(snap(cap_xml("a"), **flag).alerts[0].local)                 # no geometry: no answer
        self.assertIsNone(snap(cap_xml("a", polygon=CITY)).alerts[0].local)           # filter off: not computed
        self.assertIsNone(snap(cap_xml("a", polygon=CITY), location_mode=1).alerts[0].local)   # no location known

    def test_only_local_alerts(self):
        only = dict(location_mode=2, location=HOME)
        s = snap(cap_xml("in", polygon=CITY), cap_xml("out", polygon=ESCH), cap_xml("unknown"), **only)
        self.assertEqual(sorted(a.identifier for a in s.alerts), ["in", "unknown"])
        self.assertEqual(s.dropped["outside the location"], 1)

    def test_an_area_can_be_a_circle(self):
        s = snap(cap_xml("a", infos=[info_xml("en", circle="49.6116,6.1319 5")]), location_mode=1, location=HOME)
        self.assertIs(s.alerts[0].local, True)


class MatchTests(unittest.TestCase):
    def test_keywords_match_headline_event_description_and_instruction_in_any_language(self):
        document = cap_xml("a")
        for keyword in ("storm", "STORM", "Sturmwarnung", "wind", "110 km/h", "indoors", "tempête"):
            self.assertTrue(snap(document, keywords=(keyword,)).alerts[0].watch_match, keyword)
        self.assertFalse(snap(document, keywords=("flood", "earthquake")).alerts[0].watch_match)
        self.assertFalse(snap(document).alerts[0].watch_match)

    def test_allergens_are_matched_the_same_way_and_separately(self):
        document = cap_xml("a", description="Product recall: contains PEANUTS, not declared.")
        alert = snap(document, allergens=("peanuts",), keywords=("flood",)).alerts[0]
        self.assertTrue(alert.allergen_match)
        self.assertFalse(alert.watch_match)


class TextTests(unittest.TestCase):
    def test_references(self):
        self.assertEqual(parse_references("a,b,2026-11-02T10:00:00+01:00 c,d,2026-11-02T11:00:00Z")[0][0], "b")
        self.assertEqual([i for i, _ in parse_references("a,b,2026-11-02T10:00:00+01:00 c,d")], ["b", "d"])
        self.assertEqual(parse_references(""), [])
        self.assertEqual(parse_references("garbage no-commas"), [])

    def test_the_summary_line(self):
        alert = snap(cap_xml("a")).alerts[0]
        self.assertEqual(summary_line(alert), "[Severe] Storm warning for the whole country - until 2026-11-02 14:00")
        short = summary_line(alert, 60)
        self.assertLessEqual(len(short), 60)
        self.assertTrue(short.startswith("[Severe] ") and short.endswith(" - until 2026-11-02 14:00"))
        self.assertIn("...", short)
        # the headline never gets less than 10 characters, so a tiny limit is exceeded rather than emptied
        self.assertEqual(summary_line(alert, 20), "[Severe] Storm w... - until 2026-11-02 14:00")
        no_end = snap(cap_xml("b", expires=None)).alerts[0]
        self.assertNotIn("until", summary_line(no_end))

    def test_format_time(self):
        self.assertEqual(format_time(None), "")
        self.assertEqual(format_time(NOW), "2026-11-02 12:00")


if __name__ == "__main__":
    unittest.main()
