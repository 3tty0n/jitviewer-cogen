#!/usr/bin/env pypy-c
""" A web-based browser of your log files. Run by

baseviewer.py <path to your log file>

and point your browser to http://localhost:5000

Demo logfile available in this directory as 'log'.
"""

import sys
import os
import cgi
import flask
import inspect
from pypy.tool.logparser import parse_log_file, extract_category
from loops import (parse, slice_debug_merge_points, adjust_bridges,
                   parse_log_counts)
from storage import LoopStorage
from display import CodeRepr, CodeReprNoFile

from pygments import highlight
from pygments.lexers import PythonLexer
from pygments.formatters import HtmlFormatter

class Server(object):
    def __init__(self, storage):
        self.storage = storage

    def index(self):
        loops = []
        for index, loop in enumerate(self.storage.loops):
            if 'entry bridge' in loop.comment:
                is_entry = True
            else:
                is_entry = False
            func = slice_debug_merge_points(loop.operations, self.storage)
            func.count = loop.count
            loops.append((is_entry, index, func))
        loops.sort(lambda a, b: cmp(b[2].count, a[2].count))
        return flask.render_template('index.html', loops=loops)

    def loop(self):
        no = int(flask.request.args.get('no', '0'))
        orig_loop = self.storage.loops[no]
        ops = adjust_bridges(orig_loop, flask.request.args)
        loop = slice_debug_merge_points(ops, self.storage)
        path = flask.request.args.get('path', '').split(',')
        if path:
            up = '"' + ','.join(path[:-1]) + '"'
        else:
            up = '""'
        for e in path:
            if e:
                loop = loop.chunks[int(e)]
        
        startline, endline = loop.linerange
        if loop.filename is not None:
            code = self.storage.load_code(loop.filename)[loop.startlineno]
            source = CodeRepr(inspect.getsource(code), code, loop)
        else:
            source = CodeReprNoFile(loop)
        d = {'html': flask.render_template('loop.html',
                                           source=source,
                                           current_loop=no,
                                           upper_path=up,
                                           show_upper_path=bool(path)),
             'scrollto': startline,
             'callstack': None}
        return flask.jsonify(d)

def main():
    if not '__pypy__' in sys.builtin_module_names:
        print "Please run it using pypy-c"
        sys.exit(1)
    if len(sys.argv) != 2:
        print __doc__
        sys.exit(1)
    log = parse_log_file(sys.argv[1])
    extra_path = os.path.dirname(sys.argv[1])
    storage = LoopStorage(extra_path)
    loops = [parse(l) for l in extract_category(log, "jit-log-opt-")]
    parse_log_counts(open(sys.argv[1] + '.count').readlines(), loops)
    storage.reconnect_loops(loops)
    app = flask.Flask(__name__)
    server = Server(storage)
    app.debug = True
    app.route('/')(server.index)
    app.route('/loop')(server.loop)
    app.run(use_reloader=False, host='0.0.0.0')

if __name__ == '__main__':
    main()
