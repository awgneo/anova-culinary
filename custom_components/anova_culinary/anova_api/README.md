# anova_api

The protocol Anova's own apps speak, as a library: sign in, connect, follow each device's state, and control it. Home Assistant only reads device state and calls these functions. `PROTOCOL.md` is the reference, read from the apps (`.apks/`).

## Layers

| Module | Role |
|---|---|
| `auth.py` | Firebase sign-in and token refresh, with the Oven app's API key and Android headers |
| `connection.py` | The WebSocket: the app's URL, subprotocol and headers; each command awaits its `RESPONSE`; a flat 5-second reconnect |
| `client.py` | The account: device lists, devices added and removed, state routed to each device |
| `device.py`, `models.py` | The base device (state, availability, listeners) and the typed models both products share |
| `apo/` | Precision Oven 2.0 |
| `apc/` | Third-generation Precision Cookers |

## The oven (`apo/`)

- `state.py`: `AnovaPOState`, the oven's whole state typed after the app's `OvenStateV2` schema.
- `commands.py`: one `build_*_command` per command the app sends, in its envelope.
- `limits.py`: the app's validation rules (temperature ranges by element, mode and steam; when the fan must be high; steam mode by temperature).
- `models.py`: the recipe format: `AnovaPORecipe` and `AnovaPOStage` (mode, temperature, steam, elements, fan, a timer or probe advance, transition, rack).
- `recipe.py`: a port of the app's converter, `transformRawStagesToV2`, from the recipe format to the oven's stages and back. Recipes reach the oven exactly as the app would send them, and cooks started from the app read back into the recipe format.
- `device.py`: `AnovaPODevice`. Starts cooks (`start_manual`, `start_recipe`), and changes the running stage with the app's own commands: `set_temperature`, `set_sous_vide`, `set_steam`, `set_fan`, `set_heating_elements`, `set_timer`, `set_probe`; `set_timer_trigger` resends the stages, as the app's editor does. Also the light, descaling, and the camera.
- `stream.py`: the camera's live stream, played over WebRTC through its WHEP URL.

## Trying it

`uv run python -m custom_components.anova_culinary.anova_api [seconds]` signs in, connects, and prints each device's state, read-only.
