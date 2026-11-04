# Domoticz-LUAlert

A [Domoticz](https://www.domoticz.com) plugin that shows the official **LU-Alert** warnings of the Luxembourg
government as devices: how many alerts are active, how severe the worst one is, one device per alert, and switches
you can use in notifications, scenes and scripts. It is a port of the Home Assistant integration
[Lux-Alert-HACS-integration](https://github.com/koosoli/Lux-Alert-HACS-integration) by koosoli.

* **Active Alerts and Highest Severity.** A counter and a coloured alert device (green, yellow, orange, red) with the
  headline and the end time of the worst alert; counters for Extreme, Severe, Moderate, Minor and Information.
* **Alert 1 ... Alert 3** (up to 10): the most severe active alerts, each with severity, headline, end time and the
  start of the description (as far as the 200 characters of a Domoticz text allow).
* **Switches for your rules.** *Critical*, *Severe* and *Extreme Alert Active*; *Local Alert Active* (the area of an
  alert contains your home); *Watchlist Match* and *Allergen Match* (your keywords occur in an alert, for example
  `storm`, `flood` or `peanuts`).
* **Alerts end like the feed says.** Cancel and update messages are applied, an alert ends at its end time (also
  while the feed cannot be reached), test messages are left out.
* **No account, no Python packages.** Standard library only, Python 3.7 or newer. The data are public.
* **Careful with your privacy.** Your home location is used inside the plugin only and never reaches the log.
* **Quiet.** A problem is logged once and its recovery once; a feed that is down is asked less and less often and
  never clears the alerts you see.
* **Modular.** Feed client, CAP parser, alert rules, settings, device layer and polling logic are separate modules;
  only `plugin.py` touches Domoticz.

> **Status:** version 0.1.2. Developed against a **simulated** data.public.lu (a real TLS server inside the test
> suite) and a simulated Domoticz. Since **2026-11-04** it has run in the author's Domoticz 2026.4 (Raspberry Pi OS
> Trixie, Python 3.13) against the **live feed**: it reads the feed, creates its devices and shows the alerts. That is
> days of use, not months; the level `D` has not been seen in the feed, and
> [issue #1](https://github.com/janreimen/Domoticz-LUAlert/issues/1) (Domoticz restarted after the hardware was
> stopped) is not understood yet. Read [what is verified and what is not](#what-is-verified-and-what-is-not).
>
> **This is not a warning system.** It shows what the portal publishes, a few minutes late. Keep the official
> LU-Alert (cell broadcast, app, sirens) as your warning; use this plugin for automation next to it.

Contents: [Requirements](#requirements) · [Install](#install) · [Check the feed](#check-the-feed) ·
[Settings](#settings) · [Devices](#devices) · [What is shown](#what-is-shown) · [Using the devices](#using-the-devices) ·
[How it works](#how-it-works) · [Privacy and security](#privacy-and-security) · [Troubleshooting](#troubleshooting) ·
[FAQ](#faq) · [Verified](#what-is-verified-and-what-is-not) · [Development](#development) · [Credits](#credits) ·
[License](#license)

## Requirements

| Where | What |
|---|---|
| Domoticz host | Domoticz with Python plugin support, **Python 3.7+** |
| Network | the Domoticz host can reach `https://data.public.lu` (port 443), directly or through a proxy |

No account and no key are needed. Nothing is sent to the portal except the requests for the public files.

## Install

```sh
cd /srv/domoticz/plugins                  # your Domoticz plugin directory, e.g. ~/domoticz/plugins
git clone https://github.com/janreimen/Domoticz-LUAlert.git
sudo systemctl restart domoticz
```

`plugin.py` and the `lu_alert/` directory must stay together. The directory name does not matter to Domoticz (the
plugin is identified by its `key`, `LUAlert`). Use one directory per plugin; do not leave an old copy next to it.

Or use the bundled [`deploy.sh`](DEPLOY.md), which installs locally or over SSH, checks the syntax of the new files,
makes a backup, restores ownership and restarts Domoticz:

```sh
./deploy.sh --host jan@rpi4office
```

Then *Setup > Hardware*, type **LU-Alert Luxembourg**, fill in the [settings](#settings) (none is required), *Add*.
The devices appear within a few seconds. Full instructions, updates, rollback and removal: **[DEPLOY.md](DEPLOY.md)**.

## Check the feed

Before you add the hardware, and whenever the devices show something you do not expect:

```sh
cd /srv/domoticz/plugins/Domoticz-LUAlert
python3 -m lu_alert                       # the live feed: the alerts the plugin would show
python3 -m lu_alert --json                # the same as JSON (for a bug report; leave out --location)
python3 -m lu_alert --language de --min-severity Moderate
python3 -m lu_alert --location "49.6116;6.1319" --only-local
python3 -m lu_alert --xml saved.xml       # a CAP file from disk
```

It uses the same code and the same rules as the plugin. Exit status 0 = worked (also when no alert is active),
1 = wrong option or unreadable file, 2 = the feed cannot be read (the message says why).

## Settings

| Field | Meaning |
|---|---|
| Minimum severity | `All alerts` (default), or only alerts of at least *Information*, *Minor*, *Moderate*, *Severe* or *Extreme* |
| Language of the alert texts | `English` (default), `Deutsch`, `Français` or `Lëtzebuergesch`. The feed carries the text in several languages; if yours is missing English is used, then any |
| Update Interval (seconds) | Seconds between polls. Default 300, allowed 60 to 3600; other values are corrected and the log says so. A poll costs one small request, plus one for every *new* alert file |
| Location filter | `Off` (default); `Flag local alerts`: every alert is shown and *Local Alert Active* tells whether one of them concerns your home; `Only local alerts`: alerts whose area does not contain your home are left out (an alert without any area given is kept) |
| Home location: latitude;longitude | For example `49.6116;6.1319`. Empty = the location set in *Setup > Settings > System* of Domoticz. Used by the location filter only; never logged. A filter without any location switches itself off, with a log line |
| Watchlist keywords (comma separated) | `storm, flood, fire`: *Watchlist Match* is On while one of them occurs (any case, any language of the message) in the headline, event, description or instruction of an active alert |
| Allergens (comma separated) | The same for *Allergen Match*, for example `peanuts, milk, gluten` (useful for food recalls). The field is called *Username* in the Domoticz database; the plugin has no login |
| Debug | `Off` (default), `Basic` (what happens when), `Verbose` (adds what was left out and why), `Debug` (every file and every device update). Debug lines never contain your home location |

Several instances (for example two languages or two locations): add the hardware once per instance; each gets its own
set of devices. The technical settings below are shared.

### Technical settings: `.env`

Settings that are rarely changed go into a file named `.env` next to `plugin.py`: copy
[`.env.sample`](.env.sample) and remove the `#` of the lines you want. A variable of the same name in the environment
of the Domoticz service wins over the file; a mistyped name or a bad value is reported in the log, a bad value stops the
plugin with a message that names the key. Changes take effect when the hardware is restarted. `deploy.sh` leaves your
`.env` alone.

| Key | Default | Meaning |
|---|---|---|
| `LU_DATASET_URL` | the dataset on data.public.lu | Where the list of alert files comes from. `https://` only |
| `LU_ALLOWED_HOSTS` | (none) | Further hosts the alert files may come from; by default only the portal's own domain (`*.public.lu`). Add one only if the log says a host is not a host of the data portal |
| `LU_MAX_RESOURCES` | 100 | How many of the newest files are read (10-500). Only the first poll reads them all |
| `LU_HTTP_TIMEOUT` | 10 | Seconds to wait for an answer (3-60) |
| `LU_ALERT_DEVICES` | 3 | How many *Alert n* devices are created (1-10) |
| `LU_STALE_DAYS` | 10 | An alert without an end time is shown this many days (1-365) |
| `LU_REFRESH_INTERVAL` | 300 | An unchanged value is rewritten this often, in seconds (30-86400) |
| `LU_DEVICE_DESCRIPTION` | 1 | `1`: the alert devices show the start of the description after the headline and the end time. `0`: headline and end time only |
| `LU_SHOW_TEST_ALERTS` | 0 | `1` also shows test messages, as severity *Test* (grey) |
| `LU_TEST_LEVELS` | `T,TEST,D,LU-Alert Test,LU-Alert Exercise` | LU-Alert levels that count as test messages. **See [the level D](#the-level-d)** |
| `LU_IGNORE_CATEGORIES` | (none) | CAP categories to leave out (`Met`, `Fire`, `Health`, ...). An alert is left out only when *all* its categories are listed |

## Devices

18 devices are created by default. The full list with types and meaning is in **[docs/DEVICES.md](docs/DEVICES.md)**
(generated from the code).

| Unit | Name | Shows |
|---:|---|---|
| 1 | Active Alerts | number of alerts in force |
| 2 | Highest Severity | colour and text of the worst alert (green when none) |
| 3-5 | Critical / Severe / Extreme Alert Active | On while such an alert is active (*Critical* = Extreme or Severe) |
| 6-8 | Local Alert Active, Watchlist Match, Allergen Match | On while an active alert contains your home / your keywords / your allergens |
| 9, 10 | LU-Alert Status, Feed Info | whether the feed can be read, and the state of the last poll |
| 11-13 (up to 20) | Alert 1 ... Alert 3 | the most severe active alerts: `[Severe] Storm warning for the whole country - until 2026-11-02 14:00` |
| 21-25 | Extreme / Severe / Moderate / Minor / Information Alerts | one counter per severity |

All devices are read-only; a command is answered with the real state. They are created *in use*, so nothing has to be
added by hand. Domoticz names them `<hardware name> - <device name>`, for example `LU-Alert - Critical Alert Active`.
The unit numbers never change, so scripts and scenes keep working across updates.

| Severity | Colour |
|---|---|
| Extreme, Severe | red |
| Moderate | orange |
| Minor | yellow |
| Information | green |
| Unknown, Test | grey |

## What is shown

The rules in short; the full version, with the level table, is in **[docs/LU-ALERT-DATA.md](docs/LU-ALERT-DATA.md)**.

* **Severity** comes from the LU-Alert *level* of the message (`N1` Extreme, `N2` Severe, `A` Moderate, `N3` Minor,
  `I` Information, ...); only a message without a known level uses the CAP `severity` field.
* **Cancel and Update** messages end or replace the alert they reference; the Cancel itself is never shown.
* **An alert ends** at its *latest* end time over all its language blocks, between polls too, even while the feed is
  down. An alert without an end time is shown for 10 days.
* **Test messages** (status Test, Exercise, System, Draft; the levels `T`, `D`, `LU-Alert Test`, `LU-Alert Exercise`)
  are left out, and **each one that is left out is named once in the log**.
* **Nothing is left out because of its category**, unless you list the category in `LU_IGNORE_CATEGORIES`.
* **Order:** most severe first, newest first.

### The level D

The Home Assistant integration treats the level `D` both as Extreme and as a test level, which in practice drops it.
The plugin does the same by default, **but `D` has not been seen in the live feed** (the test messages seen there
carry the level `TEST`, which is a test level too). Wrongly hiding a real alert is the worse mistake, so every test message that is left out appears once in the Domoticz log, with its
level and headline (`Test message ignored (D): ...`). If you find that `D` is a real alert level, remove it from
`LU_TEST_LEVELS` in `.env`; it is then an Extreme alert.

## Using the devices

* **Notification:** *Setup > More Options > Notifications* on *Critical Alert Active* (On), or on *Highest Severity*
  (the text carries the headline).
* **A scene or a light:** use *Critical Alert Active* or *Extreme Alert Active* as the trigger; use *LU-Alert Status* to
  be told when the plugin cannot read the feed.
* **A script** (dzVents) *(an example, not yet tried on a real installation)*:

```lua
return {
    on = { devices = { 'LU-Alert - Critical Alert Active' } },
    execute = function(domoticz, device)
        if device.active then
            domoticz.notify('LU-Alert', domoticz.devices('LU-Alert - Highest Severity').text, domoticz.PRIORITY_EMERGENCY)
        end
    end
}
```

## How it works

```
plugin.py               Domoticz glue only: manifest, callbacks, wiring
lu_alert/
    constants.py        the frozen device model, severity tables, limits
    config.py           Settings: the hardware page and the .env file, validated
    api.py              Client: the dataset and the alert files over https, host and size checks
    feed.py             which files are read, the cache, concurrent downloads
    cap.py              CAP 1.2 / CAP-LU parser (standard library XML, DOCTYPE refused)
    geo.py              point in polygon / circle (pure Python)
    alerts.py           the rules: from CAP messages to the alerts in force now (pure functions)
    controller.py       polling in a background thread, back-off, log once, expiry
    devices.py          DeviceManager: the only module that calls the Domoticz device API
    logger.py           four log levels, secrets and the home location masked
    model.py, util.py   small data types and helpers
    cli.py              python3 -m lu_alert
docs/                   DEVICES.md (generated), LU-ALERT-DATA.md
tests/                  unit tests, a fake data.public.lu (TLS), a Domoticz stub
tools/                  gen_device_catalog.py
```

* **Heartbeat 10 s, polling by time.** Domoticz logs a plugin as "not responding" when its heartbeat is longer than
  30 seconds, so the heartbeat stays at 10 s and the plugin polls when the interval has elapsed.
* **A poll never blocks Domoticz.** It runs in a background thread that never touches Domoticz and never logs; the
  plugin thread picks up its result at the next heartbeat (so the first values appear within about ten seconds of the
  start).
* **Cheap polls.** The description of the dataset is requested conditionally; an alert file never changes once
  published, so it is downloaded once and kept in memory. A poll is normally one small request.
* **Back-off.** After a failed poll the next attempt is delayed (twice the interval, then four times, up to 30
  minutes). The first successful poll resets it.
* **A failing feed never clears an alert.** The devices keep the last known alerts and *Feed Info* says since when
  the feed cannot be read; the alerts still end at their end time.
* **Log once.** A problem is an *Error* in the log once, repeats appear only with Debug *Verbose*, and the recovery
  is one line. Files that are not valid CAP are reported once, with how many, and ignored.
* **Never crashes Domoticz.** Every callback is wrapped; an unexpected exception is logged once with its name,
  details at Debug level.

## Privacy and security

Details and the hardening checklist: **[SECURITY.md](SECURITY.md)**. In short:

* The plugin only reads public files; it has no account, and sends nothing about you anywhere.
* Your **home location is never written to the log**, at any level, and your watchlist and allergens stay in Domoticz.
* **https only, certificates always verified.** File addresses from the feed are requested only from the portal's
  own domain; redirects to other hosts or to http are refused.
* **Hostile files:** XML with a DOCTYPE is refused, answers are size-limited also after gzip decompression.
* A proxy in the environment of the Domoticz service is used; a password inside its URL is masked in the log.

## Troubleshooting

Set *Debug* to **Basic** first, **Verbose** shows what was left out. The messages below are the ones the plugin writes.

| Log message | Cause / fix |
|---|---|
| `Configuration error: Update interval must be a number of seconds` | the *Update Interval* field is not a number |
| `Configuration error: The home location must be 'latitude;longitude'` | fix the *Home location* field, for example `49.6116;6.1319` (the log does not repeat what you typed) |
| `Configuration error: LU_MAX_RESOURCES must be between 10 and 500` (and the like) | a value in `.env` is out of range or no number; the message names the key |
| `Configuration error: LU_DATASET_URL must start with https://` | the plugin only talks https |
| `Configuration warning: .env line 3: unknown setting LU_MAX_RESOURCE ignored (did you mean LU_MAX_RESOURCES?)` | a mistyped key in `.env`; the default is in force |
| `The location filter is 'Only local alerts' but no location is known` | fill in *Home location* or set the location in Domoticz; the filter is off until then |
| `LU-Alert feed poll failed: dataset description: HTTP 403` (or another HTTP code) | the portal or a proxy in between refused the request. A proxy or firewall that does not allow data.public.lu is the usual cause; try `python3 -m lu_alert` on the host |
| `... TLS error: the certificate of the server is not trusted` | the Python of the Domoticz host does not trust the certificate authority of the portal: update the host's CA certificates (`ca-certificates`), or set `SSL_CERT_FILE` in the environment of the Domoticz service. There is no setting to switch verification off |
| `... no answer within 10 s` or `Connection refused` | the portal is down or too slow, a firewall blocks it, or there is no route to the Internet |
| `... the answer is not JSON (did the data portal change its API?)` | the dataset address is wrong or the portal changed; look at `LU_DATASET_URL` and open an issue |
| `... is not a host of the data portal` | the dataset lists a file on a host outside `*.public.lu`, and the plugin does not request it. If the portal really moved its files, add the host to `LU_ALLOWED_HOSTS` |
| `Could not read 2 of 12 alert files (...): the alerts shown may be incomplete` | some downloads failed; the other files are used and the next poll tries again |
| `3 alert file(s) are not valid CAP or too large and are ignored` | the portal published something the parser does not accept. Reported once; the others are used. With *Verbose* the log names the files. Please open an issue with `python3 -m lu_alert --json` |
| `Test message ignored (D): ...` | a test message was left out ([the level D](#the-level-d)); informational |
| `Domoticz did not create the device ...` | Domoticz refuses new devices while *Setup > Settings > System > Accept new Hardware Devices* is off. Switch it on; the plugin asks again every 5 minutes, no restart needed |
| `Cannot update Domoticz unit N: no such device` | the device was deleted in Domoticz; it is created again at the next poll |
| `A poll of the LU-Alert feed did not end within 12 s; it is abandoned` | the portal did not answer while Domoticz was stopping the hardware; harmless |
| `Command for unit N ignored: the plugin did not start, see the errors above` | the configuration error above it stopped the plugin |
| `Unexpected error in ...` | a bug: please open an issue with the line and, with Debug on, the lines after it |

## FAQ

**Does it warn me?** No. It makes the alerts available to Domoticz. Keep the official LU-Alert on your phone.

**How late is it?** The portal's own delay plus up to the update interval (default 5 minutes). Lower the interval to
60 seconds if it matters; it costs one small request per poll.

**Nothing is active, but the official app showed an alert.** The alert may have ended, may be a test, or the portal
has not published it yet. Run `python3 -m lu_alert --show-test --json` and look at `dropped`, and look at the log with
*Debug* on *Verbose*.

**Why is the alert for my commune not "local"?** The test uses the polygons and circles in the message. An alert
without any area is never "local" (and, with *Only local alerts*, never dropped). Check the coordinates: they are
`latitude;longitude`, in that order.

**Can I get the text in Luxembourgish?** Choose it; if the message has no Luxembourgish block, English is used.

**Can I ignore a type of alert?** Use *Minimum severity*, or list categories in `LU_IGNORE_CATEGORIES`.

**The values are older than the poll.** Values are written when they change and every 5 minutes otherwise, so
Domoticz' sensor time-out does not mark a quiet sensor as dead.

## What is verified and what is not

**Verified (by the test suite):**

* the CAP parser on messages in the shape of the CAP-LU profile: several languages and channels, HTML descriptions,
  polygons and circles, namespaces, odd and broken input, a DOCTYPE (refused);
* the alert rules: levels and severities, newest per identifier, Cancel and Update (also chains and older
  references), expiry over the latest end, alerts without an end, test messages and levels, categories, language and
  channel choice, location (inside, outside, no geometry), watchlist and allergens, order and counts;
* the client against a fake data.public.lu that is a real TLS server (a CA made for the test): the list of files,
  gzip, conditional requests, HTTP errors, dropped connections, garbage, time-outs, an untrusted certificate,
  oversized answers and a gzip bomb, hosts that must not be requested, redirects to http or to other hosts;
* the feed: caching, new and changed files, files that drop off the list, files that cannot be read, a parser bug;
* the device logic against a stub of the Domoticz API: creation, refused creation, the frozen unit model, writes,
  refresh, deleted devices, commands; the controller: back-off, log once, recovery, a failing feed that keeps the
  alerts, alerts that end between polls, the background thread and a stop during a poll;
* that your **home location and a proxy password never reach the log**, also at Debug level, and that `plugin.py`
  binds none of the names Domoticz injects, imports only the standard library and is the only module that imports
  `Domoticz`; Python 3.7 compatibility (`vermin`).

**Seen in the live feed** (one run of `python3 -m lu_alert` on a Raspberry Pi, 2026-11-04, details in
[docs/LU-ALERT-DATA.md](docs/LU-ALERT-DATA.md#seen-in-the-live-feed)):

* the dataset lists 100 alert files; all could be read; the levels are `ALERT_LVL_1` to `ALERT_LVL_4` and `TEST`;
  Cancel and Update messages reference the alert as `[SENDER],identifier,sent`; of the 100 messages 43 were cancelled
  or replaced and 50 had expired, so 7 alerts were active;
* what that run showed and the plugin got wrong (all fixed in 0.1.1): the level `TEST` was not known, and the same
  recall published again under a new number was shown twice.

**Checked against the sources, but not run:**

* the Home Assistant integration (its level table, test levels, parameter names, handling of expiry and references);
* the Domoticz plugin framework as described in its documentation: `Used=1`, the unit of a Custom Sensor, the
  TypeNames `Text`, `Alert` and `Switch`, `SuppressTriggers`, devices stored as `<hardware name> - <name>`, new devices
  refused while *Accept new Hardware Devices* is off.

**Not verified:**

* **more of the live feed.** The machine this was written on could not reach data.public.lu; the feed was looked at
  once, on one day. Not seen: a level other than the five above, a status other than `Actual`, an alert with a polygon
  or circle, a message in a language other than the ones asked for, a long-lasting incident. **Run
  `python3 -m lu_alert` on your host** and compare the output with the official app.
* **a real Domoticz, for long.** It has run in the author's Domoticz 2026.4 since 2026-11-04: it starts, reads the feed,
  creates its devices and shows the alerts. Not known: weeks of running, other Domoticz and Python versions, how a
  long text looks on other skins, and **why Domoticz restarted when the hardware was stopped**
  ([issue #1](https://github.com/janreimen/Domoticz-LUAlert/issues/1)). The log of that report shows the plugin
  stopping cleanly and systemd then asking for the restart; the plugin starts and stops no process, but that is
  not yet an explanation. The test stub follows the documentation of Domoticz, not its source.
* **the level `D`** ([see above](#the-level-d)): never seen in the feed.
* **the licence of the data**, which is given on the dataset page, and **the licence of the integration this follows**
  (its repository has none; see [NOTICE](NOTICE)).
* **Domoticz versions and Python versions other than** the ones the tests run on (Python 3.9 to 3.13 in CI; 3.7
  compatibility is checked statically).

Reports from real installations, also "it works on my setup", are very welcome: [open an issue](https://github.com/janreimen/Domoticz-LUAlert/issues).
A saved real message (`python3 -m lu_alert --json`, without your location) is the best bug report.

## Development

```sh
git clone https://github.com/janreimen/Domoticz-LUAlert.git
cd Domoticz-LUAlert
make test            # python3 -m unittest discover -s tests
make check           # tests + flake8 + shellcheck + Python 3.7 compatibility (vermin) + generated docs up to date
make package         # dist/Domoticz-LUAlert-<version>.tar.gz
```

Rules, how to add a device and how to prepare a release: [CONTRIBUTING.md](CONTRIBUTING.md) and
[checklist.md](checklist.md). Planned work: [ROADMAP.md](ROADMAP.md). Security notes: [SECURITY.md](SECURITY.md).
Accessibility: [ACCESSIBILITY.md](ACCESSIBILITY.md). Code of conduct: [.github/CODE_OF_CONDUCT.md](.github/CODE_OF_CONDUCT.md).

## Credits

* The idea, the data source and the mapping of the LU-Alert levels: the Home Assistant integration
  [Lux-Alert-HACS-integration](https://github.com/koosoli/Lux-Alert-HACS-integration) by koosoli.
* The alerts: LU-Alert, Government of the Grand Duchy of Luxembourg, published on [data.public.lu](https://data.public.lu/).
* The Domoticz plugin: Jan Reimen.

## License

[MIT License](LICENSE); see [NOTICE](NOTICE) for the origin of the idea and the open question about the licence of the
integration this follows.
