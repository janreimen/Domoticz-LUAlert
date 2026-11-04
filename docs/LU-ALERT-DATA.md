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
| `T`, `TEST`, `LU-Alert Test`, `LU-Alert Exercise` | Test | grey |

The levels `ALERT_LVL_1` to `ALERT_LVL_4` and `TEST` were **seen in the live feed**; the others come from the Home
Assistant integration (`LEVEL_TO_SEVERITY`) and from the levels named on [lu-alert.lu](https://lu-alert.lu/) and have
**not been seen**. An unknown level is kept as it is, named **once** in the Domoticz log (`Unknown LU-Alert level
'...'`), and does not decide the severity: the CAP `severity` of the message does.

### The level D

The Home Assistant integration lists `D` both as an Extreme level and as a **test level**, so in practice it drops
messages with level D. The plugin does the same by default, because a monthly test that turns every Domoticz light
red would be worse than useless. **`D` has not been seen in the live feed** (the test messages seen there carry
the level `TEST`), so this is a decision taken from the integration, and wrongly hiding a real alert is the worse
error, so:

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
5. **Test messages.** A CAP `status` other than `Actual` (Test, Exercise, System, Draft), the levels `T`, `TEST`,
   `LU-Alert Test`, `LU-Alert Exercise` and everything in `LU_TEST_LEVELS` are left out, unless `LU_SHOW_TEST_ALERTS=1` (they
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
11. **The same message twice.** The feed publishes a recall again as a *new* alert (own number, no reference to
    the first). Alerts with the same severity, headline, description, instruction, event, area **and end time** are
    shown once, the newest; anything that differs in one of these is kept as a separate alert.

Every drop has a reason, and the totals are in the verbose log (`Left out: expired 3, test 1`).

### Location

Your home is the setting *Home location* (`latitude;longitude`), or the location set in Domoticz
(*Setup > Settings > System*) when that is empty. It is used only inside the plugin: it is **never written to the
log**, at no log level, and registered with the logger so that no message can contain it by accident.

A polygon is tested with the ray-casting rule on latitude/longitude as plane coordinates, which is exact enough
for areas the size of a municipality; a circle (`lat,lon radius-in-km`) with the haversine distance. The answer is
*inside*, *outside* or *no geometry*.

## The text of an alert

* **Description and instruction** are plain text: tags are removed, line breaks become spaces, entities are decoded.
  The feed escapes some entities twice (a literal `&quot;` in the text), so they are decoded once more after the
  tags are gone. A Markdown link `[label](https://address)` becomes the label, plus the address when the label does
  not already say it.
* **On the devices** (*Highest Severity*, *Alert 1 ...*) the text is `[Minor] Headline - until 2026-11-06 16:14 |
  start of the description`, cut to the 200 characters a Domoticz text keeps. The headline and the end time come
  first and are never cut for the description; with less than 30 characters of room the description is left out, and
  a description that only repeats the headline is left out too. `LU_DEVICE_DESCRIPTION=0` in `.env` shows headline
  and end time only.
* **Why:** the headline is often the same for different alerts. The food recalls of the live feed have one headline
  (`Recall : Curly green cabbage sold in bulk`) for several shops, and only the description says which shop and which
  period.
* **In the log**, at the verbose level, the description of every new alert (up to 600 characters).

## Seen in the live feed

`python3 -m lu_alert` was run once on a Raspberry Pi against the live feed on **2026-11-04** (100 alert files listed,
100 read, 7 active alerts, no error). What the 100 messages showed:

| What | Seen |
|---|---|
| Levels | `ALERT_LVL_1` (1 message), `ALERT_LVL_2` (25), `ALERT_LVL_3` (68), `ALERT_LVL_4` (4), `TEST` (2) |
| Message types | `Alert` (75), `Update` (7), `Cancel` (18); the status of all of them was `Actual`, also of the `TEST` ones |
| Identifier | `LU-Alert.<epoch>.<number>.<revision>`, for example `LU-Alert.1789134319.4803.0` |
| Reference (Cancel, Update) | `[SENDER],identifier,sent`, for example `[ALVA],LU-Alert.1789134319.4803.0,2026-09-11T15:45:19+02:00`; the time zone of `sent` differs from the one of the message, the instant is the same |
| Content | almost only food recalls and allergen warnings; the area is *Grand-Duché du Luxembourg* |
| Duplicates | the same text is published again as a new alert, with its own number and no reference (three cabbage alerts with the same end time); see rule 11 |

**Not seen:** the level `D`, a level other than the five above, a status other than `Actual`, an alert with a
geometry, an alert in a language other than the ones the plugin asks for. The 100 files held 43 messages that are
cancelled or replaced and 50 that had expired, so a feed this size is mostly history; only 7 messages were active.

## Differences from the Home Assistant integration

| | Home Assistant integration | This plugin |
|---|---|---|
| Polygons | `shapely` | pure Python (ray casting), no packages |
| Level names | exact match | without regard to case |
| Status `Test`, `Exercise`, `System`, `Draft` | shown | left out like tests |
| Ignored tests | silent | named once in the log |
| Level the table does not know | silent | named once in the log, the CAP severity is used |
| Same message published twice | shown twice | shown once (rule 11) |
| Category filter | none | optional, `LU_IGNORE_CATEGORIES` |
| Files | read at every update | read once, cached by URL and version |
| Files from other hosts | requested as the dataset lists them | only from the portal's own domain, or `LU_ALLOWED_HOSTS` |

## Checking the feed

```sh
cd /srv/domoticz/plugins/Domoticz-LUAlert
python3 -m lu_alert                       # the live feed, all alerts
python3 -m lu_alert --json                # the same as JSON, for a bug report
python3 -m lu_alert --xml saved.xml       # a CAP file from disk
python3 -m lu_alert --show-test           # including test messages
```

The exit status is 0 when it worked, 1 for wrong options or an unreadable file, 2 when the feed cannot be read.

`--json` also lists the test messages that were left out (`ignored_tests`) and the levels the plugin does not know
(`unknown_levels`); the text output names the unknown levels at the end. Both are what to look at after a change of
the feed.
