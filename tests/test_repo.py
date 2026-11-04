"""Repository hygiene: versions agree, docs are current, links resolve, the README tells the truth about the code."""
import glob
import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [ROOT, os.path.join(ROOT, "tools"), os.path.join(ROOT, "tests")]

from lu_alert import __version__  # noqa: E402
from lu_alert import constants as c  # noqa: E402
from lu_alert.config import ENV_SPECS, Settings  # noqa: E402


def read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as fh:
        return fh.read()


def source_text():
    """plugin.py and the package, as one string."""
    paths = [os.path.join(ROOT, "plugin.py")] + sorted(glob.glob(os.path.join(ROOT, "lu_alert", "*.py")))
    out = []
    for path in paths:
        with open(path, encoding="utf-8") as fh:
            out.append(fh.read())
    return "\n".join(out)


def text_files():
    """Every file that people read: documents, scripts, templates, the sample configuration."""
    found = glob.glob(os.path.join(ROOT, "*.md")) + glob.glob(os.path.join(ROOT, "docs", "*.md"))
    found += glob.glob(os.path.join(ROOT, ".github", "**", "*"), recursive=True)
    found += [os.path.join(ROOT, n) for n in ("deploy.sh", "Makefile", "requirements.txt", ".env.sample", "NOTICE",
                                               "LICENSE", ".gitignore")]
    return sorted(p for p in found if os.path.isfile(p))


class VersionTests(unittest.TestCase):
    def test_version_is_plain_numeric(self):
        # plugin managers (PyPluginStore) only recognise plain numeric tags: no -alpha / -rc suffix
        self.assertRegex(__version__, r"^\d+\.\d+\.\d+(\.\d+)?$")

    def test_plugin_manifest_matches_package(self):
        match = re.search(r'<plugin\b[^>]*\bversion="([^"]+)"', read("plugin.py"))
        self.assertIsNotNone(match, "no version in the plugin manifest")
        self.assertEqual(match.group(1), __version__)

    def test_plugin_key_never_changes(self):
        # changing the key would turn every existing installation into an unknown hardware type
        match = re.search(r'<plugin\b[^>]*\bkey="([^"]+)"', read("plugin.py"))
        self.assertEqual((match.group(1), c.PLUGIN_KEY), ("LUAlert", "LUAlert"))

    def test_changelog_top_entry_matches_package(self):
        headings = re.findall(r"^## \[([^\]]+)\]", read("CHANGELOG.md"), re.M)
        released = [h for h in headings if h.lower() != "unreleased"]
        self.assertTrue(released, "CHANGELOG.md has no released version")
        self.assertEqual(released[0], __version__, "newest CHANGELOG entry differs from lu_alert.__version__")

    def test_changelog_links_every_release(self):
        text = read("CHANGELOG.md")
        for version in re.findall(r"^## \[(\d[^\]]*)\]", text, re.M):
            self.assertRegex(text, r"(?m)^\[%s\]: https?://" % re.escape(version))

    def test_changelog_release_link_points_at_this_repository(self):
        self.assertIn("https://github.com/janreimen/Domoticz-LU-Alert/releases/tag/v%s" % __version__,
                      read("CHANGELOG.md"))

    def test_the_user_agent_and_the_url_carry_the_version_and_the_repository(self):
        self.assertIn(__version__, c.USER_AGENT)
        self.assertEqual(c.PLUGIN_URL, "https://github.com/janreimen/Domoticz-LU-Alert")
        self.assertIn(c.PLUGIN_URL, read("plugin.py"))


