import os
import pytest
from _jitviewer.jitcodeparser import parse_jitcode_dumps, folded_operands, \
     handler_source, parse_templates, align, highlight_insn

LOG = os.path.join(os.path.dirname(__file__), 'jitcode-dump.log')
TEMPLATE_LOG = os.path.join(os.path.dirname(__file__), 'jitcode-template.log')


def test_parse_dump():
    dumps = parse_jitcode_dumps(LOG)
    assert len(dumps) == 1
    dump = dumps[0]
    assert dump.name == 'linked-pypy-runtime-cogen'
    assert dump.size == 2220
    assert dump.pycode_ref == '$ref(0xad64e31a0)'
    assert len(dump.blocks) == 22
    assert dump.bytecode_pcs() == [0, 3, 6, 9, 12, 15, 18, 21, 24, 27, 28, 31,
                                   34, 37, 38, 41, 44, 47, 50, 51, 54, 55]
    first = dump.blocks[0]
    assert first.insns[0] == (0, 'int_copy 0 -> %i1')
    assert 'jit_merge_point' in [text.split(' ')[0]
                                 for pc, text in first.insns]
    assert 'jitcode-const' in first.html()


def block_at(pc):
    dump = parse_jitcode_dumps(LOG)[0]
    for block in dump.blocks:
        if block.bytecode_pc == pc:
            return block
    raise AssertionError(pc)


def test_folded_operands_compare_op():
    block = block_at(6)
    assert folded_operands(block, 'COMPARE_OP') == set(
        ['$6', '$2', '$9', '$ref(0xad64e31a0)'])
    assert 'jitcode-folded' in block.html('COMPARE_OP')


def test_folded_operands_load_const():
    block = block_at(3)
    assert folded_operands(block, 'LOAD_CONST') == set(
        ['$3', '$1', '$ref(0xad64e31a0)'])


def test_handler_source():
    try:
        import pypy.interpreter.pyopcode
    except ImportError:
        pytest.skip('pypy not importable')
    text, lineno = handler_source('LOAD_FAST')
    assert 'def LOAD_FAST' in text
    assert lineno > 0


def test_parse_templates():
    templates = parse_templates(TEMPLATE_LOG)
    assert sorted(templates) == [
        ('BINARY_ADD', 0), ('BINARY_ADD', 1),
        ('BINARY_SUBTRACT', 0), ('BINARY_SUBTRACT', 1),
        ('CALL_FUNCTION', 0), ('CALL_FUNCTION', 1),
        ('COMPARE_OP', 0), ('COMPARE_OP', 1),
        ('LOAD_CONST', 0), ('LOAD_CONST', 1),
        ('LOAD_FAST', 0), ('LOAD_FAST', 1),
        ('LOAD_GLOBAL', 0), ('LOAD_GLOBAL', 1),
        ('POP_JUMP_IF_FALSE', 0), ('POP_JUMP_IF_FALSE', 1),
        ('POP_JUMP_IF_TRUE', 0), ('POP_JUMP_IF_TRUE', 1),
        ('RETURN_VALUE', 0), ('RETURN_VALUE', 1)]
    load_fast = templates[('LOAD_FAST', 1)]
    assert load_fast.key == 124
    # The real build never emits a prologue for this jitdriver; the parser
    # still supports one (PROLOGUE regex) in case another jitdriver needs it.
    assert load_fast.prologue == []
    load_const = templates[('LOAD_CONST', 0)]
    assert load_const.insns[0] == (0, 'L1:', None, True)
    assert load_const.insns[2][2] == \
        ('pypy/interpreter/pyopcode.py', 273, 'interp_step')
    exits = [item for item in load_const.all_insns() if item[3] and
             item[1].startswith('exit')]
    assert exits and exits[0][1].startswith('exit 0 [')


def test_align_load_const():
    diff = align(parse_templates(TEMPLATE_LOG)[('LOAD_CONST', 0)],
                 block_at(3))
    assert diff.holes == {'pc': '$3', 'instr_start': '$3', 'oparg': '$1',
                          'pycode': '$ref(0xad64e31a0)'}
    assert diff.folded == 1
    assert diff.added == 5
    source = [diff.line_source[pc] for pc, text in block_at(3).insns
              if text.startswith('getarrayitem_gc_r_pure')]
    assert source == [('rpython/rtyper/rlist.py', 695, 'll_getitem_nonneg')]
    html = block_at(3).html('LOAD_CONST', diff)
    assert 'jitcode-folded">$1<' in html
    assert 'rlist.py:695' in html


def test_pairs_load_const():
    template = parse_templates(TEMPLATE_LOG)[('LOAD_CONST', 0)]
    block = block_at(3)
    diff = align(template, block)
    residual_seen = []
    template_seen = []
    for titem, ritem, kind in diff.pairs:
        assert kind in ('match', 'folded', 'added')
        if titem is not None:
            template_seen.append(titem)
        if ritem is not None:
            residual_seen.append(ritem)
        if kind == 'match':
            assert titem is not None and ritem is not None
        elif kind == 'folded':
            assert titem is not None and ritem is None
        else:
            assert titem is None and ritem is not None
    assert residual_seen == block.insns
    assert template_seen == template.all_insns()
    boundary_count = len([1 for item in template.all_insns() if item[3]])
    folded_count = len([1 for t, r, k in diff.pairs if k == 'folded'])
    added_count = len([1 for t, r, k in diff.pairs if k == 'added'])
    assert folded_count == diff.folded + boundary_count
    assert added_count == diff.added
    bailout = [(t, r) for t, r, k in diff.pairs
              if k == 'match' and t[1].startswith('pe_bailout_point')]
    assert len(bailout) == 1
    assert bailout[0][1][1].startswith('pe_bailout_point')


def test_highlight_insn():
    html = highlight_insn(
        "3: setfield_gc_i %i0 $ref(0xad64e31a0) <FieldS pypy.foo.Bar.x 8>")
    assert 'class="jc-pc">3:<' in html
    assert 'class="jc-op">setfield_gc_i<' in html
    assert 'class="jc-reg">%i0<' in html
    assert 'class="jc-const jitcode-const">$ref(0xad64e31a0)<' in html
    assert 'class="jc-descr">&lt;FieldS pypy.foo.Bar.x 8&gt;<' in html


def test_highlight_insn_template_source():
    html = highlight_insn(
        "20: int_copy hole(pc) -> %i0"
        "\t# pypy/interpreter/pyopcode.py:273 interp_step")
    assert 'class="jc-hole jitcode-folded">hole(pc)<' in html
    assert '<span class="jc-src">\t# pypy/interpreter/pyopcode.py:273' \
        ' interp_step</span>' in html
    assert html.count('jc-src') == 1


def test_align_load_fast_merge_point():
    diff = align(parse_templates(TEMPLATE_LOG)[('LOAD_FAST', 1)],
                 block_at(0))
    assert 20 in diff.line_holes
    assert diff.line_holes[20] == set(['$0', '$ref(0xad64e31a0)'])
    merge_line = [text for pc, text in block_at(0).insns if pc == 20][0]
    assert merge_line.startswith('jit_merge_point')
