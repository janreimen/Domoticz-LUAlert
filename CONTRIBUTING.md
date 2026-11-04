# Contributing

Bug reports, reports from real installations (also "it works on my setup...") and pull requests are welcome. The most
valuable contribution right now is **a report from a real Domoticz with the live feed**: run `python3 -m lu_alert
--json` on the Domoticz host, install the plugin, set *Debug* to *Basic*, and open an issue with the Domoticz version
and what the log shows. If you have a saved CAP file of a real alert (from data.public.lu), it is worth more than any
description: it becomes a test. Remove your location and other private data first.

## Set up

```sh
git clone https://github.com/janreimen/Domoticz-LUAlert.git
cd Domoticz-LUAlert
make test            # python3 -m unittest discover -s tests
make check           # tests + flake8 (pyflakes checks) + shellcheck + Python 3.7 compatibility (vermin) + generated docs
```

The tests need only Python 3 (and the `openssl` command for the TLS tests, which skip themselves without it). They
talk to their own fake data.public.lu on `127.0.0.1`; never point them at the real portal.

## Rules

- **No third-party Python packages**, and nothing that needs a newer Python than 3.7 (`make compat`).
- **Only `plugin.py` imports `Domoticz`**; only `devices.py` calls the Domoticz device API (through the object it is
  given). `api.py`, `feed.py`, `alerts.py`, `controller.py` and `config.py` never see Domoticz and are tested without it.
- **`plugin.py` must not bind the names Domoticz injects** (`Parameters`, `Devices`, `Images`, `Settings`): the
  injected globals would silently shadow them. A test enforces this. Import modules under another name
  (`from lu_alert import config as lu_config`). `Devices` is replaced by Domoticz before every callback, so
  the device manager reads it through a function (`lambda: Devices`), never through a reference taken at start.
- **The poll runs in a background thread that never touches Domoticz and never logs.** Whatever it has to say travels
  in its result; the plugin thread writes the log and the devices.
- **Never log the home location, and never log secrets.** The location and proxy passwords are registered with the
  logger, which masks them in every message. New code must not build log lines that bypass the logger, and must
  not put coordinates into a note, an error or a debug line. `tests/test_plugin.py` checks the log at Debug level.
- **The device model is frozen.** Units 1 - 10 (summary, switches, feed), 11 - 20 (alerts) and 21 - 25 (counters) are what
  an installation in the field uses; changing them breaks upgrades. A new device gets a new unit and a line in
  `constants.py`.
- **A problem is logged once, and its recovery once.** Use `Controller._report` / `_recovered`; repeats go to
  Verbose.
- **A failed poll never clears an alert.** An alert ends when the feed says so or when its time is up.
- **A file address from the feed is not trusted.** Requests go through `Client`, which checks https and the host.
- **Be conservative with what is dropped.** Every rule in `alerts.py` that leaves an alert out needs a test, a
  reason in `Snapshot.dropped` and a line in `docs/LU-ALERT-DATA.md`.
- **Domoticz callbacks must return quickly** and must not raise: wrap new callback code like the existing ones.
- The plugin only reads. It does not send anything anywhere.

## Adding a device

1. Add a `Device` row to `FIXED_DEVICES` in `lu_alert/constants.py` (the next free unit; never reuse one) and write
   its value in `DeviceManager.show`.
2. Add the meaning to `MEANING` in `tools/gen_device_catalog.py` and run `python3 tools/gen_device_catalog.py` to
   regenerate `docs/DEVICES.md` (a test fails if you forget).
3. Update the frozen list in `tests/test_devices.py` and add tests for creation and update.
4. Update the README device table and `CHANGELOG.md`.

## Changing the alert rules

Rules live in `lu_alert/alerts.py` as pure functions of the CAP messages, the time and the filters. Add a fixture with
`tests/cap_samples.py`, a test in `tests/test_alerts.py`, and describe the rule in `docs/LU-ALERT-DATA.md`.

## Pull requests

- One topic per pull request; keep it small enough to review. Target the `development` branch.
- Add or update tests; `make check` must pass.
- Update `CHANGELOG.md` under an `Unreleased` heading. The maintainer sets the version (see `checklist.md`).
- Describe what you tested and with which Domoticz version, and whether against the live feed, saved files or only the
  fake feed.

By contributing you agree that your contribution is licensed under the [MIT License](LICENSE).
