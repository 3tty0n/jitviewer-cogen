import os
import pytest
from _jitviewer.jitcodeparser import parse_jitcode_dumps, folded_operands, \
     handler_source, parse_templates, align

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
    assert sorted(templates) == [('LOAD_CONST', 0), ('LOAD_FAST', 1)]
    load_fast = templates[('LOAD_FAST', 1)]
    assert load_fast.key == 124
    assert load_fast.prologue == [('i', 1, 'oparg')]
    assert templates[('LOAD_CONST', 0)].insns[0][2] == \
        ('pypy/interpreter/pyopcode.py', 94, 'dispatch')


def test_align_load_const():
    diff = align(parse_templates(TEMPLATE_LOG)[('LOAD_CONST', 0)],
                 block_at(3))
    assert diff.holes == {'pc': '$3', 'oparg': '$1',
                          'pycode': '$ref(0xad64e31a0)'}
    assert diff.folded == 2
    assert diff.added >= 4
    source = [diff.line_source[pc] for pc, text in block_at(3).insns
              if text.startswith('getarrayitem_gc_r_pure')]
    assert source == [('pypy/interpreter/pyopcode.py', 625, 'LOAD_CONST')]
    html = block_at(3).html('LOAD_CONST', diff)
    assert 'jitcode-folded">$1<' in html
    assert 'pyopcode.py:625' in html