class FileTests(unittest.TestCase):
    REQUIRED = ["LICENSE", "NOTICE", "README.md", "CHANGELOG.md", "ROADMAP.md", "SECURITY.md", "CONTRIBUTING.md",
                "DEPLOY.md", "ACCESSIBILITY.md", "checklist.md", "Makefile", "deploy.sh", "requirements.txt",
                ".gitignore", ".env.sample", ".github/workflows/tests.yml", ".github/CODE_OF_CONDUCT.md",
                ".github/PULL_REQUEST_TEMPLATE.md", ".github/ISSUE_TEMPLATE/config.yml",
                ".github/ISSUE_TEMPLATE/bug_report.yml", ".github/ISSUE_TEMPLATE/feature_request.yml",
                "docs/DEVICES.md", "docs/LU-ALERT-DATA.md", "tools/gen_device_catalog.py"]

    def test_required_files_exist(self):
        missing = [p for p in self.REQUIRED if not os.path.exists(os.path.join(ROOT, p))]
        self.assertEqual(missing, [])

    def test_no_real_env_file_is_in_the_repository(self):
        self.assertFalse(os.path.exists(os.path.join(ROOT, ".env")))
        self.assertRegex(read(".gitignore"), r"(?m)^\.env$")
        self.assertRegex(read(".gitignore"), r"(?m)^!\.env\.sample$")

    @unittest.skipIf(os.name != "posix", "POSIX permissions")
    def test_scripts_are_executable(self):
        for path in ("deploy.sh", "tools/gen_device_catalog.py"):
            self.assertTrue(os.access(os.path.join(ROOT, path), os.X_OK), path + " is not executable")

    def test_markdown_links_resolve(self):
        docs = [os.path.relpath(p, ROOT) for p in text_files() if p.endswith(".md")]
        broken = []
        for doc in docs:
            base = os.path.dirname(os.path.join(ROOT, doc))
            for target in re.findall(r"\]\(([^)\s]+)\)", read(doc)):
                if re.match(r"^(https?:|mailto:|#)", target):
                    continue
                path = target.split("#", 1)[0]
                if path and not os.path.exists(os.path.normpath(os.path.join(base, path))):
                    broken.append("%s -> %s" % (doc, target))
        self.assertEqual(broken, [])

    def test_anchors_that_documents_use_exist(self):
        def slug(heading):
            heading = re.sub(r"[`*]", "", heading).strip().lower()
            heading = re.sub(r"[^\w\- ]", "", heading)
            return heading.replace(" ", "-")

        def anchors(doc):
            return {slug(h) for h in re.findall(r"^#{1,6} (.+)$", read(doc), re.M)}

        missing = []
        for path in text_files():
            if not path.endswith(".md"):
                continue
            doc = os.path.relpath(path, ROOT)
            base = os.path.dirname(doc)
            for target, anchor in re.findall(r"\]\(([^)#\s]*)#([^)\s]+)\)", read(doc)):
                if target.startswith(("http:", "https:")):
                    continue
                other = os.path.normpath(os.path.join(base, target)) if target else doc
                if anchor not in anchors(other):
                    missing.append("%s -> %s#%s" % (doc, other, anchor))
        self.assertEqual(missing, [])

    def test_the_docs_use_the_real_directory_name(self):
        text = read("README.md") + read("DEPLOY.md")
        self.assertIn("git clone https://github.com/janreimen/Domoticz-LU-Alert.git", text)

    def test_nothing_is_left_over_from_the_plugins_this_one_was_modelled_on(self):
        pattern = re.compile(r"pi-?hole|synosnmp|synology|snmp|openaq|myskoda|voyo|xorfor|meteoalarm", re.I)
        # this file holds the pattern, test_plugin.py checks the manifest for the same words, and the bug report names
        # a DNS filter (Pi-hole, AdGuard) as one thing that can sit between Domoticz and the portal
        skip = {"tests/test_repo.py", "tests/test_plugin.py"}
        allowed_line = {".github/ISSUE_TEMPLATE/bug_report.yml": "AdGuard"}
        found = []
        for path in text_files() + glob.glob(os.path.join(ROOT, "lu_alert", "*.py")) + glob.glob(
                os.path.join(ROOT, "tests", "*.py")) + [os.path.join(ROOT, "plugin.py")]:
            name = os.path.relpath(path, ROOT)
            if name in skip:
                continue
            with open(path, encoding="utf-8") as fh:
                for number, line in enumerate(fh, 1):
                    if pattern.search(line) and allowed_line.get(name, "\0") not in line:
                        found.append("%s:%d" % (name, number))
        self.assertEqual(found, [])

    def test_the_documents_name_no_assistant_or_tool_that_wrote_them(self):
        pattern = re.compile(r"claude|anthropic|chatgpt|openai|copilot|co-authored|generated with|\bAI\b|\bLLM\b", re.I)
        found = []
        for path in text_files() + glob.glob(os.path.join(ROOT, "lu_alert", "*.py")) + [os.path.join(ROOT, "plugin.py")]:
            with open(path, encoding="utf-8") as fh:
                for number, line in enumerate(fh, 1):
                    if pattern.search(line):
                        found.append("%s:%d: %s" % (os.path.relpath(path, ROOT), number, line.strip()[:80]))
        self.assertEqual(found, [])


