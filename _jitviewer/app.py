#!/usr/bin/env pypy
from misc import failout

DESCR = """Jit Viewer: A web-based browser for PyPy log files"""

EPILOG = """
Typical usage with no existing log file:

    jitviewer.py --collect <your script> <arg1> ... <argn>

Typical usage with existing log file:

    jitviewer.py --log <path to your log file>

where you collected a logfile by setting PYPYLOG, e.g.:

    PYPYLOG=jit-log-opt,jit-backend:<path to your log file> pypy arg1 ... argn

When using an existing logfile, the source code of the logged script must be
in the same location as the logfile.

Once invoked, jitviewer will run a web server. By default the the server
listens on http://localhost:5000

"""

import sys
import os.path
import argparse

try:
    import rpython
except ImportError:
    failout('Could not import the rpython module, make sure to add the '
            'rpython module to PYTHONPATH')

import jinja2
if jinja2.__version__ < '2.6':
    failout("Required jinja version is 2.6 (the git tip), older versions might segfault PyPy")

import flask
import inspect
import threading
import time

try:
    from rpython.tool.logparser import extract_category
except ImportError:
    from pypy.tool.logparser import extract_category
try:
    from rpython.tool.jitlogparser.storage import LoopStorage
except ImportError:
    from pypy.tool.jitlogparser.storage import LoopStorage
try:
    from rpython.tool.jitlogparser.parser import adjust_bridges, import_log,\
         parse_log_counts
except ImportError:
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

def collect_log(args):
    """ Collect a log file using pypy """
    import tempfile, subprocess

    print("Collecting log with: %s" % ' '.join(args))

    # create a temp file, possibly racey, but very unlikey
    (fd, path) = tempfile.mkstemp(prefix="jitviewer-")
    os.close(fd) # just the filename we want

    # possibly make this configurable if someone asks...
    os.environ["PYPYLOG"] = "jit-log-opt,jit-backend:%s" % (path, )
    print("Collecting log in '%s'..." % path)
    p = subprocess.Popen([sys.executable] + args, env=os.environ).communicate()

    # We don't check the return status. The user may want to see traces
    # for a failing program!
    return os.path.abspath(path)

def main(argv, run_app=True):
    parser = argparse.ArgumentParser(
            description = DESCR,
            epilog = EPILOG,
            formatter_class=argparse.RawDescriptionHelpFormatter
    )

    parser.add_argument("-l", "--log", help="specify existing logfile")
    parser.add_argument("-c", "--collect", nargs=argparse.REMAINDER, help="collect logfile now", metavar="ARG")
    parser.add_argument("-p", "--port", help="select HTTP port", type=int)
    parser.add_argument("-q", "--qt", action="store_true", help="use embedded QT browser")

    args = parser.parse_args()

    if args.port is None:
        args.port = 5000

    if args.collect is not None:
        if len(args.collect) < 1:
            failout("please correctly specify invokation to collect log")
        filename = collect_log(args.collect)
        extra_path = os.path.dirname(args.collect[0]) # add dirname of script to extra_path
    elif args.log is not None:
        filename = args.log
        # preserving behaviour before argparse
        # XXX not robust as it could be. Assumes the logfile is in the same
        # dir as the source code, may not be the case.
        extra_path = os.path.dirname(filename)
    else:
        failout("please specify either --log or --collect")

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
            app.run(use_reloader=bool(os.environ.get('JITVIEWER_USE_RELOADER', False)), host='0.0.0.0', port=args.port)

        if not args.qt:
            run()
        else:
            url = "http://localhost:%d/" % args.port
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
