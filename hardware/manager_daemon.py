"""Hardware manager daemon - standalone long-running wrapper."""

import signal
import sys
import time

from hardware.manager import HardwareManager


def main():
    hw = HardwareManager()
    hw.start()

    def _shutdown(*args):
        hw.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    while True:
        time.sleep(1)


if __name__ == "__main__":
    main()
