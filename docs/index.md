---
layout: default
title: Sysrupt Portable OT Range
---

<p align="center">
  <img src="https://raw.githubusercontent.com/s34s0n/sysrupt-portable-ot-range/main/images/logo.png" alt="Sysrupt" width="200"/>
</p>

---

## Getting Started

1. Plug your Ethernet cable into the OT Range board
2. Your laptop gets an IP automatically (10.0.1.x)
3. Open a terminal and start scanning:

```bash
nmap -sT 10.0.1.0/24
```

4. Find the web server. Open it. Hack your way in.

---

## Challenges

10 progressive challenges. 4700 total points. The scoreboard updates automatically.

| # | Challenge | Points | Guide |
|---|-----------|--------|-------|
| 1 | Perimeter Breach | 100 | [Start here](challenges/ch01.md) |
| 2 | Intelligence Gathering | 200 | [Hints](challenges/ch02.md) |
| 3 | Pivot to OT | 300 | [Hints](challenges/ch03.md) |
| 4 | Building Recon | 350 | [Hints](challenges/ch04.md) |
| 5 | Deep Protocol: DNP3 | 400 | [Hints](challenges/ch05.md) |
| 6 | Silent Overpressure | 450 | [Hints](challenges/ch06.md) |
| 7 | Power Blackout | 500 | [Hints](challenges/ch07.md) |
| 8 | Process Manipulation | 600 | [Hints](challenges/ch08.md) |
| 9 | Safety Assault | 800 | [Hints](challenges/ch09.md) |
| 10 | Full Compromise | 1000 | [Hints](challenges/ch10.md) |

---

## Network Map

<p align="center">
  <img src="https://raw.githubusercontent.com/s34s0n/sysrupt-portable-ot-range/main/images/architecture.svg" alt="Architecture" width="100%"/>
</p>

Five network zones based on the IEC 62443 Purdue Model:

| Zone | Subnet | What's Inside |
|------|--------|---------------|
| Corporate | 10.0.1.0/24 | Web portal, building management |
| DMZ | 10.0.2.0/24 | Historian, OPC-UA gateway, jump host |
| SCADA | 10.0.3.0/24 | HMI, engineering workstation |
| Process | 10.0.4.0/24 | PLCs: Modbus, DNP3, EtherNet/IP, IEC 104 |
| Safety | 10.0.5.0/24 | Safety Instrumented System |

---

## Protocol Tools

Six custom tools are pre-installed on your Kali machine:

```bash
python3 ~/tools/bacnet-tool.py  -h    # BACnet/IP (Building Automation)
python3 ~/tools/dnp3-tool.py    -h    # DNP3 (Power/Water SCADA)
python3 ~/tools/enip-tool.py    -h    # EtherNet/IP (Rockwell PLCs)
python3 ~/tools/iec104-tool.py  -h    # IEC 104 (Power Grid)
python3 ~/tools/modbus-tool.py  -h    # Modbus TCP (Chemical Dosing)
python3 ~/tools/s7comm-tool.py  -h    # S7comm (Siemens Safety)
```

Each tool uses the same format:

```bash
python3 ~/tools/<tool> -t <target-ip> -c <command>
```

Common commands: `scan`, `read`, `write`

---

## Kali Setup

If tools aren't installed yet:

```bash
cd kali-setup
sudo bash kali-setup.sh
```

This installs: nmap, sshpass, opcua-client, pymodbus, python-snap7, c104, cpppo, and all 6 protocol tools.

---

## Protocols You'll Encounter

| Protocol | Port | Real-World Use |
|----------|------|----------------|
| HTTP | 80 | Corporate web systems |
| OPC-UA | 4840 | Industrial data exchange |
| BACnet/IP | 47808 (UDP) | HVAC, lighting, door locks |
| DNP3 | 20000 | Power grids, water utilities |
| EtherNet/IP | 44818 | Factory automation (Rockwell) |
| IEC 104 | 2404 | European power grid SCADA |
| Modbus TCP | 502 | PLCs, chemical dosing |
| S7comm | 102 | Siemens safety controllers |

---

## Tips

- Default nmap only scans top 1000 TCP ports. Industrial protocols use non-standard ports. Scan specifically.
- Not everything is TCP. Some protocols use UDP.
- SSH tunneling is your friend for reaching isolated networks.
- Watch the SCADA HMI. Your attacks have visual impact.
- The scoreboard display shows hints after 15, 30, and 45 minutes.

---

<p align="center">
  <strong>Plug in. Hack the plant. Learn ICS security.</strong>
</p>
<p align="center">
  <a href="https://github.com/s34s0n/sysrupt-portable-ot-range">GitHub</a>
</p>
