"""CLI entry point: python3 -m orchestrator start|stop|restart|status|reset|health"""

import sys

from orchestrator.main import Orchestrator


def main():
    usage = "Usage: python3 -m orchestrator {start|stop|restart|status|reset|health}"

    if len(sys.argv) < 2:
        print(usage)
        sys.exit(1)

    command = sys.argv[1].lower()
    orch = Orchestrator()

    if command == "start":
        orch.start()
    elif command == "stop":
        orch.stop()
    elif command == "restart":
        orch.stop()
        orch.start()
    elif command == "status":
        orch.status()
    elif command == "reset":
        orch.reset()
    elif command == "health":
        results = orch.health()
        for name, ok in results.items():
            marker = "OK" if ok else "FAIL"
            print(f"  [{marker:>4}] {name}")
    else:
        print(f"Unknown command: {command}")
        print(usage)
        sys.exit(1)


if __name__ == "__main__":
    main()
