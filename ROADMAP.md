# Roadmap

Planned work, roughly in order. Nothing here is a promise; it is what would make the plugin better.

## First: check against reality

The plugin was developed without access to data.public.lu (see [what is verified](README.md#what-is-verified-and-what-is-not)).
Before anything else:

- [x] Run `python3 -m lu_alert` against the live feed (done 2026-11-04 on a Raspberry Pi: 100 files, 7 active alerts;
      found the level `TEST` and the re-published duplicates, fixed in 0.1.1)
- [ ] Compare that output with the official app
- [ ] Save a real CAP message (and, when one happens, a real Cancel / Update pair) as a test fixture
- [ ] Settle what the level `D` really is (not seen in the live feed yet) (see [docs/LU-ALERT-DATA.md](docs/LU-ALERT-DATA.md#the-level-d)) and change the
      default of `LU_TEST_LEVELS` if needed
- [ ] Confirm the licence situation of the integration this plugin follows (see [NOTICE](NOTICE))
- [ ] Run it on Domoticz for a week; look at the log, the devices and the memory use
- [ ] Add the Domoticz versions it was tried with to the README

## 0.2

- [ ] Geocode matching (the CAP `geocode` of an area) as another way to decide "local", if the feed carries
      commune codes that are easier to match than polygons
- [ ] A text device with the instruction of the most severe alert, for scripts that speak it
- [ ] Optional: the alert area as a short text (the commune names) in the *Alert n* devices

## Later

- [ ] A dzVents example script and a notification recipe in the README, tried on a real installation
- [ ] Optional per-category switches (for example *Health Alert Active*)
- [ ] Listing the plugin in a plugin manager

## Not planned

- Sending anything to the feed or to anyone: the plugin only reads.
- A replacement for the official LU-Alert: the plugin is for automation next to it, not instead of it.
- Python packages: the plugin stays standard-library only.
