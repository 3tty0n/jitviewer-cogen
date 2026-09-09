import re
import cgi
import difflib
import textwrap

try:
    from rpython.tool.logparser import parse_log_file, extract_category
except ImportError:
    from pypy.tool.logparser import parse_log_file, extract_category

try:
    from pygments import highlight as _pygments_highlight
    from pygments.lexers import PythonLexer
    from pygments.formatters import HtmlFormatter
except ImportError:
    _pygments_highlight = None

HEADER = re.compile(r'^jitcode (\S+): (\d+) bytes, '
                    r'regs i=(\d+) r=(\d+) f=(\d+), '
                    r'consts i=(\d+) r=(\d+) f=(\d+)\s*$')
INSN = re.compile(r'^\s*(\d+): (.*?)\s*$')
BLOCK_START = re.compile(r'^(?:pe_bailout_point|jit_merge_point) '
                         r'\d+ \[\$(\d+)[,\]].*?\[(\$ref\(0x[0-9a-f]+\))?\]')
RESET = re.compile(r'^(?:int_copy 0|ref_copy \$ref\(0x0\)) ->')
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


_PY_LEXER = None
_PY_FORMATTER = None


def highlight_python(text):
    if _pygments_highlight is None:
        return [cgi.escape(line) for line in text.splitlines()]
    global _PY_LEXER, _PY_FORMATTER
    if _PY_LEXER is None:
        _PY_LEXER = PythonLexer()
        _PY_FORMATTER = HtmlFormatter(nowrap=True)
    html = _pygments_highlight(text, _PY_LEXER, _PY_FORMATTER)
    lines = html.split('\n')
    nlines = len(text.splitlines())
    while len(lines) > nlines and lines and not lines[-1].strip():
        lines.pop()
    return lines


TOKEN = re.compile(
    r'(?P<hole>hole\(\w+\))'
    r'|(?P<descr><[^<>]*>)'
    r'|(?P<label>\bL\d+:?)'
    r'|(?P<live>-live-(?: @\d+)?)'
    r'|(?P<reg>%[irf]\d+)'
    r'|(?P<const>\$ref\((?:[^()]|\([^()]*\))*\)|\$-?\d+|\b\d+\b)'
    r'|(?P<op>[A-Za-z_]\w*)')
CONTROL_OP = re.compile(
    r'^(goto(_if_not\w*)?|pe_bailout_point|jit_merge_point|exit\w*|'
    r'\w*_return)$')
PC_PREFIX = re.compile(r'^(\s*)((?:-|\d+):)')


def highlight_insn(text, folded=None):
    folded = folded or ()
    src_match = SOURCE.search(text)
    if src_match is not None:
        head, src = text[:src_match.start()], text[src_match.start():]
    else:
        head, src = text, ''
    pc_match = PC_PREFIX.match(head)
    if pc_match is not None:
        ws, pcnum = pc_match.group(1), pc_match.group(2)
        body = head[pc_match.end():]
    else:
        ws, pcnum, body = '', '', head
    out = []
    if ws:
        out.append(cgi.escape(ws))
    if pcnum:
        out.append('<span class="jc-pc">%s</span>' % cgi.escape(pcnum))
    pos = 0
    for m in TOKEN.finditer(body):
        if m.start() > pos:
            out.append(cgi.escape(body[pos:m.start()]))
        kind = m.lastgroup
        value = m.group(0)
        cls = 'jc-' + kind
        if kind == 'op' and CONTROL_OP.match(value):
            cls += ' jc-control'
        elif kind == 'hole':
            cls += ' jitcode-folded'
        elif kind == 'const':
            cls += value in folded and ' jitcode-folded' or ' jitcode-const'
        out.append('<span class="%s">%s</span>' % (cls, cgi.escape(value)))
        pos = m.end()
    if pos < len(body):
        out.append(cgi.escape(body[pos:]))
    if src:
        out.append('<span class="jc-src">%s</span>' % cgi.escape(src))
    return ''.join(out)


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
        self.pairs = []

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
        return ' | '.join(parts)


