"""Tests for Anova client."""

import pytest
import json
import logging
from unittest.mock import AsyncMock

from custom_components.anova_culinary.anova_api.client import AnovaClient
from custom_components.anova_culinary.anova_api.models import DeviceType
from custom_components.anova_culinary.anova_api.exceptions import AnovaConnectionError

@pytest.mark.asyncio
async def test_client_connect(mock_session):
    """Test successful connection."""
    client = AnovaClient("anova-test-token", session=mock_session)
    success = await client.connect()
    
    assert success is True
    mock_session.ws_connect.assert_called_once()
    assert "anova-test-token" in mock_session.ws_connect.call_args[0][0]

@pytest.mark.asyncio
async def test_client_disconnect(mock_session, mock_ws_response):
    """Test close logic."""
    client = AnovaClient("test", session=mock_session)
    await client.connect()
    await client.close()
    
    mock_ws_response.close.assert_called_once()
    mock_session.close.assert_called_once()

@pytest.mark.asyncio
async def test_send_command(mock_session, mock_ws_response):
    """Test sending command."""
    client = AnovaClient("test", session=mock_session)
    await client.connect()
    
    cmd = {"command": "test"}
    await client.send_command(cmd)
    
    mock_ws_response.send_str.assert_called_once_with(json.dumps(cmd))

@pytest.mark.asyncio
async def test_handle_discovery_apc():
    """Test discovery payload updates."""
    client = AnovaClient("test")
    payload = [{
        "cookerId": "APC-123",
        "type": "a7",
        "name": "My Cooker"
    }]
    client._process_discovery(payload, DeviceType.APC)
    
    assert len(client.devices) == 1
    device = client.devices["APC-123"]
    assert device.device_id == "APC-123"
    assert device.type == DeviceType.APC
    
    state = client.get_apc_state("APC-123")
    assert state is not None
    assert state.state == "idle"

@pytest.mark.asyncio
async def test_update_state():
    """Test state update parsing."""
    client = AnovaClient("test")
    
    # Initialize Fake Device
    client._process_discovery([{"cookerId": "APC-123", "type": "a7"}], DeviceType.APC)
    
    # Send mock message
    msg = {
        "command": "EVENT_APC_STATE",
        "payload": {
            "cookerId": "APC-123",
            "state": "cooking",
            "temperature": 55.0,
            "targetTemperature": 60.0
        }
    }
    
    client._handle_message(msg)
    
    state = client.get_apc_state("APC-123")
    assert state.state == "cooking"
    assert state.current_temperature == 55.0
    assert state.target_temperature == 60.0
    assert state.is_running is True
