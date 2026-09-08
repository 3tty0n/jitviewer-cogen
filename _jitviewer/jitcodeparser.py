import re
import cgi
import textwrap

try:
    from rpython.tool.logparser import parse_log_file, extract_category
except ImportError:
    from pypy.tool.logparser import parse_log_file, extract_category

HEADER = re.compile(r'^jitcode (\S+): (\d+) bytes, '
                    r'regs i=(\d+) r=(\d+) f=(\d+), '
                    r'consts i=(\d+) r=(\d+) f=(\d+)\s*$')
INSN = re.compile(r'^\s*(\d+): (.*?)\s*$')
BLOCK_START = re.compile(r'^(?:pe_bailout_point|jit_merge_point) '
                         r'\d+ \[\$(\d+)[,\]].*?\[(\$ref\(0x[0-9a-f]+\))?\]')
RESET = re.compile(r'^(?:int_copy 0|ref_copy \$ref\(0x0\)) ->')
CONST = re.compile(r'\$(?:ref\(0x[0-9a-fA-F]+\)|-?\d+)')
CODE_OBJECT = re.compile(r'<code object (\w+)[,.] file \'([^\']+)\'[,.] '
                         r'line (\d+)>')
GREENS = re.compile(r'^(?:pe_bailout_point|jit_merge_point) \d+ '
                    r'\[(\$-?\d+)[,\]].*?\[(\$ref\(0x[0-9a-fA-F]+\))?\]')
LAST_INSTR = re.compile(r'^setfield_vable_i %\w+ (\$-?\d+) '
                        r'<FieldS[^>]*inst_last_instr')
CALL = re.compile(r'^(?:inline_call|residual_call)\S*\s+<JitCode ([^>]+)>'
                  r'(.*)$')
GETARRAY = re.compile(r'^getarrayitem_gc_r_pure %\w+ (\$-?\d+)')
CONST_ARRAY_FIELDS = ('inst_co_consts_w', 'inst_co_names_w', 'inst_fastlocals')
INT_CONST = re.compile(r'\$-?\d+')


def folded_operands(block, opname):
    folded = set()
    previous = ''
    for pc, text in block.insns:
        match = GREENS.match(text)
        if match is not None:
            folded.add(match.group(1))
            if match.group(2):
                folded.add(match.group(2))
        match = LAST_INSTR.match(text)
        if match is not None:
            folded.add(match.group(1))
        match = CALL.match(text)
        if match is not None and opname and \
                opname.lower() in match.group(1).lower():
            folded.update(INT_CONST.findall(match.group(2)))
        match = GETARRAY.match(text)
        if match is not None and \
                previous.startswith('getfield_gc_r_pure') and \
                any(f in previous for f in CONST_ARRAY_FIELDS):
            folded.add(match.group(1))
        previous = text
    return folded


class Block(object):
    def __init__(self, bytecode_pc, insns):
        self.bytecode_pc = bytecode_pc
        self.insns = insns

    def html(self, opname=None):
        folded = folded_operands(self, opname)

        def span(match):
            cls = match.group(0) in folded and 'jitcode-folded' \
                or 'jitcode-const'
            return '<span class="%s">%s</span>' % (cls, match.group(0))

        lines = []
        for pc, text in self.insns:
            lines.append('%5d: %s' % (pc, CONST.sub(span, cgi.escape(text))))
        return '\n'.join(lines)


class JitCodeDump(object):
    def __init__(self, name, size, num_regs, num_consts):
        self.name = name
        self.size = size
        self.num_regs = num_regs
        self.num_consts = num_consts
        self.pycode_ref = None
        self.blocks = []

    def bytecode_pcs(self):
        return [block.bytecode_pc for block in self.blocks]


def parse_dump(lines):
    dump = None
    insns = []
    blocks = []
    pending = []
    bytecode_pc = None
    for line in lines:
        match = HEADER.match(line)
        if match is not None:
            name = match.group(1)
            dump = JitCodeDump(name, int(match.group(2)),
                               tuple([int(x) for x in match.group(3, 4, 5)]),
                               tuple([int(x) for x in match.group(6, 7, 8)]))
            continue
        match = INSN.match(line)
        if dump is None or match is None:
            continue
        pc, text = int(match.group(1)), match.group(2)
        start = BLOCK_START.match(text)
        if start is not None:
            if bytecode_pc is not None:
                blocks.append(Block(bytecode_pc,
                                    insns[:len(insns) - len(pending)]))
                insns = pending
            if dump.pycode_ref is None:
                dump.pycode_ref = start.group(2)
            bytecode_pc = int(start.group(1))
        if RESET.match(text):
            pending.append((pc, text))
        else:
            pending = []
        insns.append((pc, text))
    if dump is None:
        return None
    if bytecode_pc is not None:
        blocks.append(Block(bytecode_pc, insns))
    dump.blocks = blocks
    return dump


def parse_jitcode_dumps(filename):
    log = parse_log_file(filename)
    dumps = []
    for section in extract_category(log, 'jit-jitcode-dump'):
        dump = parse_dump(section.splitlines())
        if dump is not None:
            dumps.append(dump)
    return dumps


def find_code_objects(filename):
    seen = []
    for name, fname, lineno in CODE_OBJECT.findall(open(filename).read()):
        key = (fname, int(lineno), name)
        if key not in seen:
            seen.append(key)
    return seen


def disassemble(storage, key):
    from rpython.tool.disassembler import dis
    fname, startlineno, name = key
    try:
        codeobjs = storage.load_code(fname)
    except (IOError, OSError):
        return None
    code = codeobjs.get((startlineno, name), None)
    if code is None:
        return None
    return dis(code)


def source_line(code, lineno):
    index = lineno - code.startlineno
    if 0 <= index < len(code.source):
        return code.source[index].rstrip()
    return ''


HANDLER_LINES = 25
_handlers = {}
_pyopcode_source = []


def pyopcode_source():
    if not _pyopcode_source:
        try:
            import inspect
            import pypy.interpreter.pyopcode as mod
            source = open(inspect.getsourcefile(mod)).read().splitlines()
        except (ImportError, IOError, OSError, TypeError):
            source = []
        _pyopcode_source.append(source)
    return _pyopcode_source[0]


def _extract(source, opname):
    header = re.compile(r'^(\s+)def %s\s*\(' % re.escape(opname))
    assign = re.compile(r'^\s+%s\s*=\s*\S' % re.escape(opname))
    for i, line in enumerate(source):
        match = header.match(line)
        if match is None:
            if assign.match(line):
                return line.strip()
            continue
        indent = len(match.group(1))
        start = i
        while start and source[start - 1].strip().startswith('@'):
            start -= 1
        end = i + 1
        while end < len(source):
            stripped = source[end].strip()
            if stripped and len(source[end]) - \
                    len(source[end].lstrip()) <= indent:
                break
            end += 1
        lines = source[start:end]
        while lines and not lines[-1].strip():
            lines.pop()
        truncated = len(lines) > HANDLER_LINES
        text = textwrap.dedent('\n'.join(lines[:HANDLER_LINES]))
        return truncated and text + '\n...' or text
    return None


def handler_source(opname):
    if opname not in _handlers:
        source = pyopcode_source()
        _handlers[opname] = source and _extract(source, opname) \
            or '(no handler)'
    return _handlers[opname]


def match_code(dump, candidates, storage):
    pcs = set(dump.bytecode_pcs())
    best = None
    for key in candidates:
        code = disassemble(storage, key)
        if code is None:
            continue
        offsets = set(code.map)
        if not pcs.issubset(offsets):
            continue
        if best is None or len(offsets) < len(best.map):
            best = code
    return best
