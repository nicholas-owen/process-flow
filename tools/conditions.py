"""Read when each process exists from a pipeline's source: the `if` blocks
around its call, and around every call above it, evaluated for each setting.

    python tools/conditions.py --source SRC --model ANALYSER_MODEL \\
        [--profile-config SRC/conf/test.config] [--report report.json]

A process exists in a run when the call path that names it is executed: its
call in the enclosing workflow, that workflow's call in its own, and so on to
the top. Each call sits inside zero or more `if`/`else` blocks. Rather than
turning the conditions into formulas, the code is interpreted for each
setting of the dimensions:

  - `params.x` is the setting when x is a dimension, else its baseline value
    (the schema default, then the profile's value, then any arg the
    Analyser fixed in every run, so the comparison is like for like);
  - a workflow input (`take:`) is the caller's argument at that position,
    evaluated where the call is (`params.skip_fastqc || params.skip_qc`);
  - a local variable replays its assignments and list appends before that
    point, each under its own `if` blocks (`prepare_tool_indices <<
    'sortmerna'`, then `'sortmerna' in prepare_tool_indices`);
  - Groovy's truth, `==`, `in`, `!`, `&&`, `||`, `?:`, and `contains`,
    `intersect`, `startsWith`, ... on strings and lists, and one-expression
    closures in `findAll`, `collect`, `any`, `every`;
  - a channel (a `ch_*` variable, or one made by `Channel.*` or `X.out`) is
    true, as any object is in Groovy, and otherwise unknown;
  - anything else (helper functions, statements that mutate, `${}` strings,
    `workflow.*`) is unknown, and unknown propagates three-valued, as in
    tools/predicates.py.

With --dims (a proposal.json) instead of --model, every proposed param is a
dimension and nothing is scored: the Explorer's case, for a pipeline with no
published model. --dag limits it to the processes a run's DAG has.

Each process is evaluated only over the dimensions its conditions read
(found by evaluating, adding any new dimension read, until none is). With
--model, every process is scored against the model's `when` over every
allowed setting: exact (agrees on all), unknown (agrees where it decides),
wrong (disagrees somewhere). The truth table also goes through
tools/infer.py to give a compact `when` in the model's form.
"""
import argparse, collections, itertools, json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from modules import Source, split_top, strip_comment, block
from predicates import holds, domain
from matrix import _allowed
from infer import infer


class _Unknown:
    def __repr__(self): return "UNKNOWN"
UNK = _Unknown()


class Chan:
    """A channel object: true in Groovy, and otherwise known only by where it
    was made: `origins` are the (workflow, position) of the assignments whose
    value it is, empty when that is not known."""
    def __init__(self, origins=frozenset()): self.origins = frozenset(origins)
    def __eq__(self, o): return isinstance(o, Chan) and o.origins == self.origins
    def __hash__(self): return hash(self.origins)
    def __repr__(self): return f"CHANNEL{sorted(self.origins) if self.origins else ''}"
CHAN = Chan()
SET = Chan()


class ListParam:
    """A comma-separated list param (sarek's --tools), read lazily: asking
    whether it contains a value reads that value's switch only; its truth
    reads the switches that are on (with none on, it is false); anything else
    reads them all and works on the joined string."""
    def __init__(self, interp, name, s):
        self.interp, self.name, self.s = interp, name, s
    def has(self, value):
        for k, v in self.interp.lists[self.name]:
            if v == value:
                self.interp.read.add(k)
                return bool(self.s.get(k))
        return False                                # a value the schema does not allow
    def truth(self):
        on = [k for k, _ in self.interp.lists[self.name] if self.s.get(k)]
        self.interp.read.update(on)
        return bool(on)
    def full(self):
        on = []
        for k, v in self.interp.lists[self.name]:
            self.interp.read.add(k)
            if self.s.get(k): on.append(v)
        return ",".join(on) if on else None        # a param that is set to a value not known: true, and nothing else


def subst(e, name, value):
    """A closure body with its parameter bound."""
    if not isinstance(e, tuple): return e
    if e == ("var", name): return ("lit", value)
    if e[0] == "closure" and e[1] == name: return e
    return tuple(subst(x, name, value) if isinstance(x, tuple) else
                 [subst(y, name, value) for y in x] if isinstance(x, list) else x for x in e)


