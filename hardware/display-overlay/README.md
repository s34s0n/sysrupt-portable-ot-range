# ILI9341 Display Overlay - Sysrupt OT Range

## Overview

The OT Range uses an ILI9341 320x240 TFT display connected via SPI1 on a
Sysrupt board.  The kernel's built-in `ili9341` DRM driver renders the
display as a standard `/dev/dri/cardN` device - no fbcp or userspace
framebuffer daemon is needed.

## Pin Assignments (SPI1)

| Signal | GPIO | Physical Pin |
|--------|------|-------------|
| SCLK   | 21   | SPI1 CLK    |
| MOSI   | 20   | SPI1 MOSI   |
| CS     | 16   | CE0 (custom)|
| DC     | 18   | Data/Cmd    |
| RST    | 17   | Reset       |
| BL     | 5    | Backlight   |

## How It Works

1. **Device Tree Overlay** - `sysrupt-ili9341-spi1.dtbo` is loaded at boot
   via `/boot/firmware/config.txt`.  The source DTS is provided in this
   directory.
2. **Kernel DRM driver** - The `ili9341` module (plus `drm_mipi_dbi`) is
   loaded automatically.  The display appears as `/dev/dri/card0`
   (`platform-*.spi-cs-0-card`).
3. **Chromium kiosk** - `display/launcher.sh` starts a Flask SocketIO
   server on port 5555 and opens Chromium in kiosk mode at 320x240
   pointing at `http://localhost:5555`.

## Kernel Modules (loaded)

```
ili9341, drm_mipi_dbi, drm_dma_helper, spi_bcm2835, drm_kms_helper, drm
backlight, drm_panel_orientation_quirks
```

## config.txt Lines

```
dtoverlay=sysrupt-ili9341-spi1
max_framebuffers=2
```

## Installation

1. Copy the compiled overlay:
   ```bash
   sudo cp sysrupt-ili9341-spi1.dtbo /boot/firmware/overlays/
   ```

2. Add to `/boot/firmware/config.txt`:
   ```
   dtoverlay=sysrupt-ili9341-spi1
   max_framebuffers=2
   ```

3. Enable SPI on the SBC (uses the Pi-style `raspi-config` CLI shipped with the base OS):
   ```bash
   sudo raspi-config nonint do_spi 0
   ```

4. Reboot:
   ```bash
   sudo reboot
   ```

5. Verify:
   ```bash
   ls /dev/dri/by-path/platform-*spi*
   lsmod | grep ili9341
   ```
