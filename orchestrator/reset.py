"""Scenario reset - clears all CTF/physics/IDS state in Redis."""

import logging

from orchestrator.state import StateManager

log = logging.getLogger("orchestrator.reset")


def reset_scenario():
    """Reset the entire OT Range to a clean initial state.

    Clears all CTF, IDS, and physics keys in Redis without restarting
    services. The engines will re-initialise their state on the next tick.
    """
    sm = StateManager()

    # CTF state
    ctf_count = sm.flush_pattern("ctf:*")
    log.info("Cleared %d CTF keys", ctf_count)

    # IDS state
    ids_count = sm.flush_pattern("ids:*")
    log.info("Cleared %d IDS keys", ids_count)

    # Physics state
    phys_count = sm.flush_pattern("physics:*")
    log.info("Cleared %d physics keys", phys_count)

    # SIS state (safety system)
    sis_count = sm.flush_pattern("sis:*")
    log.info("Cleared %d SIS keys", sis_count)

    # Service signal keys (trigger CTF auto-detection)
    svc_count = 0
    for key in ["corp:admin_login", "scada:hmi_login"]:
        if sm._r.delete(key):
            svc_count += 1
    log.info("Cleared %d service signal keys", svc_count)

    # Re-initialize essential keys so engines keep working
    sm._r.set("ctf:active", "1")
    sm._r.set("ctf:score", "0")
    sm._r.set("ctf:flags_captured", "[]")
    sm._r.set("ids:active", "true")
    sm._r.set("ids:alert_count", "0")
    sm._r.set("ids:threat_level", "NONE")

    total = ctf_count + ids_count + phys_count + sis_count + svc_count
    print(f"[reset] Cleared {total} Redis keys (CTF={ctf_count},"
          f" IDS={ids_count}, physics={phys_count}, SIS={sis_count})")
    return total
