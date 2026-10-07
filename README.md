# Anova Culinary for Home Assistant

Control and monitor Anova Precision Ovens and Precision Cookers from Home Assistant, and keep a collection of multi-stage oven recipes you can play on any oven. The integration speaks the same protocol as Anova's own apps, over the same cloud connection, so a cook started from Home Assistant shows in the Anova app and a cook started from the app shows (and can be saved) in Home Assistant.

## Supported devices

- **Anova Precision Oven 2.0** (any number of them).
- **Anova Precision Cookers, third generation**: Nano 3.0 (A6), Precision Cooker 3.0 (A7), Mini (A8) and Pro 3.0 (A9). Built from the Anova app's own schema; tested without a device.

Older devices (Precision Oven 1.0, second-generation and Bluetooth-only cookers) are skipped: they use older protocols.

## Installation

### HACS (recommended)
1. Go to HACS → Integrations → ⋮ → Custom repositories.
2. Add this repository's URL as an Integration.
3. Download **Anova Culinary**, then restart Home Assistant.
4. Go to **Settings → Devices & services → Add integration → Anova Culinary**.

### Signing in
Enter the email and password of your Anova account, the one you use in the Anova apps. Home Assistant keeps a sign-in token, not your password. Each Anova account can be added once; every device paired to it appears automatically, including ones you pair later.

If Anova stops accepting the sign-in (for example after a password change), Home Assistant asks you to sign in again.

### Removal
1. Go to **Settings → Devices & services → Anova Culinary**, open the ⋮ menu, and choose **Delete**.
2. To remove the code too, remove the integration in HACS and restart Home Assistant. Saved recipes stay in `.storage/anova_culinary.recipes` until you delete that file.

## What you can do

