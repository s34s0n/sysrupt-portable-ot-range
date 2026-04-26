# Security Policy

## Scope

This project is an intentionally vulnerable training environment. Many "vulnerabilities" inside the range (default credentials, exposed protocols, unsafe PLC logic) are deliberate teaching material - please do not report them as security issues.

What **is** in scope for a security report:

- A way for a student-controlled namespace to escape and execute code on the Sysrupt host
- A flaw in the CTF engine that lets students complete challenges they did not actually solve
- A path for a network attacker on the corporate zone (`10.0.1.0/24`) to reach the host root or SSH
- Issues in the `kali-setup/` installer that compromise the student machine
- Vulnerabilities in the public web tools (`docs/`, scoreboard) that affect users beyond their own range

## Reporting a vulnerability

Please **do not** open a public GitHub issue for security reports.

Instead, use one of:

1. **GitHub Security Advisory** (preferred) - [Create one privately](https://github.com/s34s0n/sysrupt-portable-ot-range/security/advisories/new)
2. **Email** the maintainer at the address listed on the GitHub profile

Include:

- Affected component (service / script / firmware / hardware)
- Affected version (commit SHA or release tag)
- Reproduction steps
- Impact assessment
- Suggested mitigation if you have one

## Response process

- **Acknowledgement:** within 7 days
- **Initial assessment:** within 14 days
- **Fix or mitigation plan:** within 30 days for high-severity issues

Reporters will be credited in the release notes (unless they request anonymity).

## Supported versions

Only the latest tagged release on `main` is supported with security fixes.

## Not in scope

- Misuse of the platform (deploying it on a production OT network - this is documented as out of scope in the README)
- Issues in upstream dependencies (please report those upstream; we will pull in fixed versions)
- Brute-force or denial-of-service against the lab itself (it is a training target - DoS is uninteresting)
