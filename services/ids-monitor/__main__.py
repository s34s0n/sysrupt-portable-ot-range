"""Allow running as: python3 -m services.ids_monitor or directly"""
import sys
import os

# Add project root and current dir to path
here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, here)
sys.path.insert(0, os.path.join(here, "..", ".."))

from engine import main
main()
