#!/usr/bin/env pypy
""" A web-based browser of your log files. Run by

    jitviewer.py <path to your log file> [port] [--qt]

By default the script will run a web server, point your browser to
http://localhost:5000

If you pass --qt, this script will also start a lightweight PyQT/QWebKit based
browser pointing at the jitviewer.  This assumes that CPython is installed in
/usr/bin/python, and that PyQT with WebKit support is installed.

Demo logfile available in this directory as 'log'.

To produce the logfile for your program, run:

    PYPYLOG=jit-log-opt,jit-backend-counts:mylogfile.log pypy myapp.py
"""

import sys
import os.path

try:
    import _jitviewer
except ImportError:
    sys.path.insert(0, os.path.abspath(os.path.join(__file__, '..', '..')))

try:
    import pypy
except ImportError:
    import __pypy__
    sys.path.append(os.path.join(__pypy__.__file__, '..', '..', '..'))
    try:
        import pypy
    except ImportError:
        raise ImportError('Could not import pypy module, make sure to '
            'add the pypy module to PYTHONPATH')

import jinja2
if jinja2.__version__ < '2.6':
    raise ImportError("Required jinja version is 2.6 (the git tip), older versions might segfault PyPy")

import flask
import inspect
import threading
import time
from pypy.tool.logparser import extract_category
from pypy.tool.jitlogparser.storage import LoopStorage
from pypy.tool.jitlogparser.parser import adjust_bridges, import_log
#
from _jitviewer.parser import ParserWithHtmlRepr, FunctionHtml, parse_log_counts
from _jitviewer.display import CodeRepr, CodeReprNoFile
import _jitviewer

CUTOFF = 30

class CannotFindFile(Exception):
    pass

class DummyFunc(object):
    def repr(self):
        return '???'

class Server(object):
    def __init__(self, filename, storage):
        self.filename = filename
        self.storage = storage

    def index(self):
        all = flask.request.args.get('all', None)
        loops = []
        for index, loop in enumerate(self.storage.loops):
            if 'entry bridge' in loop.comment:
                is_entry = True
            else:
                is_entry = False
            try:
                func = FunctionHtml.from_operations(loop.operations, self.storage,
                                                    limit=1,
                                                    inputargs=loop.inputargs)
            except CannotFindFile:
                func = DummyFunc()
            func.count = getattr(loop, 'count', '?')
            loops.append((is_entry, index, func))
        loops.sort(lambda a, b: cmp(b[2].count, a[2].count))
        if len(loops) > CUTOFF:
            extra_data = "Show all (%d) loops" % len(loops)
        else:
            extra_data = ""
        if not all:
            loops = loops[:CUTOFF]

        qt_workaround = ('Qt/4.7.2' in flask.request.user_agent.string)
        return flask.render_template('index.html', loops=loops,
                                     filename=self.filename,
                                     qt_workaround=qt_workaround,
                                     extra_data=extra_data)

    def loop(self):
        no = int(flask.request.args.get('no', '0'))
        orig_loop = self.storage.loops[no]
        if hasattr(orig_loop, 'force_asm'):
            orig_loop.force_asm()
        ops = adjust_bridges(orig_loop, flask.request.args)
        loop = FunctionHtml.from_operations(ops, self.storage,
                                            inputargs=orig_loop.inputargs)
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

        if not loop.has_valid_code() or loop.filename is None:
            startline = 0
            source = CodeReprNoFile(loop)
        else:
            startline, endline = loop.linerange
            code = self.storage.load_code(loop.filename)[(loop.startlineno,
                                                          loop.name)]
            if code.co_name == '<module>' and code.co_firstlineno == 1:
                try:
                    with open(code.co_filename) as f:
                        source = CodeRepr(f.read(), code, loop)
                except (IOError, OSError):
                    source = CodeReprNoFile(loop)
            else:
                source = CodeRepr(inspect.getsource(code), code, loop)
        d = {'html': flask.render_template('loop.html',
                                           source=source,
                                           current_loop=no,
                                           upper_path=up,
                                           show_upper_path=bool(path)),
             'scrollto': startline,
             'callstack': callstack}
        return flask.jsonify(d)


class OverrideFlask(flask.Flask):
    root_path = property(lambda self: self._root_path, lambda *args: None)

    def __init__(self, *args, **kwargs):
        self._root_path = kwargs.pop('root_path')
        self.servers = []
        self.evil_monkeypatch()
        flask.Flask.__init__(self, *args, **kwargs)

    def evil_monkeypatch(self):
        """
        Evil way to fish the server started by flask, necessary to be able to shut
        it down cleanly."""
        from SocketServer import BaseServer
        orig___init__ = BaseServer.__init__
        def __init__(self2, *args, **kwds):
            self.servers.append(self2)
            orig___init__(self2, *args, **kwds)
        BaseServer.__init__ = __init__

def main():
    PATH = os.path.join(os.path.dirname((_jitviewer.__file__)))
    print PATH
    if not '__pypy__' in sys.builtin_module_names:
        print "Please run it using pypy-c"
        sys.exit(1)
    #
    server_mode = True
    if '--qt' in sys.argv:
        server_mode = False
        sys.argv.remove('--qt')
    #
    if len(sys.argv) != 2 and len(sys.argv) != 3:
        print __doc__
        sys.exit(1)
    filename = sys.argv[1]
    extra_path = os.path.dirname(filename)
    if len(sys.argv) != 3:
        port = 5000
    else:
        port = int(sys.argv[2])
    storage = LoopStorage(extra_path)
    log, loops = import_log(filename, ParserWithHtmlRepr)
    parse_log_counts(extract_category(log, 'jit-backend-count'), loops)
    storage.reconnect_loops(loops)
    app = OverrideFlask('__name__', root_path=PATH)
    server = Server(filename, storage)
    app.debug = True
    app.route('/')(server.index)
    app.route('/loop')(server.loop)
    def run():
        app.run(use_reloader=False, host='0.0.0.0', port=port)

    if server_mode:
        run()
    else:
        url = "http://localhost:%d/" % port
        run_server_and_browser(app, run, url, filename)

def run_server_and_browser(app, run, url, filename):
    try:
        # start the HTTP server in another thread
        th = threading.Thread(target=run)
        th.start()
        #
        # start the webkit browser in the main thread (actually, it's a subprocess)
        time.sleep(0.5) # give the server some time to start
        start_browser(url, filename)
    finally:
        # shutdown the HTPP server and wait until it completes
        app.servers[0].shutdown()
        th.join()

def start_browser(url, filename):
    import subprocess
    qwebview_py = os.path.join(os.path.dirname(__file__), 'qwebview.py')
    title = "jitviewer: " + filename
    try:
        return subprocess.check_call(['/usr/bin/python', qwebview_py, url, title])
    except Exception, e:
        print 'Cannot start the builtin browser: %s' % e
        print "Please point your browser to: %s" % url
        try:
            raw_input("Press enter to quit and kill the server")
        except KeyboardInterrupt:
            pass

if __name__ == '__main__':
    main()
