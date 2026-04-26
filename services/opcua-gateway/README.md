# opcua-gateway

**Zone:** `dmz`
**IP:** `10.0.2.30`
**Port:** `4840`
**Protocol:** `opcua`

OPC-UA gateway bridging PROCESS to DMZ

## Architecture

The OPC-UA Gateway aggregates data from all PLCs and the SIS via Redis and
exposes it as a browsable OPC-UA node tree.  It is intentionally configured
with anonymous access and no encryption, simulating a common misconfiguration.

### Node Tree

```
WaterTreatmentPlant
  PlantInfo       - Name, ID, Location, Maintenance/ServiceHistory
  IntakePumps     - Pump1/2 status, tank level, flow rate
  ChemicalDosing  - Chlorine, pH, dosing rate, PID output, AlarmInhibit
  Filtration      - Differential pressure, turbidity, backwash
  Distribution    - Pressure, flow, residual chlorine
  PowerFeed       - Voltage, current, frequency, breaker
  FieldSensors    - Ambient/process temp, humidity
  SafetySystem    - Armed, tripped, healthy, maintenance, sensors
```

### Writable Variables

- `ChemicalDosing/AlarmInhibit` - can be set True to suppress alarms

## Vulnerabilities (INSTRUCTOR ONLY)

- Anonymous OPC-UA access (NoSecurity)
- AlarmInhibit writable without auth
- Hidden flag in deep Maintenance node tree
