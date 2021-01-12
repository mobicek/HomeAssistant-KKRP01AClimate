#!/usr/bin/python
# Do basic imports
import importlib.util
import re
import sys
import time  

import requests  
import asyncio
import logging
import os.path
import voluptuous as vol
import homeassistant.helpers.config_validation as cv

from homeassistant.components.climate import (ClimateEntity, PLATFORM_SCHEMA)

from homeassistant.components.climate.const import (
    HVAC_MODE_OFF, HVAC_MODE_AUTO, HVAC_MODE_COOL, HVAC_MODE_HEAT, SUPPORT_FAN_MODE,
    SUPPORT_TARGET_TEMPERATURE, SUPPORT_SWING_MODE)

from homeassistant.const import (
    ATTR_UNIT_OF_MEASUREMENT, ATTR_TEMPERATURE, 
    CONF_NAME, CONF_HOST, CONF_TIMEOUT, CONF_CUSTOMIZE, 
    STATE_ON, STATE_OFF, STATE_UNKNOWN, 
    TEMP_CELSIUS, PRECISION_WHOLE, PRECISION_TENTHS)

from homeassistant.helpers.event import (async_track_state_change)
from homeassistant.core import callback
from homeassistant.helpers.restore_state import RestoreEntity
from configparser import ConfigParser

_LOGGER = logging.getLogger(__name__)

SUPPORT_FLAGS = SUPPORT_TARGET_TEMPERATURE | SUPPORT_FAN_MODE | SUPPORT_SWING_MODE

DEFAULT_NAME = 'KKRP01A Climate'

CONF_TARGET_TEMP_STEP = 'target_temp_step'
CONF_UID = 'uid'

DEFAULT_TIMEOUT = 10
DEFAULT_TARGET_TEMP_STEP = 1

# from the remote control
MIN_TEMP = 18
MAX_TEMP = 30

# fixed values in kkrp01a mode lists
HVAC_MODES = [HVAC_MODE_AUTO, HVAC_MODE_COOL, HVAC_MODE_HEAT, HVAC_MODE_OFF]
AC_HVAC_MODES = ['AUTO', 'COOL', 'HEAT' , 'NONE']
FAN_MODES = ['auto', '|', '||', '|||', '||||', '|||||']
HVAC_FAN_MODES = ['FA', 'F1', 'F2', 'F3', 'F4', 'F5']
HVAC_CTRL_FAN_MODES = ['FAuto', 'Fun1', 'Fun2', 'Fun3', 'Fun4', 'Fun5']
SWING_MODES = ['On', 'Off']
HVAC_SWING_MODES = ['UD', 'OFF']

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
    vol.Required(CONF_HOST): cv.string,
    vol.Optional(CONF_TIMEOUT, default=DEFAULT_TIMEOUT): cv.positive_int,
    vol.Optional(CONF_TARGET_TEMP_STEP, default=DEFAULT_TARGET_TEMP_STEP): vol.Coerce(float),
    vol.Optional(CONF_UID): cv.positive_int
})

@asyncio.coroutine
def async_setup_platform(hass, config, async_add_devices, discovery_info=None):
    _LOGGER.info('Setting up KKRP01A climate platform')
    name = config.get(CONF_NAME)
    ip_addr = config.get(CONF_HOST)
    timeout = config.get(CONF_TIMEOUT)

    target_temp_step = config.get(CONF_TARGET_TEMP_STEP)
    hvac_modes = HVAC_MODES
    ac_hvac_modes = AC_HVAC_MODES
    fan_modes = FAN_MODES
    hvac_fan_modes = HVAC_FAN_MODES
    swing_modes = SWING_MODES
    hvac_swing_modes = HVAC_SWING_MODES
    uid = config.get(CONF_UID)
    
    _LOGGER.info('Adding KKRP01A climate device to hass')
    async_add_devices([
        KKRP01AClimate(hass, name, ip_addr, timeout, target_temp_step, ac_hvac_modes, hvac_modes, hvac_fan_modes, fan_modes, hvac_swing_modes, swing_modes, uid)
    ])

