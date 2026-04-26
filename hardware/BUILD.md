# Hardware Build Guide

The Sysrupt board is a 4-layer custom PCB designed in Altium Designer. It integrates a Sysrupt compute core, ESP32-C6 modules, a managed Ethernet switch, an SPI display, and status LEDs - all powered over a single USB-C connector.

> **Estimated parts cost:** ~$150-200 USD per board (single quantities; cheaper at 10+)
> **PCB fab:** 4-layer, ENIG finish, ~$30-50 for 5 boards from JLCPCB or PCBWay
> **Assembly difficulty:** moderate. Some 0402 passives and a QFN switch IC. Hot-air rework station recommended.

---

## What's in this directory

| Path | Contents |
|------|----------|
| `Source/` | Altium schematic (`.SchDoc`) and PCB layout (`.PcbDoc`) |
| `Gerber/` | Manufacturing files - ready to upload to a fab house |
| `BOM/` | Bill of materials (CSV) with part numbers and quantities |
| `3D/` | STEP model for mechanical integration / enclosure design |

---

## Step 1 - Fabricate the PCB

### Recommended fab houses

| Fab | Notes |
|-----|-------|
| **JLCPCB** | Cheapest. 4-layer, ENIG, 1.6mm. ~$25 for 5 boards. |
| **PCBWay** | Slightly higher quality. Better for first article. |
| **OSH Park** | Higher cost but excellent quality control. US-based. |

### What to upload

Zip the entire `Gerber/` folder and upload it. Standard settings work:

- **Layers:** 4
- **Thickness:** 1.6mm
- **Surface finish:** ENIG (recommended) or HASL
- **Min trace/space:** as exported (typically 5/5 mil)
- **Via type:** through-hole
- **Solder mask:** any colour
- **Silkscreen:** white

Lead time is typically 5-7 days plus shipping.

---

## Step 2 - Source components

The full BOM is in `BOM/`. Key components and where to source:

| Component | Suggested source | Notes |
|-----------|------------------|-------|
| Sysrupt compute core (8GB) | See BOM for the SBC part used | Stock can be tight; buy early |
| ESP32-C6 module (×2) | Mouser, DigiKey, LCSC | Espressif WROOM-1 footprint |
| RTL8367S managed switch IC | LCSC, Aliexpress | QFN-64; needs hot-air rework |
| ILI9341 320×240 display | Aliexpress, Adafruit | Standard 2.4" SPI module |
| USB-C connector + PD chip | LCSC | See BOM for exact part |
| Passives (0402 R/C) | LCSC | Bulk packs are cheaper |
| Headers, sockets, LEDs | DigiKey, Mouser | Standard pitch parts |

**Cost-saving tip:** order PCB + assembly together from JLCPCB. They stock most passives and small ICs in their parts library and can hand-place the SMT side for ~$30 extra. You then only solder through-hole connectors yourself.

---

## Step 3 - Assemble the board

### Suggested order

1. **SMT passives + small ICs** (hot-air or reflow oven; or use JLCPCB SMT service)
2. **RTL8367S switch IC** (QFN - hot-air with flux paste; check for shorts under magnification)
3. **ESP32-C6 modules** (hot-air; pre-tin pads)
4. **USB-C + PD chip** (sensitive to orientation - check datasheet)
5. **Through-hole headers and sockets** (iron)
6. **ILI9341 display** (plugs into header - no soldering)
7. **Sysrupt compute core** (sits on 40-pin header)

### Tools needed

- Hot-air rework station (essential for QFN switch IC)
- Fine-tip soldering iron (≤0.4mm)
- Tweezers
- Flux paste + solder paste
- Solder wick + isopropyl alcohol for cleanup
- 10× magnifier or USB microscope

### Inspection before powering

- [ ] No shorts between USB-C VBUS and GND
- [ ] No shorts on the 40-pin header power pins
- [ ] RTL8367S has all pins connected (QFN inspection)
- [ ] ESP32-C6 modules are correctly oriented
- [ ] Display header pinout matches silkscreen

---

## Step 4 - First boot

1. Insert SD card flashed per [`../INSTALL.md`](../INSTALL.md)
2. Connect USB-C power (5V, 3A or higher recommended)
3. Status LEDs should sequence on as services come up
4. Display shows the boot logo within ~15s, scoreboard within ~90s

If anything is off, check `journalctl -b` over SSH (the board is reachable on the WiFi configured during initial setup).

---

## Step 5 - Flash the ESP32-C6 modules

The two ESP32-C6 modules (PLC and IIoT roles) need their firmware flashed once.

```bash
cd /opt/sysrupt-ot-range/services/esp32
idf.py -p /dev/ttyUSB0 flash    # PLC module
idf.py -p /dev/ttyUSB1 flash    # IIoT module
```

ESP-IDF v5.4+ required. See `services/esp32/README.md` for build details.

---

## Enclosure

A STEP model of the assembled board is in `3D/`. It can be imported into Fusion 360, FreeCAD, or SolidWorks to design a 3D-printable case.

Recommended case features:
- Cutouts for: Ethernet jacks (depending on switch routing), USB-C, microSD slot, display window
- Vent slots above the compute core (active cooling recommended for sustained workshop use)
- Standoffs aligned with the four mounting holes on the PCB

---

## Build cost summary (single board, USD)

| Item | Cost |
|------|------|
| PCB (5-pack from JLCPCB, ENIG 4-layer) | ~$30 |
| JLCPCB SMT assembly (one side) | ~$30 |
| Sysrupt compute core (8GB) | ~$80 |
| ESP32-C6 modules (×2) | ~$10 |
| ILI9341 display | ~$8 |
| Connectors + headers + LEDs | ~$15 |
| 32GB SD card | ~$10 |
| USB-C PSU | ~$15 |
| **Total per board** | **~$200** |

Bulk builds (20+) drop the per-unit cost to ~$120 due to PCB and assembly minimums.

---

## Contributing hardware revisions

PRs welcome! If you submit a revised schematic / layout:

1. Bump the silkscreen version (`v1.0` → `v1.1`)
2. Re-export Gerbers and BOM
3. Note changes in `hardware/CHANGELOG.md`
4. Verify on a fabricated board before merging
