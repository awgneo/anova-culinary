"""Humidifier platform for Anova Precision Ovens."""

from typing import Any

from homeassistant.components.humidifier import HumidifierEntity, HumidifierDeviceClass
from homeassistant.components.humidifier.const import HumidifierEntityFeature
from homeassistant.config_entries import ConfigEntry
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
    """Set up the Anova humidifier platform."""
    client: AnovaClient = hass.data[DOMAIN][entry.entry_id]["client"]
    
    entities = []
    for device_id, device in client.devices.items():
        if device.product == AnovaProduct.APO:
            entities.append(AnovaSteamHumidifier(client, device))
            
    async_add_entities(entities)


class AnovaSteamHumidifier(HumidifierEntity):
    """Humidifier entity for Anova Precision Oven steam control."""

    _attr_has_entity_name = True
    _attr_name = "Steam"
    _attr_icon = "mdi:water"
    _attr_device_class = HumidifierDeviceClass.HUMIDIFIER
    _attr_supported_features = HumidifierEntityFeature.MODES

    def __init__(self, client: AnovaClient, device: AnovaDevice) -> None:
        """Initialize."""
        self._client = client
        self._device = device
        self._attr_unique_id = f"{DOMAIN}_{self._device.id}_steam"
        
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._device.id)},
            name=device.name,
            manufacturer=MANUFACTURER,
            model=device.model,
        )
        self._attr_target_humidity = 0
        self._attr_is_on = False
        self._remove_cb = None

    @property
    def min_humidity(self) -> int:
        """Return the minimum humidity."""
        return 0

    @property
    def max_humidity(self) -> int:
        """Return the maximum humidity."""
        return 100
        
    @property
    def available_modes(self) -> list[str]:
        """Return a list of available modes."""
        return ["relative-humidity", "steamPercentage"]

    async def async_added_to_hass(self) -> None:
        """Register callbacks."""
        self._remove_cb = self._client.register_callback(self._handle_update)
        self._handle_update(self._device.id)

    async def async_will_remove_from_hass(self) -> None:
        """Clean up."""
        if self._remove_cb:
            self._remove_cb()

    @callback
    def _handle_update(self, device_id: str) -> None:
        """Handle updated data from the websocket."""
        if device_id != self._device.id:
            return
            
        state = self._client.get_apo_state(self._device.id)
        if not state or not state.cook:
            return

        self._attr_available = state.is_running

        try:
            curr_stage = state.cook.current_stage
            if curr_stage:
                self._attr_target_humidity = int(curr_stage.steam)
                self._attr_is_on = curr_stage.steam > 0
                self._attr_mode = state.nodes.steam_generators_mode
        except Exception:
            pass
            
        self.async_write_ha_state()

    async def async_set_humidity(self, humidity: int) -> None:
        """Set new target humidity."""
        cook = self._client.get_current_cook(self._device.id)
        if cook and cook.current_stage:
            cook.current_stage.steam = humidity
            await self._client.play_cook(self._device.id, cook)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the entity on."""
        cook = self._client.get_current_cook(self._device.id)
        if cook and cook.current_stage:
            # When turning on, if humidity was 0, default to 100
            if cook.current_stage.steam == 0:
                cook.current_stage.steam = 100
            await self._client.play_cook(self._device.id, cook)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the entity off."""
        cook = self._client.get_current_cook(self._device.id)
        if cook and cook.current_stage:
            cook.current_stage.steam = 0
            await self._client.play_cook(self._device.id, cook)

    async def async_set_mode(self, mode: str) -> None:
        """Set new target mode."""
        # The mode here corresponds to boiler vs evaporator conceptually,
        # but realistically Anova API manages mode via sous vide bool or natively.
        # This is a stub for HA compliance if they try to select mode.
        pass
