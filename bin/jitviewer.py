#!/usr/bin/env pypy
import sys
import os.path

script_path = os.path.abspath(__file__)
pythonpath = os.path.dirname(os.path.dirname(script_path))
sys.path.append(pythonpath)

# Check we are running with PyPy first.
if not '__pypy__' in sys.builtin_module_names:
    from _jitviewer.misc import failout
    failout("jitviewer must be run with PyPy")

from _jitviewer.app import main
main(sys.argv)
