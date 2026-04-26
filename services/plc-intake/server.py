#!/usr/bin/env python3
"""
PLC-1: Intake Pump Controller
Modbus TCP on 10.0.4.101:502, Web IDE on :8080.
"""

from __future__ import annotations

import logging
import os
import signal
import sys
import time

# Make the project root importable when run as a script (directory name
# ``plc-intake`` contains a dash so ``python -m`` will not work).
_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(os.path.dirname(_HERE))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from services.plc_common.base_plc import BasePLC  # noqa: E402
from services.plc_common.web_ide import PLCWebIDE  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
log = logging.getLogger("plc-intake")


class IntakePLC(BasePLC):
    PLC_NAME = "PLC-1 Intake Pump Controller"
    PLC_ID = "intake"
    BIND_IP = "0.0.0.0"
    BIND_PORT = 502
    ST_FILE_PATH = os.path.join(
        _HERE, "ladder-logic", "intake_pump_control.st"
    )

    # MW0..MW9
    INITIAL_HOLDING = [30, 80, 15, 90, 1, 1, 1, 0, 0, 0]
    # IW0 tank_level (%), IW1 flow_rate (LPM)
    INITIAL_INPUT = [60, 125]
    # QX0.0..QX0.5
    INITIAL_COILS = [False] * 6
    # IX0.0..IX0.3
    INITIAL_DISCRETE = [False] * 4

    def __init__(self):
        super().__init__()
        self._alt_timer = 0

    def scan_cycle(self):
        tank_level = self.get_input(0)
        _flow = self.get_input(1)  # noqa: F841 - reserved for totaliser

        start_sp = self.get_holding(0)
        stop_sp = self.get_holding(1)
        low_alarm_sp = self.get_holding(2)
        high_alarm_sp = self.get_holding(3)
        pump_mode = self.get_holding(4)
        system_enable = self.get_holding(5)
        active_pump = self.get_holding(6)

        if system_enable == 1:
            self.set_coil(2, True)   # inlet_valve
            self.set_coil(3, True)   # outlet_valve

            # Alarms
            self.set_coil(4, tank_level < low_alarm_sp)
            self.set_coil(5, tank_level > high_alarm_sp)

            if pump_mode == 1:  # AUTO
                if tank_level < start_sp:
                    self.set_coil(0, True)
                    self.set_coil(1, False)
                elif tank_level > stop_sp:
                    self.set_coil(0, False)
                    self.set_coil(1, False)
            elif pump_mode == 2:  # ALT lead-lag
                self._alt_timer += 1
                if self._alt_timer >= 3600:
                    self._alt_timer = 0
                    active_pump = 2 if active_pump == 1 else 1
                    self.set_holding(6, active_pump)
                if tank_level < start_sp:
                    self.set_coil(0, active_pump == 1)
                    self.set_coil(1, active_pump == 2)
                elif tank_level > stop_sp:
                    self.set_coil(0, False)
                    self.set_coil(1, False)
            # pump_mode == 0 MANUAL: operator drives coils directly

            # SAFETY OVERRIDE - high-high level
            if tank_level > 95:
                self.set_coil(0, False)
                self.set_coil(1, False)
                self.set_coil(2, False)
        else:
            for i in range(4):
                self.set_coil(i, False)

        # Feedback discretes mirror coil state
        self.set_discrete(0, self.get_coil(0))
        self.set_discrete(1, self.get_coil(1))
        self.set_discrete(2, self.get_coil(2))
        self.set_discrete(3, self.get_coil(3))


def main():
    plc = IntakePLC()
    web = PLCWebIDE(plc, plc.ST_FILE_PATH, "0.0.0.0", 8080)
    plc.start()
    web.run()

    def _shutdown(signum, frame):
        log.info("signal %d received, stopping...", signum)
        web.stop()
        plc.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    log.info(
        "[PLC-1] Running on %s:%d, Web IDE on :8080",
        plc.BIND_IP,
        plc.BIND_PORT,
    )
    log.info("[PLC-1] Press Ctrl+C to stop")
    while True:
        time.sleep(1)


if __name__ == "__main__":
    main()
