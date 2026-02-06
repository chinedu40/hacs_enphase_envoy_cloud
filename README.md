# Enphase Envoy Cloud Control - HACS Integration

This custom integration lets Home Assistant read and control Enphase battery settings using the same web endpoints the Enlighten / Battery Profile UI uses (not the official API). It focuses on **battery schedules** (cfg / dtg / rbd) and provides a simple, dashboard-friendly way to **view**, **add**, **edit**, and **delete** schedules.

---

## What this integration gives you

### Two devices in Home Assistant

To keep the built-in *Device → Controls* view tidy, the integration creates **two devices**:

#### 1) Enphase Battery (Controls kept minimal)
You’ll typically see:
- **CFG / DTG / RBD enable switches**
- **Refresh / Force cloud refresh** button
- Core status sensors (where available)

#### 2) Enphase Schedule Editor (full schedule controls)
You’ll see:
- A dropdown to select an existing schedule
- Start and end time pickers
- Limit (%) selector
- Day-of-week toggles
- Buttons to **Save**, **Delete**, and **Add** schedules

This mirrors the Enlighten scheduling workflow, but uses standard Home Assistant entities.

---

## Requirements

- Home Assistant with the ability to install custom integrations
- Your Enphase Enlighten credentials (username and password) 

---

## Installation

### HACS

1. Open Hacs
2. Click on three dots and then custom repositories
3. Add https://github.com/chinedu40/hacs_enphase_envoy_cloud and for type select Integration
4. Download integration and then restart Home assistant
5. Go to: **Settings → Devices & services → Add integration**
6. Search for: **Enphase Envoy Cloud Control**
7. Follow the config flow.

### Manual install

1. Copy the integration folder into:

   `/config/custom_components/enphase_envoy_cloud_control/`

2. Restart Home Assistant.

3. Go to:

   **Settings → Devices & services → Add integration**

4. Search for:

   **Enphase Envoy Cloud Control**

5. Follow the config flow.

---

## Entities you will see

### Overview sensors
- `sensor.enphase_schedules_summary`
  A single combined view of all schedules across cfg / dtg / rbd.
- `sensor.enphase_cfg_schedule`
- `sensor.enphase_dtg_schedule`
- `sensor.enphase_rbd_schedule`

### Battery controls
- `switch.<...cfg enabled...>`
- `switch.<...dtg enabled...>`
- `switch.<...rbd enabled...>`
- `button.force_cloud_refresh`

### Schedule editor controls
**Edit existing schedule**
- `select.enphase_schedule_selected`
- `time.enphase_schedule_start`
- `time.enphase_schedule_end`
- `number.enphase_schedule_limit`
- `switch.enphase_schedule_mon` … `switch.enphase_schedule_sun`
- `button.schedule_save`
- `button.schedule_delete`

**Add new schedule**
- `select.enphase_new_schedule_type`
- `time.enphase_new_schedule_start`
- `time.enphase_new_schedule_end`
- `number.enphase_new_schedule_limit`
- `switch.enphase_new_schedule_mon` … `switch.enphase_new_schedule_sun`
- `button.new_schedule_add`

---

## Recommended dashboard (Lovelace YAML)

Add a **Manual card** (or edit dashboard YAML) and paste:

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

### Editing an existing schedule

1. Choose a schedule in **Schedule** dropdown.
2. Adjust start/end, limit, and days.
3. Press **Save changes**.

### Deleting a schedule

1. Choose a schedule.
2. Press **Delete schedule**.

### Adding a new schedule

1. Choose the schedule type (cfg / dtg / rbd).
2. Set start/end, limit, and days.
3. Press **Add schedule**.

---

## Troubleshooting

### Schedules not showing / stale data

* Press **Force cloud refresh**.
* Confirm your auth token and XSRF token are valid.

### Save/Add/Delete fails

* Check Home Assistant logs for the response body.
* Ensure the day selection is not empty.
* Ensure start and end are different.

### Device controls look cluttered

* Use the **Enphase Schedule Editor** device for schedule changes.
* Keep battery controls on the **Enphase Battery** device.

---

## Disclaimer

This integration uses non-official web endpoints that may change. If Enphase updates their UI backend, the integration may require updates.
While I was able to reverse engineer the enphase REST API, I used AI to code this integration. 

---

## Contributing

PRs welcome:

* Better error messages and retry logic
* Improved schedule normalization across cfg/dtg/rbd
* Additional battery settings exposed as entities
