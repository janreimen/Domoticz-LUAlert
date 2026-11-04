"""Domoticz-LUAlert: the official LU-Alert warnings of Luxembourg as native Domoticz devices.

Package layout (each module has exactly one job):

    config.py       plugin settings (parsed and validated from the Domoticz ``Parameters`` and the plugin-local .env)
    constants.py    device model (unit numbers, types), severity tables, defaults, timings
    logger.py       four-level logger; the only place that decides what reaches the Domoticz log
    util.py         small helpers
    model.py        plain data objects handed between the layers (CAP messages, active alerts, snapshots)
    cap.py          parser for CAP 1.2 / CAP-LU messages (standard library only, no Domoticz)
    geo.py          point-in-polygon and circle tests in pure Python (no shapely)
    api.py          HTTP client for the data.public.lu dataset and its alert files (standard library only)
    feed.py         which alert files to read, what is cached, concurrent downloads
    alerts.py       from CAP messages to the list of active alerts (cancel, expiry, severity, filters)
    devices.py      the ONLY module that talks to the Domoticz device API
    controller.py   poll scheduling in a background thread, error policy, logging of new and ended alerts
    cli.py          ``python3 -m lu_alert``: the same engine without Domoticz

``plugin.py`` is thin glue and the only module that imports ``Domoticz``.
"""

__version__ = "0.1.2"
