# Architecture - IEC 62443 Purdue Reference Model

> Sysrupt OT Range - canonical architecture reference

## Overview

The OT Range implements a five-zone IEC 62443 Purdue Reference Model
using Linux network namespaces and iptables on the Sysrupt board.

```
                        ┌─────────────────────────────┐
                        │     INTERNET / ATTACKER      │
                        └──────────────┬──────────────┘
                                       │
                    ┌──────────────────────────────────────┐
                    │           CORPORATE (br-corp)         │
  Level 4-5         │             10.0.1.0/24               │
  Enterprise        │  ┌──────────┐ ┌──────────┐ ┌───────┐ │
                    │  │Corp Portal│ │  BMS     │ │ Mail  │ │
                    │  │ .10      │ │  .20     │ │ .30   │ │
                    │  └──────────┘ └──────────┘ └───────┘ │
                    └──────────────────┬───────────────────┘
                                       │ (443, 8443, 22, 4840)
                    ┌──────────────────────────────────────┐
                    │              DMZ (br-dmz)             │
  Level 3.5         │             10.0.2.0/24               │
  DMZ               │  ┌──────────┐ ┌──────────┐ ┌───────┐ │
                    │  │Historian │ │Jump Host │ │OPC-UA │ │
                    │  │ .10      │ │ .20      │ │ .30   │ │
                    │  └──────────┘ └──────────┘ └───────┘ │
                    └──────────────────┬───────────────────┘
                                       │ (8080, 22, 4840)
                    ┌──────────────────────────────────────┐
                    │          SCADA (br-scada)             │
  Level 2-3         │             10.0.3.0/24               │
  Supervisory       │  ┌──────────┐ ┌──────────┐ ┌───────┐ │
                    │  │SCADA HMI │ │  Eng WS  │ │  IDS  │ │
                    │  │ .10 ◄────┼─┤ .20 ◄────┼─┤ .30   │ │
                    │  │ ┌─dual───┘ │ ┌─dual+──┘ │       │ │
                    │  └─┤────────┘ └─┤────────┘ └───────┘ │
                    └────┼────────────┼────────────────────┘
                         │            │
          ┌──────────────┤            ├──────────────┐
          │ 10.0.4.10    │            │ 10.0.4.20    │
          │              │            │              │
          │    ┌─────────────────────────────────┐   │
          │    │       PROCESS (br-process)      │   │
 Level 1  │    │           10.0.4.0/24           │   │
 Process  │    │ ┌─────┐┌─────┐┌─────┐┌─────┐   │   │
          │    │ │PLC-1││PLC-2││PLC-3││PLC-4│   │   │
          │    │ │ .101 ││ .102││ .103││ .104│   │   │
          │    │ └─────┘└─────┘└─────┘└─────┘   │   │
          │    │ ┌─────┐                         │   │
          │    │ │PLC-5│                         │   │
          │    │ │ .105│                         │   │
          │    │ └─────┘                         │   │
          │    └─────────────────────────────────┘   │
          │                                          │
          │                          10.0.5.20       │
          │                        ┌─┘               │
          │    ┌─────────────────────────────────┐   │
          │    │       SAFETY (br-safety)        │   │
 Level 0  │    │           10.0.5.0/24           │   │
 Safety   │    │ ┌──────────┐  ┌──────────┐     │   │
(SIL)     │    │ │Safety PLC│  │Safety HMI│     │   │
          │    │ │  .201    │  │  .202    │     │   │
          │    │ └──────────┘  └──────────┘     │   │
          │    └─────────────────────────────────┘   │
          │                                          │
          └──────────────────────────────────────────┘

  Legend:
    ◄── dual/triple homed interface
    --- firewall-controlled path
    ═══ no firewall path (direct bridge access)
```

## Zone Summary

| Zone | Bridge | Subnet | Purdue Level | Purpose |
|------|--------|--------|-------------|---------|
| CORP | br-corp | 10.0.1.0/24 | 4-5 | Enterprise, attacker entry, BMS |
| DMZ | br-dmz | 10.0.2.0/24 | 3.5 | Historian, OPC-UA, jump host |
| SCADA | br-scada | 10.0.3.0/24 | 2-3 | HMI, engineering WS, IDS |
| PROCESS | br-process | 10.0.4.0/24 | 1 | PLCs driving the simulated plant |
| SAFETY | br-safety | 10.0.5.0/24 | 0 (SIL) | Safety Instrumented System |

