import re
import cgi
import difflib
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


TEMPLATE_HEADER = re.compile(r'^template (\S+) key=(-?\d+) merge_point=(\d+) '
                             r'regs i=(\d+) r=(\d+) f=(\d+)\s*$')
PROLOGUE = re.compile(r'^\s*prologue ([irf]) (\d+) <- hole\((\w+)\)\s*$')
SOURCE = re.compile(r'\t# (\S+):(\d+) (\S+)\s*$')
EXIT = re.compile(r'^exit \d+\b')
LABEL_DEF = re.compile(r'^L\d+:$')
HOLE = re.compile(r'^hole\((\w+)\)$')
KIND_BRACKET = re.compile(r'\b[IRF]\[')
ANGLE = re.compile(r'<([^<>]*)>')
FIELD_PATH = re.compile(r'pypy(?:\.\w+)+')
# Matches, in order of preference: a hole, a $ref(...) constant (possibly
# with one level of nested parens), a $-prefixed int, a bare int not part
# of a %register or an already-collapsed <descr>, and a raw jump label.
WILDCARD = re.compile(
    r'hole\(\w+\)'
    r'|\$ref\((?:[^()]|\([^()]*\))*\)'
    r'|\$-?\d+'
    r'|(?<![%.\w])-?\d+(?!\w)'
    r'|\bL\d+\b')
KINDS = {'i': 'int_copy', 'r': 'ref_copy', 'f': 'float_copy'}


def _collapse_descr(match):
    # FieldDescr<pypy...> (template) and <FieldS pypy... N> (residual) both
    # carry the same dotted field path; keep only that. Everything else
    # (ArrayDescr/SizeDescr/Calli/...) has no shared textual form between
    # the two sides, so it collapses to one generic placeholder. A JitCode
    # callee name is the one thing worth keeping verbatim.
    inner = match.group(1)
    if inner.startswith('JitCode'):
        return '<%s>' % inner
    field = FIELD_PATH.search(inner)
    if field is not None:
        return '<%s>' % field.group(0)
    return '<descr>'


def _canon(text):
    """Normalize template and residual insn text to the same shape."""
    text = text.replace(',', ' ').replace("'", '')
    text = re.sub(r'\bFieldDescr(?=<)', '', text)
    text = KIND_BRACKET.sub('[', text)
    text = ANGLE.sub(_collapse_descr, text)
    return ' '.join(text.split())


def align_key(text):
    text = _canon(text)
    if text.startswith('-live-'):
        return '-live-'
    op, sep, rest = text.partition(' ')
    if op in ('pe_bailout_point', 'jit_merge_point'):
        op = 'merge'
    return op + sep + WILDCARD.sub('?', rest)


def hole_values(template_text, residual_text):
    template_text = _canon(template_text)
    residual_text = _canon(residual_text)
    parts = []
    names = []
    pos = 0
    for match in WILDCARD.finditer(template_text):
        parts.append(re.escape(template_text[pos:match.start()]))
        hole = HOLE.match(match.group(0))
        if hole is not None:
            names.append(hole.group(1))
            parts.append(r'(\S+?)')
        else:
            parts.append(r'\S+?')
        pos = match.end()
    if not names:
        return {}
    parts.append(re.escape(template_text[pos:]))
    match = re.match(''.join(parts) + '$', residual_text)
    if match is None:
        return {}
    return dict(zip(names, match.groups()))


class Template(object):
    def __init__(self, name, key, merge_point, num_regs):
        self.name = name
        self.key = key
        self.merge_point = merge_point
        self.num_regs = num_regs
        self.prologue = []
        self.insns = []

    def all_insns(self):
        insns = [(None, '%s hole(%s) -> %%%s%d' % (KINDS[kind], hole,
                                                   kind, index), None, False)
                 for kind, index, hole in self.prologue]
        return insns + self.insns


