# plc_common

Reusable components for the Sysrupt OT Range soft-PLCs.

- `base_plc.BasePLC` - pymodbus 3.x async TCP server, 50 ms scan loop,
  Redis state publishing, Modbus-write logging, physics input injection.
- `web_ide.PLCWebIDE` - Flask-based OpenPLC-style web IDE (program
  view/download/upload, register monitor, start/stop) with basic auth.

PLCs subclass `BasePLC`, set their `INITIAL_*` register layout, override
`scan_cycle()` to implement their ladder logic in Python, and pair with
a `PLCWebIDE` for the browser UI.
