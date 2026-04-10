"""Tests for the Anova bidirectional transpiler engine."""

import sys
import os
import pytest
import json

# Bypass the root anova_culinary __init__.py so we don't trigger homeassistant core dependencies
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../custom_components/anova_culinary')))

from anova_api.apo import (
    payload_to_state,
    recipe_to_cook,
    cook_to_payload,
    APORecipe, APOStage, APOTimer, APOTimerTrigger, 
    APOHeatingElement, APOFanSpeed
)
from anova_api.device import AnovaDevice, DeviceType

RAW_V2_PAYLOAD = {
    'nodes': {
        'wasteWaterTank': {'full': False, 'removed': False}, 
        'temperatureProbe': {'current': {'celsius': 0}, 'ntcConnected': True, 'connected': False}, 
        'exhaustFan': {'speed': 'off', 'dc12VStatus': 'no-error', 'numberOfOverCurrent': 0}, 
        'temperatureBulbs': {
            'wet': {'setpoint': {'celsius': 54.44}, 'current': {'celsius': 24.96}, 'numberOfOverCurrent': 0, 'dc12VInletStatus': 'no-error', 'ntcConnected': True, 'dosed': False}, 
            'dryBottom': {'current': {'celsius': 23.29}, 'numberOfOverCurrent': 0, 'ntcConnected': True}, 
            'dryTop': {'numberOfOverCurrent': 0, 'current': {'celsius': 23.39}, 'ntcConnected': True}, 
            'mode': 'wet', 
            'dry': {'numberOfOverCurrent': 0, 'current': {'celsius': 23.39}}
        }, 
        'steamGenerators': {
            'boiler': {'numberOfOverCurrentOutletValveDescale': 0, 'descaleRequired': False, 'numberOfOverCurrentInletPump': 0, 'ntcConnected': True, 'dc12VInletPumpStatus': 'no-error', 'failed': False, 'celsius': 37.35, 'dosed': False, 'dc12VOutletValveDescaleStatus': 'no-error', 'watts': 600, 'usageHours': 17.4}, 
            'evaporator': {'watts': 0, 'failed': False, 'celsius': 24.33, 'usageHours': 9, 'ntcConnected': True}, 
            'relativeHumidity': {'setpoint': 100, 'current': 112}, 
            'mode': 'relative-humidity'
        }, 
        'cavityCamera': {'isEmpty': True, 'streaming': False, 'detection': '', 'lastDetectionMillis': 1264600361, 'enabled': True}, 
        'heatingElements': {
            'rear': {'watts': 1200, 'on': True, 'failed': False, 'usageHours': 2525.5}, 
            'bottom': {'watts': 0, 'usageHours': 346.7, 'on': False, 'failed': False}, 
            'top': {'failed': False, 'on': False, 'watts': 0, 'usageHours': 1137.9}
        }, 
        'waterTank': {'removed': False, 'empty': False, 'low': False}, 
        'displayFan': {'dc12VStatus': 'no-error', 'speed': 'mid', 'numberOfOverCurrent': 0}, 
        'powerBoardFan': {'numberOfOverCurrent': 0, 'dc12VStatus': 'no-error', 'on': False}, 
        'exhaustVent': {'dc12VStatus': 'no-error', 'state': 'closed', 'numberOfOverCurrent': 0}, 
        'fan': {'failed': False, 'speed': 'max'}, 
        'ledFan': {'numberOfOverCurrent': 1, 'speed': 'mid', 'dc12VStatus': 'no-error'}, 
        'dc12VLine': {'numberOfFaults': 0, 'numberOfRejections': 0}, 
        'timer': {'initial': 300, 'mode': 'idle'}, 
        'displayBoard': {'celsius': 38.6}, 
        'doorLamp': {'preferences': 'on', 'on': True}, 
        'door': {'closed': True}, 
        'cavityLamp': {'on': False}
    }, 
    'cook': {
        'activeStageStartedTimestamp': '2026-04-09T22:44:11Z', 
        'stages': [
            {
                'do': {
                    'exhaustVent': {'state': 'closed'}, 
                    'type': 'cook', 
                    'steamGenerators': {'relativeHumidity': {'setpoint': 100}, 'mode': 'relative-humidity'}, 
                    'heatingElements': {'rear': {'on': True}, 'top': {'on': False}, 'bottom': {'on': False}}, 
                    'temperatureBulbs': {'wet': {'setpoint': {'celsius': 54.44}}, 'mode': 'wet'}, 
                    'timer': {'entry': {'conditions': {'or': {'userAction': {'=': True}, 'nodes.cavityCamera.isEmpty': {'=': False}}}}, 'initial': 300}, 
                    'fan': {'speed': 100}
                }, 
                'title': '', 
                'id': 'android-7511275c-3bde-4204-bc3d-82eb3d2792ba', 
                'exit': {'conditions': {'and': {'nodes.timer.mode': {'=': 'completed'}}}}, 
                'entry': {'conditions': {'and': {'nodes.temperatureBulbs.wet.current.celsius': {'>=': 54.44}}}}
            }
        ], 
        'rackPosition': 3, 
        'startedTimestamp': '2026-04-09T22:44:11Z', 
        'activeStageMode': 'entering', 
        'originSource': 'android', 
        'cookId': 'android-8e059d1a-1a1c-4075-8146-d4e0f7c2bff4', 
        'cookableId': 'MXuqSXSO9w9qDs4rpdhZ', 
        'activeStageIndex': 0, 
        'cookableType': 'manual', 
        'cookTitle': '', 
        'activeStageId': 'android-7511275c-3bde-4204-bc3d-82eb3d2792ba'
    }, 
    'systemInfo': {'firmwareUpdatedTimestamp': '2026-01-12T09:30:59Z', 'deviceId': '0123d1e411114d5401', 'ramFree': 2939, 'online': True, 'flashFree': 6892, 'firmwareVersion': '11_225_1.4.2_01.01.26', 'lastDisconnectedTimestamp': '2026-03-25T19:10:00Z', 'powerMains': 120, 'lastConnectedTimestamp': '2025-11-18T07:21:36Z', 'powerHertz': 60, 'releaseTrack': 'production', 'hardwareVersion': 'nxpke1-i500'}, 
    'state': {'cavityOverheated': False, 'temperatureUnit': 'F', 'mode': 'cook'}, 
    'updatedTimestamp': '2026-04-09T22:44:29.431Z', 
    'version': 2
}

