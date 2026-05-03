"""Sensor platform for Anova API integration."""

from homeassistant.components.sensor import SensorEntity, SensorDeviceClass, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature, UnitOfTime
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN, MANUFACTURER
from .anova_api.client import AnovaClient
from .anova_api.device import AnovaDevice
from .anova_api.product import AnovaProduct

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Anova sensor platform."""
    client: AnovaClient = hass.data[DOMAIN][entry.entry_id]["client"]
    entities = []
    for device_id, device in client.devices.items():
        if device.product == AnovaProduct.APO:
            entities.extend([
                AnovaTimerSensor(client, device),
                AnovaTimerElapsedSensor(client, device),
                AnovaRecipeSensor(client, device),
            ])
        elif device.product == AnovaProduct.APC:
            entities.extend([
                AnovaTimerSensor(client, device),
                AnovaTimerElapsedSensor(client, device)
            ])
            
    async_add_entities(entities)

class AnovaTimerSensor(SensorEntity):
    """Timer remaining sensor."""

    _attr_has_entity_name = True
    _attr_name = "Timer Remaining"
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTime.SECONDS
    _attr_icon = "mdi:timer-outline"

    def __init__(self, client: AnovaClient, device: AnovaDevice) -> None:
        self._client = client
        self._device = device
        self._attr_unique_id = f"{DOMAIN}_{self._device.id}_timer"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._device.id)},
            name=self._device.name,
            manufacturer=MANUFACTURER,
            model=self._device.model,
        )
        self._remove_cb = None

    async def async_added_to_hass(self) -> None:
        self._remove_cb = self._client.register_callback(self._handle_update)

    async def async_will_remove_from_hass(self) -> None:
        if self._remove_cb:
            self._remove_cb()

    @callback
    def _handle_update(self, device_id: str) -> None:
        if device_id != self._device.id:
            return
            
        state = self._client.get_apo_state(self._device.id) or self._client.get_apc_state(self._device.id)
        if state:
            try:
                timer = None
                if hasattr(state, "nodes"):
                    timer = state.nodes.timer_remaining
                elif hasattr(state, "timer"):
                    timer = state.timer.remaining
                
                if timer is not None:
                    self._attr_native_value = int(timer)
                    self.async_write_ha_state()
            except Exception:
                pass

class AnovaRecipeSensor(SensorEntity):
    """Active recipe sensor for APO."""

    _attr_has_entity_name = True
    _attr_name = "Recipe"
    _attr_icon = "mdi:text-box-outline"

    def __init__(self, client: AnovaClient, device: AnovaDevice) -> None:
        self._client = client
        self._device = device
        self._attr_unique_id = f"{DOMAIN}_{self._device.id}_recipe"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._device.id)},
            name=self._device.name,
            manufacturer=MANUFACTURER,
            model=self._device.model,
        )
        self._remove_cb = None
        self._attr_native_value = "Manual"

    async def async_added_to_hass(self) -> None:
        self._remove_cb = self._client.register_callback(self._handle_update)

    async def async_will_remove_from_hass(self) -> None:
        if self._remove_cb:
            self._remove_cb()

    @callback
    def _handle_update(self, device_id: str) -> None:
        if device_id != self._device.id:
            return
        state = self._client.get_apo_state(self._device.id)
        if state:
            recipe_title = "Manual"
            if state.is_running and state.cook and state.cook.recipe and state.cook.recipe.title:
                recipe_title = state.cook.recipe.title
                
            if self._attr_native_value != recipe_title:
                self._attr_native_value = recipe_title
                self.async_write_ha_state()

class AnovaTimerElapsedSensor(SensorEntity):
    """Timer elapsed sensor."""

    _attr_has_entity_name = True
    _attr_name = "Timer Elapsed"
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTime.SECONDS
    _attr_icon = "mdi:timer-sand-complete"

    def __init__(self, client: AnovaClient, device: AnovaDevice) -> None:
        self._client = client
        self._device = device
        self._attr_unique_id = f"{DOMAIN}_{self._device.id}_timer_elapsed"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._device.id)},
            name=self._device.name,
            manufacturer=MANUFACTURER,
            model=self._device.model,
        )
        self._remove_cb = None

    async def async_added_to_hass(self) -> None:
        self._remove_cb = self._client.register_callback(self._handle_update)

    async def async_will_remove_from_hass(self) -> None:
        if self._remove_cb:
            self._remove_cb()

    @callback
    def _handle_update(self, device_id: str) -> None:
        if device_id != self._device.id:
            return
            
        state = self._client.get_apo_state(self._device.id) or self._client.get_apc_state(self._device.id)
        cook = getattr(state, "cook", None)
        if state and cook and cook.cook_started_timestamp:
            try:
                from datetime import datetime, timezone
                # Parse Anova's ISO 8601 string: 2026-04-12T05:16:14Z
                started = datetime.strptime(state.cook.cook_started_timestamp, "%Y-%m-%dT%H:%M:%SZ")
                started = started.replace(tzinfo=timezone.utc)
                now = datetime.now(timezone.utc)
                
                elapsed = max(0, (now - started).total_seconds())
                self._attr_native_value = int(elapsed)
                self.async_write_ha_state()
            except Exception:
                pass
        elif not state or not state.is_running:
            self._attr_native_value = 0
            self.async_write_ha_state()
