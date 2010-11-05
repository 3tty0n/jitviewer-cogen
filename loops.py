
import re, sys
from pypy.jit.metainterp.resoperation import rop, opname
from disassembler import dis
from pypy.jit.tool.oparser import OpParser

def _new_binop(name):
    def f(self):
        return '%s = %s %s %s' % (self.res, self.args[0], name, self.args[1])
    return f

class Op(object):
    bridge = None
    
    def __init__(self, name, args, res, descr):
        self.name = name
        self.args = args
        self.res = res
        self.descr = descr
        self._is_guard = name.startswith('guard_')
        if self._is_guard:
            self.guard_no = int(self.descr[len('<Guard'):-1])

    def setfailargs(self, _):
        pass

    def html_repr(self):
        return getattr(self, 'repr_' + self.name, self.generic_repr)()

    def is_guard(self):
        return self._is_guard

    for bin_op, name in [('<', 'int_lt'),
                         ('>', 'int_gt'),
                         ('<=', 'int_le'),
                         ('>=', 'int_ge'),
                         ('+', 'int_add'),
                         ('+', 'float_add'),
                         ('-', 'int_sub'),
                         ('-', 'float_sub'),
                         ('&', 'int_and')]:
        locals()['repr_' + name] = _new_binop(bin_op)

    def repr_guard_true(self):
        return '%s is true' % self.args[0]

    def repr_guard_false(self):
        return '%s is false' % self.args[0]

    def repr_guard_value(self):
        return '%s is %s' % (self.args[0], self.args[1])

    def repr_guard_isnull(self):
        return '%s is null' % self.args[0]

    def repr_getfield_raw(self):
        name, field = self.descr.split(' ')[1].rsplit('.', 1)
        return '%s = ((%s)%s).%s' % (self.res, name, self.args[0], field[2:])

    def repr_getfield_gc(self):
        name, field = self.descr.split(' ')[1].rsplit('.', 1)
        return '%s = ((%s)%s).%s' % (self.res, name, self.args[0], field)
    repr_getfield_gc_pure = repr_getfield_gc

    def repr_setfield_raw(self):
        name, field = self.descr.split(' ')[1].rsplit('.', 1)
        return '((%s)%s).%s = %s' % (name, self.args[0], field[2:], self.args[1])

    def repr_setfield_gc(self):
        name, field = self.descr.split(' ')[1].rsplit('.', 1)
        return '((%s)%s).%s = %s' % (name, self.args[0], field, self.args[1])

    def generic_repr(self):
        if self.res is not None:
            return '%s = %s(%s)' % (self.res, self.name, ', '.join(self.args))
        else:
            return '%s(%s)' % (self.name, ', '.join(self.args))

    def __repr__(self):
        return '<%s (%s)>' % (self.name, ', '.join([repr(a)
                                                    for a in self.args]))

    def extra_style(self):
        if self.name.startswith('guard_'):
            return 'guard'
        return ''

class SimpleParser(OpParser):
    def parse_args(self, opname, argspec):
        if not argspec.strip():
            return [], None
        if opname == 'debug_merge_point':
            return [argspec], None
        else:
            args = argspec.split(', ')
            descr = None
            if args[-1].startswith('descr='):
                descr = args[-1][len('descr='):]
                args = args[:-1]
            return (args, descr)

    def box_for_var(self, res):
        return res

    def create_op(self, opnum, args, res, descr):
        return Op(intern(opname[opnum].lower()), args, res, descr)

class NonCodeError(Exception):
    pass

class Bytecode(object):
    filename = None
    startlineno = 0
    name = None
    code = None
    bytecode_no = 0
    bytecode_name = None
    is_bytecode = True
    
    def __init__(self, operations, storage):
        if operations[0].name == 'debug_merge_point':
            m = re.search('<code object ([<>\w]+), file \'(.+?)\', line (\d+)> #(\d+) (\w+)',
                         operations[0].args[0])
            if m is None:
                # a non-code loop, like StrLiteralSearch or something
                self.bytecode_name = operations[0].args[0].split(" ")[0][1:]
            else:
                self.name, self.filename, lineno, bytecode_no, self.bytecode_name = m.groups()
                self.startlineno = int(lineno)
                self.bytecode_no = int(bytecode_no)
        self.operations = operations
        self.storage = storage

    def key(self):
        return self.startlineno, self.name, self.filename

    def repr(self):
        if self.filename is None:
            return "Unknown"
        return "%s, file '%s', line %d" % (self.name, self.filename,
                                           self.startlineno)

    def getcode(self):
        if self.code is None:
            self.code = dis(self.storage.load_code(self.filename)[self.startlineno])
        return self.code

    def getlineno(self):
        code = self.getcode()
        return code.map[self.bytecode_no].lineno
    lineno = property(getlineno)

    def __repr__(self):
        return "[%s]" % ", ".join([repr(op) for op in self.operations])

    def pretty_print(self, out):
        pass

    def html_repr(self):
        return self.bytecode_name

