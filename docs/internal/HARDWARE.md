# Hardware

## Board overview

The Sysrupt board is a purpose-built ICS training appliance that integrates a compute core, industrial-style I/O, and a managed Ethernet switch on a single 4-layer PCB.

| Block              | Part         | Interface       |
|--------------------|--------------|-----------------|
| PLC MCU            | ESP32-C6     | UART / SPI      |
| IIoT gateway MCU   | ESP32-C6     | UART            |
| Managed switch     | RTL8367S     | MDIO (blank EEPROM) |
| Ethernet MAC/PHY   | W5500        | SPI             |
| TFT display        | ILI9341 2.8" | SPI1            |
| Temperature sensors| 2x LM75      | I2C-1 @ 0x48/0x49 |
| Relays             | 4x           | GPIO            |
| Zone LEDs          | 4x RGB       | GPIO            |
| Serial fieldbus    | RS-485       | UART            |
| Vehicle bus        | CAN          | SPI / UART      |

## Display pin map (verified)

```
SCLK  = GPIO21
MOSI  = GPIO20
CS    = GPIO16   (spi1-1cs, cs0)
DC    = GPIO18
RST   = GPIO17
BL    = GPIO5
```

See [`../../hardware/BUILD.md`](../../hardware/BUILD.md) for full assembly notes, BOM, and sourcing.
