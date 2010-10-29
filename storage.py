
""" This file represents a storage mechanism that let us invent unique names
for all loops and bridges, so http requests can refer to them by name
"""

from loops import Function, Bytecode

class LoopStorage(object):
    def __init__(self):
        self.loops = None
        self.functions = {}

    def reconnect_loops(self, loops):
        """ Re-connect loops in a way that entry bridges are filtered out
        and normal bridges are associated with guards. Returning list of
        normal loops.
        """
        res = []
        guard_dict = {}
        for loop_no, loop in enumerate(loops):
            for op in loop.operations:
                if op.name.startswith('guard_'):
                    guard_dict[int(op.descr[len('<Guard'):-1])] = op
        for loop in loops:
            if loop.comment:
                comment = loop.comment.strip()
                if 'entry bridge' in comment:
                    pass
                elif comment.startswith('# bridge out of'):
                    no = int(comment[len('# bridge out of Guard '):].split(' ', 1)[0])
                    guard_dict[no].bridge = loop
                    loop.no = no
                    continue
            res.append(loop)
        self.loops = res
        return res
