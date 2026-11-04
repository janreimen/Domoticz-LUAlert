# Accessibility

## Commitment

Domoticz-LUAlert aims to be usable and understandable by as many people as practical. The project will consider accessibility when updating documentation, issue templates, examples, and any user-facing text. Reports and constructive suggestions about accessibility are welcome.

## Supported environments

This is a Python plugin for Domoticz that shows the LU-Alert warnings of the Luxembourg government as Domoticz devices. Accessibility depends on the surrounding software and environment, including:

- The Domoticz web interface and the browser or client used to access it.
- The operating system, Python runtime, and Domoticz version running the plugin.
- The devices and sensor types available in the installed Domoticz environment.
- The channels you use for the notifications that you build on the plugin's switches (push messages, e-mail, a text-to-speech script, a light).

The project does not independently provide or certify an accessible user interface. Please consult the documentation of Domoticz and your operating system for their accessibility features and supported environments.

## Alerts and accessibility

The plugin shows the **severity of an alert as a colour** (green, yellow, orange, red) and, in every case, also as **text**: each *Alert* device and *Highest Severity* carry a text such as `[Severe] Storm warning for the whole country - until 2026-11-02 14:00`, and the switches and counters give the same information as On/Off and numbers. Nothing is shown by colour alone. The texts are plain text in the language you choose (English, German, French or Luxembourgish, as far as the feed provides it).

The plugin is **not a warning system** and must not be the only way you are warned: the official LU-Alert reaches people through cell broadcast, sirens and the app, and it is designed to be accessible to people who cannot see or hear a particular channel. Use the plugin to add your own channels (a spoken message, a flashing light, a vibrating device) for people for whom the usual ones are not enough, and keep the official ones.

## Current limitations

- The plugin provides its data through Domoticz devices; it is not a standalone graphical application.
- Accessibility of device labels, charts, tables, controls, and status messages is largely determined by Domoticz and the client used to view it.
- The project has not completed a formal accessibility audit or conformance assessment, so no WCAG conformance level is claimed.
- Problems are reported in the Domoticz log; the clarity and accessibility of those messages may vary by environment. The plugin writes each message as plain text, one problem per line, with a hint about what to check.

## Reporting an accessibility barrier

If you encounter a barrier using the plugin or its documentation, please open an issue:
https://github.com/janreimen/Domoticz-LUAlert/issues

Choose a bug report or feature request template as appropriate and include:

- The page, device, setting, or documentation section involved.
- What you were trying to do and what happened.
- Your Domoticz version, plugin version, operating system, and browser/client where relevant.
- Any workaround that helped, if one is available.

Please do not include your home location or other sensitive information. If the barrier involves private or sensitive details, contact the maintainer through GitHub instead of posting those details publicly.

## Improvements

Accessibility feedback will be considered alongside other project issues and contributions. Improvements may be made as project resources and technical constraints allow.
