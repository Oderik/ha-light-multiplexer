"""Regression scenarios for switching between white room light and a steady red signal."""

from homeassistant.components.light import ColorMode
from homeassistant.util.color import color_temperature_to_hs


async def check_steady_signal(hass, source, main_id, signal_id):
    """Exercise both switch orders with stored colors and brightness settings."""
    async def switch(entity_id, on, **attributes):
        await hass.services.async_call(
            "light", "turn_on" if on else "turn_off",
            {"entity_id": entity_id, **attributes}, blocking=True,
        )

    native_white = ColorMode.COLOR_TEMP in source.supported_color_modes

    for main_level, signal_level in ((255, 128), (128, 255), (128, 128)):
        await switch(main_id, True, brightness=main_level, color_temp_kelvin=3200)
        await switch(signal_id, True, brightness=signal_level, hs_color=[0, 100], effect="off")
        await switch(signal_id, False)
        await switch(main_id, False)
        previous_output = None

        async def step(entity_id, on, color, level):
            nonlocal previous_output
            before = len(source.calls)
            await switch(entity_id, on)
            context = (main_level, signal_level, entity_id, on, color, level)
            if previous_output != (color, level):
                assert len(source.calls) > before, ("missing source command", context)
            previous_output = (color, level)
            command, data = source.calls[-1]
            state = hass.states.get(source.entity_id)
            assert command == "on" and state.state == "on", context
            assert data["brightness"] == state.attributes["brightness"] == level, context
            if color == "white" and native_white:
                assert state.attributes["color_mode"] == ColorMode.COLOR_TEMP, context
                assert data["color_temp_kelvin"] == state.attributes["color_temp_kelvin"] == 3200, context
            else:
                expected = (0, 100) if color == "red" else color_temperature_to_hs(3200)
                assert state.attributes["color_mode"] == ColorMode.HS, context
                for actual in (data["hs_color"], state.attributes["hs_color"]):
                    assert all(abs(a - b) < 0.01 for a, b in zip(actual, expected, strict=True)), (context, actual, expected)

        peak = max(main_level, signal_level)
        await step(main_id, True, "white", main_level)
        await step(signal_id, True, "red", peak)
        await step(main_id, False, "red", signal_level)
        await step(main_id, True, "red", peak)
        await step(signal_id, False, "white", main_level)
