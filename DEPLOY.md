# Deploying Domoticz-LU-Alert

The plugin is a plain directory (`plugin.py` + the `lu_alert/` package) that has to sit in Domoticz' `plugins/`
directory. Nothing is compiled and no Python package is installed. This page covers the ways to get it there, how
to verify the result, and how to update, roll back and remove it.

## 0. Prerequisites

| Where | What |
|---|---|
| Domoticz host | Domoticz with Python plugin support, Python 3.7 or newer |
| Network | the Domoticz host can reach `https://data.public.lu` (port 443), directly or through a proxy |
| Optional | an `openssl`-capable Python with the system's certificate store (every normal installation has it) |

Quick check from the Domoticz host. It reads the live feed with the same code as the plugin and prints what the
plugin would show (an empty list is normal when no alert is active):

```sh
cd Domoticz-LU-Alert && python3 -m lu_alert
```

Exit status 0 = the feed was read, 2 = it could not be read (the message says why), 1 = a wrong option. If Domoticz
runs in a **container**, run the check inside it; a host-side test does not prove that the container can reach the
portal. A Python that does not know the certificate authority of the portal needs `SSL_CERT_FILE` (in the
environment of the Domoticz service) pointing to a CA bundle.

## 1. `deploy.sh` (recommended)

Run it from a checkout (or unpacked archive) of this repository.

```sh
./deploy.sh --dry-run                               # show what would happen on this machine
./deploy.sh                                         # install on this machine
./deploy.sh --host jan@rpi4office                   # install on another machine over SSH
./deploy.sh --host jan@rpi4office --rollback        # back to the previous version
```

Or through make: `make deploy HOST=jan@rpi4office`, `make deploy-dry`, `make rollback HOST=...`.

What it does on the target:

1. checks that `python3` is 3.7 or newer
2. **parses the new files before anything is touched**: a copy that does not compile on the target's Python never
   replaces the working installation
3. picks `sudo` only if the plugin directory is not writable for the SSH user (needs **passwordless** sudo then;
   otherwise log in as the Domoticz user or root)
4. backs up the installed copy to `~/domoticz-plugin-backups/Domoticz-LU-Alert-<version>-<time>.tar.gz`
   and keeps the newest 3. The backup is deliberately **outside** the plugins directory: a second copy of `plugin.py`
   in there would be loaded by Domoticz as a duplicate plugin
5. replaces `plugin.py`, `lu_alert/` and the documentation files. Other files you put in that directory, **your
   `.env` among them**, are left alone
6. gives the directory back to its previous owner (for example `domoticz:domoticz`)
7. restarts the `domoticz` systemd service

Nothing is changed when a step before the copy fails (for instance when the backup directory is not writable).

| Option | Default | Meaning |
|---|---|---|
| `--host [USER@]HOST` | this machine | deploy over SSH |
| `--ssh-opts "OPTS"` | | extra `ssh` options, e.g. `"-p 2222 -i ~/.ssh/id_ed25519"` |
| `--dir PATH` | `/srv/domoticz/plugins/Domoticz-LU-Alert` | target directory |
| `--dry-run`, `-n` | | report only; the target is not changed |
| `--rollback` | | restore the newest backup |
| `--service NAME` | `domoticz` | systemd service to restart |
| `--restart-cmd CMD` | | run CMD on the target instead (init.d, docker restart, ...) |
| `--no-restart` | | do not restart Domoticz |
| `--backup-dir PATH` | `$HOME/domoticz-plugin-backups` | backup location on the target |
| `--keep N` | `3` | backups to keep |
| `-V`, `--version` | | print the version of this source tree |

Exit status: `0` success, `1` error (nothing was changed if it happened before the copy).

The script opens two SSH connections (upload, then run). Use key authentication, or `ControlMaster auto` in
`~/.ssh/config`, to avoid being asked twice.

## 2. By hand

```sh
cd /srv/domoticz/plugins
sudo cp -r /path/to/Domoticz-LU-Alert .                   # plugin.py and lu_alert/ must stay together
sudo chown -R domoticz:domoticz Domoticz-LU-Alert         # whatever user runs Domoticz
sudo systemctl restart domoticz
```

