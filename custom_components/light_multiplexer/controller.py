"""Persistent state and one cancellable scheduler per source."""
import asyncio
from copy import deepcopy
import logging
from homeassistant.core import callback
from homeassistant.components.light import LightEntityFeature
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.storage import Store
from homeassistant.exceptions import HomeAssistantError
from .model import Model, normalize
from .const import DEFAULT_HOLD, DEFAULT_PAUSE, DEFAULT_FADE

_LOGGER = logging.getLogger(__name__)

class Controller:
    def __init__(self, hass, entry):
        self.hass, self.entry = hass, entry
        self.store = Store(hass, 1, f"light_multiplexer.{entry.entry_id}")
        self.listeners = set()
        self.lock = asyncio.Lock()
        self.active = True
        self.timer = None
        self.generation = 0
        self.unsubscribe = None
        self.registry_unsubscribe = None
        self.last_output = None
        self.fresh = False
        self.pending_initial = False

    @property
    def source(self):
        entity = er.async_get(self.hass).async_get(self.entry.data["source_registry_id"])
        return entity.entity_id if entity else self.entry.data["source"]

    @property
    def available(self):
        state = self.hass.states.get(self.source)
        return bool(state and state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN))

    @property
    def transition_supported(self):
        state = self.hass.states.get(self.source)
        return bool(state and state.attributes.get("supported_features", 0) & LightEntityFeature.TRANSITION)

    @property
    def fade(self):
        return self.entry.data.get("fade", DEFAULT_FADE) if self.transition_supported else 0

    def initial(self):
        source = self.hass.states.get(self.source)
        if not source:
            return {}
        return {"on": source.state == "on", "brightness": source.attributes.get("brightness") or 255,
                "color_temp_kelvin": source.attributes.get("color_temp_kelvin") or 3000}

    async def load(self):
        saved = await self.store.async_load()
        self.fresh = saved is None
        self.pending_initial = self.fresh and not self.available
        self.model = Model(normalize(saved, self.entry.data.get("count", 1), self.initial()))
        if not self.pending_initial:
            await self.store.async_save(self.model.states)
        registry = er.async_get(self.hass)
        source = registry.async_get(self.source)
        if self.entry.data["hide_source"] and source and source.hidden_by is None:
            self.hass.config_entries.async_update_entry(self.entry, data={**self.entry.data, "hidden_by_us": True})
            registry.async_update_entity(self.source, hidden_by=er.RegistryEntryHider.INTEGRATION)

    def start(self):
        self.unsubscribe = async_track_state_change_event(self.hass, self.source, self.source_changed)
        self.registry_unsubscribe = self.hass.bus.async_listen("entity_registry_updated", self.registry_changed)
        if not self.fresh:
            self.hass.async_create_task(self.resume())

    @callback
    def registry_changed(self, event):
        if event.data.get("action") == "update" and "old_entity_id" in event.data:
            if event.data.get("entity_id") == self.source:
                if self.unsubscribe:
                    self.unsubscribe()
                self.unsubscribe = async_track_state_change_event(self.hass, self.source, self.source_changed)
                self.hass.async_create_task(self.resume())

    def cancel_timer(self):
        self.generation += 1
        if self.timer:
            self.timer.cancel()
            self.timer = None

    def stop(self):
        self.active = False
        self.cancel_timer()
        if self.unsubscribe:
            self.unsubscribe()
        if self.registry_unsubscribe:
            self.registry_unsubscribe()

    @callback
    def notify(self):
        for listener in tuple(self.listeners):
            listener()

    @callback
    def source_changed(self, event):
        self.notify()
        old = event.data.get("old_state")
        if not self.available:
            self.cancel_timer()
            self.last_output = None
        elif old is None or old.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            self.hass.async_create_task(self.resume())

    async def resume(self):
        async with self.lock:
            if not self.active or not self.available:
                return
            if self.pending_initial:
                self.model = Model(normalize(None, self.entry.data.get("count", 1), self.initial()))
                await self.store.async_save(self.model.states)
                self.pending_initial = False
                self.notify()
                return
            self.model = Model(self.model.states)
            self.last_output = None
            self.model.advance()
            await self.safe_write(self.fade if self.model.phase == "show" else None)
            self.schedule()

    def schedule(self, immediate=False):
        self.cancel_timer()
        if not self.active or not self.available or self.model.phase == "idle":
            return
        fade = 0 if immediate else self.fade
        delay = fade + self.entry.data.get("hold", DEFAULT_HOLD) if self.model.phase == "show" else fade + self.entry.data.get("pause", DEFAULT_PAUSE)
        generation = self.generation
        self.timer = self.hass.loop.call_later(delay, lambda: self.hass.async_create_task(self.tick(generation)))

    async def tick(self, generation):
        async with self.lock:
            if not self.active or generation != self.generation or not self.available:
                return
            self.model.advance()
            await self.safe_write(self.fade)
            self.schedule()

    async def change(self, role, on, values, transition=None):
        async with self.lock:
            if not self.active:
                return
            updated = deepcopy(self.model.states)
            updated[role].update(values, on=on)
            await self.store.async_save(updated)
            self.pending_initial = False
            self.model.states = updated
            interrupted = self.model.sync()
            has_pulses = bool(self.model.current or self.model.new_queue or self.model.queue)
            if not has_pulses:
                self.model.phase = "idle"
                self.cancel_timer()
            started = self.model.phase == "idle" and bool(self.model.new_queue or self.model.queue)
            if started:
                self.model.advance()
            self.notify()
            if interrupted:
                await self.safe_write(0, force=True)
            elif started:
                await self.safe_write(self.fade)
            else:
                await self.safe_write(transition)
            if interrupted or started:
                self.schedule(immediate=interrupted)

    async def safe_write(self, transition, force=False):
        try:
            await self.write(transition, force=force)
        except HomeAssistantError:
            self.last_output = None
            _LOGGER.exception("Could not apply Light Multiplexer output to %s", self.source)

    async def write(self, transition, force=False):
        if not self.active or not self.available:
            return
        output = self.model.output()
        if output == self.last_output and not force:
            _LOGGER.debug("Unchanged output: phase=%s pulse=%s output=%s", self.model.phase, self.model.current, output)
            return
        data = {"entity_id": self.source}
        service = "turn_on" if output["on"] else "turn_off"
        if output["on"]:
            data.update({key: value for key, value in output.items() if key != "on"})
        if transition is not None and self.transition_supported:
            data["transition"] = transition
        _LOGGER.debug("Applying output: phase=%s pulse=%s service=%s data=%s", self.model.phase, self.model.current, service, data)
        await self.hass.services.async_call("light", service, data, blocking=True)
        self.last_output = output
