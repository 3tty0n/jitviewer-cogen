
from _jitviewer import disassembler
import sys
import py

def f(a, b):
    return a + b

def g(a, b):
    c = a+b
    return c

def test_disassembler():
    res = disassembler.dis(f)
    if sys.version_info[:2] != (2, 6):
        py.test.skip("2.6 only test")
    assert len(res.opcodes) == 4
    assert [x.__class__.__name__ for x in res.opcodes] == [
        'LOAD_FAST', 'LOAD_FAST', 'BINARY_ADD', 'RETURN_VALUE']
    for i in range(4):
        assert res.opcodes[i].lineno == f.func_code.co_firstlineno + 1
    assert res.opcodes[0].argstr == 'a'

def test_line_starting_opcodes():
    if sys.version_info[:2] != (2, 6):
        py.test.skip("2.6 only test")
    res = disassembler.dis(g)
    assert len(res.opcodes) == 6
    for i, opcode in enumerate(res.opcodes):
        if i in (0, 4):
            assert opcode.__class__.__name__ == 'LOAD_FAST'
            assert opcode.line_starts_here
        else:
            assert not opcode.line_starts_here
