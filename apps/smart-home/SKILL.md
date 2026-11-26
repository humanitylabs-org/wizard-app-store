---
name: smart-home
description: Use when the owner asks about or wants to control devices at home (air purifier, vacuum, lights, plugs, fans, cameras, air quality, temperature, "is X on", "start the vacuum"). Read and control them with the Home Assistant app.
---

# Home Assistant

The Home Assistant app (id smart-home) is Home Assistant run for the owner on this box, or a link to their own Home Assistant if they chose that. It holds the connection to their device brands.

## Tools

- `home_status`: call first. Says whether it is ready, which brands are connected and what to do next.
- `home_devices`: devices grouped by physical device, each with its parts (power switch, mode, sensors) and their `entity_id`s. Filter by `room`, `kind` (fan, vacuum, light, switch, sensor, camera, select...) or part of a `name`.
- `home_device`: one device's full state (mode, speed, battery, filter life, air quality) and the actions it accepts with their options.
- `home_camera`: a current snapshot from a camera, or the plain reason it can't show one and what's needed.
- `home_control`: run one action on one device, e.g. `turn_on`, `start`, `return_to_base`, `set_preset_mode` with `{"preset_mode": "sleep"}`. The result reads the state back.

## How to work

1. Find the device with `home_devices` (an air purifier is usually a `fan`; its air quality is a `sensor`).
2. If you haven't used that action before, check `home_device` for the exact action name and options.
3. Act with `home_control`, then tell the owner the state you read back, in plain words.

## Rules

- Only do what was asked. Don't change modes, speeds or other devices on the side.
- Unlocking, disarming or opening doors needs the owner's explicit yes in this chat; then pass `confirmed: true`.
- Nothing connected yet: the owner signs in themselves. Tell them to open the Home Assistant app and pick their brand, or "My own Home Assistant" if they already run one. You can't sign in for them.
- Asked to see, show or check a camera: call `home_camera`. It returns a snapshot, or explains what hardware the owner needs (e.g. an Android phone for brands that encrypt video). Relay that in plain words; don't guess.
- A device showing `unavailable` is offline (unplugged, or off Wi-Fi). Say that rather than retrying.