def parse_template(lines):
    templates = {}
    template = None
    for line in lines:
        match = TEMPLATE_HEADER.match(line)
        if match is not None:
            template = Template(match.group(1), int(match.group(2)),
                                int(match.group(3)),
                                tuple([int(x) for x in match.group(4, 5, 6)]))
            templates[(template.name, template.merge_point)] = template
            continue
        if template is None:
            continue
        match = PROLOGUE.match(line)
        if match is not None:
            template.prologue.append((match.group(1), int(match.group(2)),
                                      match.group(3)))
            continue
        source = None
        match = SOURCE.search(line)
        if match is not None:
            source = (match.group(1), int(match.group(2)), match.group(3))
            line = line[:match.start()]
        match = INSN.match(line)
        if match is not None:
            text = match.group(2)
            # Labels, like exits, are structural scaffolding: never folded,
            # never matched against a residual insn.
            boundary = EXIT.match(text) is not None or \
                LABEL_DEF.match(text) is not None
            template.insns.append((int(match.group(1)), text, source,
                                   boundary))
    return templates


def parse_templates(filename):
    log = parse_log_file(filename)
    templates = {}
    for section in extract_category(log, 'jit-jitcode-template'):
        templates.update(parse_template(section.splitlines()))
    return templates


class BlockDiff(object):
    def __init__(self, template):
        self.template = template
        self.holes = {}
        self.line_holes = {}
        self.line_source = {}
        self.matched_template = set()
        self.added = 0

    @property
    def folded(self):
        return len([1 for pos, item in enumerate(self.template.all_insns())
                    if not item[3] and pos not in self.matched_template])

    def summary(self):
        parts = []
        if self.holes:
            parts.append(u'holes: %s' % u', '.join(sorted(self.holes)))
        parts.append(u'folded %d' % self.folded)
        parts.append(u'added %d' % self.added)
        return u' · '.join(parts)

    def template_html(self):
        lines = []
        for pos, item in enumerate(self.template.all_insns()):
            idx, text, source, is_exit = item
            text = cgi.escape(text)
            if not is_exit and pos not in self.matched_template:
                text = '<span class="jitcode-struck">%s</span>' % text
            lines.append('%5s: %s' % (idx is None and '-' or idx, text))
        holes = ' '.join('%s=%s' % (name, cgi.escape(value))
                         for name, value in sorted(self.holes.items()))
        if holes:
            lines.append('holes: ' + holes)
        return '\n'.join(lines)


def align(template, block):
    diff = BlockDiff(template)
    titems = [(pos, item) for pos, item in enumerate(template.all_insns())
              if not item[3]]
    tkeys = [align_key(item[1]) for pos, item in titems]
    rkeys = [align_key(text) for pc, text in block.insns]
    matcher = difflib.SequenceMatcher(None, tkeys, rkeys)
    matched = 0
    for i, j, size in matcher.get_matching_blocks():
        for offset in range(size):
            pos, (idx, text, source, is_exit) = titems[i + offset]
            pc, residual = block.insns[j + offset]
            diff.matched_template.add(pos)
            matched += 1
            if source is not None:
                diff.line_source[pc] = source
            values = hole_values(text, residual)
            if values:
                diff.holes.update(values)
                diff.line_holes[pc] = set(values.values())
    diff.added = len(block.insns) - matched
    return diff


class Block(object):
    def __init__(self, bytecode_pc, insns):
        self.bytecode_pc = bytecode_pc
        self.insns = insns

    def html(self, opname=None, diff=None):
        folded = diff is None and folded_operands(self, opname) or set()

        lines = []
        for pc, text in self.insns:
            if diff is not None:
                folded = diff.line_holes.get(pc, set())

            def span(match, folded=folded):
                cls = match.group(0) in folded and 'jitcode-folded' \
                    or 'jitcode-const'
                return '<span class="%s">%s</span>' % (cls, match.group(0))

            line = '<span class="jitcode-text">%5d: %s</span>' % (
                pc, CONST.sub(span, cgi.escape(text)))
            source = diff is not None and diff.line_source.get(pc) or None
            if source is not None:
                line += '<span class="jitcode-src">%s:%d</span>' % (
                    cgi.escape(source[0].split('/')[-1]), source[1])
            lines.append('<div class="jitcode-line">%s</div>' % line)
        return ''.join(lines)


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
                return line.strip(), i + 1
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
        return truncated and text + '\n...' or text, start + 1
    return None


def handler_source(opname):
    if opname not in _handlers:
        source = pyopcode_source()
        _handlers[opname] = source and _extract(source, opname) \
            or ('(no handler)', 0)
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