1. **Use an oven like a smart oven.** Set a temperature on the oven's climate entity and turn it on: a one-stage cook starts. While it cooks, every control adjusts it live.
2. **Play a recipe** from your collection on one or more ovens, from the **Anova** panel or the `play_recipe` action.
3. **Save a cook started in the Anova app.** When an oven runs a cook that isn't in your collection, the panel offers to import it.
4. **Adjust the running stage** of any cook (yours or the app's): temperature, sous vide, steam, fan, heating elements, timer and when it starts, and the probe. Changes apply to the current stage only; the recipe is untouched.

## Entities

Each **oven** has:

| Entity | What it does |
|---|---|
| Oven (climate) | Off or heating; the cavity temperature and target. While off, setting a target only remembers it; turning on starts a cook at it. |
| Probe (climate) | The probe's temperature and target. Available while cooking with the probe plugged in. |
| Sous Vide (switch) | Sous vide (wet bulb) on/off for the running stage. |
| Steam, Timer (numbers) | The running stage's steam (%, 0 for none) and timer (minutes). |
| Heating Element, Fan, Timer Starts (selects) | The running stage's elements, fan speed, and when its timer starts (immediately, when preheated, when food is detected, manually). |
| Door Light (switch) | The oven light, at any time. |
| Camera (camera) | The cavity camera's live feed, over WebRTC. |
| Timer Remaining, Timer Elapsed, Recipe, Rack Position (sensors) | The running cook's timer, how long it has run, its recipe, and the stage's rack. |
| Door Status, Cavity Light, Camera Status (binary sensors) | Door open, cavity lamp, and food detected by the camera. |
| Water Tank Empty / Low / Removed, Waste Water Tank Full / Removed, Descale Required (binary sensors) | Tank and boiler conditions. |
| Descale (button) | Starts descaling (only while the oven is idle). |
| Heater and boiler power and usage (sensors, disabled by default) | Hardware diagnostics. |

The running stage's controls are unavailable while the oven is idle; the light and climate entity are always available.

Each **cooker** has a water heater (target temperature; electric while cooking, eco while idle), timer sensors, and binary sensors for low water, water leak, high temperature and a stuck motor.

## Recipes

The **Anova** sidebar panel lists your recipes, with search, import and export (JSON), and play on one or more ovens. Its editor sets each stage's mode (dry or sous vide), temperature, steam, heating elements, fan, timer or probe, rack, and (from the second stage) its transition: automatic, manual, or when food is removed. The editor shows each stage's allowed temperature range and fan speeds, using the same rules as the oven.

### Actions

| Action | Fields |
|---|---|
| `anova_culinary.play_recipe` | `device_id`: the ovens' Anova IDs; `recipe_id`: the saved recipe's ID |
| `anova_culinary.save_recipe` | `name`, `stages` (as the editor saves them); replaces a recipe with the same name |
| `anova_culinary.delete_recipe` | `name` |
| `anova_culinary.adjust_timer` | `entity_id`: an oven's Timer number; `amount`: minutes to add (negative to subtract) |

### Examples

Turn the oven light on when the door opens:

```yaml
automation:
  - triggers:
      - trigger: state
        entity_id: binary_sensor.left_oven_door_status
        to: "on"
    actions:
      - action: switch.turn_on
        target:
          entity_id: switch.left_oven_door_light
```

Add five minutes to the timer from a dashboard button:

```yaml
action: anova_culinary.adjust_timer
data:
  entity_id: number.left_oven_timer
  amount: 5
```

Notify when the water tank runs low:

```yaml
automation:
  - triggers:
      - trigger: state
        entity_id: binary_sensor.left_oven_water_tank_low
        to: "on"
    actions:
      - action: notify.notify
        data:
          message: The left oven's water tank is running low.
```

## How data updates

Anova's cloud pushes each device's state over a WebSocket as it changes; nothing polls. Commands get a reply from the device, so a rejected change shows as a failed action. If the connection drops, the integration reconnects every 5 seconds, logs the loss once and the reconnection once, and marks the devices unavailable meanwhile.

## Known limitations

- Devices are reached through Anova's cloud, so they need internet access.
- Firmware updates, the lamp preference, the oven's display unit, renaming and pairing stay in the Anova app.
- The integration doesn't read or write Anova's own recipes, favorites or cook history; its recipes are its own.
- The camera offers a live feed only, with no still images.

## Troubleshooting

- **The integration asks to sign in again**: Anova no longer accepts the sign-in (often after a password change). Sign in with the same account.
- **A setting changed something else**: the oven's rules limit some combinations, and the integration fits the stage around your change rather than refusing it. Steam, sous vide and the rear element run the fan on high; sous vide allows up to 92 °C (98 °C with steam) and the bottom element alone up to 230 °C, so the target comes down to fit; with the fan off, the bottom element alone is proofing (up to 45 °C), so above that the fan goes to low. The Fan select only offers the speeds the stage allows.
- **A device is missing**: only the devices listed under Supported devices appear. Check the log for "Skipping … only the latest Anova devices are supported".
- **Debugging**: enable debug logging for `custom_components.anova_culinary.anova_api` to see every message to and from Anova, and download the diagnostics from the integration's ⋮ menu.

## Architecture

`custom_components/anova_culinary/anova_api` is the protocol library; the Home Assistant code around it only reads device state and calls the library.

- `PROTOCOL.md`: Anova's protocol as the apps speak it, read from the apps themselves (`.apks/`).
- `auth.py`, `connection.py`, `client.py`: sign-in as the Android app does it, the WebSocket (responses, reconnects), and the account's devices.
- `apo/`: the Precision Oven 2.0. `state.py` (its state, typed after the app's schema), `commands.py` (every command the app sends), `limits.py` (the app's validation rules), `models.py` and `recipe.py` (the recipe format, and a port of the app's converter to the oven's stages), `device.py` (each control), `stream.py` (the camera's WHEP stream).
- `apc/`: third-generation cookers, the same way.

The Home Assistant side has one base entity (`entity.py`) and entity descriptions per platform, the recipe collection (`recipes.py`), actions (`services.py`), and the panel with its websocket commands (`panel.py`, `www/panel.js`).

### Checking an account from the command line

`uv run python -m custom_components.anova_culinary.anova_api [seconds]` signs in, connects, and prints each device's state. It's read-only and sends no commands.

## Developing

A Python project managed with [uv](https://docs.astral.sh/uv/); everything runs through `./flow` (the [flows](../../cellular/flows) task runner):

| Command | What it does |
| --- | --- |
| `flow test` | Runs the pytest suite under `test/` through uv (uv installs Python 3.14 and the dev dependencies) |
| `flow lint` | Lints the integration and its tests with ruff |
| `flow build [apk\|sources]` | Fetches the latest Anova apps into `.apks/` and Home Assistant's source into `.sources/`, or one of them |
| `flow doc` | Builds the Home Assistant developer guide into `.docs/HOMEASSISTANT.md` |

The tests validate every command the library builds against the apps' own schemas (`test/fixtures/schemas/`).

### Reference material
Three gitignored knowledge bases, refreshed by the commands above, are the only references for this integration:

- **`.apks/`**: Anova's official apps, the only source for Anova's protocol (their public developer API differs from what the apps use). `flow build apk` downloads the latest Anova Oven app (`.apks/oven`) and Anova app (`.apks/culinary`) from APKPure with [apkeep](https://github.com/EFForg/apkeep), refuses any APK not signed with Anova's certificate (checked with the Android SDK's `apksigner`), and decompiles it: both are React Native, so the protocol lives in `bundle.js` (decompiled from Hermes bytecode with [hermes-dec](https://github.com/P1sec/hermes-dec), run through `uvx`), with [jadx](https://github.com/skylot/jadx)'s Java under `source/`. The APKs are only read, never installed.
- **`.sources/home-assistant/`**: Home Assistant core at its latest release (`flow build sources`), since the developer docs trail the code.
- **`.docs/HOMEASSISTANT.md`**: the Home Assistant developer guide, quality scale rules included (`flow doc`), built from the guide's own Markdown.

`flow build apk` needs `apkeep`, `jadx`, `uv` and the Android SDK build-tools (`brew install apkeep jadx`; Android Studio installs the SDK).

Changes go through flows' branch workflow (`flow branch`, `flow commit`, `flow promote`, `flow merge`). Every pushed branch is tested in castle's CI, and `main` only merges a green Pull Request.
