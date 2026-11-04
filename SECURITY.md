# Security

## Scope

The plugin only **reads**: it downloads the public LU-Alert messages from data.public.lu and shows them as Domoticz
devices. It has no account, no password and no token, it sends nothing about you to anyone, and it cannot switch,
create or change anything outside Domoticz. It runs inside Domoticz as the Domoticz user, makes HTTPS requests to
the data portal, starts no processes and uses only the Python standard library.

## Things to know

| Topic | Details | What to do |
|---|---|---|
| **Your home location** | The location filter needs your home (the *Home location* field, or the location set in Domoticz). It is used only inside the plugin to test whether an alert area contains it, is **never sent anywhere**, and is **never written to the log** at any level: the logger replaces it by `<masked>` even when a message would contain it by accident | Nothing to do. If you post a log in an issue, look it over anyway |
| **Watchlist and allergens** | Your keywords stay in the Domoticz hardware settings. At Debug level the log names the alerts that matched | Review a log before you post it |
| **https only, certificates always verified** | The dataset URL must be `https://` (a `.env` value that is not is refused), a redirect to a URL that is not https is refused, and there is no setting that switches certificate verification off | Do not work around a TLS error: fix the certificate store of the Domoticz host (`SSL_CERT_FILE` of the service) |
| **File addresses are not trusted** | The dataset description lists the address of every alert file. The plugin requests a file only from the host of the dataset or from another host of its domain (`data.public.lu` -> `*.public.lu`), or from a host you allow in `.env` (`LU_ALLOWED_HOSTS`); a redirect to any other host is refused. A manipulated description can therefore not point Domoticz at a device in your own network | Add a host to `LU_ALLOWED_HOSTS` only when the portal really moved its files |
| **Hostile XML** | A file with a `DOCTYPE` or an entity declaration is refused before it is parsed (XML bomb defence). An answer is limited to 16 MB (the description) or 2 MB (one message), **also after gzip decompression**, so a small compressed answer cannot fill the memory. A file that is not valid CAP is ignored, once, and does not stop the others | Nothing to do |
| **Text from the feed** | Alert texts are plain text in Domoticz device values (cut to 200 characters); HTML in a description is turned into text, never kept. Domoticz may show device text in its web interface: the plugin never writes markup | Nothing to do |
| **Proxy** | A proxy in the environment of the Domoticz service (`HTTPS_PROXY`) is used like for any Python program. A password inside a proxy URL is registered with the logger and masked | Prefer a proxy without credentials in the URL |
| **A failing feed** | The plugin never clears an alert because the feed cannot be read: it keeps the last known alerts and says so in *Feed Info*. An alert still ends at its end time | Use *LU-Alert Status* to be told when the feed is down |
| **Not a warning system** | The plugin shows what the portal publishes, with a delay of up to the update interval plus the portal's own delay. It is **not** a replacement for the official LU-Alert on your phone, sirens or the radio | Install the official app and the cell broadcast; use the plugin for automation, not for your safety |
| **`deploy.sh`** | Runs commands on the target through SSH (`bash -s`), uses `sudo -n` only if the plugin directory is not writable, and never changes anything outside the plugin directory, the backup directory and (restart) the Domoticz service | Review the script before running it; use SSH keys |

## Hardening checklist

1. Keep the Domoticz host's certificate store up to date.
2. Leave `LU_ALLOWED_HOSTS` empty unless the log says a host of the portal is blocked.
3. Keep the plugin directory writable only for the user that deploys it.
4. Run `python3 -m lu_alert` once after an update of the host's Python or its certificates.

## Supported versions

Only the latest release receives fixes.

## Reporting a vulnerability

Please do **not** open a public issue for a security problem. Use GitHub's private vulnerability reporting
(*Security* tab of the repository > *Report a vulnerability*). Include the plugin version, what you observed and, if
possible, how to reproduce it. Do not include your home location or other private data.
