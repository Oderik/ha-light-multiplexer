import asyncio, tempfile, shutil, sys
from pathlib import Path
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from homeassistant.helpers import entity_registry as er, device_registry as dr
from homeassistant.components.light import LightEntity, ColorMode, LightEntityFeature
from homeassistant.config_entries import ConfigEntries, ConfigEntry
from types import MappingProxyType

class Source(LightEntity):
 _attr_name='Test source'
 _attr_unique_id='source-test'
 _attr_is_on=True
 _attr_brightness=180
 _attr_color_mode=ColorMode.COLOR_TEMP
 _attr_supported_color_modes={ColorMode.COLOR_TEMP,ColorMode.HS}
 _attr_color_temp_kelvin=3200
 _attr_supported_features=LightEntityFeature.TRANSITION
 _attr_min_color_temp_kelvin=2000
 _attr_max_color_temp_kelvin=6500
 calls=[]
 async def async_turn_on(self,**kw):
  self.calls.append(('on',kw))
  self._attr_is_on=True
  if 'brightness' in kw: self._attr_brightness=kw['brightness']
  if 'color_temp_kelvin' in kw:
   self._attr_color_temp_kelvin=kw['color_temp_kelvin'];self._attr_color_mode=ColorMode.COLOR_TEMP
  if 'hs_color' in kw:
   self._attr_hs_color=kw['hs_color'];self._attr_color_mode=ColorMode.HS
  self.async_write_ha_state()
 async def async_turn_off(self,**kw):
  self.calls.append(('off',kw));self._attr_is_on=False;self.async_write_ha_state()