# ---- text: blank comments and string contents, keeping positions ----------------------------
def clean(text):
    out, i, n, q = list(text), 0, len(text), None
    while i < n:
        ch = text[i]
        if q:
            if ch == "\\": out[i] = " "; i += 1; out[i] = " " if i < n else ""; i += 1; continue
            if text.startswith(q, i):
                i += len(q); q = None; continue
            if ch != "\n": out[i] = " "
            i += 1; continue
        if text.startswith("//", i):
            j = text.find("\n", i); j = n if j < 0 else j
            for k in range(i, j): out[k] = " "
            i = j; continue
        if text.startswith("/*", i):
            j = text.find("*/", i + 2); j = n if j < 0 else j + 2
            for k in range(i, j):
                if text[k] != "\n": out[k] = " "
            i = j; continue
        for qq in ('"""', "'''", '"', "'"):
            if text.startswith(qq, i):
                q = qq; i += len(qq); break
        else:
            i += 1
    return "".join(out)


def match_close(c, i):
    """Index of the bracket closing the one at c[i]."""
    pairs = {"(": ")", "[": "]", "{": "}"}
    depth = 0
    for j in range(i, len(c)):
        if c[j] in pairs: depth += 1
        elif c[j] in ")]}":
            depth -= 1
            if depth == 0: return j
    return len(c) - 1


IF = re.compile(r"(?<![\w.])if\s*\(")


def regions(text):
    """Every if/else branch of a body as (start, end, [(cond text, pos, negated)])."""
    c = clean(text)
    out, skip = [], set()
    for m in IF.finditer(c):
        if m.start() in skip:
            continue
        chain, pos = [], m.start()
        while True:
            op = c.index("(", pos)
            cl = match_close(c, op)
            cond = text[op + 1:cl]
            k = cl + 1
            while k < len(c) and c[k] in " \t\r\n": k += 1
            if k < len(c) and c[k] == "{":
                end = match_close(c, k); start = k
            else:
                start = k; end = c.find("\n", k); end = len(c) if end < 0 else end
            conds = [(t, p, True) for t, p in chain] + [(cond, op, False)]
            out.append((start, end, conds))
            chain.append((cond, op))
            k = end + 1
            while k < len(c) and c[k] in " \t\r\n": k += 1
            if not c.startswith("else", k):
                break
            k += 4
            while k < len(c) and c[k] in " \t\r\n": k += 1
            m2 = IF.match(c, k)
            if m2:
                skip.add(k); pos = k; continue
            if k < len(c) and c[k] == "{":
                end = match_close(c, k)
                out.append((k, end, [(t, p, True) for t, p in chain]))
            break
    return out


# ---- a small Groovy expression parser ---------------------------------------------------------
TOKEN = re.compile(r"""\s*(?:(?P<num>\d+(?:\.\d+)?)|(?P<str>'(?:[^'\\]|\\.)*'|"(?:[^"\\]|\\.)*")|"""
                   r"""(?P<op>->|\?:|\?\.|\|\||&&|==|!=|<=|>=|!in\b|\bin\b|\binstanceof\b|[!<>?:()\[\],.{}])|(?P<id>[A-Za-z_]\w*))""")


def tokenize(s):
    out, i = [], 0
    while i < len(s):
        if s[i:].strip() == "":
            break
        m = TOKEN.match(s, i)
        if not m or m.end() == i:
            raise SyntaxError(s[i:i + 20])
        kind = m.lastgroup
        out.append((kind, m.group(kind))); i = m.end()
    return out