class ParamType:
    
    COMM = 0
    AIRONOF = 1
    AIRMODE = 2
    AIRTEMP = 3
    AIRFUN = 4
    SWING = 5
    ROOMT = 6
    TIMER = 7
    REMOTE = 8
    ERROR = 9
    CHGD = 10
    NAME = 11
    OLDVAL = 12
    USER = 13
    OUTTEMP = 14
    HUMID = 15
    WIND = 16
    RAIN = 17
    SUN = 18

class KKRP01AClimate(ClimateEntity):

    def __init__(self, hass, name, ip_addr, timeout, target_temp_step, ac_hvac_modes, hvac_modes, hvac_fan_modes, fan_modes, hvac_swing_modes, swing_modes, uid=None):
        _LOGGER.info('Initialize the KKRP01A climate device')
        self.hass = hass
        self._name = name
        self._ip_addr = ip_addr
        self._timeout = timeout

        self._target_temperature = None
        self._target_temperature_old = None
        self._target_temperature_step = target_temp_step
        self._unit_of_measurement = hass.config.units.temperature_unit
        
        self._current_temperature = None

        self._hvac_mode = None
        self._fan_mode = None
        self._fan_mode_old = None
        self._swing_mode = None

        self._hvac_modes = hvac_modes
        self._ac_hvac_modes = ac_hvac_modes
        self._fan_modes = fan_modes
        self._hvac_fan_modes = hvac_fan_modes
        self._swing_modes = swing_modes
        self._hvac_swing_modes = hvac_swing_modes
        if uid:
            self._uid = uid
        else:
            self._uid = 0
        
        self._acOptions = { 'wiON': None,'wiMODE': None,'wiTEMP': None,'wiFUN': None,'wiSWNG': None }

        self._firstTimeRun = True
                
    def FetchResult(self, ip_addr, timeout):
        valuesUrl = "http://" + ip_addr + "/param.csv"
        valuesCsv = requests.get(valuesUrl, allow_redirects=True, timeout=timeout)       
        return valuesCsv.content.decode("utf-8").split(".\r\n")

    def GetValues(self):
        return self.FetchResult(self._ip_addr, self._timeout)

    def SetAcOptions(self, acOptions, newOptionsToOverride, optionValuesToOverride = None):
        if not (optionValuesToOverride is None):
            _LOGGER.info('Setting acOptions with retrieved HVAC values')
            for key in newOptionsToOverride:
                _LOGGER.info('Setting %s: %s' % (key, optionValuesToOverride[newOptionsToOverride.index(key) + 1]))
                acOptions[key] = optionValuesToOverride[newOptionsToOverride.index(key) + 1]
            _LOGGER.info('Done setting acOptions')
        else:
            _LOGGER.info('Overwriting acOptions with new settings')
            for key, value in newOptionsToOverride.items():
                _LOGGER.info('Overwriting %s: %s' % (key, value))
                acOptions[key] = value
            _LOGGER.info('Done overwriting acOptions')
        return acOptions
        
    def SendStateToAc(self, timeout):
        _LOGGER.info('Start sending state to HVAC')
        headers = {'Content-type': 'application/x-www-form-urlencoded'}
        data = self._acOptions.copy()
        
        #replace fun state with control command 
        data['wiFUN'] = HVAC_CTRL_FAN_MODES[int(self._hvac_fan_modes.index(data.get('wiFUN')))]
        
        #modify other states for control command
        for key in data:
          if (key != 'wiTEMP' and key != 'wiFUN'):
            data[key] = data.get(key).capitalize()
        
        #send control commands to AC   
        r = requests.post('http://' + self._ip_addr, headers=headers, data=data, timeout=timeout)
        
    def UpdateHATargetTemperature(self):
        if (self._acOptions['wiON'] == 'ON' and self._acOptions['wiTEMP'] != 'NONE'):
            self._target_temperature = int(self._acOptions['wiTEMP'])
        else:
            self._target_temperature = self._target_temperature_old
        _LOGGER.info('HA target temp set according to HVAC state to: ' + str(self._target_temperature))
    
    def UpdateHAHvacMode(self):
        
        # Sync current HVAC operation mode to HA
        if (self._acOptions['wiON'] == 'ON'):
            self._hvac_mode = self._hvac_modes[int(self._ac_hvac_modes.index(self._acOptions['wiMODE']))]
        else:
            self._hvac_mode = HVAC_MODE_OFF    
        
        _LOGGER.info('HA operation mode set according to HVAC state to: ' + str(self._hvac_mode))

    def UpdateHACurrentSwingMode(self):
        # Sync current HVAC Swing mode state to HA
        self._swing_mode = self._swing_modes[int(self._hvac_swing_modes.index(self._acOptions['wiSWNG']))]
        _LOGGER.info('HA swing mode set to ' + self._swing_mode)

    def UpdateHAFanMode(self):
        # Sync current HVAC Fan mode state to HA    'Auto','1','2','3','4','5'
        if (self._acOptions['wiON'] == 'ON' and self._acOptions['wiFUN'] != 'NONE'):
            self._fan_mode = self._fan_modes[int(self._hvac_fan_modes.index(self._acOptions['wiFUN']))]
        else:
            self._fan_mode = self._fan_modes[int(self._hvac_fan_modes.index(self._fan_mode_old))]
            
        _LOGGER.info('HA fan mode set according to HVAC state to: ' + str(self._fan_mode))

    def UpdateHAStateToCurrentACState(self):
        self.UpdateHATargetTemperature()
        self.UpdateHAHvacMode()
        self.UpdateHACurrentSwingMode()
        self.UpdateHAFanMode()

    def SendState(self, acOptions = {}):
        
        # Overwrite status with our choices
        if not(acOptions == {}):
            self._acOptions = self.SetAcOptions(self._acOptions, acOptions)

        self.SendStateToAc(self._timeout)
        self.UpdateHAStateToCurrentACState()

        _LOGGER.info('Finished SendState')
        return ''

    def SyncState(self):
        #Fetch current settings from HVAC
        _LOGGER.info('Starting SyncState')

        optionsToFetch = ["wiON","wiMODE","wiTEMP","wiFUN","wiSWNG"]
        currentValues = self.GetValues()
        self._current_temperature = float(currentValues[ParamType.ROOMT].replace(',','.'))
        self._target_temperature_old = int(currentValues[ParamType.OLDVAL].split('.')[2])
        self._fan_mode_old = currentValues[ParamType.OLDVAL].split('.')[4]

        if (self._firstTimeRun):
            self._acOptions = self.SetAcOptions(self._acOptions, optionsToFetch, currentValues)
            if (self._acOptions['wiFUN'] == 'NONE'):
                self._acOptions['wiFUN'] = self._fan_mode_old
            if (self._acOptions['wiTEMP'] == 'NONE'):
                self._acOptions['wiTEMP'] = self._target_temperature_old    
            self._firstTimeRun = False
        
        # Set latest status from device
        #self._acOptions = self.SetAcOptions(self._acOptions, optionsToFetch, currentValues)

        # Update HA state to current HVAC state
        self.UpdateHAStateToCurrentACState()

        _LOGGER.info('Finished SyncState')
        return ''

    @property
    def should_poll(self):
        _LOGGER.info('should_poll()')
        # Return the polling state.
        return True

    def update(self):
        _LOGGER.info('update()')
        # Update HA State from Device
        self.SyncState()

    @property
    def name(self):
        _LOGGER.info('name(): ' + str(self._name))
        # Return the name of the climate device.
        return self._name

    @property
    def temperature_unit(self):
        _LOGGER.info('temperature_unit(): ' + str(self._unit_of_measurement))
        # Return the unit of measurement.
        return self._unit_of_measurement

    @property
    def current_temperature(self):
        _LOGGER.info('current_temperature(): ' + str(self._current_temperature))
        # Return the current temperature.
        return self._current_temperature

    @property
    def min_temp(self):
        _LOGGER.info('min_temp(): ' + str(MIN_TEMP))
        # Return the minimum temperature.
        return MIN_TEMP
        
    @property
    def max_temp(self):
        _LOGGER.info('max_temp(): ' + str(MAX_TEMP))
        # Return the maximum temperature.
        return MAX_TEMP
        
    @property
    def target_temperature(self):
        _LOGGER.info('target_temperature(): ' + str(self._target_temperature))
        # Return the temperature we try to reach.
        return self._target_temperature
        
    @property
    def target_temperature_step(self):
        _LOGGER.info('target_temperature_step(): ' + str(self._target_temperature_step))
        # Return the supported step of target temperature.
        return self._target_temperature_step

    @property
    def swing_mode(self):
        _LOGGER.info('swing_mode(): ' + str(self._swing_mode))
        # get the current swing mode
        return self._swing_mode

    @property
    def swing_modes(self):
        _LOGGER.info('swing_modes(): ' + str(self._swing_modes))
        # get the list of available swing modes
        return self._swing_modes

    @property
    def hvac_mode(self):
        _LOGGER.info('hvac_mode(): ' + str(self._hvac_mode))
        # Return current operation mode ie. heat, cool, idle.
        return self._hvac_mode
    
    @property
    def hvac_modes(self):
        _LOGGER.info('hvac_modes(): ' + str(self._hvac_modes))
        # Return the list of available operation modes.
        return self._hvac_modes

    @property
    def fan_mode(self):
        _LOGGER.info('fan_mode(): ' + str(self._fan_mode))
        # Return the fan mode.
        return self._fan_mode

    @property
    def fan_modes(self):
        _LOGGER.info('fan_list(): ' + str(self._fan_modes))
        # Return the list of available fan modes.
        return self._fan_modes
        
    @property
    def supported_features(self):
        _LOGGER.info('supported_features(): ' + str(SUPPORT_FLAGS))
        # Return the list of supported features.
        return SUPPORT_FLAGS        
 
    def set_temperature(self, **kwargs):
        _LOGGER.info('set_temperature(): ' + str(kwargs.get(ATTR_TEMPERATURE)))
        # Set new target temperatures.
        if kwargs.get(ATTR_TEMPERATURE) is not None:
            # do nothing if temperature is none
            if not (self._acOptions['wiON'] == 'OFF'):
                # do nothing if HVAC is switched off
                _LOGGER.info('SendState with wiTEMP=' + str(kwargs.get(ATTR_TEMPERATURE)))
                self.SendState({ 'wiTEMP': int(kwargs.get(ATTR_TEMPERATURE))})
                self.schedule_update_ha_state()

    def set_swing_mode(self, swing_mode):
        _LOGGER.info('Set swing mode(): ' + str(swing_mode))
        # set the swing mode
        if (self._acOptions['wiON'] == 'ON'):
            # do nothing if HVAC is switched off
            _LOGGER.info('SendState with swing mode ' + str(swing_mode))
            self.SendState({'wiSWNG': self._hvac_swing_modes[int(self._swing_modes.index(swing_mode))]})
            self.schedule_update_ha_state()

    def set_fan_mode(self, fan):
        _LOGGER.info('set_fan_mode(): ' + str(fan))
        # Set the fan mode.
        if (self._acOptions['wiON'] == 'ON'):    
            _LOGGER.info('Setting fan mode to ' + self._hvac_fan_modes[int(self._fan_modes.index(fan))])    
            self.SendState({'wiFUN': self._hvac_fan_modes[int(self._fan_modes.index(fan))]})
            self.schedule_update_ha_state()

    def set_hvac_mode(self, hvac_mode):
        _LOGGER.info('set_hvac_mode(): ' + str(hvac_mode))
        # Set new operation mode.
        if (hvac_mode == HVAC_MODE_OFF):
            self.SendState({'wiON': 'OFF'})
        else:
            _LOGGER.info('Setting hvac mode to ' + self._ac_hvac_modes[int(self._hvac_modes.index(hvac_mode))])
            self.SendState({'wiON': 'ON', 'wiMODE': self._ac_hvac_modes[int(self._hvac_modes.index(hvac_mode))]})
        
        self.schedule_update_ha_state()

    @asyncio.coroutine
    def async_added_to_hass(self):
        _LOGGER.info('KKRP01A climate device added to hass()')
        self.SyncState()