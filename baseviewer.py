
import cgi
import flask
import inspect
from pypy.tool.logparser import parse_log_file, extract_category
from module_finder import load_code
from loops import parse, slice_debug_merge_points, adjust_bridges
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
        for loop in self.storage.loops:
            if 'entry bridge' in loop.comment:
                is_entry = True
            else:
                is_entry = False
            loops.append((is_entry, slice_debug_merge_points(loop.operations)))
        return flask.render_template('index.html', loops=loops)

    def loop(self):
        no = int(flask.request.args.get('no', '1'))
        orig_loop = self.storage.loops[no - 1]
        ops = adjust_bridges(orig_loop, flask.request.args)
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
        if loop.filename is not None:
            code = load_code(loop.filename, loop.name, loop.startlineno)
            source = CodeRepr(inspect.getsource(code), code, loop)
        else:
            source = CodeReprNoFile(loop)
        d = {'html': flask.render_template('loop.html',
                                           source=source,
                                           current_loop=no,
                                           upper_path=up,
                                           show_upper_path=bool(path)),
             'scrollto': startline}
        return flask.jsonify(d)

def main():
    log = parse_log_file('log')
    storage = LoopStorage()
    loops = [parse(l) for l in extract_category(log, "jit-log-opt-")]
    parse_log_counts(open('log.count').readlines(), loops)
    storage.reconnect_loops(loops)
    app = flask.Flask(__name__)
    server = Server(storage)
    app.debug = True
    app.route('/')(server.index)
    app.route('/loop')(server.loop)
    app.run(use_reloader=False, host='0.0.0.0')

if __name__ == '__main__':
    main()
