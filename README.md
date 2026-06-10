# Enphase Envoy Cloud Control - HACS Integration

This custom integration lets Home Assistant read and control Enphase battery settings using the same web endpoints the Enlighten / Battery Profile UI uses (not the official API). It focuses on **battery schedules** (cfg / dtg / rbd) and provides a simple, dashboard-friendly way to **view**, **add**, **edit**, and **delete** schedules.

### Glossary

| Term | Meaning |
|------|---------|
| **CFG** | **Charge from Grid** — charge the battery from the grid (e.g. during cheap tariff windows) |
| **DTG** | **Discharge to Grid** — export battery energy to the grid |
| **RBD** | **Restrict Battery Discharge** — stop the battery from discharging (e.g. save it for peak hours) |

> **Note:** CFG and DTG must be enabled for your site by Enphase. If a feature is not enabled, the cloud may silently re-create deleted schedules (the integration detects this and tells you).

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
- Your Enphase Enlighten **homeowner** credentials (the email and password you use at enlighten.enphaseenergy.com)

Credentials are validated during setup — if the login fails you will see an error in the setup form instead of broken entities later. If your password changes afterwards, Home Assistant will prompt you to **reauthenticate** (Settings → Devices & services → the integration shows a "Reauthenticate" repair).

Multiple Enphase accounts are supported: add the integration once per account. Each entry keeps its own login session and token cache.

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

### Battery setting sensors (read-only, created when your system reports them)
- `sensor.enphase_battery_reserve` — backup reserve percentage
- `sensor.enphase_battery_profile` — active system profile
- `sensor.enphase_battery_grid_mode` — current grid mode
- `sensor.enphase_battery_very_low_soc` — very-low state-of-charge threshold

These come straight from the battery settings payload the integration already polls; no extra cloud calls are made. If a field is not present for your system, the sensor is simply not created.

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

## Services & automations

The integration registers these services (see Developer Tools → Actions for full schemas):

| Service | Purpose |
|---------|---------|
| `enphase_envoy_cloud_control.force_refresh` | Refresh cloud data immediately |
| `enphase_envoy_cloud_control.add_schedule` | Create a schedule (validates feature support and **rejects overlapping schedules**) |
| `enphase_envoy_cloud_control.update_schedule` | Replace an existing schedule |
| `enphase_envoy_cloud_control.delete_schedule` | Delete schedule(s) — **verifies the cloud actually removed them** |
| `enphase_envoy_cloud_control.validate_schedule` | Ask Enphase whether a schedule type is currently valid for your site |

### Example: dynamic cheap-tariff charge window

When your energy provider signals a cheap window (e.g. via a price sensor turning a `binary_sensor` on), create a one-hour CFG schedule and enable charging; remove it when the window ends:

```yaml
automation:
  - alias: "Enphase: start grid charging in cheap window"
    trigger:
      - platform: state
        entity_id: binary_sensor.cheap_energy_window
        to: "on"
    action:
      - service: enphase_envoy_cloud_control.add_schedule
        data:
          schedule_type: cfg
          start_time: "{{ now().strftime('%H:%M') }}"
          end_time: "{{ (now() + timedelta(hours=1)).strftime('%H:%M') }}"
          limit: 100
          days: ["{{ now().isoweekday() }}"]
      - service: switch.turn_on
        target:
          entity_id: switch.enphase_cfg_mode

  - alias: "Enphase: stop grid charging after cheap window"
    trigger:
      - platform: state
        entity_id: binary_sensor.cheap_energy_window
        to: "off"
    action:
      - service: switch.turn_off
        target:
          entity_id: switch.enphase_cfg_mode
      # Delete today's CFG schedules using the summary sensor's attributes
      - service: enphase_envoy_cloud_control.delete_schedule
        data:
          confirm: true
          schedule_ids: >-
            {{ state_attr('sensor.enphase_schedules_summary', 'schedules')
               | selectattr('type', 'eq', 'cfg')
               | map(attribute='id') | list }}
```

### Blueprints

Two importable blueprints ship in [`blueprints/`](blueprints/):

- **Charge from grid during a time window** — toggles the CFG switch on/off at fixed times
- **Block battery discharge during a time window** — toggles the RBD switch on/off (e.g. peak hours)

Import via **Settings → Automations & scenes → Blueprints → Import blueprint** using the raw GitHub URL of the YAML file.

---

## Diagnostics

The integration supports Home Assistant diagnostics: on the integration page choose **Download diagnostics** to get a redacted dump (credentials, tokens and IDs removed) that you can attach to bug reports.

---

## Troubleshooting

### Schedules not showing / stale data

* Press **Force cloud refresh**.
* Confirm your auth token and XSRF token are valid.

### Save/Add/Delete fails

* Check Home Assistant logs for the response body.
* Ensure the day selection is not empty.
* Ensure start and end are different.
* Overlapping schedules of the same type are rejected before they reach Enphase — adjust the times or days.
* If a deletion reports that Enphase restored the schedule, that feature (CFG/DTG) is likely not enabled for your site — contact Enphase support.

### Authentication problems

* A persistent notification appears when cloud authentication fails; the integration retries automatically.
* After repeated failures Home Assistant shows a **Reauthenticate** prompt on the integration — enter your current Enlighten password there. No need to remove and re-add the integration.

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
