# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions are plain numbers
(`MAJOR.MINOR.PATCH`, optionally a fourth `.N` for small fixes) so that release tags work with plugin managers
such as PyPluginStore.

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

[0.1.0]: https://github.com/janreimen/Domoticz-LU-Alert/releases/tag/v0.1.0
