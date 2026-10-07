"""Climate platform for Anova Precision Ovens: the oven itself, and its probe."""

from typing import Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import AnovaConfigEntry
from .anova_api import AnovaDevice, AnovaPODevice
from .anova_api.apo import AnovaPOStage, limits
from .entity import AnovaEntity, AnovaEntityDescription, async_setup_device_entities

PARALLEL_UPDATES = 0

# The oven's target before one is set, as the app's default (350 °F)
DEFAULT_TARGET = 176.67

OVEN = AnovaEntityDescription(key="", name=None, translation_key="oven")
PROBE = AnovaEntityDescription(
    key="probe",
    translation_key="probe",
    available_fn=lambda oven: oven.is_cooking and oven.state.nodes.temperature_probe.connected,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AnovaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Anova climate platform."""

    def entities_for(device: AnovaDevice) -> list[ClimateEntity]:
        if not isinstance(device, AnovaPODevice):
            return []
        return [AnovaOven(device, OVEN), AnovaProbe(device, PROBE)]

    async_setup_device_entities(hass, entry, async_add_entities, entities_for)


class AnovaOven(AnovaEntity[AnovaPODevice], ClimateEntity):
    """Representation of an Anova Precision Oven: heat to a target, or off.

    While off, a target is only remembered; turning on starts a one-stage cook at it.
    """

    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.TURN_ON | ClimateEntityFeature.TURN_OFF
    )
    _attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT]
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_target_temperature = DEFAULT_TARGET

    @property
    def current_temperature(self) -> float | None:
        """The cavity temperature."""
        return self.device.temperature

    @property
    def target_temperature(self) -> float | None:
        """The running stage's target, or the one remembered while off."""
        stage = self.device.current_stage
        return stage.temperature if stage else self._attr_target_temperature

    @property
    def min_temp(self) -> float:
        """Return the minimum temperature."""
        return limits.TEMPERATURE_MIN

    @property
    def max_temp(self) -> float:
        """Return the maximum temperature for the running stage's settings."""
        stage = self.device.current_stage
        return limits.stage_range(stage)[1] if stage else limits.DRY_MAX

    @property
    def hvac_mode(self) -> HVACMode:
        """Heat while cooking."""
        return HVACMode.HEAT if self.device.is_cooking else HVACMode.OFF

    @property
    def hvac_action(self) -> HVACAction:
        """Heating while cooking."""
        return HVACAction.HEATING if self.device.is_cooking else HVACAction.IDLE

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set new target temperature."""
        temperature = kwargs[ATTR_TEMPERATURE]
        if not self.device.is_cooking:
            self._attr_target_temperature = temperature
            self.async_write_ha_state()
            return
        await self._call(self.device.set_temperature(temperature))

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Start a one-stage cook at the target, or stop."""
        if hvac_mode == HVACMode.OFF:
            await self._call(self.device.stop())
        elif not self.device.is_cooking:
            await self._call(self.device.start_manual(AnovaPOStage(temperature=self._attr_target_temperature)))

    async def async_turn_on(self) -> None:
        """Turn the entity on."""
        await self.async_set_hvac_mode(HVACMode.HEAT)

    async def async_turn_off(self) -> None:
        """Turn the entity off."""
        await self.async_set_hvac_mode(HVACMode.OFF)


class AnovaProbe(AnovaEntity[AnovaPODevice], ClimateEntity):
    """Representation of an Anova Physical Probe target."""

    _attr_supported_features = ClimateEntityFeature.TARGET_TEMPERATURE
    _attr_hvac_modes = [HVACMode.HEAT]
    _attr_hvac_mode = HVACMode.HEAT
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_min_temp = limits.PROBE_MIN
    _attr_max_temp = limits.PROBE_MAX

    @property
    def current_temperature(self) -> float | None:
        """The probe's temperature."""
        return self.device.probe_temperature

    @property
    def target_temperature(self) -> float | None:
        """The running stage's probe target."""
        return self.device.probe_target

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set the probe target."""
        await self._call(self.device.set_probe(kwargs[ATTR_TEMPERATURE]))

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """The probe has one mode."""
