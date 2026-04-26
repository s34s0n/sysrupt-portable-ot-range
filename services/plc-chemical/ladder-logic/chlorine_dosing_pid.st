(*
 * PLC-2: Chemical Dosing Controller (Chlorine + pH)
 * Sysrupt OT Range - Water Treatment Plant
 *
 * PID-controlled chlorine dosing pump based on free-chlorine analyzer.
 * Secondary pH monitor with alarm band.
 * Safety: hard stop if chlorine > 5.00 ppm.
 *
 * All analog values scaled integer:
 *   chlorine  = ppm * 100    (150 = 1.50 ppm)
 *   temperature = C * 10     (263 = 26.3 C)
 *   pH        = pH * 100     (720 = 7.20)
 *   flow_rate = LPM          (125 LPM)
 *
 * Register Map (Modbus):
 *   MW0  cl_setpoint        (150 = 1.50 ppm)
 *   MW1  cl_alarm_high      (400 = 4.00 ppm)
 *   MW2  cl_alarm_low       (50  = 0.50 ppm)
 *   MW3  ph_setpoint        (720 = 7.20)
 *   MW4  ph_alarm_high      (850)
 *   MW5  ph_alarm_low       (650)
 *   MW6  pid_kp             (200 = 2.00)
 *   MW7  pid_ki             (50  = 0.50)
 *   MW8  pid_kd             (10  = 0.10)
 *   MW9  pid_mode           (0=MAN, 1=AUTO)
 *   MW10 manual_speed       (0-100 %)
 *   MW11 pid_output         (0-100 % - RO)
 *   MW12 dosing_total_ml
 *   MW13 pid_integral       (signed, stored as uint16)
 *   MW14 pid_error          (signed, stored as uint16)
 *   MW15 alarm_inhibit      (0=armed, 1=inhibited)
 *   MW16..MW27 reserved
 *   MW28 hidden_flag_hi     (16723)
 *   MW29 hidden_flag_lo     (17481)
 *
 *   IW0 chlorine_raw
 *   IW1 temperature_raw
 *   IW2 ph_raw
 *   IW3 flow_rate
 *
 *   QX0.0 dosing_pump_cmd
 *   QX0.1 dosing_valve
 *   QX0.2 mixer_cmd
 *   QX0.3 cl_alarm_high
 *   QX0.4 cl_alarm_low
 *   QX0.5 ph_alarm_high
 *   QX0.6 ph_alarm_low
 *
 *   IX0.0 dosing_fb
 *   IX0.1 valve_fb
 *   IX0.2 mixer_fb
 *   IX0.3 safety_ok
 *)

PROGRAM chlorine_dosing_pid
VAR
    cl_raw          : INT;
    temp_raw        : INT;
    ph_raw          : INT;
    flow            : INT;

    cl_sp           : INT := 150;
    cl_high         : INT := 400;
    cl_low          : INT := 50;
    ph_high         : INT := 850;
    ph_low          : INT := 650;

    kp              : INT := 200;
    ki              : INT := 50;
    kd              : INT := 10;

    pid_mode        : INT := 1;
    manual_speed    : INT := 0;
    pid_output      : INT := 0;

    pid_error       : INT := 0;
    prev_error      : INT := 0;
    pid_integral    : INT := 0;
    p_term          : INT;
    i_term          : INT;
    d_term          : INT;

    alarm_inhibit   : INT := 0;

    dosing_pump_cmd : BOOL;
    dosing_valve    : BOOL;
    mixer_cmd       : BOOL;
    cl_alarm_h      : BOOL;
    cl_alarm_l      : BOOL;
    ph_alarm_h      : BOOL;
    ph_alarm_l      : BOOL;
END_VAR

cl_raw   := IW0;
temp_raw := IW1;
ph_raw   := IW2;
flow     := IW3;

(* ALARMS *)
IF alarm_inhibit = 0 THEN
    cl_alarm_h := cl_raw > cl_high;
    cl_alarm_l := cl_raw < cl_low;
    ph_alarm_h := ph_raw > ph_high;
    ph_alarm_l := ph_raw < ph_low;
ELSE
    cl_alarm_h := FALSE;
    cl_alarm_l := FALSE;
    ph_alarm_h := FALSE;
    ph_alarm_l := FALSE;
END_IF;

(* PID LOOP - scaled integer math *)
IF pid_mode = 1 THEN
    pid_error    := cl_sp - cl_raw;
    p_term       := (kp * pid_error) / 100;
    pid_integral := pid_integral + pid_error;
    IF pid_integral > 10000 THEN
        pid_integral := 10000;
    END_IF;
    IF pid_integral < -10000 THEN
        pid_integral := -10000;
    END_IF;
    i_term     := (ki * pid_integral) / 100;
    d_term     := (kd * (pid_error - prev_error)) / 100;
    prev_error := pid_error;
    pid_output := (p_term + i_term + d_term) / 100;
    IF pid_output > 100 THEN
        pid_output := 100;
    END_IF;
    IF pid_output < 0 THEN
        pid_output := 0;
    END_IF;
    dosing_pump_cmd := pid_output > 5;
ELSE
    pid_output      := manual_speed;
    dosing_pump_cmd := manual_speed > 0;
END_IF;

(* SAFETY OVERRIDE - chlorine runaway *)
IF cl_raw > 500 THEN
    dosing_pump_cmd := FALSE;
    pid_output      := 0;
END_IF;

QX0.0 := dosing_pump_cmd;
QX0.3 := cl_alarm_h;
QX0.4 := cl_alarm_l;
QX0.5 := ph_alarm_h;
QX0.6 := ph_alarm_l;

(* Hidden flag lives at MW28/MW29 - students extract via Modbus read *)
MW28 := 16723;
MW29 := 17481;

END_PROGRAM
