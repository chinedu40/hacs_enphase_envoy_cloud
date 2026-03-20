# Enphase Envoy Cloud Control — HACS Integration

![Version](https://img.shields.io/badge/version-1.6.0-blue)
![HACS](https://img.shields.io/badge/HACS-Custom-orange)
![HA](https://img.shields.io/badge/Home%20Assistant-2023.1%2B-brightgreen)

Control and schedule your Enphase battery directly from Home Assistant. This integration
communicates with the same cloud endpoints used by the Enlighten / Battery Profile UI and
exposes **CFG**, **DTG**, and **RBD** battery modes as entities you can automate or
control from your dashboard.

> **Note:** This integration uses unofficial cloud endpoints that are not part of the
> Enphase public API. It may require updates if Enphase changes their backend.

---

## What do CFG, DTG, and RBD mean?

| Mode | Full name | What it does |
|------|-----------|-------------|
| **CFG** | Charge From Grid | Allows the battery to charge from the utility grid on a schedule |
| **DTG** | Discharge To Grid | Schedules battery discharge back to the grid |
| **RBD** | Reserve Battery Discharge | Reserves a percentage of battery capacity and controls discharge timing |

Each mode can be enabled/disabled independently and supports time-based schedules
with day-of-week selection and a charge/discharge limit percentage.

---

## What this integration gives you

### Two devices in Home Assistant

The integration creates **two logical devices** to keep the HA device controls view clean:

#### Enphase Battery
Core controls for the battery:
- **CFG / DTG / RBD** enable/disable switches
- **Force Cloud Refresh** button
- Battery mode diagnostic sensor

#### Enphase Schedule Editor
Full schedule management UI:
- Dropdown to select an existing schedule
- Start and end time pickers
- Limit (%) number input
- Day-of-week toggles (Mon–Sun)
- **Save**, **Delete**, and **Add** schedule buttons

---

## Requirements

- Home Assistant **2023.1** or newer
- A valid **Enphase Enlighten** account (username and password)
- An Enphase system with battery storage (Encharge / IQ Battery)

---

## Installation

### Via HACS (recommended)

1. Open **HACS** in the Home Assistant sidebar.
2. Click the three-dot menu → **Custom repositories**.
3. Add `https://github.com/chinedu40/hacs_enphase_envoy_cloud` and select type **Integration**.
4. Click **Download**, then restart Home Assistant.
5. Go to **Settings → Devices & services → Add integration**.
6. Search for **Enphase Envoy Cloud Control** and follow the setup flow.

### Manual install

1. Copy the `enphase_envoy_cloud_control` folder into:
   ```
   /config/custom_components/enphase_envoy_cloud_control/
   ```
2. Restart Home Assistant.
3. Go to **Settings → Devices & services → Add integration**.
4. Search for **Enphase Envoy Cloud Control** and follow the setup flow.

---

## Configuration

### Initial setup

You will be prompted for your **Enphase Enlighten email and password**. These are the
same credentials you use to log in at [enlighten.enphaseenergy.com](https://enlighten.enphaseenergy.com).

> **Security note:** Credentials are stored in the Home Assistant config entry. The
> integration also caches auth tokens locally in `.cache/auth.json` inside the custom
> component folder. Ensure your Home Assistant instance is not publicly accessible and
> that the config directory has appropriate file-system permissions.

### Options (after setup)

You can adjust integration options from **Settings → Devices & services →
Enphase Envoy Cloud Control → Configure**:

| Option | Default | Description |
|--------|---------|-------------|
| **Poll interval (seconds)** | `30` | How frequently the integration fetches fresh data from the Enphase cloud. Lower values give faster state updates but increase API traffic. |

---

## Entities

### Sensors

| Entity | Description |
|--------|-------------|
| `sensor.enphase_schedules_summary` | Combined view of all schedules across CFG / DTG / RBD. State = total schedule count. |
| `sensor.enphase_cfg_schedule` | Active CFG schedules with start/end times and IDs |
| `sensor.enphase_dtg_schedule` | Active DTG schedules with start/end times and IDs |
| `sensor.enphase_rbd_schedule` | Active RBD schedules with start/end times and IDs |
| `sensor.enphase_battery_modes` | Diagnostic sensor showing full battery control state |

### Switches

| Entity | Description |
|--------|-------------|
| `switch.enphase_cfg_enabled` | Enable / disable Charge From Grid mode |
| `switch.enphase_dtg_enabled` | Enable / disable Discharge To Grid mode |
| `switch.enphase_rbd_enabled` | Enable / disable Reserve Battery Discharge mode |

### Buttons

| Entity | Description |
|--------|-------------|
| `button.force_cloud_refresh` | Immediately fetch fresh data from Enphase cloud |
| `button.schedule_save` | Save edits to the currently selected schedule |
| `button.schedule_delete` | Delete the currently selected schedule |
| `button.new_schedule_add` | Create the new schedule from the editor fields |

### Schedule editor (existing schedule)

| Entity | Description |
|--------|-------------|
| `select.enphase_schedule_selected` | Pick which schedule to edit |
| `time.enphase_schedule_start` | Start time for the selected schedule |
| `time.enphase_schedule_end` | End time for the selected schedule |
| `number.enphase_schedule_limit` | Charge/discharge limit (0–100%) |
| `switch.enphase_schedule_mon` … `switch.enphase_schedule_sun` | Active days |

### Schedule editor (new schedule)

| Entity | Description |
|--------|-------------|
| `select.enphase_new_schedule_type` | Choose mode: CFG / DTG / RBD |
| `time.enphase_new_schedule_start` | Start time for the new schedule |
| `time.enphase_new_schedule_end` | End time for the new schedule |
| `number.enphase_new_schedule_limit` | Charge/discharge limit (0–100%) |
| `switch.enphase_new_schedule_mon` … `switch.enphase_new_schedule_sun` | Active days |

---

## Dashboard (Lovelace YAML)

Add a **Manual card** and paste the following to get a full schedule management dashboard:

```yaml
type: vertical-stack
cards:
  - type: entities
    title: Enphase – Battery schedules (overview)
    entities:
      - entity: sensor.enphase_schedules_summary
      - entity: sensor.enphase_cfg_schedule
      - entity: sensor.enphase_dtg_schedule
      - entity: sensor.enphase_rbd_schedule
      - entity: button.force_cloud_refresh
  - type: entities
    title: Edit existing schedule
    entities:
      - entity: select.enphase_schedule_selected
        name: Schedule
      - entity: time.enphase_schedule_start
        name: Start
      - entity: time.enphase_schedule_end
        name: End
      - entity: number.enphase_schedule_limit
        name: Limit (%)
      - type: section
        label: Days
      - entity: switch.enphase_schedule_mon
      - entity: switch.enphase_schedule_tue
      - entity: switch.enphase_schedule_wed
      - entity: switch.enphase_schedule_thu
      - entity: switch.enphase_schedule_fri
      - entity: switch.enphase_schedule_sat
      - entity: switch.enphase_schedule_sun
      - type: section
      - entity: button.schedule_save
        name: Save changes
      - entity: button.schedule_delete
        name: Delete schedule
  - type: entities
    title: Add new schedule
    entities:
      - entity: select.enphase_new_schedule_type
        name: Type
      - entity: time.enphase_new_schedule_start
        name: Start
      - entity: time.enphase_new_schedule_end
        name: End
      - entity: number.enphase_new_schedule_limit
        name: Limit (%)
      - type: section
        label: Days
      - entity: switch.enphase_new_schedule_mon
      - entity: switch.enphase_new_schedule_tue
      - entity: switch.enphase_new_schedule_wed
      - entity: switch.enphase_new_schedule_thu
      - entity: switch.enphase_new_schedule_fri
      - entity: switch.enphase_new_schedule_sat
      - entity: switch.enphase_new_schedule_sun
      - type: section
      - entity: button.new_schedule_add
        name: Add schedule
```

---

## How schedule editing works

### Edit an existing schedule

1. Select a schedule from the **Schedule** dropdown.
2. Adjust the start/end times, limit percentage, and active days.
3. Press **Save changes**. The integration will delete the old schedule and create a
   new one with your updated values, then re-enable the mode.

### Delete a schedule

1. Select the schedule you want to remove.
2. Press **Delete schedule**.

### Add a new schedule

1. Select the **Type** (CFG / DTG / RBD).
2. Set the start time, end time, limit, and active days.
3. Press **Add schedule**.

---

## Services

You can also control schedules from automations using HA services:

| Service | Description |
|---------|-------------|
| `enphase_envoy_cloud_control.add_schedule` | Add a new schedule programmatically |
| `enphase_envoy_cloud_control.update_schedule` | Update an existing schedule by ID |
| `enphase_envoy_cloud_control.delete_schedule` | Delete one or more schedules by ID |
| `enphase_envoy_cloud_control.validate_schedule` | Check if a schedule type is valid |
| `enphase_envoy_cloud_control.force_refresh` | Trigger an immediate data refresh |

See **Developer tools → Services** in Home Assistant for full parameter documentation.

---

## Troubleshooting

### Schedules not showing or showing stale data

1. Press **Force Cloud Refresh** and wait a few seconds.
2. Check **Settings → System → Logs** and filter for `enphase` to see any API errors.
3. If you see `401` or `403` errors, your session has expired — the integration will
   automatically re-authenticate on the next poll cycle. You can also reload the
   integration from **Settings → Devices & services**.

### Save / Add / Delete button does nothing

1. Open Home Assistant logs and look for `[Enphase]` entries at the `ERROR` level.
2. Common causes:
   - **Empty day selection** — at least one day must be toggled on.
   - **Identical start and end time** — the times must differ.
   - **Token expired mid-operation** — reload the integration and try again.

### Authentication fails on setup

- Double-check your Enlighten email and password at
  [enlighten.enphaseenergy.com](https://enlighten.enphaseenergy.com).
- Ensure your account has access to a system with battery storage.
- If you use SSO (Google / Apple login) for Enlighten, you may need to set a separate
  Enlighten password in your account settings.

### Integration loads but no battery data appears

- Confirm your Enphase system has an IQ Battery or Encharge unit.
- Systems with only solar panels (no storage) will not have battery control endpoints.

---

## Known limitations

- Uses **unofficial cloud endpoints** — Enphase may change these without notice.
- **No local/LAN polling** — all data goes through the Enphase cloud. An internet
  connection is required.
- **No official Enphase API key** is used; this integration reverse-engineers the
  Enlighten web UI traffic.
- Propagation of schedule changes can take a few seconds to reflect on the cloud side.

---

## Disclaimer

This is an independent, community-built integration and is not affiliated with or
endorsed by Enphase Energy. Use at your own risk. The integration may stop working if
Enphase modifies their backend APIs.

---

## Contributing

Pull requests are welcome. Areas where help is appreciated:

- Unit and integration test coverage
- Exposing additional battery settings (reserve percentage, storm guard, etc.)
- Handling multi-system Enlighten accounts
- Improved schedule conflict detection
