# engineering-ws

**Zone:** `scada`
**IP:** `10.0.3.20`
**Port:** `8080`
**Protocol:** `http`

Engineering workstation hosting PLC project files. Reachable from the SCADA zone; pivot target for several CTF challenges.

## Simulated points / registers

See the per-PLC `config.yml` and `services/*/README.md` files for the canonical register maps.

## Intentional weaknesses (instructor-only)

This service exposes deliberate misconfigurations used by the CTF. Solutions are documented in the private instructor guide; the public student site at [docs/challenges/](../../docs/challenges/) only ships progressive hints.