## Services

| Service | Namespace | Zone | IP | Protocol | Port |
|---------|-----------|------|----|----------|------|
| Corporate Portal | svc-corp-web | CORP | 10.0.1.10 | HTTP | 80/443 |
| BMS (BACnet) | svc-rtu-sensors | CORP | 10.0.1.20 | BACnet/IP | 47808/udp |
| Corporate Mail | svc-corp-mail | CORP | 10.0.1.30 | SMTP | 25 |
| Historian | svc-historian | DMZ | 10.0.2.10 | HTTP | 8443 |
| Jump Host | svc-jumphost | DMZ | 10.0.2.20 | SSH | 22 |
| OPC-UA Gateway | svc-opcua | DMZ | 10.0.2.30 | OPC-UA | 4840 |
| SCADA HMI | svc-scada-hmi | SCADA | 10.0.3.10 | HTTP | 8080 |
| Engineering WS | svc-eng-ws | SCADA | 10.0.3.20 | SSH/HTTP | 22/8080 |
| IDS Monitor | svc-ids | SCADA | 10.0.3.30 | - | - |
| PLC-1 Intake | svc-plc-intake | PROCESS | 10.0.4.101 | Modbus TCP | 502 |
| PLC-2 Chemical | svc-plc-chemical | PROCESS | 10.0.4.102 | Modbus TCP | 502 |
| PLC-3 Filtration | svc-plc-filter | PROCESS | 10.0.4.103 | DNP3 | 20000 |
| PLC-4 Distribution | svc-plc-distrib | PROCESS | 10.0.4.104 | EtherNet/IP | 44818 |
| PLC-5 Power | svc-plc-power | PROCESS | 10.0.4.105 | IEC 104 | 2404 |
| Safety PLC | svc-safety-plc | SAFETY | 10.0.5.201 | S7comm | 102 |
| Safety HMI | svc-safety-hmi | SAFETY | 10.0.5.202 | HTTP | 8080 |

## Dual/Triple Homing

| Host | Primary | Secondary | Tertiary |
|------|---------|-----------|----------|
| SCADA HMI | 10.0.3.10 (br-scada) | 10.0.4.10 (br-process) | - |
| Engineering WS | 10.0.3.20 (br-scada) | 10.0.4.20 (br-process) | 10.0.5.20 (br-safety) |

The EWS safety interface is a "forgotten" maintenance bridge from commissioning.
It is the ONLY path to the safety network (no firewall rules allow process->safety).

## Firewall Rules (OT-RANGE-FORWARD)

| Source | Destination | Ports | Protocol |
|--------|-------------|-------|----------|
| CORP (10.0.1.0/24) | DMZ (10.0.2.0/24) | 22, 443, 8443 | TCP |
| CORP (10.0.1.0/24) | OPC-UA (10.0.2.30) | 4840 | TCP |
| DMZ (10.0.2.0/24) | SCADA (10.0.3.0/24) | 22, 4840, 8080 | TCP |
| SCADA (10.0.3.0/24) | PROCESS (10.0.4.0/24) | 502 | TCP (Modbus) |
| SCADA (10.0.3.0/24) | PLC-3 (10.0.4.103) | 20000 | TCP (DNP3) |
| SCADA (10.0.3.0/24) | PLC-4 (10.0.4.104) | 44818 | TCP+UDP (EtherNet/IP) |
| SCADA (10.0.3.0/24) | PLC-5 (10.0.4.105) | 2404 | TCP (IEC 104) |
| **ALL** | **SAFETY** | **NONE** | **No rules - isolated** |

The safety zone has NO ACCEPT rules in the FORWARD chain. The only access
path is via the EWS safety bridge (127.0.0.1:10102 -> 10.0.5.201:102),
which requires compromising the engineering workstation first.

## Attack Path

```
1. Corp Portal → default creds → webmail/IDOR → recon
2. OPC-UA Gateway → anonymous browse → intelligence gathering
3. Jump Host → SSH → pivot to SCADA zone
4. BMS on corporate → BACnet discovery → building recon
5. SCADA → process protocols (Modbus, DNP3, EtherNet/IP, IEC 104)
6. Engineering WS → discover safety bridge (ss -tlnp)
7. Safety bridge → S7comm to safety PLC → bypass SIS
8. Full compromise: PID manipulation + safety bypass + persistence
```
