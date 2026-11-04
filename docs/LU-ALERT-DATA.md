# LU-Alert data and rules

How the plugin gets the alerts and decides what to show. This is the reference behind the README; the code is in
`lu_alert/api.py`, `feed.py`, `cap.py` and `alerts.py`.

> **Not verified against the live feed.** The machine this plugin was developed on could not reach data.public.lu,
> so the message shape below follows the CAP-LU profile and the Home Assistant integration this plugin is based on,
> not a message downloaded from the portal. Run `python3 -m lu_alert` on your Domoticz host first: it reads the live
> feed with the same code and shows what the plugin would show (see [Checking the feed](#checking-the-feed)).

## Where the alerts come from

The Luxembourg government publishes every LU-Alert message as a [CAP](https://docs.oasis-open.org/emergency/cap/v1.2/CAP-v1.2.html)
XML file in the dataset *Alertes du système LU-Alert* on [data.public.lu](https://data.public.lu/):

```
https://data.public.lu/api/1/datasets/67aca67bcaea3ae62308114f/
```

The answer is a JSON document with a `resources` list. Each entry that has `format: xml` (or an XML mime type) is one
message: its `url`, `last_modified` and `checksum` are what the plugin uses. The list is sorted by date, newest
first, and cut to the newest `LU_MAX_RESOURCES` files (default 100).

* **One request per poll for the description, one per *new* file.** A published file never changes (a change of an
  alert is a new message), so a file is downloaded once and kept in memory under its URL and version. Only the first
  poll after a start reads many files.
* The description request is conditional (`ETag`, `If-Modified-Since`) when the server supports it, and answers are
  accepted gzip-compressed.
* A file that is not valid CAP, uses a DOCTYPE, or is too large (2 MB, also after decompression) is **ignored and
  not requested again** for that version of the file; one such file never stops the others. A file that could not be
  downloaded is tried again at the next poll.

## What a message looks like

A CAP-LU message has one `<info>` block **per language and per channel** (Mobile-App, Siren, Cell-Broadcast, SMS,
...). The plugin reads from each block: language, categories, event, severity, `effective`/`expires`, headline,
description (HTML is turned into plain text), instruction, web link, parameters and areas (`areaDesc`, `polygon`,
`circle`).

* **The text** shown is taken from the block in your language (English, German, French, Luxembourgish: setting
  *Language*), else English, else any block; among those the **fullest channel**: app and website before
  cell-broadcast, SMS and e-mail, and a siren block (which has no text for people) last.
* **The level** is the value of the parameter whose name ends in `cb-eu-level` or `cb-lu-level` (the feed writes
  the profile prefix `urn:oasis:names:tc:emergency:cap:1.2:profile:cap-lu:1.0:` before it; the part after the last
  `:` counts). It may be in any block.

## Severity

The severity of an alert is the one of its LU-Alert level. Only a message without a known level falls back to the
CAP `severity` field (Extreme, Severe, Moderate, Minor, Unknown). Levels are compared without regard to case.

| Level in the feed | Severity | Colour |
|---|---|---|
| `N1`, `L1`, `LU-Alert Level 1`, `ALERT_LVL_1` | Extreme | red |
| `D` | *test message by default*; Extreme when taken out of `LU_TEST_LEVELS` | (grey / red) |
| `N2`, `L2`, `LU-Alert Level 2`, `ALERT_LVL_2` | Severe | red |
| `A`, `LU-Alert Amber` | Moderate | orange |
| `N3`, `L3`, `LU-Alert Level 3`, `ALERT_LVL_3` | Minor | yellow |
| `I`, `LU-Alert Level 4`, `ALERT_LVL_4` | Information | green |
| `T`, `LU-Alert Test`, `LU-Alert Exercise` | Test | grey |

The levels come from the Home Assistant integration (`LEVEL_TO_SEVERITY`) and from the levels named on
[lu-alert.lu](https://lu-alert.lu/); an unknown level is kept as it is, shown in the log, and does not decide the
severity.

### The level D

The Home Assistant integration lists `D` both as an Extreme level and as a **test level**, so in practice it drops
messages with level D. The plugin does the same by default, because a monthly test that turns every Domoticz light
red would be worse than useless. **This is a decision made without a look at the live feed**, and wrongly hiding a
real alert is the worse error, so:

* every test message that is left out is written to the Domoticz log **once**, with its level and headline
  (`Test message ignored (D): ...`), so a real alert taken for a test is not silent;
* if you find that `D` is a real alert level, remove it from `LU_TEST_LEVELS` in `.env` (see `.env.sample`); it is
  then an Extreme alert.

## What is shown

The rules in the order the plugin applies them (`lu_alert/alerts.py`):

1. **Replies are not alerts.** `Ack` and `Error` messages are dropped. Of several messages with the same
   identifier the newest counts.
2. **Cancel and Update.** A `Cancel` message ends the alert it names in `<references>`
   (`sender,identifier,sent`), and an `Update` replaces the alert it references. The referenced message is dropped;
   the Cancel itself is never shown. A reference to an *older* version does not end a newer one.
3. **Expiry.** An alert ends when its **latest** `expires` over all its blocks has passed. The plugin also checks
   this between polls (every heartbeat), so an alert ends on time even while the feed cannot be reached.
4. **No end time.** An alert without any `expires` is shown for `LU_STALE_DAYS` (default 10) days after it was sent.
5. **Test messages.** A CAP `status` other than `Actual` (Test, Exercise, System, Draft), the levels `T`, `LU-Alert
   Test`, `LU-Alert Exercise` and everything in `LU_TEST_LEVELS` are left out, unless `LU_SHOW_TEST_ALERTS=1` (they
   are then shown as severity *Test*, grey, below everything else).
6. **Categories.** Nothing is dropped because of its category unless you list it in `LU_IGNORE_CATEGORIES`; an
   alert is dropped only when *all* its categories are listed.
7. **Minimum severity** (hardware setting). *All alerts* shows even those without a severity.
8. **Location.** With the location filter *Only local alerts*, an alert whose area does not contain your home is
   dropped; an alert **without any geometry** (no polygon or circle) is kept, because "no area given" more likely
   means "everywhere". With *Flag local alerts* nothing is dropped and the switch *Local Alert Active* shows
   whether one of the active alerts contains your home.
9. **Watchlist and allergens.** A keyword matches when it occurs (without regard to case) in the headline, event,
   description or instruction of any block, in any language.
10. **Order.** Most severe first, newest first within a severity.

Every drop has a reason, and the totals are in the verbose log (`Left out: expired 3, test 1`).

### Location

Your home is the setting *Home location* (`latitude;longitude`), or the location set in Domoticz
(*Setup > Settings > System*) when that is empty. It is used only inside the plugin: it is **never written to the
log**, at no log level, and registered with the logger so that no message can contain it by accident.

A polygon is tested with the ray-casting rule on latitude/longitude as plane coordinates, which is exact enough
for areas the size of a municipality; a circle (`lat,lon radius-in-km`) with the haversine distance. The answer is
*inside*, *outside* or *no geometry*.

## Differences from the Home Assistant integration

| | Home Assistant integration | This plugin |
|---|---|---|
| Polygons | `shapely` | pure Python (ray casting), no packages |
| Level names | exact match | without regard to case |
| Status `Test`, `Exercise`, `System`, `Draft` | shown | left out like tests |
| Ignored tests | silent | named once in the log |
| Category filter | none | optional, `LU_IGNORE_CATEGORIES` |
| Files | read at every update | read once, cached by URL and version |
| Files from other hosts | requested as the dataset lists them | only from the portal's own domain, or `LU_ALLOWED_HOSTS` |

## Checking the feed

```sh
cd /srv/domoticz/plugins/Domoticz-LU-Alert
python3 -m lu_alert                       # the live feed, all alerts
python3 -m lu_alert --json                # the same as JSON, for a bug report
python3 -m lu_alert --xml saved.xml       # a CAP file from disk
python3 -m lu_alert --show-test           # including test messages
```

The exit status is 0 when it worked, 1 for wrong options or an unreadable file, 2 when the feed cannot be read.
