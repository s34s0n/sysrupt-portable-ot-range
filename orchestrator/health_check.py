"""Health check - run all service health checks."""

import logging
from typing import Dict

from orchestrator.main import SERVICES, run_health_check

log = logging.getLogger("orchestrator.health")


def check_all() -> Dict[str, bool]:
    """Return a map of service name -> healthy boolean."""
    results = {}
    for svc in SERVICES:
        ok = run_health_check(svc, pid=None)
        results[svc.name] = ok
    return results
