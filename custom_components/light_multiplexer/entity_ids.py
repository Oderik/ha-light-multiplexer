"""Manage the optional one-time transfer of the source entity ID."""
import asyncio
from homeassistant.helpers import entity_registry as er


def source_alias(hass, original):
    registry = er.async_get(hass)
    index = 1
    while True:
        suffix = "_source" if index == 1 else f"_source_{index}"
        candidate = original[:255 - len(suffix)].rstrip("_") + suffix
        if registry.async_get(candidate) is None and hass.states.async_available(candidate):
            return candidate
        index += 1


async def wait_until_free(hass, entity_id):
    # Registry updates are synchronous, but platforms move live states asynchronously.
    async with asyncio.timeout(5):
        while not hass.states.async_available(entity_id):
            await asyncio.sleep(0.05)


async def restore_source(hass, entry, *, removing=False):
    move = entry.data.get("id_transfer")
    if not move:
        return
    registry = er.async_get(hass)
    source = registry.async_get(move["source_registry_id"])
    if source is None or source.entity_id != move["alias"]:
        return
    original = move["original"]
    holder = registry.async_get(original)
    if holder:
        if not removing or holder.config_entry_id != entry.entry_id or holder.unique_id != f"{entry.entry_id}_base":
            return
        registry.async_remove(original)
    try:
        await wait_until_free(hass, original)
    except TimeoutError:
        return
    source = registry.async_get(move["source_registry_id"])
    if source and source.entity_id == move["alias"] and registry.async_get(original) is None:
        registry.async_update_entity(source.entity_id, new_entity_id=original)


async def take_over(hass, entry):
    registry = er.async_get(hass)
    source = registry.async_get(entry.data["source_registry_id"])
    if source is None:
        raise ValueError("Source registry entry is missing")
    main_id = registry.async_get_entity_id("light", entry.domain, f"{entry.entry_id}_base")
    if main_id is None:
        raise ValueError("Main light registry entry is missing")
    move = entry.data.get("id_transfer")
    if move is None:
        original = source.entity_id
        move = {"source_registry_id": source.id, "original": original, "alias": source_alias(hass, original)}
        hass.config_entries.async_update_entry(entry, data={**entry.data, "id_transfer": move})
    original, alias = move["original"], move["alias"]
    if source.entity_id == original:
        registry.async_update_entity(original, new_entity_id=alias)
    elif source.entity_id != alias:
        raise ValueError("Source entity ID changed during setup")
    if main_id != original:
        try:
            await wait_until_free(hass, original)
            registry.async_update_entity(main_id, new_entity_id=original)
        except (ValueError, TimeoutError):
            await restore_source(hass, entry)
            raise
    hass.config_entries.async_update_entry(entry, data={**entry.data, "source": alias, "take_over_id": False})