async def main():
 directory=tempfile.mkdtemp(prefix='ha-mux-')
 shutil.copytree(str(Path(__file__).resolve().parents[1] / 'custom_components'),directory+'/custom_components')
 fixture=Path(directory)/'custom_components/test'
 fixture.mkdir()
 (fixture/'manifest.json').write_text('{"domain":"test","name":"Test source","version":"1.0.0","requirements":[]}')
 (fixture/'config_flow.py').write_text('from homeassistant.config_entries import ConfigFlow\nclass Flow(ConfigFlow, domain="test"):\n    VERSION=1\n')
 (fixture/'__init__.py').write_text('async def async_setup_entry(hass, entry):\n    return True\n')
 sys.path.insert(0,directory)
 hass=HomeAssistant(directory)
 from homeassistant import loader, bootstrap
 loader.async_setup(hass)
 hass.config_entries=ConfigEntries(hass,{})
 await hass.config_entries.async_initialize()
 await bootstrap.async_load_base_functionality(hass)
 assert await async_setup_component(hass,'light',{})
 source=Source()
 if '--rgb-only' in sys.argv:
  source._attr_supported_color_modes={ColorMode.HS}
  source._attr_color_mode=ColorMode.HS
  source._attr_hs_color=(0,0)
 await hass.data['light'].async_add_entities([source])
 await hass.async_block_till_done()
 print('SOURCE',source.entity_id,flush=True)
 original_id=source.entity_id
 takeover='--takeover' in sys.argv
 collision='--collision' in sys.argv
 if collision:
  hass.states.async_set(original_id+'_source','on')
 flow=await hass.config_entries.flow.async_init('light_multiplexer',context={'source':'user'})
 print('FLOW',flow['type'],flush=True)
 result=await hass.config_entries.flow.async_configure(flow['flow_id'],{'source':source.entity_id,'hide_source':True})
 assert result['step_id']=='settings'
 assert any(str(key)=='fade' for key in result['data_schema'].schema)
 defaults=result['data_schema']({})
 assert defaults['hold']==1 and defaults['pause']==2 and defaults['fade']==0.25,defaults
 result=await hass.config_entries.flow.async_configure(flow['flow_id'],{'take_over_id':takeover,'count':3,'hold':0.1,'pause':0.1,'fade':0})
 print('CREATED',result['type'],flush=True)
 await hass.async_block_till_done()
 entry=result['result']
 print('ENTRY',entry.state,flush=True)
 entities=er.async_entries_for_config_entry(er.async_get(hass),entry.entry_id)
 print('ENTITIES',[(e.entity_id,e.unique_id) for e in entities],flush=True)
 assert len(entities)==4
 assert source.calls==[],source.calls
 signals=[e.entity_id for e in entities if e.unique_id.endswith('_signal')]
 assert len(signals)==1
 main_entity=next(e for e in entities if e.unique_id.endswith('_base'))
 if takeover:
  assert main_entity.entity_id==original_id
  assert source.entity_id==original_id+('_source_2' if collision else '_source')
 else:
  assert main_entity.entity_id.endswith('_main')
 assert hass.states.get(main_entity.entity_id).name=='Test source Main'
 assert hass.states.get(signals[0]).attributes['effect_list']==['off','Pulse']
 await hass.services.async_call('light','turn_on',{'entity_id':signals[0],'hs_color':[240,100],'brightness':40},blocking=True)
 assert source.calls[-1][1]['brightness']==180,source.calls
 await hass.services.async_call('light','turn_on',{'entity_id':signals[0],'effect':'Pulse'},blocking=True)
 assert entry.runtime_data.model.current=='signal'
 await hass.services.async_call('light','turn_off',{'entity_id':signals[0]},blocking=True)
 assert entry.runtime_data.model.current is None
 if '--rgb-only' in sys.argv:
  assert 'hs_color' in source.calls[-1][1],source.calls[-1]
 # Check actual source commands on every pause, including equal output brightness.
 main_light=next(e.entity_id for e in entities if e.unique_id.endswith('_base'))
 for main_brightness,signal_brightness in ((220,40),(100,100),(40,220)):
  await hass.services.async_call('light','turn_on',{'entity_id':main_light,'brightness':main_brightness,'color_temp_kelvin':3200},blocking=True)
  await hass.services.async_call('light','turn_on',{'entity_id':signals[0],'brightness':signal_brightness,'effect':'Pulse','hs_color':[240,100]},blocking=True)
  assert source.calls[-1][1]['brightness']==max(main_brightness,signal_brightness)
  await entry.runtime_data.tick(entry.runtime_data.generation)
  assert entry.runtime_data.model.phase=='pause'
  actual=source.calls[-1][1]
  assert actual['brightness']==main_brightness,actual
  if '--rgb-only' in sys.argv:
   assert actual['hs_color']!=[240,100],actual
  else:
   assert actual['color_temp_kelvin']==3200,actual
   assert source.color_mode==ColorMode.COLOR_TEMP
  await hass.services.async_call('light','turn_off',{'entity_id':signals[0]},blocking=True)
 # Exercise live timers, not only a manually advanced state machine.
 signal2=next(e.entity_id for e in entities if e.unique_id.endswith('_signal_2'))
 await hass.services.async_call('light','turn_on',{'entity_id':signals[0],'effect':'Pulse'},blocking=True)
 await hass.services.async_call('light','turn_on',{'entity_id':signal2,'effect':'Pulse','hs_color':[120,100]},blocking=True)
 await asyncio.sleep(0.25)
 assert entry.runtime_data.model.current=='signal_2',entry.runtime_data.model.phase
 await hass.services.async_call('light','turn_off',{'entity_id':[signals[0],signal2]},blocking=True)
 assert entry.runtime_data.model.phase=='idle'
 assert entry.runtime_data.timer is None
 await hass.services.async_call('light','turn_on',{'entity_id':signals[0]},blocking=True)
 assert entry.runtime_data.model.current=='signal'
 await hass.services.async_call('light','turn_off',{'entity_id':signals[0]},blocking=True)
 # Concurrent partial commands must preserve both requested values.
 await asyncio.gather(
  hass.services.async_call('light','turn_on',{'entity_id':signal2,'brightness':77},blocking=True),
  hass.services.async_call('light','turn_on',{'entity_id':signal2,'hs_color':[42,80]},blocking=True))
 assert entry.runtime_data.model.states['signal_2']['brightness']==77
 assert list(entry.runtime_data.model.states['signal_2']['hs_color'])==[42,80]
 await hass.services.async_call('light','turn_off',{'entity_id':signal2},blocking=True)
 options=await hass.config_entries.options.async_init(entry.entry_id)
 assert options['type']=='menu'
 form=await hass.config_entries.options.async_configure(options['flow_id'],{'next_step_id':'signals'})
 confirm=await hass.config_entries.options.async_configure(options['flow_id'],{'count':2})
 assert confirm['step_id']=='remove_signals'
 await hass.config_entries.options.async_configure(options['flow_id'],{})
 await hass.async_block_till_done()
 assert len(er.async_entries_for_config_entry(er.async_get(hass),entry.entry_id))==3
 # Device association uses the actual source device, not a synthetic device.
 owner=ConfigEntry(domain='test',data={},options={},title='Source integration',unique_id=None,version=1,minor_version=1,source='user',discovery_keys=MappingProxyType({}),subentries_data=[])
 await hass.config_entries.async_add(owner)
 device=dr.async_get(hass).async_get_or_create(config_entry_id=owner.entry_id, identifiers={('test','source-device')},name='Test device')
 er.async_get(hass).async_update_entity(source.entity_id,device_id=device.id)
 await hass.config_entries.async_reload(entry.entry_id)
 await hass.async_block_till_done()
 assert all(e.device_id==device.id for e in er.async_entries_for_config_entry(er.async_get(hass),entry.entry_id))
 # Persistence across reload, including the effect on an off signal.
 assert entry.runtime_data.model.states['signal']['effect']=='Pulse'
 assert not entry.runtime_data.model.states['signal']['on']
 options=await hass.config_entries.options.async_init(entry.entry_id)
 await hass.config_entries.options.async_configure(options['flow_id'],{'next_step_id':'source'})
 await hass.config_entries.options.async_configure(options['flow_id'],{'source':source.entity_id,'hide_source':False})
 await hass.async_block_till_done()
 assert er.async_get(hass).async_get(source.entity_id).hidden_by is None
 if '--remove-now' in sys.argv:
  expected=original_id
  if '--manual-rename' in sys.argv:
   expected='light.user_selected'
   er.async_get(hass).async_update_entity(source.entity_id,new_entity_id=expected)
   await hass.async_block_till_done()
  await hass.config_entries.async_remove(entry.entry_id)
  await hass.async_block_till_done()
  assert source.entity_id==expected,source.entity_id
  assert hass.states.get(expected) is not None
  await hass.async_stop(force=True)
  print('REMOVAL PASSED',flush=True)
  return
 # A replacement source receives output, while existing virtual identities persist.
 replacement=Source()
 replacement._attr_unique_id='replacement-test'
 replacement._attr_name='Replacement'
 replacement.calls=[]
 await hass.data['light'].async_add_entities([replacement])
 await hass.async_block_till_done()
 before={e.unique_id:e.entity_id for e in er.async_entries_for_config_entry(er.async_get(hass),entry.entry_id)}
 options=await hass.config_entries.options.async_init(entry.entry_id)
 await hass.config_entries.options.async_configure(options['flow_id'],{'next_step_id':'source'})
 await hass.config_entries.options.async_configure(options['flow_id'],{'source':replacement.entity_id,'hide_source':True})
 await hass.async_block_till_done()
 assert entry.runtime_data.source==replacement.entity_id
 assert before=={e.unique_id:e.entity_id for e in er.async_entries_for_config_entry(er.async_get(hass),entry.entry_id)}
 assert replacement.calls
 assert all(e.device_id is None for e in er.async_entries_for_config_entry(er.async_get(hass),entry.entry_id))
 assert dr.async_get(hass).async_get(device.id).config_entry_id==owner.entry_id
 # Source renames must rebind availability listeners without a helper reload.
 er.async_get(hass).async_update_entity(replacement.entity_id,new_entity_id='light.renamed_source')
 await hass.async_block_till_done()
 assert entry.runtime_data.source=='light.renamed_source'
 replacement._attr_available=False
 replacement.async_write_ha_state()
 await hass.async_block_till_done()
 assert not entry.runtime_data.available
 assert entry.runtime_data.timer is None
 previous=len(replacement.calls)
 replacement._attr_available=True
 replacement.async_write_ha_state()
 await hass.async_block_till_done()
 assert entry.runtime_data.available
 assert len(replacement.calls)>previous
 # Removing the helper restores a source hidden by this integration.
 await hass.config_entries.async_remove(entry.entry_id)
 await hass.async_block_till_done()
 assert er.async_get(hass).async_get(replacement.entity_id).hidden_by is None
 if takeover:
  assert source.entity_id==original_id, source.entity_id
 print('INTEGRATION SMOKE PASSED',flush=True)
 await hass.async_stop(force=True)
asyncio.run(main())
