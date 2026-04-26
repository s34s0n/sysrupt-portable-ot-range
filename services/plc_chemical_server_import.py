"""
Import shim so tests can do ``from services.plc_chemical_server_import
import ChemicalPLC`` despite the ``plc-chemical`` directory name containing
a dash (which is illegal in Python package names).
"""

import importlib.util
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
_SERVER_PATH = os.path.join(_HERE, "plc-chemical", "server.py")

_spec = importlib.util.spec_from_file_location(
    "plc_chemical_server_module", _SERVER_PATH
)
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)

ChemicalPLC = _module.ChemicalPLC
