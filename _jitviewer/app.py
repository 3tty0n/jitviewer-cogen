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

    PYPYLOG=jit-log-opt,jit-backend:mylogfile.pypylog pypy myapp.py
"""

import sys
import os.path
import argparse

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
try:
    from rpython.tool.logparser import extract_category
except ImportError:
    from pypy.tool.logparser import extract_category
from pypy.tool.jitlogparser.storage import LoopStorage
from pypy.tool.jitlogparser.parser import adjust_bridges, import_log,\
     parse_log_counts
#
from _jitviewer.parser import ParserWithHtmlRepr, FunctionHtml
from _jitviewer.display import CodeRepr, CodeReprNoFile
import _jitviewer

CUTOFF = 30

class CannotFindFile(Exception):
    pass

class DummyFunc(object):
    def repr(self):
        return '???'

def mangle_descr(descr):
    if descr.startswith('TargetToken('):
        return descr[len('TargetToken('):-1]
    if descr.startswith('<Guard'):
        return 'bridge-' + str(int(descr[len('<Guard0x'):-1], 16))
    if descr.startswith('<Loop'):
        return 'entry-' + descr[len('<Loop'):-1]
    return descr.replace(" ", '-')

def create_loop_dict(loops):
    d = {}
    for loop in loops:
        d[mangle_descr(loop.descr)] = loop
    return d

class Server(object):
    def __init__(self, filename, storage):
        self.filename = filename
        self.storage = storage

    def index(self):
        all = flask.request.args.get('all', None)
        loops = []
        for index, loop in enumerate(self.storage.loops):
            try:
                start, stop = loop.comment.find('('), loop.comment.rfind(')')
                name = loop.comment[start + 1:stop]
                func = FunctionHtml.from_operations(loop.operations, self.storage,
                                                    limit=1,
                                                    inputargs=loop.inputargs,
                                                    loopname=name)
            except CannotFindFile:
                func = DummyFunc()
            func.count = getattr(loop, 'count', '?')
            func.descr = mangle_descr(loop.descr)
            loops.append(func)
        loops.sort(lambda a, b: cmp(b.count, a.count))
        if len(loops) > CUTOFF:
            extra_data = "Show all (%d) loops" % len(loops)
        else:
            extra_data = ""
        if not all:
            loops = loops[:CUTOFF]

        qt_workaround = ('Qt/4.7.2' in flask.request.user_agent.string)
        return flask.render_template("index.html", loops=loops,
                                     filename=self.filename,
                                     qt_workaround=qt_workaround,
                                     extra_data=extra_data)

    def loop(self):
        name = mangle_descr(flask.request.args['name'])
        orig_loop = self.storage.loop_dict[name]
        if hasattr(orig_loop, 'force_asm'):
            orig_loop.force_asm()
        ops = orig_loop.operations
        for op in ops:
            if op.is_guard():
                descr = mangle_descr(op.descr)
                subloop = self.storage.loop_dict.get(descr, None)
                if subloop is not None:
                    op.bridge = descr
                    op.count = getattr(subloop, 'count', '?')
                    if (hasattr(subloop, 'count') and
                        hasattr(orig_loop, 'count')):
                        op.percentage = int((float(subloop.count) / orig_loop.count)*100)
                    else:
                        op.percentage = '?'
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
        callstack.append((','.join(path_so_far), '%s in %s:%d' % (loop.name,
                                        loop.filename, loop.startlineno)))

        if not loop.has_valid_code() or loop.filename is None:
            startline = 0
            source = CodeReprNoFile(loop)
        else:
            startline, endline = loop.linerange
            try:
                code = self.storage.load_code(loop.filename)[(loop.startlineno,
                                                              loop.name)]
                if code.co_name == '<module>':
                    with open(code.co_filename) as f:
                        source = f.readlines()
                    striplines = max(code.co_firstlineno - 1, 0)
                    source = ''.join(source[striplines:])
                else:
                    source = inspect.getsource(code)
                source = CodeRepr(source, code, loop)
            except (IOError, OSError):
                source = CodeReprNoFile(loop)
        d = {'html': flask.render_template('loop.html',
                                           source=source,
                                           current_loop=name,
                                           upper_path=up,
                                           show_upper_path=bool(path)),
             'scrollto': startline,
             'callstack': callstack}
        return flask.jsonify(d)


class OverrideFlask(flask.Flask):

    def __init__(self, *args, **kwargs):
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

def collect_log(args, logpath="log.pypylog"):
    """ Collect a log file using pypy """

    # XXX Randomise log file name
    # XXX Search path

    import subprocess

    p = subprocess.Popen(args,
            env={"PYPYLOG" : "jit-log-opt,jit-backend:%s" % (logpath, )}
    )
    p.communicate()
    # We don't check the return status. The user may want to see traces
    # for a failing program!
    return os.path.abspath(logpath)

def main(argv, run_app=True):
    if not '__pypy__' in sys.builtin_module_names:
        print "Please run it using pypy-c"
        sys.exit(1)

    parser = argparse.ArgumentParser()

    parser.add_argument("-l", "--log", help="Specify logfile")
    parser.add_argument("-c", "--collect", nargs="*", help="Collect logfile now")
    parser.add_argument("-p", "--port", help="Select HTTP port")
    parser.add_argument("-q", "--qt", action="store_true", help="Use QT")

    args = parser.parse_args()

    if args.port is not None:
        port = int(args.port)
    else:
        port = 5000

    if args.collect is not None:
        if len(args.collect) == 0:
            print("*Error: Please specify invokation to collect log")
            sys.exit(1)
        filename = collect_log(args.collect)
    else:
        filename = args.log

    extra_path = os.path.dirname(filename)
    storage = LoopStorage(extra_path)

    log, loops = import_log(filename, ParserWithHtmlRepr)
    parse_log_counts(extract_category(log, 'jit-backend-count'), loops)
    storage.loops = [loop for loop in loops
                     if not loop.descr.startswith('bridge')]
    storage.loop_dict = create_loop_dict(loops)
    app = OverrideFlask('_jitviewer')
    server = Server(filename, storage)
    app.debug = True
    app.route('/')(server.index)
    app.route('/loop')(server.loop)
    if run_app:
        def run():
            app.run(use_reloader=bool(os.environ.get('JITVIEWER_USE_RELOADER', False)), host='0.0.0.0', port=port)

        if not args.qt:
            run()
        else:
            url = "http://localhost:%d/" % port
            run_server_and_browser(app, run, url, filename)
    else:
        return app

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
