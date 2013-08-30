#!/usr/bin/env pypy
import sys
import os.path

script_path = os.path.abspath(__file__)
pythonpath = os.path.dirname(os.path.dirname(script_path))
sys.path.append(pythonpath)

from _jitviewer.app import main
main(sys.argv)
