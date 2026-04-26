"""ILI9341 status display for the Sysrupt OT Range.

Session 9: Flask + Socket.IO game hub on :5555 for 320x240 ILI9341 screen.
"""

from display.server import app, socketio, DisplayStateMachine, main as start_server


class DisplayServer:
    """High-level wrapper for the display game hub."""

    def __init__(self):
        self.app = app
        self.socketio = socketio

    def run(self):
        start_server()

    def stop(self):
        pass