class Parser:
    def __init__(self, s):
        self.t, self.i = tokenize(s), 0
    def peek(self, k=0):
        return self.t[self.i + k] if self.i + k < len(self.t) else (None, None)
    def take(self, v=None):
        tok = self.peek()
        if v is not None and tok[1] != v: raise SyntaxError(f"expected {v}, got {tok[1]}")
        self.i += 1; return tok
    def parse(self):
        e = self.ternary()
        if self.i != len(self.t): raise SyntaxError("trailing " + str(self.t[self.i:]))
        return e
    def ternary(self):
        e = self.or_()
        if self.peek()[1] == "?":
            self.take(); a = self.ternary(); self.take(":"); b = self.ternary()
            return ("if", e, a, b)
        if self.peek()[1] == "?:":
            self.take(); return ("elvis", e, self.ternary())
        return e
    def or_(self):
        e = self.and_()
        while self.peek()[1] == "||":
            self.take(); e = ("or", e, self.and_())
        return e
    def and_(self):
        e = self.unary()
        while self.peek()[1] == "&&":
            self.take(); e = ("and", e, self.unary())
        return e
    def unary(self):
        if self.peek()[1] == "!":
            self.take(); return ("not", self.unary())
        return self.cmp()
    def cmp(self):
        e = self.postfix()
        op = self.peek()[1]
        if op in ("==", "!=", "<", ">", "<=", ">=", "in", "!in", "instanceof"):
            self.take(); return ("cmp", op, e, self.postfix())
        return e
    def postfix(self):
        e = self.primary()
        while self.peek()[1] in (".", "?.", "["):
            if self.take()[1] == "[":
                idx = self.ternary(); self.take("]"); e = ("index", e, idx); continue
            name = self.take()[1]
            if self.peek()[1] == "(":
                self.take(); args = []
                while self.peek()[1] != ")":
                    args.append(self.ternary())
                    if self.peek()[1] == ",": self.take()
                self.take(")")
                if self.peek()[1] == "{": args.append(self.closure())
                e = ("call", e, name, args)
            elif self.peek()[1] == "{":
                e = ("call", e, name, [self.closure()])
            else:
                e = ("field", e, name)
        return e
    def closure(self):
        """{ x -> expr } or { expr with it }: one expression only."""
        self.take("{")
        param = "it"
        if self.peek()[0] == "id" and self.peek(1)[1] == "->":
            param = self.take()[1]; self.take("->")
        body = self.ternary(); self.take("}")
        return ("closure", param, body)

    def primary(self):
        kind, v = self.take()
        if kind == "num": return ("lit", float(v) if "." in v else int(v))
        if kind == "str":
            body = v[1:-1]
            return ("unk",) if "${" in body or (v[0] == '"' and "$" in body) else ("lit", body)
        if v == "(":
            e = self.ternary(); self.take(")"); return e
        if v == "[":
            items = []
            while self.peek()[1] != "]":
                if self.peek()[1] == ":" : raise SyntaxError("map literal")
                items.append(self.ternary())
                if self.peek()[1] == ",": self.take()
            self.take("]"); return ("list", items)
        if kind == "id":
            if v in ("true", "false"): return ("lit", v == "true")
            if v == "null": return ("lit", None)
            if self.peek()[1] == "(":            # a bare function call: unknown
                self.take(); depth = 1
                while depth and self.i < len(self.t):
                    t = self.take()[1]; depth += (t == "(") - (t == ")")
                return ("unk",)
            return ("var", v)
        raise SyntaxError(f"unexpected {v}")


def parse(s):
    try:
        return Parser(s.strip()).parse()
    except (SyntaxError, IndexError, ValueError):
        return ("unk",)


# ---- three-valued Groovy semantics --------------------------------------------------------------
def truth(v):
    if v is UNK: return None
    if isinstance(v, Chan): return True
    if isinstance(v, ListParam): return v.truth()
    if v is None or v is False or v == "" or v == [] or v == 0: return False
    return True


def _and(a, b):
    if a is False or b is False: return False
    return None if a is None or b is None else True


def _or(a, b):
    if a is True or b is True: return True
    return None if a is None or b is None else False


METHODS = {
    "contains": lambda o, a: a[0] in o, "startsWith": lambda o, a: o.startswith(a[0]),
    "endsWith": lambda o, a: o.endswith(a[0]), "size": lambda o, a: len(o), "isEmpty": lambda o, a: len(o) == 0,
    "intersect": lambda o, a: [x for x in o if x in a[0]], "toLowerCase": lambda o, a: o.lower(),
    "toUpperCase": lambda o, a: o.upper(), "toString": lambda o, a: str(o), "trim": lambda o, a: o.strip(),
    "split": lambda o, a: o.split(a[0]), "tokenize": lambda o, a: [x for x in re.split("[" + re.escape(a[0]) + "]", o) if x],
    "toBoolean": lambda o, a: str(o).lower() == "true", "toInteger": lambda o, a: int(o),
    "replace": lambda o, a: o.replace(a[0], a[1]),
}


