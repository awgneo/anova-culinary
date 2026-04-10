"""Sensor platform for Anova API integration."""

from homeassistant.components.sensor import SensorEntity, SensorDeviceClass, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature, UnitOfTime
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN
from .anova_api.client import AnovaClient
from .anova_api.device import DeviceType


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Anova sensor platform."""
    client: AnovaClient = hass.data[DOMAIN][entry.entry_id]["client"]
    entities = []
    for device_id, device in client.devices.items():
        if device.type == DeviceType.APO:
            entities.extend([
                AnovaProbeSensor(client, device_id, device.name, device.model),
                AnovaTimerSensor(client, device_id, device.name, device.model),
            ])
        elif device.type == DeviceType.APC:
            entities.append(AnovaTimerSensor(client, device_id, device.name, device.model))
            
    async_add_entities(entities)


class AnovaProbeSensor(SensorEntity):
    """Probe temperature sensor for APO."""

    _attr_has_entity_name = True
    _attr_name = "Probe Temperature"
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS

    def __init__(self, client: AnovaClient, device_id: str, name: str, model: str) -> None:
        self._client = client
        self._device_id = device_id
        self._attr_unique_id = f"anova_apo_{device_id}_probe"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, device_id)})
        self._remove_cb = None

    async def async_added_to_hass(self) -> None:
        self._remove_cb = self._client.register_callback(self._handle_update)

    async def async_will_remove_from_hass(self) -> None:
        if self._remove_cb:
            self._remove_cb()

    @callback
    def _handle_update(self, device_id: str, payload: dict) -> None:
        if device_id != self._device_id:
            return
        state = self._client.get_apo_state(self._device_id)
        if state:
            try:
                probe_temp = state.raw_state.get("payload", {}).get("probe", {}).get("current", {}).get("celsius")
                if probe_temp is not None:
                    self._attr_native_value = probe_temp
                    self.async_write_ha_state()
            except Exception:
                pass


class AnovaTimerSensor(SensorEntity):
    """Timer remaining sensor."""

    _attr_has_entity_name = True
    _attr_name = "Timer Remaining"
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTime.SECONDS
    _attr_icon = "mdi:timer-outline"

    def __init__(self, client: AnovaClient, device_id: str, name: str, model: str) -> None:
        self._client = client
        self._device_id = device_id
        self._attr_unique_id = f"anova_{device_id}_timer"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, device_id)})
        self._remove_cb = None

    async def async_added_to_hass(self) -> None:
        self._remove_cb = self._client.register_callback(self._handle_update)

    async def async_will_remove_from_hass(self) -> None:
        if self._remove_cb:
            self._remove_cb()

    @callback
    def _handle_update(self, device_id: str, payload: dict) -> None:
        if device_id != self._device_id:
            return
            
        state = self._client.get_apo_state(self._device_id) or self._client.get_apc_state(self._device_id)
        if state and hasattr(state, 'raw_state'):
            try:
                timer = state.raw_state.get("payload", {}).get("timer", {}).get("remaining")
                if timer is not None:
                    self._attr_native_value = timer
                    self.async_write_ha_state()
            except Exception:
                pass
