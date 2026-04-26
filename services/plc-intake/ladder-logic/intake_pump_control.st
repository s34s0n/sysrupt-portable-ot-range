(*
 * PLC-1: Intake Pump Controller
 * Sysrupt OT Range - Water Treatment Plant
 *
 * Controls raw water intake from reservoir into Tank T-101.
 * Two redundant pumps (P-101A/P-101B) with lead-lag alternation.
 * Safety: high-high level override closes inlet valve and stops pumps.
 *
 * Register Map (Modbus):
 *   MW0  start_setpoint     (% tank level, default 30)
 *   MW1  stop_setpoint      (% tank level, default 80)
 *   MW2  low_alarm_sp       (% tank level, default 15)
 *   MW3  high_alarm_sp      (% tank level, default 90)
 *   MW4  pump_mode          (0=MAN, 1=AUTO, 2=ALT)
 *   MW5  system_enable      (0=off, 1=on)
 *   MW6  active_pump        (1 or 2, lead in ALT mode)
 *
 *   IW0  tank_level         (% 0-100)
 *   IW1  flow_rate          (LPM)
 *
 *   QX0.0 pump1_cmd
 *   QX0.1 pump2_cmd
 *   QX0.2 inlet_valve
 *   QX0.3 outlet_valve
 *   QX0.4 alarm_low
 *   QX0.5 alarm_high
 *
 *   IX0.0 pump1_fb
 *   IX0.1 pump2_fb
 *   IX0.2 inlet_valve_fb
 *   IX0.3 outlet_valve_fb
 *)

PROGRAM intake_pump_control
VAR
    tank_level      : INT;
    flow_rate       : INT;
    start_sp        : INT := 30;
    stop_sp         : INT := 80;
    low_alarm_sp    : INT := 15;
    high_alarm_sp   : INT := 90;
    pump_mode       : INT := 1;   (* 0=MAN, 1=AUTO, 2=ALT *)
    system_enable   : BOOL := TRUE;
    active_pump     : INT := 1;
    alt_timer       : INT := 0;   (* scan ticks *)

    pump1_cmd       : BOOL;
    pump2_cmd       : BOOL;
    inlet_valve     : BOOL;
    outlet_valve    : BOOL;
    alarm_low       : BOOL;
    alarm_high      : BOOL;
END_VAR

(* Acquire I/O - read scaled ints *)
tank_level := IW0;
flow_rate  := IW1;

IF system_enable THEN
    inlet_valve  := TRUE;
    outlet_valve := TRUE;

    (* Level alarms *)
    alarm_low  := tank_level < low_alarm_sp;
    alarm_high := tank_level > high_alarm_sp;

    CASE pump_mode OF
        0: (* MANUAL - operator drives QX0.0 / QX0.1 directly over Modbus *)
            ;
        1: (* AUTO - pump1 only *)
            IF tank_level < start_sp THEN
                pump1_cmd := TRUE;
                pump2_cmd := FALSE;
            ELSIF tank_level > stop_sp THEN
                pump1_cmd := FALSE;
                pump2_cmd := FALSE;
            END_IF;
        2: (* ALT - lead-lag alternation every 3600 scan ticks (~3 minutes at 50ms) *)
            alt_timer := alt_timer + 1;
            IF alt_timer >= 3600 THEN
                alt_timer := 0;
                IF active_pump = 1 THEN
                    active_pump := 2;
                ELSE
                    active_pump := 1;
                END_IF;
            END_IF;
            IF tank_level < start_sp THEN
                pump1_cmd := active_pump = 1;
                pump2_cmd := active_pump = 2;
            ELSIF tank_level > stop_sp THEN
                pump1_cmd := FALSE;
                pump2_cmd := FALSE;
            END_IF;
    END_CASE;

    (* SAFETY OVERRIDE - high-high level *)
    IF tank_level > 95 THEN
        pump1_cmd   := FALSE;
        pump2_cmd   := FALSE;
        inlet_valve := FALSE;
    END_IF;
ELSE
    pump1_cmd    := FALSE;
    pump2_cmd    := FALSE;
    inlet_valve  := FALSE;
    outlet_valve := FALSE;
END_IF;

(* Write outputs *)
QX0.0 := pump1_cmd;
QX0.1 := pump2_cmd;
QX0.2 := inlet_valve;
QX0.3 := outlet_valve;
QX0.4 := alarm_low;
QX0.5 := alarm_high;

END_PROGRAM