# ---- scopes: a workflow body, entered through one call ----------------------------------------
ASSIGN = re.compile(r"(?:^|[{;])[ \t]*(?:def\s+(?:\w+\s+)?)?(\w+)\s*(=(?!=)|<<|\+=)\s*", re.M)
TAKE = re.compile(r"^\s*take\s*:\s*$(.*?)^\s*(?:main|emit)\s*:", re.M | re.S)
LINE_CONT = re.compile(r"(\|\||&&|[?:+,(\[{]|\bin)\s*$")


def statement_end(c, i):
    """End of the statement starting at i: the end of a line at bracket depth
    0 that does not end in an operator."""
    depth, j = 0, i
    while j < len(c):
        ch = c[j]
        if ch in "([{": depth += 1
        elif ch in ")]}":
            depth -= 1
            if depth < 0: return j
        elif ch == "\n" and depth == 0 and not LINE_CONT.search(c[i:j]):
            nxt = c[j + 1:].lstrip(" \t\r\n")
            if not nxt.startswith(".") or nxt.startswith(".."):   # a chain continues on a line starting with '.'
                return j
        j += 1
    return j


class Body:
    """A workflow (or the entry block) parsed once: regions, assignments, takes."""
    def __init__(self, name, file, text):
        self.name, self.file, self.text = name, file, text
        self.c = clean(text)
        self.regions = regions(text)
        t = TAKE.search(self.c)
        self.takes = []
        if t:
            for line in t.group(1).splitlines():
                m = re.match(r"\s*(\w+)", line)
                if m: self.takes.append(m.group(1))
        self.assigns = collections.defaultdict(list)    # var -> [(pos, op, expr text)]
        for m in ASSIGN.finditer(self.c):
            end = statement_end(self.c, m.end())
            expr = self.text[m.end():end].strip()
            self.assigns[m.group(1)].append((m.start(), m.group(2), expr))
        self.parsed = {}

    def ast(self, s):
        if s not in self.parsed: self.parsed[s] = parse(s)
        return self.parsed[s]

    def conds_at(self, pos):
        """[(cond text, cond pos, negated)] of every branch around pos."""
        out = []
        for s, e, conds in self.regions:
            if s <= pos <= e:
                out += conds
        return out

    def calls(self, alias):
        """Positions of `alias(` calls, with their argument texts."""
        out = []
        for m in re.finditer(rf"(?<![\w.]){re.escape(alias)}\s*\(", self.c):
            op = m.end() - 1
            cl = match_close(self.c, op)
            args = "\n".join(strip_comment(l) for l in self.text[op + 1:cl].splitlines())
            out.append((m.start(), [x.strip() for x in split_top(args)]))
        return out


