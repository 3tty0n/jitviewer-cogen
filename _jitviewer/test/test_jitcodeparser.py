import os
from _jitviewer.jitcodeparser import parse_jitcode_dumps

LOG = os.path.join(os.path.dirname(__file__), 'jitcode-dump.log')


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
