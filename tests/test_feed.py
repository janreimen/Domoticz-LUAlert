"""The feed: which files are read, what is cached, what a bad file does to the others."""
import unittest

import helpers  # noqa: F401
from cap_samples import cap_xml
from helpers import start_feed
from lu_alert.api import ApiError, Client
from lu_alert.constants import MAX_XML_BYTES
from lu_alert.feed import Feed


class FeedCase(unittest.TestCase):
    def setUp(self):
        helpers.dz.reset()
        self.fake, self.context = start_feed(self)
        self.feed = self.make_feed()

    def make_feed(self, max_resources=100):
        return Feed(Client(self.fake.dataset_url, timeout=3, ssl_context=self.context), max_resources, workers=3)

    def files(self):
        return self.fake.count("/files/")


class ReadingTests(FeedCase):
    def test_the_messages_of_all_files(self):
        self.fake.add("a", cap_xml("a"))
        self.fake.add("b", cap_xml("b"), modified="2026-11-02T11:00:00")
        result = self.feed.refresh()
        self.assertEqual(sorted(m.identifier for m in result.cap_alerts), ["a", "b"])
        self.assertEqual((result.listed, result.fetched, result.cached, result.failed, result.unreadable),
                         (2, 2, 0, 0, 0))
        self.assertEqual(result.errors, [])

    def test_a_file_is_read_once(self):
        self.fake.add("a", cap_xml("a"))
        self.feed.refresh()
        result = self.feed.refresh()
        self.assertEqual((result.fetched, result.cached, len(result.cap_alerts)), (0, 1, 1))
        self.assertEqual(self.files(), 1)

    def test_a_new_file_is_the_only_one_read_later(self):
        self.fake.add("a", cap_xml("a"))
        self.feed.refresh()
        self.fake.add("b", cap_xml("b"), modified="2026-11-02T11:00:00")
        result = self.feed.refresh()
        self.assertEqual((result.fetched, result.cached, len(result.cap_alerts)), (1, 1, 2))
        self.assertEqual(self.files(), 2)

    def test_a_file_with_a_new_version_stamp_is_read_again(self):
        self.fake.add("a", cap_xml("a", headline="one"), modified="2026-11-02T10:00:00")
        self.feed.refresh()
        self.fake.add("a", cap_xml("a", headline="two"), modified="2026-11-02T10:05:00")
        result = self.feed.refresh()
        self.assertEqual(result.fetched, 1)
        self.assertEqual(result.cap_alerts[0].infos[0].headline, "two")

    def test_a_file_that_drops_off_the_list_is_forgotten(self):
        self.fake.add("a", cap_xml("a"))
        self.fake.add("b", cap_xml("b"), modified="2026-11-02T11:00:00")
        self.feed.refresh()
        self.fake.remove("a")
        result = self.feed.refresh()
        self.assertEqual([m.identifier for m in result.cap_alerts], ["b"])
        self.fake.add("a", cap_xml("a"))                    # it comes back: read again, not kept from before
        self.assertEqual(self.feed.refresh().fetched, 1)

    def test_only_the_newest_files_are_read(self):
        for i in range(6):
            self.fake.add("f%d" % i, cap_xml("f%d" % i), modified="2026-11-02T0%d:00:00" % i)
        result = self.make_feed(max_resources=2).refresh()
        self.assertEqual(sorted(m.identifier for m in result.cap_alerts), ["f4", "f5"])
        self.assertEqual((result.listed, self.files()), (2, 2))

    def test_a_file_with_several_messages(self):
        self.fake.add("a", cap_xml("a"))
        result = self.feed.refresh()
        self.assertEqual(len(result.cap_alerts), 1)

    def test_the_log_lines_travel_with_the_result_not_to_domoticz(self):
        self.fake.add("a", cap_xml("a"))
        result = self.feed.refresh()
        self.assertEqual(result.messages[0][0], "basic")
        self.assertIn("lists 1 alert files (limit 100): 1 to read, 0 cached", result.messages[0][1])
        self.assertTrue(any(level == "debug" and "1 message(s)" in text for level, text in result.messages))
        self.assertEqual(helpers.dz.logs, [])


