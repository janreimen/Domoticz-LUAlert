# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions are plain numbers
(`MAJOR.MINOR.PATCH`, optionally a fourth `.N` for small fixes) so that release tags work with plugin managers
such as PyPluginStore.

## [0.1.2] - 2026-11-04

### Added
- **The alert devices show the start of the description.** *Highest Severity* and *Alert 1 ...* now read
  `[Minor] Recall : Savoy cabbage sold in bulk - until 2026-11-06 16:14 | Reason: Too high content of prothioconazole
  (pesticide residue) Name: Savoy Cabbage Bulk sale in: Colruyt Period of sale: 14/1...`, as far as the 200 characters
  of a Domoticz text allow. The reason: the live feed publishes several alerts with one headline (a recall per shop)
  and only the description tells them apart. Headline and end time always come first. `LU_DEVICE_DESCRIPTION=0` in
  `.env` brings the old text back. The unit numbers do not change.

### Fixed
- **Entities and links in descriptions.** The feed escapes some entities twice, so the text held a literal `&quot;`;
  they are decoded now (also `&amp;`, which was shown as `&amp;` before). Markdown links
  `[label](https://address)` become the label, plus the address when the label does not already say it.
- **The repository name** in the plugin, the documents, the issue templates and `deploy.sh` is `Domoticz-LUAlert`,
  like the repository (it said `Domoticz-LU-Alert`, which does not exist). The default directory of `deploy.sh` is
  `Domoticz-LUAlert` now. An installation in the old directory keeps working: update it with `--dir`.
- **`deploy.sh` does not leave two copies.** When another directory below `plugins/` already holds this plugin (the
  plugin key is the same, Domoticz would load both), it stops before changing anything and names that directory.
  A rollback is not affected.

### Changed
- The documents say that the plugin runs in a real Domoticz 2026.4 since 2026-11-04, and name
  [issue #1](https://github.com/janreimen/Domoticz-LUAlert/issues/1) (Domoticz restarted after the hardware was
  stopped; not understood yet).

## [0.1.1] - 2026-11-04

The first look at the live feed: `python3 -m lu_alert` was run on a Raspberry Pi against data.public.lu (100 alert
files listed and read, 7 active alerts, no error), and showed two things the plugin got wrong. The plugin itself has
**not yet been run in a real Domoticz**. See [docs/LU-ALERT-DATA.md](docs/LU-ALERT-DATA.md#seen-in-the-live-feed).

### Fixed
- **The level `TEST` is a test level.** The live feed marks its test messages with the level `TEST` (status
  `Actual`), which the plugin did not know; they would have been shown with the CAP severity. `TEST` is now in the
  level table and in the default of `LU_TEST_LEVELS` (`T,TEST,D,LU-Alert Test,LU-Alert Exercise`). If you have set
  `LU_TEST_LEVELS` yourself, add `TEST`.
- **The same alert published again is shown once.** The feed publishes a recall again as a new alert, with its own
  number and no reference to the first one. Alerts with the same severity, headline, description, instruction,
  event, area and end time are now shown once (the newest); `Left out:` counts them as `duplicate`.

### Added
- **A level the plugin does not know is named once in the log** (`Unknown LU-Alert level '...'`), and in
  `python3 -m lu_alert --json`, so a change of the feed does not go unnoticed. The CAP severity is still used.
- Tests for the shapes seen live: the levels `ALERT_LVL_1` to `ALERT_LVL_4` and `TEST`, a Cancel and an Update
  with a reference in the form of the feed (a different time zone, the same instant), duplicates.
- The data reference has a section *Seen in the live feed*; the level `D` is still not seen there.

## [0.1.0] - 2026-11-04

First version: a port of the Home Assistant integration
[Lux-Alert-HACS-integration](https://github.com/koosoli/Lux-Alert-HACS-integration) by koosoli to a Domoticz
plugin. Developed against a simulated data.public.lu (a real TLS server inside the test suite) and a simulated
Domoticz; **not yet run against the live feed or on a real Domoticz**, see
[what is verified](README.md#what-is-verified-and-what-is-not).

### Added
- **The LU-Alert warnings of the Luxembourg government** read from the CAP files of the dataset *Alertes du système
  LU-Alert* on data.public.lu, in the background (a poll never blocks Domoticz), every 5 minutes by default.
- **Devices** (18 by default, see [docs/DEVICES.md](docs/DEVICES.md)): *Active Alerts*, *Highest Severity* (a coloured
  alert), the switches *Critical / Severe / Extreme Alert Active*, *Local Alert Active*, *Watchlist Match* and
  *Allergen Match*, *LU-Alert Status* and *Feed Info*, one counter per severity, and *Alert 1 ... Alert 3* (up to 10)
  with severity, headline and end time of the most severe active alerts.
- **Alert rules** ([docs/LU-ALERT-DATA.md](docs/LU-ALERT-DATA.md)): cancel and update messages end or replace the
  alert they reference; an alert ends at its latest end time (also while the feed is down); alerts without an end
  time are shown for 10 days; test, exercise, system and draft messages are left out; the severity comes from the
  LU-Alert level (N1, N2, A, N3, I, ...), the CAP severity is the fallback; the text is taken from the language you
  choose and the fullest channel.
- **Hardware settings:** minimum severity, language (en, de, fr, lb), update interval, location filter (off, flag
  local alerts, only local alerts), home location (empty = the location of Domoticz), watchlist keywords, allergens
  and the debug level.
- **Location** by pure-Python polygon and circle tests; the home location is never written to the log, at any
  level.
- **`.env`** beside `plugin.py` for the technical settings (`.env.sample`): dataset URL, number of files and devices,
  time-outs, test levels, ignored categories, allowed hosts. A mistyped name is reported with a suggestion.
- **`python3 -m lu_alert`**: the engine without Domoticz, on the live feed or on CAP files, with `--json`.
- **Security:** https only with verified certificates; file addresses are requested only from the portal's own
  domain (or `LU_ALLOWED_HOSTS`); a redirect to another host or to http is refused; XML with a DOCTYPE is refused;
  answers are size-limited also after gzip decompression.
- **Quiet and careful:** a problem is logged once and its recovery once; a failing feed is asked less and less often;
  a failing feed never clears an alert; files that are not valid CAP are ignored once and do not stop the others.
- Tests (a fake data.public.lu on a real TLS server, a Domoticz stub), `make check`, `deploy.sh`, GitHub workflow,
  documentation.

### Decided without a look at the live feed
- The level code **D** is treated as a **test message**, like the Home Assistant integration does, and every test
  message that is left out is named once in the log. If D is a real level, take it out of `LU_TEST_LEVELS`.
  (0.1.1: the live feed has not shown a `D` yet.)

[0.1.2]: https://github.com/janreimen/Domoticz-LUAlert/releases/tag/v0.1.2
[0.1.1]: https://github.com/janreimen/Domoticz-LUAlert/releases/tag/v0.1.1
[0.1.0]: https://github.com/janreimen/Domoticz-LUAlert/releases/tag/v0.1.0
