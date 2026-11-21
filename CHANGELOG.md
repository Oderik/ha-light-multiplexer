# Changelog

## 0.3.3 — Optional source entity ID takeover

New helpers can give the main light the source’s original entity ID. Setup previews the physical source’s new ID. The option is disabled by default. Removing the helper restores the original ID when it is free and the source still uses the assigned alias.

## 0.3.2 — English defaults and HACS metadata

- Translate the README, changelog, default configuration strings and English localization; retain the German localization.
- Use English names and suggested entity IDs for newly created main lights. Existing registered entity IDs and user-assigned names remain unchanged.
- Rename the pulse effect to `Pulse` (breaking change). Unsupported saved effects reset to `off`; unsupported effect commands are rejected. Select `Pulse` again and update automations that send or compare effect names.
- Replace room-specific test fixture names with generic names.
- Add `hacs.json` and documentation, issue tracker and code owner metadata.
- Add regression coverage for resetting unsupported saved effects to steady mode.

The reported brightness-dependent pause issue remains open. These changes do not claim to fix it.

## 0.3.1 — Timing defaults and targeted diagnostics

- Set defaults to a 1-second hold, 2-second pause and 0.25-second transition. Preserve existing user settings.
- Share timing constants between setup and controller; accept transition input in 0.01-second increments.
- Add debug logging of output phases and actual light commands.
- Expand the brightness matrix to cover the main light being brighter, equally bright, dimmer, and between two signals. Verify white output during pauses without changing saved signal brightness.
- Update simulated sources to apply brightness and color mode from commands. Both Home Assistant backend test variants inspect actual pause commands.

**Open:** The reported missing main-light output could not be reproduced. This version adds diagnostics, not a confirmed fix. Further investigation requires the source model/integration and potentially debug logs.

Validation at the time: 21 regression tests and backend tests with Home Assistant Core 2026.11.0 for RGB and RGB+white sources. No hardware testing.

## 0.3.0 — Test version overhaul

- Standardize the name, domain, translations and installation directory as Light Multiplexer.
- Split setup into source selection and signal/pulse timing, including transition settings during setup.
- Add shared options for source, signal count and timing; require confirmation before removing signals.
- Preserve unrelated desired values during concurrent partial light commands.
- Fully stop rotation when its last signal is disabled; start immediately on a new activation.
- Interrupt a pulse with transition 0 and no additional transition wait.
- Associate virtual entities with the source device without changing its ownership or lifecycle.
- Preserve virtual entity IDs and update device association when switching sources.
- Rebind the state listener when the source is renamed; restore desired output when connectivity returns.
- Send no source command during initial setup.

Validation at the time: 19 isolated model/controller regression tests, plus backend integration tests with Home Assistant Core 2026.11.0 / Python 3.14 for simulated RGB and RGB+white sources. Coverage included setup, initial state, brightness floors, rotation timers, cancellation and restart, concurrent partial commands, options and signal reduction, persistence on reload, device association, source replacement with stable IDs, source renaming, availability recovery, and visibility restoration on removal.

No physical-hardware or frontend tests. Persistence was tested through helper reload, not a full Home Assistant process restart. No migration from earlier versions.
