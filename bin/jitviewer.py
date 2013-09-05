#!/usr/bin/env pypy
import sys
import os.path

script_path = os.path.abspath(__file__)
pythonpath = os.path.dirname(os.path.dirname(script_path))
sys.path.append(pythonpath)

# Check we are running with PyPy
if "pypy" not in os.path.basename(sys.executable):
    print("error: jitviewer must be run with PyPy")
    sys.exit(1)

from _jitviewer.app import main
main(sys.argv)