def test_payload_to_state():
    """Verify raw json parses robustly into APONodes and APOCook."""
    state = payload_to_state(RAW_V2_PAYLOAD)
    
    # 1. Verify Nodes Engine mapped core flats
    assert state.nodes.rear_heater_watts == 1200
    assert state.nodes.current_wet_temp == 24.96
    assert state.nodes.setpoint_wet_temp == 54.44
    assert state.nodes.boiler_celsius == 37.35
    assert state.nodes.water_tank_empty is False
    assert state.nodes.cavity_camera_is_empty is True
    assert state.nodes.exhaust_fan_speed == "off"
    assert state.nodes.display_board_celsius == 38.6
    
    # 2. Verify state inferencer mapped global constraints
    assert state.is_running is True 
    assert state.state == "cook" # Pulled from raw_payload.state.mode fallback inside parser since state.status wasn't present
    
    # 3. Verify inner Cook Logic Engine
    assert state.cook is not None
    assert state.cook.cook_id == 'android-8e059d1a-1a1c-4075-8146-d4e0f7c2bff4'
    assert state.cook.active_stage_index == 0
    assert len(state.cook.recipe.stages) == 1
    
    stage = state.cook.recipe.stages[0]
    assert stage.id == 'android-7511275c-3bde-4204-bc3d-82eb3d2792ba'
    assert stage.sous_vide is True
    assert stage.temperature == 54.44
    assert stage.steam == 100
    assert stage.heating_elements == APOHeatingElement.REAR
    assert stage.fan == APOFanSpeed.HIGH
    
    # 4. Verify Advance Conditions decoded 
    assert isinstance(stage.advance, APOTimer)
    assert stage.advance.duration == 300
    assert stage.advance.trigger == APOTimerTrigger.FOOD_DETECTED

def test_recipe_to_cook():
    """Verify static schemas convert to live proxies seamlessly."""
    recipe = APORecipe(
        stages=[
            APOStage(
                sous_vide=True, 
                temperature=60.0, 
                steam=100, 
                advance=APOTimer(duration=1800, trigger=APOTimerTrigger.PREHEATED)
            ),
            APOStage(
                sous_vide=False, 
                temperature=200.0, 
                heating_elements=APOHeatingElement.TOP_REAR,
                fan=APOFanSpeed.MEDIUM
            )
        ]
    )
    
    cook = recipe_to_cook(recipe)
    
    # Validate proxy instantiation
    assert cook.cook_id != ""
    assert cook.active_stage_index == 0
    
    # Validate UUID generation for missing tracking IDs
    for stage in cook.recipe.stages:
        assert stage.id != ""
        assert len(stage.id) == 36 # UUID standard
        
    assert len(cook.recipe.stages) == 2
    assert cook.active_stage_id == cook.recipe.stages[0].id

def test_cook_to_payload():
    """Verify live proxies compile purely into Anova intent bytes (stripping nodes)."""
    recipe = APORecipe(
        stages=[
            APOStage(
                id="static-unit-test-1",
                sous_vide=False, 
                temperature=175.0, 
                heating_elements=APOHeatingElement.REAR,
                fan=APOFanSpeed.MEDIUM,
                advance=APOTimer(duration=600, trigger=APOTimerTrigger.MANUALLY)
            )
        ]
    )
    cook = recipe_to_cook(recipe)
    
    device = AnovaDevice(
        device_id="dummy_device_id",
        type=DeviceType.APO,
        model="oven_v2",
        name="Test Oven"
    )
    
    payload = cook_to_payload(cook, device)
    
    assert "type" in payload
    assert payload["type"] == "oven_v2"
    assert payload["cookerId"] == "dummy_device_id"
    assert len(payload["stages"]) == 1
    
    stg = payload["stages"][0]
    assert stg["id"] == "static-unit-test-1"
    
    # Verify exact schema constraints 
    do_block = stg["do"]
    assert do_block["fan"]["speed"] == 50 # Converted from MEDIUM
    assert do_block["heatingElements"]["top"]["on"] is False
    assert do_block["heatingElements"]["bottom"]["on"] is False
    assert do_block["heatingElements"]["rear"]["on"] is True
    assert do_block["temperatureBulbs"]["mode"] == "dry"
    assert do_block["temperatureBulbs"]["dry"]["setpoint"]["celsius"] == 175.0
    
    # Verify condition formatting
    assert do_block["timer"]["initial"] == 600
    assert do_block["timer"]["entry"]["conditions"]["or"]["userAction"]["="] is True # Manually trigger natively mapped to userAction
    # Node telemetry MUST NOT EXIST in upstream payload
    assert "nodes" not in payload
