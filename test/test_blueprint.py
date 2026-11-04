"""Tests for the oven alerts blueprint, run as an automation."""

import shutil
from pathlib import Path

import pytest
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import async_mock_service

from conftest import OVEN_ID, oven_state

BLUEPRINT = Path(__file__).parent.parent / "blueprints/automation/anova_culinary/oven_alerts.yaml"


@pytest.fixture
async def notified(hass, sent, tmp_path):
    """The blueprint as an automation for the test oven; returns the notifications it sends."""
    hass.config.config_dir = str(tmp_path)
    target = tmp_path / "blueprints/automation/anova_culinary/oven_alerts.yaml"
    target.parent.mkdir(parents=True)
    shutil.copy(BLUEPRINT, target)
    calls = async_mock_service(hass, "notify", "phones")
    assert await async_setup_component(
        hass,
        "automation",
        {
            "automation": {
                "use_blueprint": {
                    "path": "anova_culinary/oven_alerts.yaml",
                    "input": {
                        "status": "sensor.test_oven_stage_status",
                        "continue_button": "button.test_oven_continue",
                        "water_tank": "binary_sensor.test_oven_water_tank_empty",
                        "notify": "notify.phones",
                    },
                }
            }
        },
    )
    await hass.async_block_till_done()
    return calls


async def push(hass, client, state) -> None:
    client.devices[OVEN_ID].update(state)
    await hass.async_block_till_done()


async def test_preheated_with_continue(hass, sent, client, notified) -> None:
    """Preheated with a timer waiting on food: a notification whose action presses Continue."""
    state = oven_state()
    state["cook"]["activeStageMode"] = "running"
    await push(hass, client, state)
    assert len(notified) == 1
    data = notified[0].data
    assert data["title"] == "Test Oven"
    assert data["message"].startswith("Preheated. Put the food in")
    [action] = data["data"]["actions"]
    assert action == {"action": "ANOVA_CONTINUE_button.test_oven_continue", "title": "Start timer now"}
    hass.bus.async_fire("mobile_app_notification_action", {"action": "SOMETHING_ELSE"})
    hass.bus.async_fire("mobile_app_notification_action", {"action": action["action"]})
    await hass.async_block_till_done()
    assert sent.commands == [("CMD_APO_START_STAGE", {"stageId": state["cook"]["activeStageId"]})]


async def test_holding_and_water(hass, sent, client, notified) -> None:
    """Done (holding) has no action; the water tank emptying is told too; preheating isn't by default."""
    state = oven_state()
    state["cook"]["activeStageMode"] = "running"
    state["nodes"]["timer"] = {"mode": "completed"}
    state["nodes"]["waterTank"]["empty"] = True
    await push(hass, client, state)
    messages = sorted(call.data["message"] for call in notified)
    assert messages == ["Done. The oven is holding its temperature.", "The water tank is empty."]
    assert all("actions" not in call.data["data"] for call in notified)


async def test_stage_done_names_it(hass, sent, client, notified) -> None:
    """A finished stage before a manual one names the stage, with Start next stage."""
    state = oven_state()
    state["cook"]["activeStageMode"] = "running"
    first = state["cook"]["stages"][0]
    first["exit"] = {"conditions": {"and": {"userAction": {"=": True}}}}
    state["cook"]["stages"].append({**first, "id": "stage-2"})
    state["nodes"]["timer"] = {"mode": "completed"}
    await push(hass, client, state)
    [call] = notified
    assert call.data["message"] == "Stage 1 of 2 is done. Start the next stage when you're ready."
    assert call.data["data"]["actions"][0]["title"] == "Start next stage"
