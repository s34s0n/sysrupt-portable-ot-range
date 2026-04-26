# Physics Engine - Session 7

Water treatment plant physics simulation for the Sysrupt OT Range.

## Architecture

The physics engine runs a 10 Hz (100ms) tick loop that:
1. Reads PLC control states from Redis
2. Updates all physics models (tank, pumps, chlorine, pH, filters, power, ambient)
3. Publishes sensor readings back to Redis for PLCs to consume
4. Checks victory condition and attack indicators

## Models

- **WaterTank** - 50,000L tank with inlet/outlet flows and overflow protection
- **PumpModel** - Centrifugal pump with ramp-up/down and thermal simulation
- **ChlorineModel** - Free chlorine with dosing, decay, and dilution
- **PHModel** - pH with dosing effects and natural drift
- **FilterModel** - 4-bed filtration with differential pressure and backwash
- **PIDController** - Standard PID with anti-windup
- **PowerModel** - Mains/UPS/generator power supply
- **AmbientSensors** - Environmental conditions (temp, humidity, vibration)

## Running

```bash
# Start the physics engine
python3 -m physics.engine

# Or
python3 -m physics

# Live monitoring CLI
python3 -m physics.cli
```

## Victory Condition

All three must be true:
- Chlorine > 8.0 ppm
- SIS not tripped
- High chlorine alarm not active

## Redis Channels

Published by physics engine:
- `physics:plc:intake:inputs` - tank level, flow rate
- `physics:plc:chemical:inputs` - chlorine, temp, pH, flow
- `physics:sis:inputs` - safety system inputs
- `physics:plc:filtration:inputs` - filter DPs, turbidity
- `physics:plc:distribution:inputs` - distribution data
- `physics:plc:power:inputs` - voltage, frequency, current
- `physics:plc:sensors:inputs` - ambient sensor data
- `physics:plant_state` (SET) - full plant state JSON
- `physics:state` (PUBLISH) - real-time state updates

Read by physics engine:
- `plc:intake:coils` - pump and valve states
- `plc:chemical:coils` - dosing pump state
- `plc:chemical:holding` - setpoints, PID mode, dosing speed
- `plc:power:full_state` - breaker status
- `sis:status` - safety system status
- `sis:maintenance_mode` - maintenance bypass

## Tests

```bash
pytest physics/tests/test_physics.py -v
```