class Interp:
    def __init__(self, bodies, dims, baseline, derived=()):
        self.bodies, self.dims, self.baseline = bodies, dims, baseline
        self.derived = dict(derived) if isinstance(derived, dict) else {k: None for k in derived}
        self.lists = collections.defaultdict(list)    # list param -> [(dimension id, value)]
        for k, d in dims.items():
            if d.get("list_value"):
                self.lists[d.get("param")].append((k, d["list_value"]))
        # (params main.nf assigns at script level, which Nextflow applies where unset)
        self.read = set()

    # a frame is (body, call args from the caller or None, caller frame or None, call pos in caller)
    def filled(self, name):
        """What main.nf fills an unset param with: a genome attribute is null
        with no --genome (nf-core's getGenomeAttribute), its value with a
        genome the config describes, else unknown."""
        attr = self.derived.get(name)
        if attr is None:
            return UNK
        genome, genomes = self.baseline.get("genome"), self.baseline.get("genomes")
        if genome is None or genome is False or genome == "":
            return None
        if isinstance(genomes, dict) and isinstance(genomes.get(genome), dict):
            return genomes[genome].get(attr)
        return UNK

    def param(self, name, s):
        if name in self.lists:
            return ListParam(self, name, s)
        if name in self.dims:
            self.read.add(name)
            v, d = s.get(name), self.dims[name]
            if d["kind"] == "presence":
                # set: its real value where the baseline has one (sarek's
                # `tools.split(',').contains('strelka')` reads the contents),
                # else a value that is true and nothing else known
                if v != "present":
                    if name not in self.derived: return None
                    f = self.filled(name)
                    return None if f is None else UNK     # unset, then filled: set, to a value not known here
                real = self.baseline.get(name)
                return real if real not in (None, "", False) and real is not UNK else SET
            if v == "unset": return self.filled(name) if name in self.derived else None
            return v
        v = self.baseline.get(name, UNK)
        return self.filled(name) if v is None and name in self.derived else v

    def var(self, name, pos, frame, s, depth):
        body, args, caller, cpos = frame
        if depth > 40: return UNK
        if name == "params": return ("params",)
        hist = [a for a in body.assigns.get(name, []) if a[0] < pos]
        val = UNK
        if name in body.takes:
            i = body.takes.index(name)
            val = self.eval(caller[0].ast(args[i]), cpos, caller, s, depth + 1) if args is not None and i < len(args) and caller else UNK
            if not hist: return chan(name, args[i] if args is not None and i < len(args) else "", val)
        for apos, op, expr in hist:
            c = self.region_truth(apos, frame, s, depth)
            if c is False: continue
            new = self.eval(body.ast(expr), apos, frame, s, depth + 1)
            if op == "=":
                # a channel made here is known by this assignment
                res = Chan({(body.name, apos)}) if (new is UNK or new == CHAN) and (
                    name.startswith("ch_") or CHANNEL_EXPR.match(expr)) else new
            elif op == "<<":
                res = (val + [new]) if isinstance(val, list) else UNK
            else:
                res = (val + new) if isinstance(val, list) and isinstance(new, list) else UNK
            if c is None:
                val = val if res == val else UNK
            else:
                val = res
        return chan(name, hist[-1][2] if hist else "", val)

    def region_truth(self, pos, frame, s, depth=0):
        body = frame[0]
        out = True
        for text, cpos, neg in body.conds_at(pos):
            t = truth(self.eval(body.ast(text), cpos, frame, s, depth + 1))
            if neg: t = None if t is None else not t
            out = _and(out, t)
            if out is False: return False
        return out

    def eval(self, e, pos, frame, s, depth=0):
        k = e[0]
        if k == "lit": return e[1]
        if k == "unk": return UNK
        if k == "list":
            vals = [self.eval(x, pos, frame, s, depth) for x in e[1]]
            return UNK if any(v is UNK for v in vals) else vals
        if k == "var": return self.var(e[1], pos, frame, s, depth)
        if k == "field":
            o = self.eval(e[1], pos, frame, s, depth)
            if o == ("params",): return self.param(e[2], s)
            return UNK
        if k == "index":
            o, i = self.eval(e[1], pos, frame, s, depth), self.eval(e[2], pos, frame, s, depth)
            try: return o[i] if o is not UNK and i is not UNK else UNK
            except Exception: return UNK
        if k == "call" and e[3] and e[3][-1][0] == "closure":
            o = self.eval(e[1], pos, frame, s, depth)
            _, param, body = e[3][-1]
            if not isinstance(o, list): return UNK
            vals = [self.eval(subst(body, param, x), pos, frame, s, depth) for x in o]
            if e[2] == "collect": return UNK if any(v is UNK for v in vals) else vals
            ts = [truth(v) for v in vals]
            if e[2] == "findAll": return UNK if None in ts else [x for x, t in zip(o, ts) if t]
            if e[2] == "any": return True if True in ts else (UNK if None in ts else False)
            if e[2] == "every": return False if False in ts else (UNK if None in ts else True)
            return UNK
        if k == "call":
            o = self.eval(e[1], pos, frame, s, depth)
            a = [self.eval(x, pos, frame, s, depth) for x in e[3]]
            if isinstance(o, ListParam):
                if e[2] in ("split", "tokenize", "toString", "trim"): return o
                if e[2] == "contains" and len(a) == 1 and isinstance(a[0], str): return o.has(a[0])
                o = o.full()
            a = [x.full() if isinstance(x, ListParam) else x for x in a]
            if o is UNK or o is None or any(x is UNK for x in a) or e[2] not in METHODS: return UNK
            try: return METHODS[e[2]](o, a)
            except Exception: return UNK
        if k == "not":
            t = truth(self.eval(e[1], pos, frame, s, depth)); return None_to_unk(None if t is None else not t)
        if k in ("and", "or"):
            # both sides always, so the reads of each are found (the value is
            # the same: three-valued && and || need no short cut)
            a = truth(self.eval(e[1], pos, frame, s, depth))
            b = truth(self.eval(e[2], pos, frame, s, depth))
            return None_to_unk(_and(a, b) if k == "and" else _or(a, b))
        if k == "if":
            t = truth(self.eval(e[1], pos, frame, s, depth))
            if t is None: return UNK
            return self.eval(e[2] if t else e[3], pos, frame, s, depth)
        if k == "elvis":
            a = self.eval(e[1], pos, frame, s, depth)
            t = truth(a)
            return UNK if t is None else (a if t else self.eval(e[2], pos, frame, s, depth))
        if k == "cmp":
            op, a, b = e[1], self.eval(e[2], pos, frame, s, depth), self.eval(e[3], pos, frame, s, depth)
            if op in ("in", "!in") and isinstance(b, ListParam) and isinstance(a, str):
                return b.has(a) if op == "in" else not b.has(a)
            a, b = (x.full() if isinstance(x, ListParam) else x for x in (a, b))
            if op == "instanceof" or a is UNK or b is UNK or isinstance(a, Chan) or isinstance(b, Chan): return UNK
            try:
                if op == "==": return a == b
                if op == "!=": return a != b
                if op == "in": return a in b
                if op == "!in": return a not in b
                return {"<": a < b, ">": a > b, "<=": a <= b, ">=": a >= b}[op]
            except Exception:
                return UNK
        return UNK


