"""Set up and configure Light Multiplexer with HA selectors."""
import math
import probatio as vol

from homeassistant import config_entries
from homeassistant.components.light import LightEntityFeature
from homeassistant.core import callback
from homeassistant.helpers import entity_registry as er, selector

from .const import DEFAULT_HOLD, DEFAULT_PAUSE, DEFAULT_FADE

DOMAIN = "light_multiplexer"
DEFAULTS = {"hide_source": True, "count": 1, "hold": DEFAULT_HOLD, "pause": DEFAULT_PAUSE, "fade": DEFAULT_FADE}


def number(minimum, step):
    return selector.NumberSelector(selector.NumberSelectorConfig(min=minimum, step=step, mode=selector.NumberSelectorMode.BOX))


def source_schema(values):
    return vol.Schema({
        vol.Required("source", default=values.get("source", "")): selector.EntitySelector(selector.EntitySelectorConfig(domain="light")),
        vol.Required("hide_source", default=values.get("hide_source", True)): selector.BooleanSelector(),
    })


def settings_schema(hass, values, include_count=True):
    fields = {}
    if include_count:
        fields[vol.Required("count", default=values.get("count", 1))] = number(1, 1)
    fields[vol.Required("hold", default=values.get("hold", DEFAULT_HOLD))] = number(0.1, 0.1)
    fields[vol.Required("pause", default=values.get("pause", DEFAULT_PAUSE))] = number(0.1, 0.1)
    state = hass.states.get(values.get("source", ""))
    if state and state.attributes.get("supported_features", 0) & LightEntityFeature.TRANSITION:
        fields[vol.Required("fade", default=values.get("fade", DEFAULT_FADE))] = number(0, 0.01)
    return vol.Schema(fields)


def validate_numbers(values):
    for key, minimum in (("count", 1), ("hold", 0.1), ("pause", 0.1), ("fade", 0)):
        if key not in values:
            continue
        value = values[key]
        if not math.isfinite(value) or value < minimum:
            return "invalid_number"
        if key == "count" and value != int(value):
            return "invalid_number"
    if "count" in values:
        values["count"] = int(values["count"])
    return None


def validate_source(hass, values, own_entry=None):
    entity = er.async_get(hass).async_get(values["source"])
    state = hass.states.get(values["source"])
    if not entity or not state or state.state in ("unavailable", "unknown") or entity.platform in (DOMAIN, "dual_light") or entity.disabled_by:
        return "invalid_source"
    if not set(state.attributes.get("supported_color_modes", [])) & {"hs", "xy", "rgb", "rgbw", "rgbww"}:
        return "no_color"
    for domain in (DOMAIN, "dual_light"):
        for entry in hass.config_entries.async_entries(domain):
            if entry.entry_id != own_entry and entry.data.get("source_registry_id") == entity.id:
                return "already_configured"
    values["source_registry_id"] = entity.id
    return None


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            error = validate_source(self.hass, user_input)
            if error:
                errors["base"] = error
            else:
                self.values = {**DEFAULTS, **user_input}
                return await self.async_step_settings()
        return self.async_show_form(step_id="user", data_schema=source_schema(user_input or {}), errors=errors)

    async def async_step_settings(self, user_input=None):
        errors = {}
        if user_input is not None:
            error = validate_numbers(user_input) or validate_source(self.hass, self.values)
            if error:
                errors["base"] = error
            else:
                self.values.update(user_input)
                await self.async_set_unique_id(self.values["source_registry_id"])
                self._abort_if_unique_id_configured()
                state = self.hass.states.get(self.values["source"])
                return self.async_create_entry(title=f"{state.name} · Light Multiplexer", data=self.values)
        return self.async_show_form(step_id="settings", data_schema=settings_schema(self.hass, self.values), errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return OptionsFlow()


class OptionsFlow(config_entries.OptionsFlow):
    def current_values(self):
        values = {**DEFAULTS, **self.config_entry.data}
        entity = er.async_get(self.hass).async_get(values["source_registry_id"])
        if entity:
            values["source"] = entity.entity_id
        return values

    async def async_step_init(self, user_input=None):
        return self.async_show_menu(step_id="init", menu_options=["source", "signals", "timing"])

    async def async_step_source(self, user_input=None):
        errors = {}
        if user_input is not None:
            error = validate_source(self.hass, user_input, self.config_entry.entry_id)
            if error:
                errors["base"] = error
            else:
                return await self.save(user_input)
        return self.async_show_form(step_id="source", data_schema=source_schema(self.current_values()), errors=errors)

    async def async_step_signals(self, user_input=None):
        errors = {}
        if user_input is not None:
            error = validate_numbers(user_input)
            if error:
                errors["base"] = error
            elif user_input["count"] < self.current_values()["count"]:
                self.pending_values = user_input
                return await self.async_step_remove_signals()
            else:
                return await self.save(user_input)
        schema = vol.Schema({vol.Required("count", default=self.current_values()["count"]): number(1, 1)})
        return self.async_show_form(step_id="signals", data_schema=schema, errors=errors)

    async def async_step_remove_signals(self, user_input=None):
        if user_input is not None:
            return await self.save(self.pending_values)
        return self.async_show_form(step_id="remove_signals", data_schema=vol.Schema({}))

    async def async_step_timing(self, user_input=None):
        errors = {}
        if user_input is not None:
            error = validate_numbers(user_input)
            if error:
                errors["base"] = error
            else:
                return await self.save(user_input)
        return self.async_show_form(step_id="timing", data_schema=settings_schema(self.hass, self.current_values(), False), errors=errors)

    async def save(self, changes):
        entry = self.config_entry
        old = dict(entry.data)
        data = {**self.current_values(), **changes}
        # Stop the old controller before changing its source or touching devices.
        if not await self.hass.config_entries.async_unload(entry.entry_id):
            return self.async_abort(reason="unload_failed")
        registry = er.async_get(self.hass)
        old_source = registry.async_get(old["source_registry_id"])
        source_changed = old["source_registry_id"] != data["source_registry_id"]
        if source_changed or not data["hide_source"]:
            if old.get("hidden_by_us") and old_source and old_source.hidden_by == er.RegistryEntryHider.INTEGRATION:
                registry.async_update_entity(old_source.entity_id, hidden_by=None)
            data.pop("hidden_by_us", None)
        self.hass.config_entries.async_update_entry(entry, data=data, unique_id=data["source_registry_id"])
        if not await self.hass.config_entries.async_setup(entry.entry_id):
            return self.async_abort(reason="setup_failed")
        return self.async_create_entry(title="", data={})
