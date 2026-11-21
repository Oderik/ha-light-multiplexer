"""Isolated regression tests with simulated HA I/O."""
import asyncio
import importlib.util
import sys
import types
import unittest
from enum import IntFlag
from pathlib import Path
from unittest.mock import AsyncMock

ROOT = Path(__file__).parents[1] / 'custom_components/light_multiplexer'
package = types.ModuleType('light_multiplexer')
package.__path__ = [str(ROOT)]
sys.modules['light_multiplexer'] = package
from light_multiplexer.model import Model, normalize, PULSE

class ModelTests(unittest.TestCase):
    def model(self):
        return Model(normalize(None, 3))
    def test_initial_source_on(self):
        m = Model(normalize(None, 1, {'on': True, 'brightness': 40}))
        self.assertEqual(m.output()['brightness'], 40)
        self.assertTrue(m.output()['on'])
    def test_normalize_persisted_roles(self):
        m = Model(normalize({'base': {'on': True, 'brightness': 43, 'hs_color':[0,0]}, 'signal': {'on': True,'brightness':90,'hs_color':[120,100]}}, 2))
        self.assertEqual(m.output()['hs_color'], [120,100])
        self.assertNotIn('hs_color', m.states['base'])
        self.assertFalse(m.states['signal_2']['on'])
    def test_unsupported_saved_effect_resets_to_steady(self):
        m = Model(normalize({"signal": {"on": True, "effect": "unsupported_effect"}}, 1))
        self.assertEqual(m.states["signal"]["effect"], "off")
        m.advance()
        self.assertIsNone(m.current)

    def test_priority(self):
        m=self.model()
        for s in m.states.values(): s['on']=True
        m.states['signal']['hs_color']=[10,100]
        m.states['signal_3']['hs_color']=[30,100]
        self.assertEqual(m.output()['hs_color'], [30,100])
    def test_brightness_floor_is_not_persistent(self):
        m=self.model();m.states['base'].update(on=True,brightness=200)
        m.states['signal'].update(on=True,brightness=40)
        self.assertEqual(m.output()['brightness'],200)
        self.assertEqual(m.states['signal']['brightness'],40)
        m.states['base']['on']=False
        self.assertEqual(m.output()['brightness'],40)
    def test_rotation_with_newcomers(self):
        m=self.model();m.states['signal'].update(on=True,effect=PULSE)
        m.sync();m.advance();self.assertEqual(m.current,'signal')
        m.states['signal_2'].update(on=True,effect=PULSE);m.sync()
        m.states['signal_3'].update(on=True,effect=PULSE);m.sync()
        m.advance();self.assertIsNone(m.current)
        m.advance();self.assertEqual(m.current,'signal_2')
        m.advance();m.advance();self.assertEqual(m.current,'signal_3')
        m.advance();m.advance();self.assertEqual(m.current,'signal')
    def test_pause_uses_normal_then_base(self):
        m=self.model();m.states['base']['on']=True
        m.states['signal'].update(on=True,effect=PULSE)
        m.states['signal_2'].update(on=True,hs_color=[120,100])
        m.sync();m.advance();m.advance()
        self.assertEqual(m.output()['hs_color'],[120,100])
        m.states['signal_2']['on']=False;m.sync()
        self.assertIn('color_temp_kelvin',m.output())
    def test_interruption(self):
        m=self.model();m.states['signal'].update(on=True,effect=PULSE)
        m.sync();m.advance();m.states['signal']['on']=False
        self.assertTrue(m.sync());self.assertIsNone(m.current)
        self.assertEqual(m.output(),{'on':False})
    def test_repeated_activation_does_not_reorder(self):
        m=self.model()
        for role in ['signal','signal_2']:m.states[role].update(on=True,effect=PULSE)
        m.sync();m.advance();m.sync();m.sync()
        self.assertEqual(m.new_queue,['signal_2'])
    def test_reduction_removes_only_tail(self):
        states=normalize(None,3);states['signal']['brightness']=33
        reduced=normalize(states,1)
        self.assertEqual(set(reduced),{'base','signal'})
        self.assertEqual(reduced['signal']['brightness'],33)

for name in ['homeassistant','homeassistant.core','homeassistant.const','homeassistant.components','homeassistant.components.light','homeassistant.helpers','homeassistant.helpers.entity_registry','homeassistant.helpers.event','homeassistant.helpers.storage','homeassistant.exceptions']:
    sys.modules[name]=types.ModuleType(name)
class Features(IntFlag):
    TRANSITION=32
sys.modules['homeassistant.components.light'].LightEntityFeature=Features
sys.modules['homeassistant.core'].callback=lambda f:f
sys.modules['homeassistant.const'].STATE_UNAVAILABLE='unavailable'
sys.modules['homeassistant.const'].STATE_UNKNOWN='unknown'
sys.modules['homeassistant.helpers.event'].async_track_state_change_event=lambda *a:lambda:None
sys.modules['homeassistant.helpers.storage'].Store=lambda *a:types.SimpleNamespace(async_save=AsyncMock())
sys.modules['homeassistant.exceptions'].HomeAssistantError=RuntimeError
from light_multiplexer.controller import Controller
class FakeController(Controller):
    source='light.source'
    available=True
    transition_supported=True
class ControllerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.hass=types.SimpleNamespace(loop=asyncio.get_running_loop(),async_create_task=asyncio.create_task,services=types.SimpleNamespace(async_call=AsyncMock()))
        self.c=FakeController(self.hass,types.SimpleNamespace(entry_id='test',data={'hold':2,'pause':5,'fade':0.5}))
        self.c.model=Model(normalize(None,2))
    async def asyncTearDown(self):self.c.stop()
    async def test_failure_to_save_does_not_mutate(self):
        self.c.store.async_save.side_effect=OSError()
        with self.assertRaises(OSError):await self.c.change('base',True,{})
        self.assertFalse(self.c.model.states['base']['on'])
    async def test_concurrent_commands(self):
        await asyncio.gather(self.c.change('base',True,{'brightness':220}),self.c.change('signal',True,{'brightness':40}))
        self.assertEqual(self.c.model.output()['brightness'],220)
        self.assertEqual(self.c.store.async_save.call_args.args[0],self.c.model.states)
    async def test_stale_timer_and_cancel_current(self):
        await self.c.change('signal',True,{'effect':PULSE})
        generation=self.c.generation
        await self.c.change('signal',False,{})
        count=self.hass.services.async_call.call_count
        await self.c.tick(generation)
        self.assertEqual(self.hass.services.async_call.call_count,count)
        self.assertEqual(self.hass.services.async_call.call_args.args[1],'turn_off')
        self.assertEqual(self.hass.services.async_call.call_args.args[2]['transition'],0)
    async def test_hidden_command_does_not_restart_transition(self):
        await self.c.change('signal',True,{'effect':PULSE,'brightness':255})
        count=self.hass.services.async_call.call_count
        await self.c.change('base',True,{'brightness':50},9)
        self.assertEqual(self.hass.services.async_call.call_count,count)
    async def test_default_transition_is_omitted(self):
        await self.c.change('base',True,{})
        self.assertNotIn('transition',self.hass.services.async_call.call_args.args[2])
    async def test_no_transition_support(self):
        self.c.transition_supported=False
        await self.c.change('signal',True,{'effect':PULSE})
        self.assertEqual(self.c.fade,0)
        self.assertNotIn('transition',self.hass.services.async_call.call_args.args[2])
    async def test_no_write_after_unload(self):
        self.c.stop();await self.c.change('base',True,{})
        self.hass.services.async_call.assert_not_called()

    async def test_last_pulse_removed_clears_timer(self):
        await self.c.change('signal', True, {'effect': PULSE})
        await self.c.change('signal', False, {})
        self.assertEqual(self.c.model.phase, 'idle')
        self.assertIsNone(self.c.timer)
        await self.c.change('signal_2', True, {'effect': PULSE})
        self.assertEqual(self.c.model.current, 'signal_2')

    async def test_partial_updates_preserve_other_values(self):
        await asyncio.gather(
            self.c.change('signal', True, {'brightness': 77}),
            self.c.change('signal', True, {'hs_color': [42, 80]}),
        )
        self.assertEqual(self.c.model.states['signal']['brightness'], 77)
        self.assertEqual(self.c.model.states['signal']['hs_color'], [42, 80])

    async def test_interrupted_pulse_pause_has_no_unused_fade(self):
        await self.c.change('signal', True, {'effect': PULSE})
        await self.c.change('signal_2', True, {'effect': PULSE})
        await self.c.change('signal', False, {})
        self.assertEqual(self.c.model.phase, 'pause')
        remaining = self.c.timer.when() - self.hass.loop.time()
        self.assertGreater(remaining, 4.9)
        self.assertLessEqual(remaining, 5.0)

    async def test_pause_returns_to_main_at_every_relative_brightness(self):
        for main, first, second in ((220,40,80),(100,100,100),(40,180,220),(150,40,220)):
            with self.subTest(main=main, first=first, second=second):
                self.c.cancel_timer()
                self.c.model=Model(normalize(None,2))
                self.c.last_output=None
                await self.c.change('base',True,{'brightness':main,'color_temp_kelvin':3200})
                await self.c.change('signal',True,{'brightness':first,'hs_color':[240,100],'effect':PULSE})
                await self.c.change('signal_2',True,{'brightness':second,'hs_color':[120,100],'effect':PULSE})
                self.assertEqual(self.hass.services.async_call.call_args.args[2]['brightness'],max(main,first))
                for expected in (second,first):
                    await self.c.tick(self.c.generation)
                    command=self.hass.services.async_call.call_args.args[2]
                    self.assertEqual(command['brightness'],main)
                    self.assertEqual(command['color_temp_kelvin'],3200)
                    self.assertNotIn('hs_color',command)
                    await self.c.tick(self.c.generation)
                    command=self.hass.services.async_call.call_args.args[2]
                    self.assertEqual(command['brightness'],max(main,expected))
                    self.assertIn('hs_color',command)
                self.assertEqual(self.c.model.states['signal']['brightness'],first)
                self.assertEqual(self.c.model.states['signal_2']['brightness'],second)

    async def test_new_defaults(self):
        self.c.entry.data={}
        self.assertEqual(self.c.fade,0.25)
        await self.c.change('signal',True,{'effect':PULSE})
        self.assertAlmostEqual(self.c.timer.when()-self.hass.loop.time(),1.25,places=2)
        await self.c.tick(self.c.generation)
        self.assertAlmostEqual(self.c.timer.when()-self.hass.loop.time(),2.25,places=2)
