"""A Precision Oven 2.0: its state, the running stage, and every control the app offers.

Controls on a running cook change the active stage with the app's own commands (PROTOCOL.md,
part 2, §3.2); a change those can't express (the timer's start) resends the stages, as the
app's stage editor does.
"""

from __future__ import annotations

import time
from functools import cached_property
from datetime import UTC, datetime
from typing import Any, ClassVar

from ..device import AnovaDevice
from ..exceptions import AnovaValidationError
from ..product import AnovaProduct
from . import commands, limits
from .models import (
    AnovaPOFanSpeed,
    AnovaPOHeatingElement,
    AnovaPORecipe,
    AnovaPOStage,
    AnovaPOTimerTrigger,
)
from .recipe import recipe_from_cook, stage_from_payload, stages_to_payload, with_timer_trigger
from .state import AnovaPOState
from .stream import AnovaPOLiveStream

# How long a lamp change shows before the oven confirms it
LAMP_PENDING = 3.0
# Steam turned back on without a setting seen before
DEFAULT_STEAM = 100


class AnovaPODevice(AnovaDevice[AnovaPOState]):
    """An Anova Precision Oven 2.0."""

    product: ClassVar[AnovaProduct] = AnovaProduct.APO
    state_class = AnovaPOState
    models: ClassVar[dict[str, str]] = {commands.OVEN_TYPE: "Anova Precision Oven 2.0"}

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize."""
        super().__init__(*args, **kwargs)
        self._lamp_pending: tuple[bool, float] | None = None
        self._last_steam = DEFAULT_STEAM

    def update(self, state: dict[str, Any]) -> None:
        """Takes a state event's state, remembering the last steam setting."""
        super().update(state)
        if (stage := self.current_stage) is not None and stage.steam > 0:
            self._last_steam = stage.steam

    @cached_property
    def live_stream(self) -> AnovaPOLiveStream:
        """The cavity camera's stream."""
        return AnovaPOLiveStream(self, self._client.session)

    @property
    def is_cooking(self) -> bool:
        """Whether a cook is running."""
        return self.state is not None and self.state.is_cooking

    @property
    def recipe(self) -> AnovaPORecipe | None:
        """The running cook as a recipe (the app's or ours)."""
        if not self.is_cooking:
            return None
        return recipe_from_cook(self.state.cook)

    @property
    def current_stage(self) -> AnovaPOStage | None:
        """The running stage, in the recipe format."""
        if not self.is_cooking or (stage := self.state.cook.active_stage) is None:
            return None
        return stage_from_payload(stage)

    @property
    def temperature(self) -> float | None:
        """The cavity temperature on the bulb the oven regulates (dry unless sous vide)."""
        if self.state is None:
            return None
        return self.state.nodes.temperature_bulbs.active.current.celsius

    @property
    def probe_temperature(self) -> float | None:
        """The probe's temperature, while it's plugged in."""
        probe = self.state.nodes.temperature_probe if self.state else None
        return probe.current.celsius if probe and probe.connected and probe.current else None

    @property
    def probe_target(self) -> float | None:
        """The running stage's probe target, if it has one."""
        stage = self.state.cook.active_stage if self.is_cooking else None
        celsius = ((stage or {}).get("do", {}).get("temperatureProbe") or {}).get("setpoint", {}).get("celsius")
        return celsius or None

    @property
    def timer_remaining(self) -> int | None:
        """Seconds left on the running stage's timer."""
        return self.state.nodes.timer.remaining(datetime.now(UTC)) if self.state else None

    @property
    def lamp_on(self) -> bool:
        """Whether the light is on, showing a change until the oven confirms it."""
        actual = self.state.nodes.door_lamp.on if self.state else False
        if self._lamp_pending is not None:
            wanted, since = self._lamp_pending
            if wanted != actual and time.monotonic() - since < LAMP_PENDING:
                return wanted
            self._lamp_pending = None
        return actual

    async def start_recipe(self, recipe: AnovaPORecipe, cookable_type: str = "recipe") -> None:
        """Starts a cook from a recipe; every start is a new cook."""
        if not recipe.stages:
            raise AnovaValidationError("A recipe needs at least one stage")
        await self._request(
            commands.build_start_command(self.id, stages_to_payload(recipe.stages), recipe.title, cookable_type)
        )

    async def start_manual(self, stage: AnovaPOStage) -> None:
        """Starts a one-stage cook, as setting a temperature in the app does."""
        await self.start_recipe(AnovaPORecipe(stages=[stage]), cookable_type="manual")

    async def stop(self) -> None:
        """Stops the cook."""
        await self._request(commands.build_stop_command(self.id))

    async def set_temperature(self, celsius: float) -> None:
        """Changes the running stage's target."""
        stage = self._running_stage()
        limits.validate_temperature(stage, celsius)
        await self._request(commands.build_set_temperature_bulbs_command(self.id, stage.mode, celsius))

    async def set_sous_vide(self, on: bool) -> None:
        """Switches the running stage between sous vide (wet bulb) and dry heat, keeping its
        target within the new mode's range. Sous vide runs the fan on high."""
        stage = self._running_stage()
        if stage.sous_vide == on:
            return
        changed = AnovaPOStage(sous_vide=on, heating_elements=stage.heating_elements, steam=stage.steam, fan=stage.fan)
        low, high = limits.stage_range(changed)
        await self._raise_fan(changed)
        await self._request(
            commands.build_set_temperature_bulbs_command(self.id, changed.mode, min(max(stage.celsius, low), high))
        )

    async def set_steam(self, setpoint: int) -> None:
        """Changes the running stage's steam (0 turns it off). Steam runs the fan on high."""
        stage = self._running_stage()
        limits.validate_steam(setpoint)
        stage.steam = setpoint
        await self._raise_fan(stage)
        await self._request(
            commands.build_set_steam_generators_command(self.id, limits.steam_mode(stage.celsius), setpoint)
        )

    async def set_steam_enabled(self, on: bool) -> None:
        """Turns the running stage's steam off, or back on at its last setting."""
        await self.set_steam(self._last_steam if on else 0)

    async def set_fan(self, fan: AnovaPOFanSpeed) -> None:
        """Changes the running stage's fan, within what its other settings allow."""
        stage = self._running_stage()
        if fan not in limits.allowed_fans(stage.sous_vide, stage.heating_elements, stage.steam):
            raise AnovaValidationError("Steam, sous vide and the rear element need the fan on high")
        stage.fan = fan
        limits.validate_temperature(stage, stage.celsius)
        await self._request(commands.build_set_fan_command(self.id, fan.speed))

    async def set_heating_elements(self, elements: AnovaPOHeatingElement) -> None:
        """Changes the running stage's elements, raising the fan to high first if they need it."""
        stage = self._running_stage()
        stage.heating_elements = elements
        await self._raise_fan(stage)
        limits.validate_temperature(stage, stage.celsius)
        await self._request(
            commands.build_set_heating_elements_command(self.id, elements.top, elements.bottom, elements.rear)
        )

    async def set_timer(self, seconds: int) -> None:
        """Changes the running stage's timer length, leaving when it starts alone."""
        self._running_stage()
        limits.validate_timer(seconds)
        await self._request(commands.build_set_timer_command(self.id, seconds))

    async def set_timer_trigger(self, trigger: AnovaPOTimerTrigger) -> None:
        """Changes when the running stage's timer starts, by resending the stages as the app's
        editor does (no command changes it alone)."""
        self._running_stage()
        cook = self.state.cook
        stages = [
            with_timer_trigger(stage, trigger) if stage is cook.active_stage else stage for stage in cook.stages
        ]
        await self._request(commands.build_update_cook_stages_command(self.id, stages))

    async def set_probe(self, celsius: float | None) -> None:
        """Sets or clears (None) the running stage's probe target."""
        self._running_stage()
        if celsius is not None:
            limits.validate_probe(celsius)
        await self._request(commands.build_set_probe_command(self.id, celsius or 0))

    async def set_lamp(self, on: bool) -> None:
        """Turns the light on or off."""
        self._lamp_pending = (on, time.monotonic())
        self.notify()
        await self._request(commands.build_set_lamp_command(self.id, on))

    async def start_descale(self) -> None:
        """Starts descaling the steam boiler."""
        if self.is_cooking:
            raise AnovaValidationError("The oven can't descale while cooking")
        await self._request(commands.build_start_descale_command(self.id))

    async def start_live_stream(self) -> str:
        """Starts (or keeps alive) the camera stream; returns its WebRTC (WHEP) URL."""
        response = await self._request(commands.build_start_live_stream_command(self.id))
        return response["data"]["webRTCPlayback"]["url"]

    async def stop_live_stream(self) -> None:
        """Stops the camera stream."""
        await self._request(commands.build_stop_live_stream_command(self.id))

    def _running_stage(self) -> AnovaPOStage:
        """The running stage; controls other than the light need one."""
        if (stage := self.current_stage) is None:
            raise AnovaValidationError("No cook is running")
        return stage

    async def _raise_fan(self, stage: AnovaPOStage) -> None:
        """Sets the fan to high when `stage`'s settings require it and it isn't."""
        if stage.fan not in limits.allowed_fans(stage.sous_vide, stage.heating_elements, stage.steam):
            await self._request(commands.build_set_fan_command(self.id, AnovaPOFanSpeed.HIGH.speed))
            stage.fan = AnovaPOFanSpeed.HIGH

