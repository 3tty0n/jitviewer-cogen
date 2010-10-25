
import cgi
import flask
import inspect
from pypy.tool.logparser import parse_log_file, extract_category
from module_finder import load_code
from loops import NonCodeLoop, parse, slice_debug_merge_points, adjust_bridges
from storage import LoopStorage
from display import CodeRepr

from pygments import highlight
from pygments.lexers import PythonLexer
from pygments.formatters import HtmlFormatter

class Server(object):
    def __init__(self, storage):
        self.storage = storage

    def index(self):
        # XXX cache results possibly
        loops = [slice_debug_merge_points(loop.operations)
                 for loop in self.storage.loops]
        return flask.render_template('index.html', loops=loops)

    def loop(self):
        no = int(flask.request.args.get('no', '1'))
        ops = adjust_bridges(self.storage.loops[no - 1], flask.request.args)
        loop = slice_debug_merge_points(ops)
        path = flask.request.args.get('path', '').split(',')
        if path:
            up = '"' + ','.join(path[:-1]) + '"'
        else:
            up = '""'
        for e in path:
            if e:
                loop = loop.chunks[int(e)]
        startline, endline = loop.linerange
        code = load_code(loop.filename, loop.name, loop.startlineno)
        source = inspect.getsource(code)
        d = {'html': flask.render_template('loop.html',
                                           source=CodeRepr(source, code,
                                                           loop),
                                           current_loop=no,
                                           upper_path=up,
                                           show_upper_path=bool(path)),
             'scrollto': startline}
        return flask.jsonify(d)

    # def show(self): 
    #     no = int(flask.request.args.get('no', '1'))       

    # def loop(self):
    #     no = int(flask.request.args.get('no', '1'))
    #     scroll_to = int(flask.request.args.get('scroll_to', '0'))
    #     # gather all functions
    #     loop = self.storage.loops[no - 1]
    #             upper_start = loop.chunks[nr - 1].lineno # XXX what if it's
    #             # also a Function? is it even possible without a bytecode
    #             # in between?
    #         loop = loop.chunks[nr]
    #     startline, endline = loop.linerange
    #     code = load_code(loop.filename, loop.name, loop.startlineno)
    #     source = inspect.getsource(code)
    #     return flask.render_template('loop.html',
    #                                  source=CodeRepr(source, code, loop),
    #                                  startline=scroll_to or startline,
    #                                  current_loop=no,
    #                                  upper_path=','.join(path[:-1]),
    #                                  upper_start=upper_start)

def main():
    log = parse_log_file('log')
    storage = LoopStorage()
    #log_counts = parse_log_counts(open('log.count').readlines())
    storage.reconnect_loops([parse(l) for l in
                             extract_category(log, "jit-log-opt-")])
    app = flask.Flask(__name__)
    server = Server(storage)
    app.debug = True
    app.route('/')(server.index)
    app.route('/loop')(server.loop)
    app.run(use_reloader=False)

if __name__ == '__main__':
    main()