Or with git, which makes updates a `git pull`:

```sh
cd /srv/domoticz/plugins
git clone https://github.com/janreimen/Domoticz-LU-Alert.git
# later:
cd Domoticz-LU-Alert && git pull && sudo systemctl restart domoticz
```

The directory name does not matter to Domoticz; the plugin is identified by the `key` in the manifest (`LUAlert`).
Use one directory per plugin: do not leave an old copy, a `.bak` folder or an unpacked archive next to it (Domoticz
loads every `plugin.py` it finds one level below `plugins/`).

## 3. Add the hardware

1. *Setup > Hardware*, type **LU-Alert Luxembourg**, name it (for example `LU-Alert`).
2. Nothing is required. Choose the language of the alert texts; for the location filter fill in *Home location*
   (or leave it empty to use the location set in Domoticz).
3. *Add*. The log shows `LU-Alert Luxembourg <version> starting ...` and, after the first poll, `Connected to the
   LU-Alert feed ...`, and the 18 devices are created (units 1-10, 11-13, 21-25).

All fields are explained in the [README](README.md#settings). Technical settings go into a `.env` file next to
`plugin.py` (copy `.env.sample`); they take effect when the hardware is restarted.

**No devices appear?** Domoticz only accepts new devices from plugins while *Setup > Settings > System > Accept new
Hardware Devices* is on. The plugin says so once in the log (`Domoticz did not create the device ...`) and asks again
every five minutes: switch the setting on and the devices appear without a restart.

## 4. Verify

In the Domoticz log (*Setup > Log*), with *Debug* at *Basic* for the first run:

* `LU-Alert Luxembourg X.Y.Z starting (update every 300 s, ...)`: the plugin started with the settings you expect
* `Connected to the LU-Alert feed: N alert files, M message(s) read`: the first poll worked (within about ten seconds
  of the start, at the next heartbeat)
* `No active LU-Alert alerts`, or one line per active alert (`Active alert: [Severe] ...`)
* the devices (*Setup > Devices*) have values, `LU-Alert Status` is On, *Feed Info* says `OK ...`

If something is wrong, set *Debug* to *Verbose*, reload the hardware and read the log; the
[README troubleshooting table](README.md#troubleshooting) explains the messages. Check the text before you post it.

## 5. Update, roll back, remove

* **Update:** run `deploy.sh` again (or `git pull`) and restart Domoticz. Devices are matched by their unit, so
  existing devices, their names, history, scenes and schedules are kept. Your `.env` stays.
* **Roll back:** `./deploy.sh [--host ...] --rollback`, or unpack the newest archive from the backup directory
  over the plugin directory.
* **Remove:** delete the hardware in *Setup > Hardware* (this removes its devices), delete the plugin directory,
  restart Domoticz.

## 6. Troubleshooting a deployment

| Symptom | Cause / fix |
|---|---|
| Hardware type "LU-Alert Luxembourg" is not in the list | Domoticz was not restarted, the directory is not directly below `plugins/`, or `plugin.py` is not readable by the Domoticz user. See the Domoticz log at start-up |
| `ModuleNotFoundError: No module named 'lu_alert'` | the `lu_alert/` directory is missing or not next to `plugin.py` (copied only `plugin.py`) |
| Hardware added, but no devices | *Setup > Settings > System > Accept new Hardware Devices* is off (see the log line `Domoticz did not create the device ...`). Switch it on, wait up to five minutes |
| Two hardware types / duplicate plugin errors | a second copy of the plugin sits in `plugins/` (backup folder, old version): remove it |
| The old behaviour is still there after an update | Domoticz keeps the old modules in memory: restart Domoticz, a hardware reload is not enough when a module was added or renamed |
| A change in `.env` has no effect | the file is read when the hardware starts: restart the hardware. A variable of the same name in the Domoticz service's environment wins over the file |
| `deploy.sh`: `not writable ... sudo needs a password` | log in as the Domoticz user or root, or allow passwordless sudo for the SSH user |
| `deploy.sh`: `the new files do not parse` | the target's Python is older than the code needs; the installation was not touched |
