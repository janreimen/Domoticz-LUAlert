"""``python3 -m lu_alert``: the engine without Domoticz, on files and on the (fake) live feed."""
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

import helpers
from cap_samples import CITY, ESCH, HOME, cap_xml
from helpers import ROOT, start_feed
from lu_alert import __version__, cli
from lu_alert.config import KNOWN_KEYS


def fresh(identifier, **kw):
    now = datetime.now(timezone.utc)
    kw.setdefault("sent", now - timedelta(minutes=5))
    kw.setdefault("expires", now + timedelta(hours=1))
    return cap_xml(identifier, **kw)


class CliCase(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = folder.name
        clean = {k: v for k, v in os.environ.items() if k not in KNOWN_KEYS}
        patcher = mock.patch.dict(os.environ, clean, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def file(self, name, text):
        path = os.path.join(self.folder, name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        return path

    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        try:
            code = cli.main(list(argv), out, err)
        except SystemExit as exc:
            code = exc.code
        return code, out.getvalue(), err.getvalue()


class FileTests(CliCase):
    def test_a_file_with_one_alert(self):
        path = self.file("a.xml", fresh("a"))
        code, out, err = self.run_cli("--xml", path)
        self.assertEqual((code, err), (0, ""))
        self.assertIn("[Severe] Storm warning for the whole country  (level N2, until ", out)
        self.assertIn("area: Luxembourg", out)
        self.assertIn("instruction: Stay indoors.", out)
        self.assertIn("1 active alert(s) (Severe 1); 1 file(s) read.", out)

    def test_nothing_active(self):
        path = self.file("a.xml", cap_xml("a", expires=helpers.NOW))          # long over
        code, out, _ = self.run_cli("--xml", path)
        self.assertEqual(code, 0)
        self.assertIn("No active alerts (1 file(s) read).", out)
        self.assertIn("Left out: expired 1.", out)

    def test_json(self):
        path = self.file("a.xml", fresh("a", description="<p>Contains peanuts.</p>"))
        code, out, _ = self.run_cli("--xml", path, "--json", "--keywords", "storm", "--allergens", "peanuts")
        data = json.loads(out)
        self.assertEqual(code, 0)
        alert = data["alerts"][0]
        self.assertEqual((alert["identifier"], alert["severity"], alert["level"]), ("a", "Severe", "N2"))
        self.assertEqual((alert["watchlist_match"], alert["allergen_match"], alert["local"]), (True, True, None))
        self.assertEqual(alert["areas"], ["Luxembourg"])
        self.assertEqual(data["counts"]["Severe"], 1)
        self.assertEqual(data["dropped"], {})
        self.assertEqual((data["ignored_tests"], data["unknown_levels"]), ([], []))

    def test_a_test_message_of_the_live_feed_and_an_unknown_level_are_reported(self):
        test = self.file("t.xml", fresh("t", level="TEST", status="Actual", headline="Monthly test"))
        odd = self.file("o.xml", fresh("o", level="ALERT_LVL_9", severity="Moderate"))
        code, out, _ = self.run_cli("--xml", test, odd, "--json")
        data = json.loads(out)
        self.assertEqual(code, 0)
        self.assertEqual(data["ignored_tests"], [{"identifier": "t", "level": "TEST", "headline": "Monthly test"}])
        self.assertEqual(data["unknown_levels"], ["ALERT_LVL_9"])
        self.assertEqual(data["dropped"], {"test": 1})
        text = self.run_cli("--xml", test, odd)[1]
        self.assertIn("Left out: test 1.", text)
        self.assertIn("Unknown level(s): ALERT_LVL_9.", text)

    def test_the_minimum_severity_and_the_language(self):
        path = self.file("a.xml", fresh("a", level="N3"))
        self.assertIn("No active alerts", self.run_cli("--xml", path, "--min-severity", "Severe")[1])
        out = self.run_cli("--xml", path, "--language", "de")[1]
        self.assertIn("Sturmwarnung für das ganze Land", out)

    def test_the_location(self):
        city, esch = self.file("c.xml", fresh("c", polygon=CITY)), self.file("e.xml", fresh("e", polygon=ESCH))
        here = "%s;%s" % HOME
        out = self.run_cli("--xml", city, esch, "--location", here)[1]
        self.assertEqual(out.count("<- your location"), 1)
        out = self.run_cli("--xml", city, esch, "--location", here, "--only-local")[1]
        self.assertIn("1 active alert(s)", out)
        self.assertIn("outside the location 1", out)

    def test_test_messages_are_left_out_unless_asked(self):
        path = self.file("t.xml", fresh("t", status="Test"))
        self.assertIn("No active alerts", self.run_cli("--xml", path)[1])
        out = self.run_cli("--xml", path, "--show-test")[1]
        self.assertIn("[Test]", out)

    def test_a_file_that_is_not_cap_is_exit_1_with_the_name(self):
        path = self.file("junk.xml", "not xml")
        code, out, err = self.run_cli("--xml", path)
        self.assertEqual((code, out), (1, ""))
        self.assertIn("junk.xml", err)
        self.assertTrue(err.startswith("error: "))

    def test_a_file_that_does_not_exist_is_exit_1(self):
        code, _, err = self.run_cli("--xml", os.path.join(self.folder, "none.xml"))
        self.assertEqual(code, 1)
        self.assertIn("none.xml", err)

    def test_bad_options_are_exit_1_not_the_2_of_argparse(self):
        for argv in (["--min-severity", "loud"], ["--no-such-option"], ["--location", "nowhere", "--xml", "x"]):
            code, out, err = self.run_cli(*argv)
            self.assertEqual(code, 1, argv)
            self.assertEqual(out, "")
            self.assertTrue(err)

    def test_the_version(self):
        code, out, _ = self.run_cli("--version")
        self.assertEqual((code, out.strip()), (0, "lu_alert " + __version__))

    def test_notes_about_corrections_go_to_stderr(self):
        path = self.file("a.xml", fresh("a"))
        _, out, err = self.run_cli("--xml", path, "--only-local")
        self.assertIn("note: ", err)
        self.assertIn("no location is known", err)
        self.assertNotIn("note:", out)

    def test_the_location_is_not_printed_back(self):
        path = self.file("a.xml", fresh("a", polygon=CITY))
        code, out, err = self.run_cli("--xml", path, "--location", "49.6116;6.1319")
        self.assertEqual(code, 0)
        self.assertNotIn("49.6116", out + err)


class LiveTests(CliCase):
    def setUp(self):
        super().setUp()
        self.fake, self.context = start_feed(self)
        os.environ["SSL_CERT_FILE"] = helpers.certs.get()[1]          # the CLI builds the default context of the system
        self.addCleanup(os.environ.pop, "SSL_CERT_FILE", None)

    def test_the_feed_is_read_and_shown(self):
        self.fake.add("a", fresh("a"))
        code, out, err = self.run_cli("--dataset-url", self.fake.dataset_url)
        self.assertEqual((code, err), (0, ""))
        self.assertIn("1 active alert(s)", out)
        self.assertIn("1 alert files listed, 1 read now.", out)

    def test_the_number_of_files_can_be_limited(self):
        for i in range(4):
            self.fake.add("f%d" % i, fresh("f%d" % i), modified="2026-11-02T0%d:00:00" % i)
        code, out, _ = self.run_cli("--dataset-url", self.fake.dataset_url, "--max-resources", "10")
        self.assertIn("4 alert files listed", out)

    def test_an_unreachable_feed_is_exit_2_and_says_why(self):
        self.fake.fail.append(("status", 503))
        code, out, err = self.run_cli("--dataset-url", self.fake.dataset_url)
        self.assertEqual((code, out), (2, ""))
        self.assertIn("the LU-Alert feed cannot be read: dataset description: HTTP 503", err)

    def test_files_that_cannot_be_read_are_a_note_not_a_failure(self):
        self.fake.add("a", fresh("a"))
        self.fake.add("junk", "no xml", modified="2026-11-02T11:00:00")
        code, out, err = self.run_cli("--dataset-url", self.fake.dataset_url)
        self.assertEqual(code, 0)
        self.assertIn("1 not valid CAP", err)
        self.assertIn("1 active alert(s)", out)

    def test_an_http_dataset_url_is_refused(self):
        code, _, err = self.run_cli("--dataset-url", self.fake.dataset_url.replace("https://", "http://"))
        self.assertEqual(code, 2)
        self.assertIn("only https URLs are used", err)


class ModuleTests(unittest.TestCase):
    def test_python_dash_m_runs_and_returns_the_exit_status(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        path = os.path.join(folder.name, "a.xml")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(fresh("a"))
        done = subprocess.run([sys.executable, "-m", "lu_alert", "--xml", path, "--json"], cwd=ROOT, capture_output=True,
                              text=True, timeout=30)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(json.loads(done.stdout)["counts"]["Severe"], 1)
        bad = subprocess.run([sys.executable, "-m", "lu_alert", "--min-severity", "loud"], cwd=ROOT, capture_output=True,
                             text=True, timeout=30)
        self.assertEqual(bad.returncode, 1)


if __name__ == "__main__":
    unittest.main()
