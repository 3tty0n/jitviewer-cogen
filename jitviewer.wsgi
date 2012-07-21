#!/usr/bin/env pypy
from _jitviewer.app import main
app = main(['pypy-c', 'log.pypylog'], run_app=False)