CHANNEL_EXPR = re.compile(r"^(ch_\w+|[Cc]hannel\.\w+|\w+\.out\b)")


def chan(name, expr, val):
    """An unknown value that is a channel (by its name or what made it) is a
    channel: true, and nothing else."""
    if val is UNK and (name.startswith("ch_") or CHANNEL_EXPR.match(expr or "")):
        return CHAN
    return val


def None_to_unk(t):
    return UNK if t is None else t


# ---- call paths ------------------------------------------------------------------------------------
class Pipeline:
    def __init__(self, root):
        self.src = Source(root)
        self.bodies = {n: Body(n, f, b) for n, (f, b) in self.src.workflows.items()}
        # the unnamed entry workflow of main.nf, and the params it assigns at
        # script level (`params.fasta = getGenomeAttribute('fasta')`), which
        # Nextflow applies only where the config left them unset
        self.derived = {}
        main = os.path.join(self.src.root, "main.nf")
        if os.path.exists(main):
            text = open(main, encoding="utf-8", errors="replace").read()
            # name -> the genome attribute it reads (nf-core's getGenomeAttribute), or None
            c = clean(text)
            for m in re.finditer(r"^params\.(\w+)\s*=(?!=)\s*(.*)$", c, re.M):
                g = re.match(r"getGenomeAttribute\(\s*['\"](\w+)['\"]\s*\)", text[m.start(2):m.end(2)].strip())
                self.derived[m.group(1)] = g.group(1) if g else None
            m = re.search(r"^\s*workflow\s*\{", text, re.M)
            if m:
                self.bodies["<entry>"] = Body("<entry>", "main.nf", block(text, m.end() - 1))

    def definition(self, alias, caller_file):
        """A workflow alias -> its body, through the caller's includes."""
        inc = self.src.includes.get(caller_file, {})
        if alias in inc and inc[alias][0] in self.bodies:
            return self.bodies[inc[alias][0]]
        return self.bodies.get(alias)

    def frames(self, path):
        """Every way of entering the call path: a list of (frame, call pos of the
        last element) chains, one per combination of call sites."""
        top = self.bodies.get(path[0])
        entry = self.bodies.get("<entry>")
        starts = []
        if top and entry:
            for pos, args in entry.calls(path[0]):
                starts.append(((top, args, (entry, None, None, None), pos),))
        if not starts and top:
            starts = [((top, None, None, None),)]
        chains = [list(s) for s in starts]
        for name in path[1:]:
            new = []
            for chain in chains:
                frame = chain[-1]
                body = frame[0]
                for pos, args in body.calls(name):
                    if name == path[-1]:
                        new.append(chain + [("call", pos)])
                    else:
                        sub = self.definition(name, body.file)
                        if sub:
                            new.append(chain + [(sub, args, frame, pos)])
            chains = new
        return chains


