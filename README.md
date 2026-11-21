# Light Multiplexer

A Home Assistant helper that presents one physical RGB-capable light as a white main light and one or more RGB signal lights. Each virtual light keeps its own desired state; the helper selects what the physical source displays.

This is experimental software targeting **Home Assistant Core 2026.11.0 or later**. Backend tests target 2026.11.0; other versions and physical hardware have not been verified. The configuration UI is available in English and German.

## Installation

### HACS

The repository includes `hacs.json` and the standard custom integration directory layout. Once the repository is public, add `https://github.com/Oderik/ha-light-multiplexer` as a custom repository of type **Integration** in HACS, then download Light Multiplexer. Inclusion in the default HACS catalog is not required. HACS installation is not available while this repository remains private.

Restart Home Assistant after installing or updating the integration's Python code. Reloading a helper applies configuration changes but does not reliably load changed Python modules.

### Manual installation

1. Copy `custom_components/light_multiplexer` into `/config/custom_components/light_multiplexer` on your Home Assistant installation.
2. Restart Home Assistant.
3. Go to **Settings → Devices & services → Helpers → Create helper** and select **Light Multiplexer**. Alternatively, use **Add integration**. Refresh the frontend if an old label appears.
4. Select a source light and the number of signals (one by default).

Initial setup sends no light command, so an already illuminated source stays on. The main light adopts its on/off state and brightness, with best-effort color-temperature initialization.

## Updating

Replace the integration directory and restart Home Assistant. Existing helpers, registered entity IDs, saved light states and configured timings are retained for updates within the 0.3 series. New main lights use an English `Main` name and `_main` entity ID suffix; existing registry IDs are not renamed. User-assigned names are preserved.

In 0.3.2 the pulse effect is named `Pulse`. This is a breaking change: the previous effect identifier is no longer supported. Unsupported saved effects reset to `off` (steady). Select `Pulse` again after updating, and update automations that send or compare the effect attribute.

For the old **Dual Light** integration, remove its helper through Devices & services, then remove `/config/custom_components/dual_light` before installing Light Multiplexer. Deleting individual entities does not remove the helper. Removing the old helper deletes its saved states and restores source visibility if it hid the source. Migration from that earlier integration is not included.

## Light behavior

The main light exposes color temperature and brightness. Signal lights expose color, brightness and two effects: `off` (steady) and `Pulse`. Choose colors through the normal light controls. On/off state, brightness, color and effect are saved independently for each light.

When the main light is on, a displayed signal uses `max(signal brightness, main brightness)`. Otherwise it uses its own brightness. The main light always uses its own brightness. This output calculation does not modify the saved brightness values.

Display priority is:

1. The currently displayed pulse.
2. The enabled steady signal with the highest signal number.
3. The main light, if enabled.
4. Off.

Signal numbers determine steady-signal priority, regardless of names or activation order. Custom ordering and separate priority fields are not implemented.

Pulsing signals rotate with a pause after each signal. The pause displays the winning steady signal, the main light, or off according to the same priority rules. A newly enabled pulse is queued next; multiple newcomers are handled in arrival order. Repeated turn-on commands do not reorder an already active signal. Turning off the currently displayed signal interrupts it immediately with transition 0 and begins the pause. Changing a steady signal to `Pulse` adds it to the rotation. Rotation starts anew after a restart.

| Setting | Default |
| --- | --- |
| Hold duration | 1 second |
| Pause duration | 2 seconds |
| Transition in each direction | 0.25 seconds |

Transitions are additional to hold and pause durations, so a default cycle takes 3.5 seconds. Set transition to 0 for blinking. Sources without transition support switch directly. Ordinary commands forward an explicit transition; otherwise the source's default applies. Actual transition behavior depends on the source integration and hardware. The source integration handles color conversions; native source effects and flash are not exposed.

Existing installations retain their configured timings. Change these through the helper options if needed. JSON uses a decimal point (`0.25`); the localized frontend may display a decimal comma. The transition field accepts hundredths of a second.

## Configuration and entities

All virtual lights belong to one configuration entry. Navigate from an entity's information to its integration and open **Configure/Options**. The exact link and label depend on the Home Assistant frontend. The options menu contains source/visibility, signal count and pulse timing. Changes reload this helper.

Names and entity IDs can be edited through Home Assistant's entity settings. Initial names and IDs are derived from the source. Virtual entities are attached to the source's device, if present, without taking ownership of that device.

Reducing the signal count requires confirmation and removes the highest-numbered signals and their saved states. Increasing the count creates disabled signals. Switching sources recalculates capabilities and device association while preserving registered virtual entity IDs. The old source stays at its last output and becomes visible again if hidden by this helper; the new source receives the saved virtual desired states. Sources must be enabled RGB-capable lights. Multiplexer entities cannot be selected as sources.

Hiding the source does not prevent direct service calls. Update existing automations and voice-assistant exposure to use the virtual entities. Direct source changes are not translated back into virtual desired states. When an unavailable source returns, the helper restores its desired output. Source entity-ID changes are tracked through the entity registry.

## Testing

Run isolated model and controller tests:

```sh
python -m unittest discover -s tests -v
python -m compileall -q custom_components
```

For backend integration tests, use a separate Python 3.14 environment with `homeassistant==2026.11.0` installed:

```sh
python checks/ha_smoke.py
python checks/ha_smoke.py --rgb-only
```

These tests use temporary Home Assistant configurations and simulated lights. They cover setup without an initial light command, brightness arbitration, real rotation timers, interruptions, concurrent partial updates, options, signal removal, persistence on helper reload, device association, source replacement and renaming, availability recovery, and visibility restoration on removal. They do not test physical hardware, frontend navigation, or a full Home Assistant process restart.

On a real installation, verify white-light restoration after signals, brightness changes with the main light on/off, rotation with multiple pulses, newcomer order, immediate cancellation, persistence across a restart, and entity association after option changes.

## Known issue and diagnostics

[Issue #1](https://github.com/Oderik/ha-light-multiplexer/issues/1) tracks a report that the main light is skipped during pauses when its brightness is higher than a signal's. Automated tests have not reproduced this. They verify white commands with the main light's brightness for higher, equal and lower relative brightness values. An active steady signal legitimately takes priority during a pause. No hardware-specific workaround or confirmed fix is claimed.

Enable debug logging for the integration, capture a few cycles, and disable it again. `Applying output` records the phase, current pulse and command sent to the source; `Unchanged output` records deliberately suppressed identical outputs. Logs may include entity IDs: review them before sharing.

## License

[MIT](LICENSE) — Copyright (c) 2026 [Oderik](https://github.com/Oderik).
