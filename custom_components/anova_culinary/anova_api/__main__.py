"""Checks an Anova account from the command line, read-only: signs in the way the apps do,
connects, and prints each device and what it's doing. Sends no commands.

    uv run python -m custom_components.anova_culinary.anova_api [seconds]

Prompts for the email and password (or reads ANOVA_EMAIL and ANOVA_PASSWORD).
"""

import asyncio
import getpass
import json
import logging
import os
import sys

import aiohttp

from .apc import AnovaPCDevice
from .apo import AnovaPODevice
from .auth import AnovaAuth
from .client import AnovaClient
from .device import AnovaDevice


def describe(device: AnovaDevice) -> dict:
    """What a device is doing, briefly."""
    summary: dict = {"name": device.name, "model": device.model, "id": device.id, "available": device.available}
    state = device.state
    if state is None:
        return {**summary, "state": "none received"}
    summary.update(mode=state.status.mode, online=state.system_info.online, firmware=state.system_info.firmware_version)
    if isinstance(device, AnovaPODevice):
        stage = device.current_stage
        recipe = device.recipe
        summary.update(
            temperature=device.temperature,
            probe=device.probe_temperature,
            lamp=device.lamp_on,
            timer_remaining=device.timer_remaining,
            recipe=recipe.title if recipe else None,
            stage=stage.to_dict() if stage else None,
        )
    elif isinstance(device, AnovaPCDevice):
        summary.update(temperature=device.temperature, target=device.target_temperature, timer_remaining=device.timer_remaining)
    return summary


async def main(seconds: float) -> None:
    """Signs in, connects, prints every device for `seconds`, and disconnects."""
    email = os.environ.get("ANOVA_EMAIL") or input("Anova email: ")
    password = os.environ.get("ANOVA_PASSWORD") or getpass.getpass("Anova password: ")
    async with aiohttp.ClientSession() as session:
        sign_in = await AnovaAuth.login(session, email, password)
        print(f"Signed in (user {sign_in.user_id})")
        client = AnovaClient(sign_in.refresh_token, session)
        await client.connect()
        print(f"Connected; {len(client.devices)} device(s)")
        await asyncio.sleep(seconds)
        for device in client.devices.values():
            print(json.dumps(describe(device), indent=2, default=str))
        await client.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO if "-v" not in sys.argv else logging.DEBUG)
    arguments = [a for a in sys.argv[1:] if a != "-v"]
    asyncio.run(main(float(arguments[0]) if arguments else 5))