class Function(object):
    filename = None
    name = None
    startlineno = 0
    _linerange = None
    is_bytecode = False
    
    def __init__(self, chunks, path, storage):
        self.path = path
        self.chunks = chunks
        for chunk in self.chunks:
            if chunk.filename is not None:
                self.startlineno = chunk.startlineno
                self.filename = chunk.filename
                self.name = chunk.name
                break
        self.storage = storage

    def key(self):
        return self.startlineno, self.name, self.filename

    def getlinerange(self):
        if self._linerange is None:
            minline = sys.maxint
            maxline = -1
            for chunk in self.chunks:
                if chunk.is_bytecode and chunk.filename is not None:
                    lineno = chunk.lineno
                    minline = min(minline, lineno)
                    maxline = max(maxline, lineno)
            if minline == sys.maxint:
                minline = 0
                maxline = 0
            self._linerange = minline, maxline
        return self._linerange
    linerange = property(getlinerange)

    def html_repr(self):
        return "inlined call to %s in %s" % (self.name, self.filename)

    def repr(self):
        if self.filename is None:
            return "Unknown"
        return "%s, file '%s', line %d" % (self.name, self.filename,
                                           self.startlineno)
        
    def __repr__(self):
        return "[%s]" % ", ".join([repr(chunk) for chunk in self.chunks])

    def pretty_print(self, out):
        print >>out, "Loop starting at %s in %s at %d" % (self.name,
                                        self.filename, self.startlineno)
        lineno = -1
        for chunk in self.chunks:
            if chunk.filename is not None and chunk.lineno != lineno:
                lineno = chunk.lineno
                source = chunk.getcode().source[chunk.lineno -
                                                chunk.startlineno]
                print >>out, "  ", source
            chunk.pretty_print(out)

def parse_log_counts(lines, loops):
    nums = []
    i = 0
    for line in lines:
        if line:
            num, count = line.split(':')
            assert int(num) == i
            count = int(count)
            nums.append(count)
            loops[i].count = count
            i += 1
    return nums

def parse(input):
    return SimpleParser(input, None, {}, 'lltype', None,
                        nonstrict=True).parse()

def slice_debug_merge_points(operations, storage):
    """ Slice given operation list into a chain of Bytecode chunks.
    Also detect inlined functions and make them Function
    """
    stack = []

    def getpath(stack):
        return ",".join([str(len(v)) for _, v in stack])

    def append_to_res(bc):
        if not stack:
            stack.append((bc.key(), []))
        else:
            if stack[-1][0] != bc.key():
                previous_bytecode = stack[-1][1][-1]
                # XXX PRETTY FRAGILE
                # if any of those bytecodes were encountered and next bytecode
                # is from somewhere else, then we need to pop one block
                if (previous_bytecode.bytecode_name in
                    ['RAISE_VARARGS', 'RETURN_VALUE', 'YIELD_VALUE']):
                    _, last = stack.pop()
                    stack[-1][1].append(Function(last, getpath(stack), storage))
                else:
                    stack.append((bc.key(), []))
        stack[-1][1].append(bc)

    so_far = []
    stack = []
    for op in operations:
        if op.name == 'debug_merge_point':
            if so_far:
                append_to_res(Bytecode(so_far, storage))
                so_far = []
        so_far.append(op)
    if so_far:
        append_to_res(Bytecode(so_far, storage))
    # wrap stack back up
    if not stack:
        # no ops whatsoever
        return Function([], getpath(stack), storage)
    while True:
        _, next = stack.pop()
        if not stack:
            return Function(next, getpath(stack), storage)
        stack[-1][1].append(Function(next, getpath(stack), storage))

def adjust_bridges(loop, bridges):
    """ Slice given loop according to given bridges to follow. Returns a plain
    list of operations.
    """
    ops = loop.operations
    res = []
    i = 0
    while i < len(ops):
        op = ops[i]
        if op.is_guard() and bridges.get('loop-' + str(op.guard_no), None):
            res.append(op)
            i = 0
            ops = op.bridge.operations
        else:
            res.append(op)
            i += 1
    return res
