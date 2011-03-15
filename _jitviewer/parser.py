import re, sys
from lib_pypy.disassembler import dis # imported from the pypy source tree
from pypy.jit.metainterp.resoperation import rop, opname
from pypy.jit.tool.oparser import OpParser
from pypy.tool.jitlogparser import parser

class Html(str):
    def __html__(self):
        return self

    def plaintext(self):
        # This is not a general way to strip tags, but it's good enough to use
        # in tests
        import re
        s = re.sub('<.*?>', '', self)
        s = s.replace("&lt;", "<")
        s = s.replace("&gt;", ">")
        s = s.replace("&amp;", "&")
        return s


def cssclass(cls, s, **kwds):
    attrs = ['%s="%s"' % (name, value) for name, value in kwds.iteritems()]
    return '<span class="%s" %s>%s</span>' % (cls, ' '.join(attrs), s)


def _new_binop(name):
    import cgi
    name = cgi.escape(name)
    def f(self):
        return '%s = %s %s %s' % (self.getres(), self.getarg(0), name, self.getarg(1))
    return f

class OpHtml(parser.Op):
    """
    Subclass of Op with human-friendly html representation
    """

    def html_repr(self):
        s = getattr(self, 'repr_' + self.name, self.repr)()
        if self.is_guard():
            s = '<span class="guard">guard</span>(' + s + ')'
        return Html(s)

    def _getvar(self, v):
        return cssclass(v, v, onmouseover='highlight_var(this)', onmouseout='disable_var(this)')

    for bin_op, name in [('==', 'int_eq'),
                         ('!=', 'int_ne'),
                         ('==', 'float_eq'),
                         ('!=', 'float_ne'),
                         ('>', 'int_gt'),
                         ('<', 'int_lt'),
                         ('<=', 'int_le'),
                         ('>=', 'int_ge'),
                         ('+', 'int_add'),
                         ('+', 'float_add'),
                         ('-', 'int_sub'),
                         ('-', 'float_sub'),
                         ('*', 'int_mul'),
                         ('*', 'float_mul'),
                         ('&', 'int_and')]:
        locals()['repr_' + name] = _new_binop(bin_op)

    def repr_guard_true(self):
        return '%s is true' % self.getarg(0)

    def repr_guard_false(self):
        return '%s is false' % self.getarg(0)

    def repr_guard_value(self):
        return '%s is %s' % (self.getarg(0), self.getarg(1))

    def repr_guard_isnull(self):
        return '%s is null' % self.getarg(0)

    def repr_getfield_raw(self):
        name, field = self.descr.split(' ')[1].rsplit('.', 1)
        return '%s = ((%s)%s).%s' % (self.getres(), name, self.getarg(0), field[2:])

    def repr_getfield_gc(self):
        fullname, field = self.descr.split(' ')[1].rsplit('.', 1)
        names = fullname.rsplit('.', 1)
        if len(names) == 2:
            namespace, classname = names
        else:
            namespace = ''
            classname = names[0]
        namespace = cssclass('namespace', namespace)
        classname = cssclass('classname', classname)
        field = cssclass('fieldname', field)
            
        obj = self.getarg(0)
        return '%s = ((%s.%s)%s).%s' % (self.getres(), namespace, classname, obj, field)

    def repr_getfield_gc_pure(self):
        return self.repr_getfield_gc() + " [pure]"

    def repr_setfield_raw(self):
        name, field = self.descr.split(' ')[1].rsplit('.', 1)
        return '((%s)%s).%s = %s' % (name, self.getarg(0), field[2:], self.getarg(1))

    def repr_setfield_gc(self):
        name, field = self.descr.split(' ')[1].rsplit('.', 1)
        return '((%s)%s).%s = %s' % (name, self.getarg(0), field, self.getarg(1))

    def repr_jump(self):
        no = int(re.search("\d+", self.descr).group(0))
        return ("<a href='' onclick='show_loop(%d);return false'>" % no +
                self.repr() + "</a>")

class ParserWithHtmlRepr(parser.SimpleParser):
    Op = OpHtml


class TraceForOpcodeHtml(parser.TraceForOpcode):

    def html_repr(self):
        if self.filename is not None:
            code = self.getcode()
            opcode = self.code.map[self.bytecode_no]
            return '%s %s' % (self.bytecode_name, opcode.argstr)
        else:
            return self.bytecode_name

class FunctionHtml(parser.Function):
    TraceForOpcode = TraceForOpcodeHtml
    
    def html_repr(self):
        return "inlined call to %s in %s" % (self.name, self.filename)


def parse_log_counts(input, loops):
    if not input:
        return
    lines = input[-1].splitlines()
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