class BadFileTests(FeedCase):
    def test_a_file_that_cannot_be_downloaded_is_tried_again_and_the_others_are_used(self):
        self.fake.add("a", cap_xml("a"))
        self.fake.add("b", cap_xml("b"), modified="2026-11-02T11:00:00")
        self.fake.fail.extend([("ok",), ("status", 503)])        # the description works, the first file fails
        result = self.feed.refresh()
        self.assertEqual((result.failed, result.unreadable, len(result.cap_alerts)), (1, 0, 1))
        self.assertIn("HTTP 503", result.errors[0])
        again = self.feed.refresh()
        self.assertEqual((again.failed, again.fetched, len(again.cap_alerts)), (0, 1, 2))

    def test_a_file_that_is_not_cap_is_not_requested_again(self):
        self.fake.add("a", cap_xml("a"))
        self.fake.add("junk", "this is not xml", modified="2026-11-02T11:00:00")
        result = self.feed.refresh()
        self.assertEqual((result.failed, result.unreadable, len(result.cap_alerts)), (0, 1, 1))
        requests = self.files()
        result = self.feed.refresh()
        self.assertEqual((result.unreadable, result.fetched, self.files()), (1, 0, requests))   # counted, not fetched

    def test_a_dtd_is_refused_and_counted_as_unreadable(self):
        bomb = ('<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY a "aaaa"><!ENTITY b "&a;&a;&a;">]>'
                '<alert xmlns="urn:oasis:names:tc:emergency:cap:1.2"><identifier>&b;</identifier></alert>')
        self.fake.add("bomb", bomb)
        result = self.feed.refresh()
        self.assertEqual((result.unreadable, result.cap_alerts), (1, []))
        self.assertIn("DOCTYPE", result.errors[0])

    def test_a_file_that_is_too_large_is_unreadable_for_good(self):
        self.fake.add("big", b"<a>" + b"x" * (MAX_XML_BYTES + 10) + b"</a>")
        result = self.feed.refresh()
        self.assertEqual((result.unreadable, result.failed), (1, 0))
        self.assertEqual(self.feed.refresh().fetched, 0)

    def test_a_changed_version_of_an_unreadable_file_gets_a_new_chance(self):
        self.fake.add("a", "garbage", modified="2026-11-02T10:00:00")
        self.assertEqual(self.feed.refresh().unreadable, 1)
        self.fake.add("a", cap_xml("a"), modified="2026-11-02T10:10:00")
        result = self.feed.refresh()
        self.assertEqual((result.unreadable, len(result.cap_alerts)), (0, 1))

    def test_the_description_that_cannot_be_read_raises(self):
        self.fake.fail.append(("status", 500))
        with self.assertRaises(ApiError):
            self.feed.refresh()

    def test_the_cache_survives_a_failed_description(self):
        self.fake.add("a", cap_xml("a"))
        self.feed.refresh()
        self.fake.fail.append(("status", 500))
        with self.assertRaises(ApiError):
            self.feed.refresh()
        result = self.feed.refresh()
        self.assertEqual((result.fetched, len(result.cap_alerts)), (0, 1))

    def test_a_parser_bug_does_not_take_the_poll_down(self):
        self.fake.add("a", cap_xml("a"))
        self.fake.add("b", cap_xml("b"), modified="2026-11-02T11:00:00")
        import lu_alert.feed as feed_module
        real = feed_module.parse_cap
        calls = []

        def flaky(data):
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError("boom")
            return real(data)
        feed_module.parse_cap = flaky
        self.addCleanup(setattr, feed_module, "parse_cap", real)
        result = self.make_feed().refresh()
        self.assertEqual((result.unreadable, len(result.cap_alerts)), (1, 1))
        self.assertIn("RuntimeError: boom", result.errors[0])

    def test_should_stop_ends_the_downloads_early(self):
        for i in range(5):
            self.fake.add("f%d" % i, cap_xml("f%d" % i), modified="2026-11-02T0%d:00:00" % i)
        result = self.feed.refresh(should_stop=lambda: True)
        self.assertEqual(result.fetched, 0)

    def test_the_errors_are_a_few_examples_not_a_flood(self):
        for i in range(8):
            self.fake.add("j%d" % i, "junk", modified="2026-11-02T0%d:00:00" % i)
        result = self.feed.refresh()
        self.assertEqual(result.unreadable, 8)
        self.assertEqual(len(result.errors), 3)


if __name__ == "__main__":
    unittest.main()
