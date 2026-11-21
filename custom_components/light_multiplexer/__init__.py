"""Light Multiplexer setup and cleanup."""
from homeassistant.const import Platform
from homeassistant.helpers import entity_registry as er
from .controller import Controller
from .entity_ids import restore_source, take_over

async def async_setup_entry(hass, entry):
    controller = Controller(hass, entry)
    await controller.load()
    entry.runtime_data = controller
    await hass.config_entries.async_forward_entry_setups(entry, [Platform.LIGHT])
    if entry.data.get("take_over_id"):
        try:
            await take_over(hass, entry)
        except Exception:
            await hass.config_entries.async_unload_platforms(entry, [Platform.LIGHT])
            raise
    controller.start()
    return True

async def async_unload_entry(hass, entry):
    if await hass.config_entries.async_unload_platforms(entry, [Platform.LIGHT]):
        entry.runtime_data.stop()
        async with entry.runtime_data.lock:
            pass
        return True
    return False

async def async_remove_entry(hass, entry):
    registry = er.async_get(hass)
    source = registry.async_get(entry.data["source_registry_id"])
    if entry.data.get("hidden_by_us") and source and source.hidden_by == er.RegistryEntryHider.INTEGRATION:
        registry.async_update_entity(source.entity_id, hidden_by=None)
    await restore_source(hass, entry, removing=True)
    from homeassistant.helpers.storage import Store
    await Store(hass, 1, f"light_multiplexer.{entry.entry_id}").async_remove()
