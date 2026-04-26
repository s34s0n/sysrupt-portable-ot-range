# IDS Monitor -- Intrusion Detection System

Passive OT intrusion detection engine for the Sysrupt OT Range. Watches Redis
pub/sub events from all OT services and applies 24 detection rules across 6
categories. Publishes alerts for the display and SCADA HMI.

## Quick Start

```bash
cd services/ids-monitor
./run.sh          # Start engine
python3 cli.py    # Live alert monitor (separate terminal)
```

## Detection Rules (24)

| ID | Name | Severity | Cooldown |
|----|------|----------|----------|
| IDS-001 | Port Scan Detected | LOW | 60s |
| IDS-002 | OPC-UA Enumeration | LOW | 120s |
| IDS-003 | BACnet Discovery | LOW | 120s |
| IDS-004 | Modbus Device Scan | LOW | 60s |
| IDS-010 | Unauthorized Modbus Source | MEDIUM | 30s |
| IDS-011 | Unauthorized S7comm Access | HIGH | 10s |
| IDS-012 | Unauthorized DNP3 Control | MEDIUM | 30s |
| IDS-013 | Unauthorized ENIP Write | MEDIUM | 30s |
| IDS-014 | Unauthorized IEC104 Command | HIGH | 10s |
| IDS-020 | PID Mode Change to Manual | HIGH | 0 |
| IDS-021 | Setpoint Change Anomaly | MEDIUM | 30s |
| IDS-022 | Alarm Inhibit Activated | CRITICAL | 0 |
| IDS-023 | Alarm Threshold Raised | CRITICAL | 0 |
| IDS-024 | Manual Dosing Excessive | HIGH | 30s |
| IDS-025-M | Chlorine Level Elevated | MEDIUM | 60s |
| IDS-025-H | Chlorine Level High | HIGH | 60s |
| IDS-025-C | Chlorine Level Critical | CRITICAL | 60s |
| IDS-030 | SIS Maintenance Mode Enabled | CRITICAL | 0 |
| IDS-031 | SIS Trip Threshold Modified | CRITICAL | 0 |
| IDS-032 | SIS Trip Delay Increased | HIGH | 0 |
| IDS-040 | PLC Program Upload | CRITICAL | 0 |
| IDS-041 | PLC Program Download | MEDIUM | 120s |
| IDS-050 | Power Breaker Open Command | CRITICAL | 0 |
| IDS-051 | OPC-UA Write from DMZ | HIGH | 30s |

## Threat Levels

Based on alerts in the last 5 minutes:

- **NONE** -- No alerts
- **LOW** -- 1-3 LOW severity only
- **MEDIUM** -- Any MEDIUM or 4+ LOW
- **HIGH** -- Any HIGH or 3+ MEDIUM
- **CRITICAL** -- Any CRITICAL

## Redis Keys

| Key | Description |
|-----|-------------|
| `ids:active` | "true"/"false" |
| `ids:alert_count` | Total alert count |
| `ids:alerts` | JSON list (last 20) |
| `ids:latest_alert` | Most recent alert |
| `ids:threat_level` | NONE/LOW/MEDIUM/HIGH/CRITICAL |
| `ids:alert` (channel) | Real-time pub/sub |

## Allowed Sources

Modbus writes from these IPs are NOT flagged as unauthorized:
- 10.0.4.10 (SCADA HMI process interface)
- 10.0.3.10 (SCADA HMI SCADA interface)
- 127.0.0.1 (localhost)

## Tests

```bash
python3 -m pytest services/ids-monitor/tests/test_ids.py -v
```
