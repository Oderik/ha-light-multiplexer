"""White main light and RGB signal lights."""
from homeassistant.components.light import LightEntity, ColorMode, LightEntityFeature
from homeassistant.helpers import entity_registry as er
from homeassistant.exceptions import ServiceValidationError
from .model import PULSE, NORMAL, signal_key

async def async_setup_entry(hass, entry, async_add_entities):
    roles = ["base"] + [signal_key(i) for i in range(1, entry.data.get("count", 1) + 1)]
    registry = er.async_get(hass)
    wanted = {f"{entry.entry_id}_{role}" for role in roles}
    for entity in er.async_entries_for_config_entry(registry, entry.entry_id):
        if entity.unique_id not in wanted:
            registry.async_remove(entity.entity_id)
    async_add_entities([MultiplexLight(entry, role, index) for index, role in enumerate(roles)])

class MultiplexLight(LightEntity):
    _attr_should_poll = False

    def __init__(self, entry, role, index):
        self.entry = entry
        self.controller = entry.runtime_data
        self.role = role
        self._attr_unique_id = f"{entry.entry_id}_{role}"
        source = self.controller.hass.states.get(self.controller.source)
        source_name = source.name if source else entry.title
        suffix = "Main" if role == "base" else f"Signal {index}"
        self._attr_name = f"{source_name} {suffix}"
        object_id = self.controller.source.split(".", 1)[1]
        self.entity_id = f"light.{object_id}_{'main' if role == 'base' else f'signal_{index}'}"
        self._attr_color_mode = ColorMode.COLOR_TEMP if role == "base" else ColorMode.HS
        self._attr_supported_color_modes = {self._attr_color_mode}
        attributes = source.attributes if source else {}
        self._attr_min_color_temp_kelvin = attributes.get("min_color_temp_kelvin") or 2000
        self._attr_max_color_temp_kelvin = attributes.get("max_color_temp_kelvin") or 6500
        self._attr_supported_features = LightEntityFeature.EFFECT if role != "base" else LightEntityFeature(0)
        if self.controller.transition_supported:
            self._attr_supported_features |= LightEntityFeature.TRANSITION
        if role != "base":
            self._attr_effect_list = [NORMAL, PULSE]

    @property
    def desired(self):
        return self.controller.model.states[self.role]

    @property
    def available(self):
        return self.controller.available

    @property
    def is_on(self):
        return self.desired["on"]

    @property
    def brightness(self):
        return self.desired["brightness"]

    @property
    def hs_color(self):
        return tuple(self.desired.get("hs_color", (0, 0)))

    @property
    def color_temp_kelvin(self):
        return max(self.min_color_temp_kelvin, min(self.max_color_temp_kelvin, self.desired.get("color_temp_kelvin", 3000)))

    @property
    def effect(self):
        return self.desired.get("effect")

    async def async_added_to_hass(self):
        registry = er.async_get(self.hass)
        source = registry.async_get(self.controller.source)
        if source:
            registry.async_update_entity(self.entity_id, device_id=source.device_id)
        self.controller.listeners.add(self.async_write_ha_state)
        self.async_on_remove(lambda: self.controller.listeners.discard(self.async_write_ha_state))

    async def async_turn_on(self, **kwargs):
        allowed = {"brightness", "color_temp_kelvin"} if self.role == "base" else {"brightness", "hs_color", "effect"}
        values = {key: value for key, value in kwargs.items() if key in allowed}
        if "effect" in values and values["effect"] not in (NORMAL, PULSE):
            raise ServiceValidationError("Unsupported effect. Choose off or Pulse.")
        await self.controller.change(self.role, True, values, kwargs.get("transition"))

    async def async_turn_off(self, **kwargs):
        await self.controller.change(self.role, False, {}, kwargs.get("transition"))
