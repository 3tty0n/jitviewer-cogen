# jitviewer-cogen usage

Fork of PyPy's jitviewer with a residual JitCode view for the online-cogen
branch. Python 2 only (run everything with `pypy2` or `python2`).

## Requirements

- A PyPy source checkout of the online-cogen branch on `PYTHONPATH`
  (for `rpython.tool.logparser`, `pypy.tool.jitlogparser`, and the
  interpreter handler column, which reads `pypy/interpreter/pyopcode.py`).
- Flask and Jinja2 (`pip2 install -r requirements.txt`).
- A translated binary with runtime cogen built in (`PYPY_PE_COGEN=1` at
  translation time, or a branch where it is the default, e.g.
  `pypy-cogen-c`). A plain `pypy-c` never emits `jit-jitcode-dump`.

## 1. Collect a log

    cd path/to/benchmarks/own
    PYPY_COGEN_THRESHOLD=1 \
    PYPYLOG=jit-log-opt,jit-backend-counts,jit-jitcode-dump,jit-jitcode-template:fib.log \
        pypy-cogen-c fib.py -n 3

- `jit-jitcode-dump` carries the residual JitCode.
- `jit-jitcode-template` carries the per-opcode cogen templates, emitted
  once per process; without it the JitCode still renders, using the older
  constant-folding heuristic for the highlighting.
- `jit-log-opt` carries the code objects used to align the dump with the
  Python source and bytecode; without it the JitCode still renders but has
  no source column.
- `PYPY_COGEN_THRESHOLD=1` makes cogen generate on the first miss; the
  default (32 misses) produces nothing on short runs.
- Add `pe-cogen` to the category list to also record the cogen gate and
  fold statistics (not used by the viewer, but useful next to it).

## 2. Start the viewer

    cd path/to/jitviewer-cogen
    PYTHONPATH=$PWD:path/to/pypy-cogen \
        pypy2 bin/jitviewer.py --log path/to/fib.log --port 5001

Then open http://localhost:5001/. Put the repository first on `PYTHONPATH`:
`bin/jitviewer.py` appends itself to `sys.path`, so an older `_jitviewer`
installed in site-packages would otherwise shadow this checkout.

Keep the log next to the benchmark source: jitviewer resolves the `.py`
files named in the log relative to the log file's directory, so write the
log into the directory that holds `fib.py` (as in step 1). `--collect`
can also run the program and collect the log in one go:

    pypy2 bin/jitviewer.py --collect pypy-cogen-c fib.py -n 3

## 3. Read the JitCode page

The index page lists loops as before, plus a "Residual JitCode dumps"
section. Each entry opens `/jitcode/<index>` with one row per Python
bytecode:

| column | content |
|---|---|
| source | the Python line, with the bytecode's dis line under it |
| handler | the RPython method for that opcode from `pyopcode.py` (toggle with the checkbox above the table) |
| JitCode | the residual block, verbatim from the log |

If the log has `jit-jitcode-template`, each residual block is diffed against
the template of its opcode (merge point 1 for the first block, 0 for the
rest) by sequence alignment on a key made of the instruction text with holes
and `$` constants wildcarded and register names kept. The result gives, per
block: the holes the cogen filled in (highlighted blue in the JitCode
column, listed under the PC label), the template lines the cogen folded away
and the residual lines it added (counted in the same summary line), the
RPython source position of every residual line that matched a template line
(grey, right of the line, and highlighted in the handler column), and the
template itself under the block ("show cogen template" checkbox, collapsed
by default, folded lines struck through).

Each block starts with register resets, then `pe_bailout_point` (or
`jit_merge_point` for the first block) whose first green is the bytecode
offset, then `setfield_vable_i ... inst_last_instr`, the specialised body,
and a `goto` to the next block. `pe_bailout_point` is the bytecode boundary
where the residual program can return to the generic interpreter and where
traces and bridges may start or end.

Highlighting:

- blue, bold: constants the cogen folded in from the program (bytecode
  offsets, opargs and `next_instr` passed to opcode handlers, `co_consts`
  and `co_names` indices, the PyCode reference)
- grey: every other `$` constant

If the viewer cannot match a dump to a code object (it looks for the
smallest code object whose bytecode offsets cover all block offsets), the
page lists the candidates as `?code=<n>` links to pick one by hand.

## 4. Tests

    PYTHONPATH=$PWD:path/to/pypy-cogen pypy2 -m pytest _jitviewer/test/test_jitcodeparser.py -q

`_jitviewer/test/jitcode-dump.log` is a fixture holding the `fib` dump
(22 blocks); `_jitviewer/test/jitcode-template.log` is a hand-written
template section for its `LOAD_FAST` and `LOAD_CONST` blocks.

## Known limits

- `RETURN_VALUE` shows "(no handler)" because it is inlined in
  `dispatch_bytecode` rather than defined as a method.
- Two tests in `_jitviewer/test/test_parser.py` predate this fork and fail
  against current rpython (`<Guard0x...>` descr format).
