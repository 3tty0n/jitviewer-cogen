#!/usr/bin/env pypy-c
""" A web-based browser of your log files. Run by

jitviewer.py <path to your log file> [port]

and point your browser to http://localhost:5000

Demo logfile available in this directory as 'log'.
"""

import sys
import os.path

try:
    import _jitviewer
except ImportError:
    sys.path.insert(0, os.path.abspath(os.path.join(__file__, '..', '..')))

import cgi
import flask
import inspect
from pypy.tool.logparser import parse_log_file, extract_category
from pypy.tool.jitlogparser.storage import LoopStorage
from pypy.tool.jitlogparser.parser import adjust_bridges
#
from _jitviewer.parser import parse, FunctionHtml, parse_log_counts
from _jitviewer.display import CodeRepr, CodeReprNoFile
import _jitviewer

from pygments import highlight
from pygments.lexers import PythonLexer
from pygments.formatters import HtmlFormatter

from jinja2 import Environment, FileSystemLoader

from werkzeug import Response
from flask.helpers import send_from_directory

CUTOFF = 30

class Server(object):
    def __init__(self, storage):
        self.storage = storage

    def index(self):
        all = flask.request.args.get('all', None)
        loops = []
        for index, loop in enumerate(self.storage.loops):
            if 'entry bridge' in loop.comment:
                is_entry = True
            else:
                is_entry = False
            func = FunctionHtml.from_operations(loop.operations, self.storage,
                                                limit=1)
            func.count = getattr(loop, 'count', '?')
            loops.append((is_entry, index, func))
        loops.sort(lambda a, b: cmp(b[2].count, a[2].count))
        if len(loops) > CUTOFF:
            extra_data = "Show all (%d) loops" % len(loops)
        else:
            extra_data = ""
        if not all:
            loops = loops[:CUTOFF]
        return flask.render_template('index.html', loops=loops,
                                    extra_data=extra_data)

    def loop(self):
        no = int(flask.request.args.get('no', '0'))
        orig_loop = self.storage.loops[no]
        ops = adjust_bridges(orig_loop, flask.request.args)
        loop = FunctionHtml.from_operations(ops, self.storage)
        path = flask.request.args.get('path', '').split(',')
        if path:
            up = '"' + ','.join(path[:-1]) + '"'
        else:
            up = '""'
        callstack = []
        path_so_far = []
        for e in path:
            if e:
                callstack.append((','.join(path_so_far),
                                  '%s in %s at %d' % (loop.name,
                                                      loop.filename,
                                                      loop.startlineno)))
                loop = loop.chunks[int(e)]
                path_so_far.append(e)
        callstack.append((','.join(path_so_far), '%s in %s at %d' % (loop.name,
                                        loop.filename, loop.startlineno)))

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
             'callstack': callstack}
        return flask.jsonify(d)

def start_browser(url):
    import time
    import webbrowser
    import threading
    def run():
        time.sleep(0.5) # give the server some time to start
        webbrowser.open(url)
    th = threading.Thread(target=run)
    th.start()
    return th

class OverrideFlask(flask.Flask):
    root_path = property(lambda self: self._root_path, lambda *args: None)

    def __init__(self, *args, **kwargs):
        self._root_path = kwargs.pop('root_path')
        flask.Flask.__init__(self, *args, **kwargs)

def main():
    PATH = os.path.join(os.path.dirname(
        os.path.dirname(_jitviewer.__file__)))
    print PATH
    if not '__pypy__' in sys.builtin_module_names:
        print "Please run it using pypy-c"
        sys.exit(1)
    if len(sys.argv) != 2 and len(sys.argv) != 3:
        print __doc__
        sys.exit(1)
    log = parse_log_file(sys.argv[1])
    extra_path = os.path.dirname(sys.argv[1])
    if len(sys.argv) != 3:
        port = 5000
    else:
        port = int(sys.argv[2])
    storage = LoopStorage(extra_path)
    loops = [parse(l) for l in extract_category(log, "jit-log-opt-")]
    parse_log_counts(extract_category(log, 'jit-backend-count'), loops)
    storage.reconnect_loops(loops)
    app = OverrideFlask('__name__', root_path=PATH)
    server = Server(storage)
    app.debug = True
    app.route('/')(server.index)
    app.route('/loop')(server.loop)
    #th = start_browser('http://localhost:5000/')
    app.run(use_reloader=False, host='0.0.0.0', port=port)
    #th.join()

if __name__ == '__main__':
    main()