def align(template, block):
    diff = BlockDiff(template)
    allitems = list(enumerate(template.all_insns()))
    titems = [(pos, item) for pos, item in allitems if not item[3]]
    tkeys = [align_key(item[1]) for pos, item in titems]
    rkeys = [align_key(text) for pc, text in block.insns]
    matcher = difflib.SequenceMatcher(None, tkeys, rkeys)
    pairs = []
    emitted = set()

    def emit_boundaries(limit_pos):
        for pos, item in allitems:
            if not item[3] or pos in emitted:
                continue
            if limit_pos is not None and pos >= limit_pos:
                break
            pairs.append((item, None, 'folded'))
            emitted.add(pos)

    matched = 0
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == 'equal':
            for offset in range(i2 - i1):
                pos, (idx, text, source, is_exit) = titems[i1 + offset]
                emit_boundaries(pos)
                pc, residual = block.insns[j1 + offset]
                diff.matched_template.add(pos)
                matched += 1
                if source is not None:
                    diff.line_source[pc] = source
                values = hole_values(text, residual)
                if values:
                    diff.holes.update(values)
                    diff.line_holes[pc] = set(values.values())
                pairs.append((titems[i1 + offset][1], (pc, residual), 'match'))
        else:
            for offset in range(i1, i2):
                pos, item = titems[offset]
                emit_boundaries(pos)
                pairs.append((item, None, 'folded'))
            for offset in range(j1, j2):
                pairs.append((None, block.insns[offset], 'added'))
    emit_boundaries(None)
    diff.added = len(block.insns) - matched
    diff.pairs = pairs
    return diff


class Block(object):
    def __init__(self, bytecode_pc, insns):
        self.bytecode_pc = bytecode_pc
        self.insns = insns

    def html(self, opname=None, diff=None):
        default_folded = diff is None and folded_operands(self, opname) or set()

        lines = []
        for pc, text in self.insns:
            folded = diff.line_holes.get(pc, set()) if diff is not None \
                else default_folded
            line_text = '%5d: %s' % (pc, text)
            line = '<span class="jitcode-text">%s</span>' % \
                highlight_insn(line_text, folded)
            source = diff is not None and diff.line_source.get(pc) or None
            if source is not None:
                line += '<span class="jitcode-src">%s:%d</span>' % (
                    cgi.escape(source[0].split('/')[-1]), source[1])
            lines.append('<div class="jitcode-line">%s</div>' % line)
        return ''.join(lines)


def diff_table_html(block, opname, diff):
    rows = []
    if diff is None:
        folded = folded_operands(block, opname)
        for pc, text in block.insns:
            line_text = '%5d: %s' % (pc, text)
            res_html = highlight_insn(line_text, folded)
            rows.append('<tr><td class="res">%s</td></tr>' % res_html)
    else:
        for titem, ritem, kind in diff.pairs:
            tmpl_html = ''
            tmpl_title = ''
            if titem is not None:
                idx, text, source, is_exit = titem
                line_text = '%5s: %s' % (idx is None and '-' or idx, text)
                tmpl_html = highlight_insn(line_text)
                tmpl_title = cgi.escape(text, True)
            res_html = ''
            res_title = ''
            if ritem is not None:
                pc, text = ritem
                line_text = '%5d: %s' % (pc, text)
                res_html = highlight_insn(line_text, diff.line_holes.get(pc, set()))
                res_title = cgi.escape(text, True)
                source = diff.line_source.get(pc)
                if source is not None:
                    res_html += '<span class="jitcode-src">%s:%d</span>' % (
                        cgi.escape(source[0].split('/')[-1]), source[1])
            rows.append('<tr class="jc-row-%s"><td class="tmpl" title="%s">%s'
                        '</td><td class="res" title="%s">%s</td></tr>' % (
                            kind, tmpl_title, tmpl_html, res_title, res_html))
    return '<table class="jitcode-diff">%s</table>' % ''.join(rows)


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
