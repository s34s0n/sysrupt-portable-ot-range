#!/usr/bin/env python3
"""
PLC-2: Chemical Dosing Controller (Chlorine + pH)
Modbus TCP on 10.0.4.102:502, Web IDE on :8080.
"""

from __future__ import annotations

import logging
import os
import signal
import sys
import time

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
log = logging.getLogger("plc-chemical")


def _u16(value: int) -> int:
    """Wrap a signed int into an unsigned 16-bit register value."""
    return int(value) & 0xFFFF


def _s16(value: int) -> int:
    """Interpret an unsigned 16-bit register as signed."""
    value &= 0xFFFF
    return value - 0x10000 if value & 0x8000 else value


class ChemicalPLC(BasePLC):
    PLC_NAME = "PLC-2 Chemical Dosing Controller"
    PLC_ID = "chemical"
    BIND_IP = "0.0.0.0"
    BIND_PORT = 502
    ST_FILE_PATH = os.path.join(
        _HERE, "ladder-logic", "chlorine_dosing_pid.st"
    )

    # MW0..MW29 - note hidden flag at MW28, MW29
    INITIAL_HOLDING = [
        150, 400, 50,            # cl_setpoint, cl_alarm_high, cl_alarm_low
        720, 850, 650,           # ph_setpoint, ph_alarm_high, ph_alarm_low
        200, 50, 10,             # pid_kp, pid_ki, pid_kd
        1, 0, 0,                 # pid_mode(auto), manual_speed, pid_output
        0, 0, 0, 0,              # dosing_total_ml, pid_integral, pid_error,
                                 # alarm_inhibit
        0, 0, 0, 0, 0, 0, 0, 0,  # MW16..MW23 reserved
        0, 0, 0, 0,              # MW24..MW27 reserved
        16723, 17481,            # MW28, MW29 hidden flag parts
    ]
    # IW0 chlorine 1.50ppm, IW1 temp 26.3C, IW2 pH 7.20, IW3 flow 125 LPM
    INITIAL_INPUT = [150, 263, 720, 125]
    INITIAL_COILS = [True, False, False, False, False, False, False]
    INITIAL_DISCRETE = [True, False, False, True]

    def __init__(self):
        super().__init__()
        self._prev_error = 0

    def scan_cycle(self):
        cl_raw = self.get_input(0)
        _temp = self.get_input(1)  # noqa: F841 - reserved
        ph_raw = self.get_input(2)
        _flow = self.get_input(3)  # noqa: F841

        cl_sp = self.get_holding(0)
        cl_high = self.get_holding(1)
        cl_low = self.get_holding(2)
        ph_high = self.get_holding(4)
        ph_low = self.get_holding(5)
        kp = self.get_holding(6)
        ki = self.get_holding(7)
        kd = self.get_holding(8)
        pid_mode = self.get_holding(9)
        manual_speed = self.get_holding(10)
        alarm_inhibit = self.get_holding(15)

        # ----- alarms ----- #
        if alarm_inhibit == 0:
            self.set_coil(3, cl_raw > cl_high)
            self.set_coil(4, cl_raw < cl_low)
            self.set_coil(5, ph_raw > ph_high)
            self.set_coil(6, ph_raw < ph_low)
        else:
            for i in (3, 4, 5, 6):
                self.set_coil(i, False)

        # ----- PID or manual ----- #
        if pid_mode == 1:
            error = cl_sp - cl_raw
            p_term = (kp * error) // 100

            integral = _s16(self.get_holding(13)) + error
            if integral > 10000:
                integral = 10000
            elif integral < -10000:
                integral = -10000
            self.set_holding(13, _u16(integral))

            i_term = (ki * integral) // 100
            d_term = (kd * (error - self._prev_error)) // 100
            self._prev_error = error

            output = (p_term + i_term + d_term) // 100
            output = max(0, min(100, output))
            self.set_holding(11, output)
            self.set_holding(14, _u16(error))
            self.set_coil(0, output > 5)
        else:
            self.set_holding(11, manual_speed)
            self.set_coil(0, manual_speed > 0)

        # ----- safety override: chlorine > 5.00 ppm ----- #
        # Only active when alarms are NOT inhibited
        if cl_raw > 500 and alarm_inhibit == 0:
            self.set_coil(0, False)
            self.set_holding(11, 0)

        # ----- hidden flag registers stay constant ----- #
        self.set_holding(28, 16723)
        self.set_holding(29, 17481)

        # ----- feedback discretes ----- #
        self.set_discrete(0, self.get_coil(0))
        self.set_discrete(1, self.get_coil(1))
        self.set_discrete(2, self.get_coil(2))


def main():
    plc = ChemicalPLC()
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
        "[PLC-2] Running on %s:%d, Web IDE on :8080",
        plc.BIND_IP,
        plc.BIND_PORT,
    )
    log.info("[PLC-2] Press Ctrl+C to stop")
    while True:
        time.sleep(1)


if __name__ == "__main__":
    main()