def exists(interp, chains, s):
    """Three-valued: is the process called under settings s?"""
    out = False
    for chain in chains:
        t = True
        frames = [f for f in chain if len(f) == 4]
        call_pos = chain[-1][1]
        for i, f in enumerate(frames):
            pos = frames[i + 1][3] if i + 1 < len(frames) else call_pos
            t = _and(t, interp.region_truth(pos, f, s))
            if t is False: break
        out = _or(out, t)
        if out is True: return True
    return out


def table(interp, chains, dims, base):
    """Truth table over the dimensions the conditions read."""
    read = set()
    while True:
        interp.read = set()
        rows = {}
        names = sorted(read)
        for combo in itertools.product(*[domain(dims[k]) for k in names]):
            s = dict(base); s.update(zip(names, combo))
            rows[combo] = exists(interp, chains, s)
        if interp.read <= read:
            return names, rows
        read |= interp.read


def config_params(path):
    """`key = value` lines of a config's params { } blocks and `params.key =
    value` lines: literals as values, anything else unknown."""
    out = {}
    if not path or not os.path.exists(path):
        return out
    raw = open(path, encoding="utf-8", errors="replace").read()
    c = clean(raw)
    for m in re.finditer(r"(?<![\w.])params\s*\{", c):
        op = m.end() - 1
        cl = match_close(c, op)
        for a in re.finditer(r"^\s*(\w+)\s*=\s*(.+)$", c[op + 1:cl], re.M):
            v = raw[op + 1 + a.start(2):op + 1 + a.end(2)].strip()
            e = parse(v)
            out[a.group(1)] = e[1] if e[0] == "lit" else UNK
    for a in re.finditer(r"^\s*params\.(\w+)\s*=\s*(.+)$", c, re.M):
        e = parse(raw[a.start(2):a.end(2)].strip())
        out[a.group(1)] = e[1] if e[0] == "lit" else UNK
    return out


