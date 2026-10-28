# Contributing

Thanks for helping! Changes are made through **pull requests**; the `main` branch is protected and
cannot be pushed to directly.

1. Fork the repository and create a branch.
2. Make your change. Keep it focused; one topic per pull request.
3. Open a pull request against `main` and fill in the template. A maintainer reviews and merges it.

## Guidelines

- `custom_components/dji_power/core/` is framework-agnostic: it must not import Home Assistant.
  Home Assistant specific code lives next to it (`config_flow.py`, `coordinator.py`, `ble.py`, …).
- Update the translations in `strings.json`, `translations/en.json` and `translations/nl.json` when you
  change user-facing texts.
- **Never post tokens, pairing keys or serial numbers** in issues, pull requests or logs. Redact them first.
- The maintainer could only test on their own DJI Power 1000 Mini. Reports and fixes for other models are
  very welcome; please say which model and connection mode (cloud / Bluetooth) you used.

## Reporting a problem

Open an issue with your Home Assistant version, the connection mode, and the relevant log lines
(enable debug logging for `custom_components.dji_power`).

## License

By contributing you agree that your contribution is licensed under the
[Apache License 2.0](LICENSE), the same license as the rest of the project.
