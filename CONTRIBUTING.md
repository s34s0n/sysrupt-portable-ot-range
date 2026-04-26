# Contributing to Sysrupt Portable OT Range

Thanks for your interest! This project welcomes contributions across hardware, firmware, services, challenges, and documentation.

---

## Quick links

- [Open an issue](https://github.com/s34s0n/sysrupt-portable-ot-range/issues)
- [Discussions](https://github.com/s34s0n/sysrupt-portable-ot-range/discussions) for questions and ideas
- [Security policy](SECURITY.md) for vulnerability reports
- [Code of Conduct](CODE_OF_CONDUCT.md)

---

## Ways to contribute

### 1. Report bugs
Use the [Issues tab](https://github.com/s34s0n/sysrupt-portable-ot-range/issues). Include:
- Hardware (Sysrupt board / other compatible SBC)
- OS image and version
- Output of `journalctl -u sysrupt-orchestrator`
- Steps to reproduce

### 2. Add a new challenge
Each challenge lives under `ctf/challenges/<chNN>/` plus a markdown hint file in `docs/challenges/`. A challenge needs:
- A trigger detector (Redis key change, log line, network event)
- Point value
- Hint progression (3 levels: 15min, 30min, 45min)
- An auto-detection path in `ctf/engine.py`

See `ctf/challenges/ch01/` as a reference implementation.

### 3. Add a new protocol
Drop a server in `services/plc-<name>/` and a client tool in `kali-setup/tools/<name>-tool.py`. Match the existing CLI shape:

```bash
python3 <name>-tool.py -t <ip> -c <scan|read|write> [args]
```

### 4. Improve the HMI
Templates and static assets live under `services/scada-hmi/app/`. Run locally with:

```bash
cd services/scada-hmi && python3 -m flask run
```

### 5. Improve documentation
- Student-facing: `docs/` (Jekyll site)
- Internal/architectural: `docs/internal/`
- Setup/build: `INSTALL.md`, `hardware/BUILD.md`

---

## Development setup

```bash
git clone https://github.com/s34s0n/sysrupt-portable-ot-range.git
cd sysrupt-portable-ot-range
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Most services can be run individually for development without standing up the full network.

---

## Pull request checklist

- [ ] Branch from `main`
- [ ] Tests pass: `./tests/run_all.sh`
- [ ] No hardcoded credentials, flags, or IPs added
- [ ] New code follows existing style (no formatter enforced yet - match the surrounding file)
- [ ] Docs updated if behaviour changed
- [ ] One logical change per PR (split unrelated changes)
- [ ] PR description explains *why*, not just *what*

---

## Coding style

- **Python:** PEP 8 with 4-space indent. Type hints encouraged but not required.
- **Bash:** `set -e` at the top of every script. `shellcheck` clean.
- **Markdown:** wrap at ~100 chars where reasonable. Use fenced code blocks with language tags.
- **Comments:** explain *why*, not *what*. Skip obvious comments.

---

## Commit messages

Short imperative subject line, optional body.

```
Fix CRC validation in DNP3 challenge

The fast-path was using little-endian CRC against the spec's
big-endian table, so valid frames were rejected ~50% of the time.
```

Avoid: `update`, `fix bug`, `wip`. Be specific.

---

## Adding hardware revisions

See [`hardware/BUILD.md`](hardware/BUILD.md) for the revision workflow. Always verify on a fabricated board before merging schematic / layout changes.

---

## Questions?

Open a [Discussion](https://github.com/s34s0n/sysrupt-portable-ot-range/discussions). For private matters, see [SECURITY.md](SECURITY.md).
