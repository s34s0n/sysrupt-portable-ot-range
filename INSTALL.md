# Installation Guide

This guide walks you from a blank Sysrupt board to a fully operational OT Range.

> **Time required:** ~30 minutes (most of it is package installation)
> **Hardware required:** Sysrupt board (8GB compute core recommended)

---

## Option A - Flash the official Sysrupt OS image (fastest)

If a release image is published in [GitHub Releases](https://github.com/s34s0n/sysrupt-portable-ot-range/releases):

1. Download `sysrupt-os-v*.img.xz`
2. Flash to a 32GB+ SD card with any standard SD writer:
   ```bash
   xzcat sysrupt-os-v1.img.xz | sudo dd of=/dev/sdX bs=4M status=progress
   ```
3. Insert into the Sysrupt board, power on. Wait ~90 seconds. Plug Ethernet into your laptop. Done.

Default credentials and IP plan are documented in `docs/internal/SETUP.md`.

---

## Option B - Install from source on a fresh Sysrupt board

### 1. Prepare the board

Flash a 64-bit ARM Linux base image to your SD card. Boot, complete first-time setup, then SSH in.

```bash
sudo apt update && sudo apt full-upgrade -y
sudo apt install -y git
```

### 2. Clone the repository

```bash
cd /opt
sudo git clone https://github.com/s34s0n/sysrupt-portable-ot-range.git sysrupt-ot-range
cd sysrupt-ot-range
```

### 3. Run the installer

```bash
sudo ./install.sh
```

What it does (idempotent - safe to re-run):
- Installs system packages (`python3-venv`, `redis-server`, `dnsmasq`, `iptables-persistent`, `bridge-utils`, build tools)
- Creates a Python virtualenv at `/opt/sysrupt-ot-range/.venv`
- Installs Python dependencies from `requirements.txt`
- Sets up Linux network namespaces and bridges (5 zones, 16 namespaces)
- Configures `dnsmasq` to hand out DHCP on the corporate bridge
- Installs systemd units for orchestrator + display + HMI
- Initialises Redis state for the CTF engine
- Enables services to start on boot

### 4. Reboot

```bash
sudo reboot
```

After ~90 seconds the range is live. The scoreboard display lights up and the corporate web portal is reachable from your laptop.

### 5. Connect a student laptop

1. Plug an Ethernet cable from the laptop to the Sysrupt board
2. The laptop receives an IP via DHCP (`10.0.1.x`)
3. Start scanning:
   ```bash
   nmap -sT 10.0.1.0/24
   ```

The student-side toolchain is in `kali-setup/` - see `kali-setup/README.md` for the install steps on the attacker machine.

---

## Verifying the install

```bash
# All systemd services running?
systemctl status sysrupt-orchestrator sysrupt-display sysrupt-hmi

# All zones up?
sudo ip netns list   # expect ~16 namespaces
sudo ip link | grep br-   # expect br-corp, br-dmz, br-scada, br-process, br-safety

# CTF engine responding?
redis-cli ping       # → PONG
redis-cli get ctf:score   # → "0" on a fresh boot
```

Run the test suite:

```bash
cd /opt/sysrupt-ot-range
sudo ./tests/run_all.sh
```

---

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| Laptop doesn't get an IP | dnsmasq not running on `br-corp` | `sudo systemctl restart sysrupt-orchestrator` |
| HMI page is blank | Redis state not initialised | `sudo redis-cli flushall && sudo systemctl restart sysrupt-orchestrator` |
| `nmap` shows no hosts | Bridges didn't come up | Check `journalctl -u sysrupt-orchestrator` |
| Display stays black | SPI peripheral not enabled | Run the SBC config tool, enable SPI, reboot |
| Tests fail on `c104` import | Build deps missing | `sudo apt install -y build-essential cmake` and re-run installer |

---

## Resetting between workshops

```bash
sudo /opt/sysrupt-ot-range/scripts/reset-scenario.sh
```

This wipes Redis CTF state, restores PLC tag values, and resets the scoreboard. Services keep running.

---

## Uninstalling

```bash
sudo systemctl disable --now sysrupt-orchestrator sysrupt-display sysrupt-hmi
sudo rm -rf /etc/systemd/system/sysrupt-*.service
sudo rm -rf /opt/sysrupt-ot-range
```

Network namespaces and bridges are torn down on the next reboot.

---

## Next steps

- **Students:** see [`docs/index.md`](docs/index.md) (also published at https://s34s0n.github.io/sysrupt-portable-ot-range/)
- **Hardware:** see [`hardware/BUILD.md`](hardware/BUILD.md) for fabricating the Sysrupt board
- **Architecture:** see [`docs/internal/ARCHITECTURE.md`](docs/internal/ARCHITECTURE.md)
