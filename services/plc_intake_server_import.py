"""
Import shim so tests can do ``from services.plc_intake_server_import
import IntakePLC`` despite the ``plc-intake`` directory name containing
a dash (which is illegal in Python package names).
"""

import importlib.util
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
_SERVER_PATH = os.path.join(_HERE, "plc-intake", "server.py")

_spec = importlib.util.spec_from_file_location(
    "plc_intake_server_module", _SERVER_PATH
)
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)

IntakePLC = _module.IntakePLC
