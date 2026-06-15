<img src="logo.png" alt="Sensmos" height="96">

# Sensmos — Home Assistant integration (HACS)

Connect a Sensmos ESP32 node to Home Assistant — **locally, no cloud, no broker**. The integration talks to the node's HTTP API on your LAN.

> Sensmos is a DePIN sensor network: nodes publish data, earn GALU, and can subscribe to each other. This integration brings that into Home Assistant both ways — read node data in HA, and feed HA data to the node.

## Features

- **Your node's own data as sensors** — the node's native (`pub.*`) and custom (`own.*`) entities show up in HA automatically (entities you feed *from* HA are skipped to avoid loops).
- **Feed the node from HA** — map any HA sensor → a node entity (native `pub.*` or custom `own.*`). Units are converted automatically (kW→W, mV→V, °F→°C…). Binary sensors (motion, door…) are sent as `1`/`0`. No automations to write — the integration tracks state changes and refreshes every 5 min.
- **Subscription sensors** — data your node subscribes to from other nodes (`sub.*` / your prefix) appears as HA sensors as soon as it arrives.
- **Subscribe from HA** — pick a target node's device ID, preview its entities, confirm; sensors appear on their own.
- **Node status** — GALU available / claimable, uptime, online, backend (WS) connectivity.
- **Node events as HA events** — `sensmos_event` (batch_sent, sub_received, ws_connected) and `sensmos_message` (incoming message) for automations. The webhook is configured on the node automatically.

## Installation

1. HACS → Integrations → ⋮ → **Custom repositories** → add this repo (category *Integration*).
2. Install **Sensmos**, then restart Home Assistant.
3. Settings → Devices & Services → **Add Integration** → **Sensmos**.
4. Enter the **node address** (the IP shown in the Sensmos app, or `sensmos-xxxxxx.local`) and the **PIN**.

The device and its sensors appear immediately.

## Feeding the node (entity mapping)

Settings → Devices & Services → Sensmos → **Configure**:

- **➕ Feed a native entity (`pub.*`)** — pick a network-rewarded native entity (with its unit), then a matching HA sensor; the picker is filtered to compatible sensors and units are converted automatically.
- **➕ Feed a custom entity (`own.*`)** — a name + any HA sensor or binary sensor. Stored on the node as `own.<name>` (usable in node scripts). The unit is taken from the HA entity; binary states become `1`/`0`.
- **➖ Remove a feed mapping**.

## Subscriptions

**Configure → 📡 Subscribe to another node**: enter the device ID, a local prefix (e.g. `neighbor`), and a number of days. You'll see the available entities and the cost; after confirming, data shows up in HA as `neighbor_*` sensors. Billed daily in GALU from the wallet pool.

## Events

```yaml
# Automation triggered by a message received by the node
trigger:
  - platform: event
    event_type: sensmos_message
action:
  - service: notify.mobile_app
    data:
      message: "Node received a message: {{ trigger.event.data }}"
```

## Service `sensmos.push`

Send a value to the node manually (e.g. from an automation):

```yaml
service: sensmos.push
data:
  entity_id: own.tariff
  value: "0.89"
  unit: "PLN/kWh"
```

## Requirements

- A Sensmos node on the same network (firmware with the HTTP API).
- Home Assistant 2024.6+.

## Links

- Website: https://sensmos.com