class DocumentationTests(unittest.TestCase):
    def test_troubleshooting_messages_exist_in_the_code_and_in_the_readme(self):
        # the README quotes log messages: if one is reworded in the code, the table must follow
        fragments = ["Update interval must be a number of seconds", "The home location must be 'latitude;longitude'",
                     "must be between", "must start with https://", "unknown setting",
                     "no location is known", "LU-Alert feed poll failed", "TLS error: the certificate of the server is not "
                     "trusted", "no answer within", "the answer is not JSON", "is not a host of the data portal",
                     "alert files (", "are not valid CAP or too large and are ignored", "Test message ignored",
                     "Domoticz did not create the device", "Accept new Hardware Devices", "Cannot update Domoticz unit",
                     "did not end within", "the plugin did not start, see the errors above", "Unexpected error in"]
        code, readme = source_text(), read("README.md")
        for fragment in fragments:
            self.assertIn(fragment, code, "no longer in the code: " + fragment)
        for fragment in fragments:
            if fragment == "alert files (":
                fragment = "of 12 alert files"          # "Could not read %d of %d alert files (%s)"
                self.assertIn("of %d alert files", code)
            self.assertIn(fragment, readme, "not in the README troubleshooting table: " + fragment)

    def test_the_readme_quotes_the_http_message_as_the_code_builds_it(self):
        self.assertIn('"%s: HTTP %d %s"', source_text())
        self.assertIn("dataset description: HTTP 403", read("README.md"))
        self.assertIn('"dataset description"', source_text())

    def test_deploy_guide_quotes_the_start_up_messages_the_code_writes(self):
        code, deploy = source_text(), read("DEPLOY.md")
        for fragment in ("Connected to the LU-Alert feed", "starting (update every", "No active LU-Alert alerts",
                         "Active alert", "Domoticz did not create the device"):
            self.assertIn(fragment, code, "no longer in the code: " + fragment)
            self.assertIn(fragment.split(" (")[0], deploy, "not in DEPLOY.md: " + fragment)

    def test_readme_names_the_hardware_type_of_the_manifest(self):
        name = re.search(r'<plugin\b[^>]*\bname="([^"]+)"', read("plugin.py")).group(1)
        self.assertIn(name, read("README.md"))
        self.assertIn(name, read("DEPLOY.md"))

    def test_the_readme_lists_every_hardware_field_of_the_manifest(self):
        readme = read("README.md")
        for label in re.findall(r'<param\b[^>]*\blabel="([^"]+)"', read("plugin.py")):
            first = re.split(r"[:(]", label)[0].strip()
            self.assertIn(first, readme, "hardware field not in the README: " + label)

    def test_the_readme_lists_every_env_key_with_its_default_and_range(self):
        readme = read("README.md")
        defaults = Settings()
        shown = {"LU_MAX_RESOURCES": defaults.max_resources, "LU_HTTP_TIMEOUT": defaults.http_timeout,
                 "LU_ALERT_DEVICES": defaults.alert_devices, "LU_STALE_DAYS": defaults.stale_days,
                 "LU_REFRESH_INTERVAL": defaults.refresh_interval}
        for key, spec in ENV_SPECS.items():
            self.assertRegex(readme, r"\| `%s` \|" % key)
            if key in shown:
                row = re.search(r"\| `%s` \| ([^|]+) \|[^\n]*" % key, readme).group(0)
                self.assertIn("| %s |" % shown[key], row, key)
                self.assertIn("(%d-%d)" % (spec.low, spec.high), row, key)

    def test_the_sample_env_file_documents_the_defaults_and_nothing_else(self):
        # every commented example line is a valid value, and the default of the sample is the default of the code
        text = read(".env.sample")
        keys = re.findall(r"(?m)^# (LU_[A-Z_]+)=(.*)$", text)
        self.assertEqual(sorted(k for k, _ in keys), sorted(ENV_SPECS))
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, ".env")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("\n".join("%s=%s" % pair for pair in keys))
            saved = {k: os.environ.pop(k) for k in list(os.environ) if k in ENV_SPECS}
            try:
                from_sample = Settings.from_parameters({}, env_path=path)
            finally:
                os.environ.update(saved)
        plain = Settings()
        for attribute in ("dataset_url", "max_resources", "http_timeout", "alert_devices", "refresh_interval",
                          "stale_days", "show_test", "test_levels", "ignore_categories", "allowed_hosts"):
            self.assertEqual(getattr(from_sample, attribute), getattr(plain, attribute), attribute)
        self.assertEqual(from_sample.warnings, [])

    def test_readme_device_table_names_every_device(self):
        readme = read("README.md")
        for spec in list(c.FIXED_DEVICES) + [c.alert_slot(1)]:
            self.assertIn(spec.name.split(" ")[0], readme)
        for name in ("Active Alerts", "Highest Severity", "Critical / Severe / Extreme Alert Active",
                     "Local Alert Active, Watchlist Match, Allergen Match", "LU-Alert Status, Feed Info",
                     "Extreme / Severe / Moderate / Minor / Information Alerts"):
            self.assertIn(name, readme)

    def test_readme_unit_numbers_match_the_code(self):
        readme = read("README.md")
        self.assertIn("| %d | Active Alerts |" % c.UNIT_ACTIVE, readme)
        self.assertIn("| %d | Highest Severity |" % c.UNIT_HIGHEST, readme)
        self.assertIn("| %d-%d | Critical / Severe / Extreme" % (c.UNIT_CRITICAL, c.UNIT_EXTREME), readme)
        self.assertIn("| %d, %d | LU-Alert Status, Feed Info |" % (c.UNIT_STATUS, c.UNIT_FEED_INFO), readme)
        self.assertIn("| %d-%d (up to %d) |" % (c.UNIT_ALERT_FIRST, c.UNIT_ALERT_FIRST + c.DEFAULT_ALERT_DEVICES - 1,
                                               c.UNIT_ALERT_LAST), readme)
        self.assertIn("| %d-%d | Extreme / Severe" % (c.UNIT_COUNT_EXTREME, c.UNIT_COUNT_INFORMATION), readme)
        self.assertIn("%d to %d" % (c.MIN_INTERVAL, c.MAX_INTERVAL), readme)
        self.assertIn("Default %d" % c.DEFAULT_INTERVAL, readme)

    def test_the_level_table_of_the_data_document_matches_the_code(self):
        text = read("docs", "LU-ALERT-DATA.md")
        rows = dict(re.findall(r"(?m)^\| ([^|]+) \| ([^|]+) \|", text.split("## Severity")[1].split("### The level D")[0]))
        documented = {}
        for cell, severity in rows.items():
            for level in re.findall(r"`([^`]+)`", cell):
                documented[level.lower()] = severity.strip()
        for level, severity in c.LEVEL_TO_SEVERITY.items():
            self.assertIn(level, documented, "level not documented: " + level)
            if level == "d":
                continue
            self.assertEqual(documented[level].split(" ")[0], severity, level)
        self.assertEqual(set(documented) - set(c.LEVEL_TO_SEVERITY), set())

    def test_the_test_levels_of_the_code_the_sample_and_the_documents_agree(self):
        joined = ",".join(c.DEFAULT_TEST_LEVELS)
        self.assertEqual(joined, "T,D,LU-Alert Test,LU-Alert Exercise")
        for name in ("README.md", ".env.sample"):
            self.assertIn(joined, read(name), name)
        self.assertIn("LU_TEST_LEVELS", read("docs", "LU-ALERT-DATA.md"))

    def test_the_decision_about_level_d_is_said_where_a_reader_looks(self):
        for name in ("README.md", "docs/LU-ALERT-DATA.md", "CHANGELOG.md", "ROADMAP.md"):
            self.assertRegex(read(*name.split("/")), r"(?i)level( code)? \W{0,3}D\W", name)
        self.assertIn("without a look at the live feed", read("README.md"))

    def test_the_documents_say_that_the_live_feed_was_not_checked(self):
        for name in ("README.md", "docs/LU-ALERT-DATA.md", "CHANGELOG.md"):
            self.assertRegex(read(*name.split("/")), r"(?i)not (yet )?(been )?(run against|verified against|checked against)",
                             name)

    def test_the_licence_question_is_in_the_notice_and_the_readme(self):
        self.assertIn("no licence", read("NOTICE"))
        self.assertIn("licence of the integration", read("README.md"))


class GeneratedDocsTests(unittest.TestCase):
    def test_device_catalogue_is_up_to_date(self):
        import gen_device_catalog
        self.assertEqual(read("docs", "DEVICES.md"), gen_device_catalog.render(),
                         "docs/DEVICES.md is stale: run python3 tools/gen_device_catalog.py")

    def test_every_fixed_device_is_in_exactly_one_section_of_the_catalogue(self):
        import gen_device_catalog
        for spec in c.FIXED_DEVICES:
            sections = [title for title, _, units in gen_device_catalog.SECTIONS if spec.unit in units]
            self.assertEqual(len(sections), 1, "%s (unit %d) is in %d sections" % (spec.name, spec.unit, len(sections)))

    def test_every_fixed_device_has_a_meaning(self):
        import gen_device_catalog
        missing = [spec.key for spec in c.FIXED_DEVICES if spec.key not in gen_device_catalog.MEANING]
        self.assertEqual(missing, [])

    def test_the_catalogue_lists_every_alert_slot(self):
        text = read("docs", "DEVICES.md")
        for spec in c.ALERT_SLOTS:
            self.assertIn("| %d | %s |" % (spec.unit, spec.name), text)


if __name__ == "__main__":
    unittest.main()