def baseline_params(src_root, profile=None, fixed=None):
    """Every param's value in the baseline run: the schema (its default, else
    null), the pipeline's nextflow.config, the profile, then the args the
    Analyser fixed in every run."""
    base = {}
    schema = os.path.join(src_root, "nextflow_schema.json")
    if os.path.exists(schema):
        sj = json.load(open(schema, encoding="utf-8"))
        for grp in list((sj.get("$defs") or sj.get("definitions") or {}).values()) + [sj]:
            for k, p in (grp.get("properties") or {}).items():
                base[k] = p.get("default")
    base.update(config_params(os.path.join(src_root, "nextflow.config")))
    base.update(config_params(profile))
    for f in fixed or []:
        base[f["param"]] = None if f["value"] == "null" else f["value"]
    return base


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--source", required=True)
    ap.add_argument("--model", help="a model whose dimensions to use, and whose `when`s to score against")
    ap.add_argument("--dims", help="instead of --model: a proposal.json (tools/propose.py), every proposed param a dimension")
    ap.add_argument("--dag", help="with --dims: the processes to read, from a DAG (default: every process called)")
    ap.add_argument("--profile-config", help="e.g. SRC/conf/test.config: its params are the baseline")
    ap.add_argument("--report", help="write every process's result as JSON")
    a = ap.parse_args()
    if not (a.model or a.dims):
        ap.error("give --model or --dims")
    if a.model:
        model = json.load(open(a.model, encoding="utf-8"))
    else:
        from generate import dims_from_proposal
        from dot import parse as parse_dot
        prop = json.load(open(a.dims, encoding="utf-8"))
        for p in prop["params"]:
            p["include"] = bool(p.get("dimension"))         # every proposed param, not only those kept
        tmp = os.path.join(os.path.dirname(os.path.abspath(a.report or a.dims)), ".conditions-dims.json")
        json.dump(prop, open(tmp, "w", encoding="utf-8"))
        dl = dims_from_proposal(tmp); os.remove(tmp)
        procs = sorted({n["label"] for n in parse_dot(a.dag)[0].values() if n["kind"] == "process"}) if a.dag else []
        model = {"pipeline": {}, "dimensions": dl, "nodes": [{"id": p, "kind": "process"} for p in procs]}
    dims = {d["id"]: d for d in model["dimensions"]}
    scoring = bool(a.model)
    fixed = ((model.get("generated") or {}).get("evidence") or {}).get("fixed_args")
    base = baseline_params(a.source, a.profile_config, fixed)
    pipe = Pipeline(a.source)
    interp = Interp(pipe.bodies, dims, base, pipe.derived)
    prefix = model["pipeline"].get("prefix") or []
    if scoring:
        allowed = [dict(zip(dims, c)) for c in itertools.product(*[domain(d) for d in dims.values()])]
        allowed = [s for s in allowed if _allowed(s, dims)]
    else:
        allowed = []
    default = {k: d.get("default", domain(d)[0]) for k, d in dims.items()}
    results, tally = {}, collections.Counter()
    for n in model["nodes"]:
        if n["kind"] != "process":
            continue
        path = n["id"].split(":")
        chains = pipe.frames(path)
        if not chains:
            results[n["id"]] = {"status": "no call found"}; tally["no call found"] += 1; continue
        names, rows = table(interp, chains, dims, default)
        if not scoring:
            unknown = sum(1 for v in rows.values() if v is None)
            status = "unknown" if unknown else "decided"
            tally[status] += 1
            r = {"status": status, "reads": names, "rows": len(rows), "unknown": unknown}
            if not unknown and names:
                runs = {i: dict(zip(names, k)) for i, k in enumerate(rows)}
                r["source_when"] = infer({i for i, k in enumerate(rows) if rows[k]}, runs, {k: dims[k] for k in names})[0]
            elif not unknown:
                r["source_when"] = None if rows[()] else {"params": {}}
            results[n["id"]] = r
            continue
        agree = wrong = unknown = 0
        for s in allowed:
            got = rows[tuple(s[k] for k in names)]
            want = holds(n.get("when"), s, dims)
            if got is None: unknown += 1
            elif got == want: agree += 1
            else: wrong += 1
        status = "wrong" if wrong else "unknown" if unknown else "exact"
        tally[status] += 1
        r = {"status": status, "reads": names, "agree": agree, "wrong": wrong, "unknown": unknown,
             "model_when": n.get("when"), "call_paths": len(chains)}
        if not unknown and names:
            runs = {i: dict(zip(names, k)) for i, k in enumerate(rows)}
            pred, ok = infer({i for i, k in enumerate(rows) if rows[k]}, runs, {k: dims[k] for k in names})
            r["source_when"] = pred
        results[n["id"]] = r
    total = sum(tally.values())
    print(f"{total} processes: " + ", ".join(f"{v} {k}" for k, v in tally.most_common()))
    for pid, r in results.items():
        if r["status"] in ("wrong", "no call found"):
            print(f"  {r['status']}: {pid.split(':')[-1]}  reads {r.get('reads')}  wrong on {r.get('wrong')} of {len(allowed)}; model: {json.dumps(r.get('model_when'))}")
    unk = [p.split(":")[-1] for p, r in results.items() if r["status"] == "unknown"]
    if unk:
        print(f"  unknown ({len(unk)}): {', '.join(unk)}")
    if a.report:
        with open(a.report, "w", encoding="utf-8", newline="\n") as f:
            json.dump({"tally": tally, "settings": len(allowed), "baseline": {k: (None if v is UNK else v) for k, v in base.items()},
                       "processes": results}, f, indent=1, ensure_ascii=False, default=str)


if __name__ == "__main__":
    main()
