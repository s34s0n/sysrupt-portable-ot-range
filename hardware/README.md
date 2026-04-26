# Hardware Abstraction Layer

Central hardware interface for the Sysrupt OT Range. Provides a single
`HardwareManager` class that exposes sensors, relays, and status LEDs in either
**simulated** mode (current) or **real** mode (future, Session 14+). State and
events are published to Redis so the web UI, scenario engine, and other
components can subscribe without talking to GPIO directly.

## Modes

| Mode      | Status        | Description                                          |
|-----------|---------------|------------------------------------------------------|
| simulated | available     | Software-only sensors/relays/LEDs, noise + drift     |
| real      | NotImplemented | ESP32-C6 / LM75 / GPIO via ESP bridge - Session 14   |

Switch by editing `hardware/config.yml`:

```yaml
mode: simulated   # or "real"
```

`real` currently raises `NotImplementedError`.

## HardwareManager API

| Method                                        | Description                               |
|-----------------------------------------------|-------------------------------------------|
| `start()`                                     | Start background Redis publisher thread  |
| `stop()`                                      | Stop thread and close Redis              |
| `get_temperature(sensor_id)`                  | Single temperature reading (float, C)    |
| `get_all_temperatures()`                      | Dict of all temperature readings         |
| `set_temperature_override(id, value\|None)`  | Force a value; None to clear             |
| `set_relay(relay_id, bool)`                   | Turn a relay on/off (debounced)          |
| `get_relay(relay_id)`                         | Current relay state                      |
| `get_all_relays()`                            | Dict of all relay states                 |
| `set_led(led_id, "off"\|"on"\|"blink")`     | Set LED state                            |
| `get_led(led_id)`                             | Current LED state                        |
| `get_all_leds()`                              | Dict of all LED states                   |
| `get_full_state()`                            | Snapshot of everything + timestamp       |
| `reset()`                                     | Reset relays/LEDs/overrides to initial   |

All methods are thread-safe via an internal `threading.Lock`.

## Running Tests

```bash
pytest hardware/tests/test_hardware.py -v
```

Tests covering Redis are skipped automatically if Redis is not reachable on
127.0.0.1:6379.

## CLI

```bash
python3 -m hardware.cli
```

Commands: `status`, `temp [id]`, `relay <id> on|off`, `led <id> on|off|blink`,
`reset`, `monitor`, `help`, `quit`.

## Redis Schema

Prefix: `hw:` (configurable).

| Key                      | Type   | Description                         |
|--------------------------|--------|-------------------------------------|
| `hw:mode`                | string | Current mode (simulated/real)       |
| `hw:temp:<sensor_id>`    | string | Latest temperature (float as str)   |
| `hw:relay:<relay_id>`    | string | "1" = on, "0" = off                 |
| `hw:led:<led_id>`        | string | off / on / blink                    |
| `hw:uptime`              | string | Seconds since manager start         |
| `hw:full_state`          | string | JSON blob of full state snapshot    |

Pub/Sub channels:

| Channel                   | Payload (JSON)                                       |
|---------------------------|------------------------------------------------------|
| `hardware.state`          | Full state snapshot, published every 500 ms         |
| `hardware.relay.change`   | `{relay_id, state, timestamp, total_cycles}`         |
| `hardware.led.change`     | `{led_id, state, color, timestamp}`                  |

## Switching to Real Mode

Real-mode hardware drivers (`gpio_manager.py`, `lm75_reader.py`,
`relay_driver.py`, `led_controller.py`) are stubs that raise
`NotImplementedError`. They will be wired up in Session 14 when the ESP32-C6
bridge firmware is integrated. To switch modes later:

```yaml
# hardware/config.yml
mode: real
```

Until Session 14, this will raise `NotImplementedError` at `HardwareManager`
construction.
