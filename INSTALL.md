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

### Before you start - read this

| Gotcha | Why it matters |
|--------|----------------|
| Use **Raspberry Pi OS Desktop (64-bit)** — NOT Lite | The kiosk display needs a Wayland session (labwc + Firefox). Lite has no GUI stack. |
| Pi must have **internet during install** | `apt` and `pip` download ~50 packages. WiFi or wired-to-router both work. |
| **Wait 90 seconds** after first power-on | First boot does cloud-init, OS expansion, package finalisation. Black display ≠ broken. |
| **Tested on Raspberry Pi OS Trixie (Debian 13)** | Older versions (Bookworm/Bullseye) likely work but unverified. |
| Pre-set the username via Pi Imager (we use `sysrupt`) | install.sh detects the repo-owning user; if you cloned as `pi`, services run as `pi`. |
| Re-flashing same hostname triggers SSH host-key warning | Run `ssh-keygen -R <host-or-ip>` on your laptop |

### 1. Flash + first boot

Use Raspberry Pi Imager:
- **OS:** Raspberry Pi OS (64-bit) Desktop
- **Storage:** 16GB+ SD card
- **Settings (gear ⚙):**
  - Set **hostname** (e.g. `sysrupt`)
  - Set **username + password** (you'll log in via SSH with these)
  - Set **WiFi SSID + password** (or skip if you'll use ethernet for setup)
  - Tick **Enable SSH** (password auth)
  - Set **WiFi country**
- Write, eject, plug into Pi, power on, **wait 90 seconds**

### 2. Find the Pi and SSH in

```bash
ping <hostname>.local              # mDNS (works on most LANs)
# or check your router admin page for a new client
ssh <username>@<ip-or-hostname>
```

Then update + install git on the Pi:
```bash
sudo apt update && sudo apt full-upgrade -y
sudo apt install -y git
```

### 3. Clone the repository

```bash
cd ~
git clone https://github.com/s34s0n/sysrupt-portable-ot-range.git
cd sysrupt-portable-ot-range
```

### 4. Run the installer

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
| `install.sh` aborts at step 1 with "Required package missing" | apt couldn't reach mirrors (no internet) | Connect Pi to internet, re-run `sudo ./install.sh` |
| `install.sh` finishes but `ot-range.service` is `failed` after reboot | First-boot timing race, or services started before Redis | `sudo systemctl restart ot-range` once |
| Firefox kiosk shows "Unable to connect" | display.server slower than 120s polling window on this Pi | Press F5 in the kiosk, or `pkill firefox` and let labwc respawn |
| Laptop doesn't get an IP | dnsmasq not running on `br-corp` | `sudo systemctl restart ot-range-network` |
| HMI page is blank | Redis state not initialised | `sudo redis-cli flushall && sudo systemctl restart ot-range` |
| `nmap` shows no hosts on 10.0.1.x | Mac/laptop has its own DHCP server (Internet Sharing) winning the race | Disable laptop's Internet Sharing, unplug+replug ethernet |
| Display stays black | Pi OS Lite installed instead of Desktop | Re-flash with Desktop edition |
| Tests fail on `c104` or `pymodbus` import | pip install partially failed | `sudo DEBIAN_FRONTEND=noninteractive pip3 install --break-system-packages -r requirements.txt` |
| CH-8 / CH-10 don't fire | pymodbus pinned to wrong version (3.13+ breaks PLC servers) | Verify `pip3 show pymodbus` shows `<3.13`. If not: `pip3 install --break-system-packages 'pymodbus>=3.5,<3.13'` |

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
