"""Conditions for every node and edge, read from source, scored against a model.

    python tools/graph_conditions.py --source SRC --model ANALYSER_MODEL \\
        [--profile-config SRC/conf/test.config] [--report report.json]

tools/conditions.py gives each process the conditions around its call path.
This extends them to the rest of the graph:

  - an operator, or a channel source (`channel.empty`, `channel.of`, ...),
    is made by a statement. The DAG does not say which, but its readable id
    names its anchors (`map@UNTAR_HISAT2_INDEX>ch_hisat2_index`): the
    statements with that operator (`.map`) naming the most anchors (as
    written or with nf-core's `ch_` prefix, and counting the process whose
    argument list a statement sits in), then nearest the node's processes,
    are its candidates. A weak match far from them is dropped. The statement
    runs when its `if` blocks hold, through the call paths into its workflow
    that lead to the node's processes (a subworkflow called from three places
    is three operators);
  - the union graph splits one statement into a node per producer, so an
    operator exists when its statement runs and one of its producers exists;
    a source, when its statement runs and one of its consumers exists (an
    unused `channel.empty()` is not drawn);
  - an input or output point (a value fed to a process, an emit nothing
    reads) exists with the node it hangs off;
  - an edge exists when both its ends do; and where the channel is a
    variable assigned more than once (not an accumulator, `ch_x =
    ch_x.mix(...)`), only when its producer made the value that reaches the
    consumer: channel values carry the assignment that made them
    (tools/conditions.py `Chan`), so this is evaluated like any condition
    (fetchngs' `ch_sra_metadata`, replaced when downloads run);
  - a node with no candidate takes its producers, or, with none known
    either, its consumers (a channel made in one workflow and named only
    where it is used, through emit: and a call).

Every element gets a truth value per allowed setting, three-valued, and is
scored against the model's `when` as tools/conditions.py scores processes:
exact, unknown (agrees where it decides) or wrong.

Scores (tools/test_conditions.py): nf-core/fetchngs 1.13.0 117 of 117
exact; nf-core/rnaseq 3.27.0 1,902 of 2,289 exact, 281 wrong, 106 unknown
(main lane 84% exact, MultiQC plumbing 74%). What is left wrong is mostly
where the union graph merges structurally alike operators that the code
makes in different places (chains of `mix` into ch_multiqc_files, the
per-sample MultiQC `join`s, `channel.empty()` placeholders in the parallel
trimgalore and fastp subworkflows), so a node does not map to one statement.
"""
import argparse, collections, itertools, json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from conditions import (Pipeline, Interp, baseline_params, exists, _and, _or, LINE_CONT, match_close, Chan, statement_end)
from predicates import holds, domain, variables
from infer import infer
from matrix import _allowed


# ---- where each workflow body is entered ----------------------------------------------------
def body_chains(pipe, process_ids):
    """Body name -> chains of frames ending in that body, from the call paths
    of the model's processes (every workflow on a process's path)."""
    out = collections.defaultdict(list)
    seen = set()
    for pid in process_ids:
        path = pid.split(":")
        for chain in pipe.frames(path):
            frames = [f for f in chain if len(f) == 4]
            for i in range(len(frames)):
                key = tuple(id(f[0]) for f in frames[:i + 1]) + tuple(f[3] or 0 for f in frames[:i + 1])
                if key in seen: continue
                seen.add(key)
                out[frames[i][0].name].append((tuple(path[:i + 1]), frames[:i + 1]))
    # workflows with no process of their own (fetchngs' CHANNEL_SRA_CREATE_CSV):
    # follow every workflow call from the bodies reached so far
    todo = [(ap, ch) for chs in list(out.values()) for ap, ch in chs]
    entry = pipe.bodies.get("<entry>")
    if entry:                                         # and from the entry block itself
        root = [(entry, None, None, None)]
        out["<entry>"].append(((), root))
        todo.append(((), root))
    while todo:
        ap, chain = todo.pop()
        body = chain[-1][0]
        for alias in set(pipe.src.includes.get(body.file, {})) | set(pipe.bodies):
            sub = pipe.definition(alias, body.file)
            if not sub or sub is body: continue
            for pos, args in body.calls(alias):
                new = chain + [(sub, args, chain[-1], pos)]
                key = tuple(id(f[0]) for f in new) + tuple(f[3] or 0 for f in new)
                if key in seen: continue
                seen.add(key)
                out[sub.name].append((ap + (alias,), new)); todo.append((ap + (alias,), new))
    return out


def truth_at(interp, chain, pos, s):
    t = True
    for i, f in enumerate(chain):
        p = chain[i + 1][3] if i + 1 < len(chain) else pos
        t = _and(t, interp.region_truth(p, f, s))
        if t is False: return False
    return t


# ---- locating an operator's statement ---------------------------------------------------------------
ID = re.compile(r"^([^@]+)@(.*?)(?:#\d+)?$")


def anchors(node_id):
    m = ID.match(node_id)
    if not m: return None, []
    typ, rest = m.group(1), m.group(2)
    ups, _, downs = rest.partition(">")
    names = [a for a in (ups.split("+") + downs.split("+")) if a and a not in ("start", "end")]
    return typ, names


def statement_span(c, pos):
    """The statement around pos: back to a line that starts it, forward over
    lines that continue it (a line ending in an operator, the next starting
    with '.')."""
    # back: a newline at bracket depth 0, after which the line does not start with '.'
    depth, i = 0, pos
    while i > 0:
        ch = c[i - 1]
        if ch in ")]}": depth += 1
        elif ch in "([{":
            if depth == 0: break                        # inside an argument list or a block: its start
            depth -= 1
        elif ch == "\n" and depth == 0:
            line = c[i:c.find("\n", i) if c.find("\n", i) >= 0 else len(c)].strip()
            prev = c[c.rfind("\n", 0, i - 1) + 1:i - 1]
            if not line.startswith(".") and not LINE_CONT.search(prev):
                break
        i -= 1
    start = i
    depth, j = 0, pos
    while j < len(c):
        ch = c[j]
        if ch in "([{": depth += 1
        elif ch in ")]}":
            depth -= 1
            if depth < 0: break
        elif ch == "\n" and depth == 0:
            nxt = c[j + 1:c.find("\n", j + 1) if c.find("\n", j + 1) >= 0 else len(c)].strip()
            if not nxt.startswith(".") and not LINE_CONT.search(c[start:j]):
                break
        j += 1
    return start, j


def spellings(name):
    """A channel name as code may spell it: nf-core names its channels ch_x,
    and a DAG labels them by the last name given (an emit, a take)."""
    return [name] + ([name[3:]] if name.startswith("ch_") else ["ch_" + name])


def callee(c, start):
    """The process or workflow whose argument list a statement starts in."""
    if start > 0 and c[start - 1] == "(":
        m = re.search(r"(\w+)\s*$", c[:start - 1])
        return m.group(1) if m else ""
    return ""


def candidates(pipe, chains_of, typ, names, near=()):
    """[(body, pos, score)] of the best-matching statements: most anchors
    named, then in the workflow nearest the neighbouring processes (the one
    that calls them, or its caller)."""
    if "." in typ:                                      # channel.empty, channel.of, ...
        pat = re.compile(rf"(?<![\w.])[Cc]hannel\.{re.escape(typ.split('.', 1)[1])}\b")
    else:
        pat = re.compile(rf"\.{re.escape(typ)}\b")
    best, out = (0, 0), []
    for name, body in pipe.bodies.items():
        if name not in chains_of: continue
        loc = max([len(ap) for ap, _ in chains_of[name] for p in near if p[:len(ap)] == list(ap)] or [0])
        for m in pat.finditer(body.c):
            s, e = statement_span(body.c, m.start())
            text = body.c[s:e] + " " + body.text[s:e] + " " + callee(body.c, s)
            hits = sum(1 for n in names if any(re.search(rf"(?<!\w){re.escape(v)}(?!\w)", text) for v in spellings(n)))
            if names and hits == 0: continue
            score = (hits, loc)
            if score > best: best, out = score, []
            if score == best: out.append((body, m.start(), score))
    # a weak match, far from the node's processes, misleads more than it helps
    if out and best[1] == 0 and best[0] < len(names):
        return []
    return out


def near_processes(nid, succ, pred, nodes, limit=4):
    """Paths of the processes nearest to a node, both ways, through other nodes."""
    out = []
    for adj in (succ, pred):
        seen, frontier = {nid}, [nid]
        for _ in range(limit):
            nxt = []
            for x in frontier:
                for y in adj[x]:
                    if y in seen: continue
                    seen.add(y)
                    if nodes.get(y, {}).get("kind") == "process": out.append(y.split(":"))
                    else: nxt.append(y)
            frontier = nxt
            if out: break
    return out


# ---- truth vectors over the allowed settings ------------------------------------------------------
def vector_of(fn, interp, dims, base, allowed):
    """fn(settings) evaluated over the dims it reads, spread over `allowed`."""
    read = set()
    while True:
        interp.read = set()
        names = sorted(read)
        rows = {}
        for combo in itertools.product(*[domain(dims[k]) for k in names]):
            s = dict(base); s.update(zip(names, combo))
            rows[combo] = fn(s)
        if interp.read <= read: break
        read |= interp.read
    return [rows[tuple(s[k] for k in names)] for s in allowed]


def v_and(a, b): return [_and(x, y) for x, y in zip(a, b)]
def v_or(a, b): return [_or(x, y) for x, y in zip(a, b)]


class VectorAlgebra:
    """Truth values over every allowed setting: for scoring against a model."""
    def __init__(self, interp, dims, default, allowed):
        self.interp, self.dims, self.default, self.allowed = interp, dims, default, allowed
        self.unknown = [None] * len(allowed)
    def lift(self, fn): return vector_of(fn, self.interp, self.dims, self.default, self.allowed)
    def AND(self, a, b): return v_and(a, b)
    def OR(self, a, b): return v_or(a, b)
    def restricts(self, r): return False in r


NEVER = {"not": {"params": {}}}


class P:
    """A predicate in the model's form (None: always), and whether any
    setting was left undecided (counted as present)."""
    __slots__ = ("pred", "unk")
    def __init__(self, pred, unk=False): self.pred, self.unk = pred, unk


class PredicateAlgebra:
    """Predicates: for writing `when`s into a model when there are too many
    dimensions to enumerate. Each truth table covers only the dimensions an
    expression reads; tools/infer.py reduces it to a compact predicate."""
    LIMIT = 20000
    def __init__(self, interp, dims, default):
        self.interp, self.dims, self.default = interp, dims, default
        self.unknown = P(None, True)
        self.cache = {}
    def _reduce(self, names, rows):
        unk = any(v is None for v in rows.values())
        on = {k for k, v in rows.items() if v is not False}
        if len(on) == len(rows): return P(None, unk)
        if not on: return P(NEVER, unk)
        # drop dimensions that never change the answer (read is not the same
        # as relevant): inference is costly in the size of the table
        for i in reversed(range(len(names))):
            groups = collections.defaultdict(set)
            for k in rows:
                groups[k[:i] + k[i + 1:]].add(k in on)
            if all(len(g) == 1 for g in groups.values()):
                names = names[:i] + names[i + 1:]
                rows = {k[:i] + k[i + 1:]: v for k, v in rows.items()}
                on = {k[:i] + k[i + 1:] for k in on}
        runs = {i: dict(zip(names, k)) for i, k in enumerate(rows)}
        key = (tuple(names), frozenset(on))
        if key not in self.cache:
            self.cache[key] = infer({i for i, k in enumerate(rows) if k in on}, runs, {k: self.dims[k] for k in names})[0]
        return P(self.cache[key], unk)
    def lift(self, fn):
        read = set()
        while True:
            self.interp.read = set()
            names = sorted(read)
            rows = {}
            for combo in itertools.product(*[domain(self.dims[k]) for k in names]):
                st = dict(self.default); st.update(zip(names, combo))
                rows[combo] = fn(st)
            if self.interp.read <= read: break
            read |= self.interp.read
        return self._reduce(names, rows)
    def _combine(self, a, b, op):
        names = sorted(variables(a.pred) | variables(b.pred)) if a.pred and b.pred else None
        size = 1
        for k in names or []: size *= len(domain(self.dims[k]))
        if names is not None and size <= self.LIMIT:
            rows = {}
            for combo in itertools.product(*[domain(self.dims[k]) for k in names]):
                st = dict(zip(names, combo))
                rows[combo] = op(holds(a.pred, st, self.dims), holds(b.pred, st, self.dims))
            r = self._reduce(names, rows)
            return P(r.pred, a.unk or b.unk or r.unk)
        return None
    def AND(self, a, b):
        if a.pred is None: return P(b.pred, a.unk or b.unk)
        if b.pred is None: return P(a.pred, a.unk or b.unk)
        return self._combine(a, b, _and) or P({"params": {}, "not": {"any": [{"not": a.pred}, {"not": b.pred}]}}, a.unk or b.unk)
    def OR(self, a, b):
        if a.pred is None or b.pred is None: return P(None, a.unk or b.unk)
        return self._combine(a, b, _or) or P({"any": [a.pred, b.pred]}, a.unk or b.unk)
    def restricts(self, r): return r.pred is not None


def score(vec, want):
    wrong = sum(1 for g, w in zip(vec, want) if g is not None and g != w)
    unknown = sum(1 for g in vec if g is None)
    return "wrong" if wrong else "unknown" if unknown else "exact", wrong, unknown


def compute(model, pipe, interp, default, A):
    """Every node's and edge's condition, in algebra A (VectorAlgebra to
    score, PredicateAlgebra to write a model). Returns (values, how)."""
    nodes = {n["id"]: n for n in model["nodes"]}
    procs = [i for i, n in nodes.items() if n["kind"] == "process"]
    chains_of = body_chains(pipe, procs)
    succ, pred = collections.defaultdict(list), collections.defaultdict(list)
    for e in model["edges"]:
        succ[e["from"]].append(e["to"]); pred[e["to"]].append(e["from"])

    vec, how = {}, {}
    for pid in procs:
        chains = pipe.frames(pid.split(":"))
        vec[pid] = A.lift(lambda s: exists(interp, chains, s)) if chains else A.unknown
        how[pid] = "call path"
    stmt, cands_of, near_of = {}, {}, {}
    for nid, n in nodes.items():
        if n["kind"] in ("operator", "source"):
            typ, names = anchors(nid)
            near = near_processes(nid, succ, pred, nodes)
            cands = candidates(pipe, chains_of, typ, names, near) if typ else []
            if cands:
                cands_of[nid], near_of[nid] = cands, near
                def f(s, cands=cands, near=near):
                    t = False
                    for body, pos, _ in cands:
                        chains = [ch for ap, ch in chains_of[body.name] if any(p[:len(ap)] == list(ap) for p in near)]                                  or [ch for _, ch in chains_of[body.name]]
                        for chain in chains:
                            t = _or(t, truth_at(interp, chain, pos, s))
                            if t is True: return True
                    return t
                stmt[nid] = A.lift(f)
                how[nid] = f"statement ({len(cands)} candidate{'s' if len(cands) > 1 else ''})"

    def any_of(vs):
        vs = [v for v in vs if v is not None]
        if not vs: return None
        out = vs[0]
        for x in vs[1:]: out = A.OR(out, x)
        return out
    known = lambda q: vec[q] if q in vec else stmt.get(q)
    # inputs feed processes; sources are drawn only when something consumes them
    for nid, n in nodes.items():
        if n["kind"] == "input":
            d = any_of([known(q) for q in succ[nid]])
            if d is not None: vec[nid], how[nid] = d, "its consumer"
        elif n["kind"] == "source" and nid in stmt:
            d = any_of([known(q) for q in succ[nid]])
            vec[nid] = A.AND(stmt[nid], d) if d is not None else stmt[nid]
            how[nid] += ", and a consumer"
    # operators and outputs in graph order: an operator exists when its
    # statement runs and one of its producers exists (the union graph splits
    # one statement into a node per producer)
    indeg = {i: sum(1 for p in pred[i] if p in nodes) for i in nodes}
    order, ready = [], [i for i, d in indeg.items() if d == 0]
    while ready:
        x = ready.pop(); order.append(x)
        for q in succ[x]:
            indeg[q] -= 1
            if indeg[q] == 0: ready.append(q)
    order += [i for i in nodes if i not in set(order)]
    for nid in order:
        n = nodes[nid]
        if nid in vec or n["kind"] not in ("operator", "output", "source"):
            continue
        ups = any_of([vec[p] if p in vec else None for p in pred[nid]])
        if n["kind"] == "output":
            if ups is not None: vec[nid], how[nid] = ups, "its producer"
        elif nid in stmt:
            vec[nid] = A.AND(stmt[nid], ups) if ups is not None else stmt[nid]
            if ups is not None: how[nid] += ", and a producer"
        elif ups is not None:
            vec[nid], how[nid] = ups, "fallback: its producers"
    # nodes reached neither way (a channel made in one workflow and named only
    # where it is used, through emit: and a call): from their consumers, then
    # whatever hangs off them again from their producers
    for nid in reversed(order):
        if nid not in vec and nodes[nid]["kind"] in ("operator", "source", "input"):
            d = any_of([vec[q] if q in vec else None for q in succ[nid]])
            if d is not None: vec[nid], how[nid] = d, "fallback: its consumers"
    for nid in order:
        if nid not in vec and nodes[nid]["kind"] in ("operator", "output"):
            ups = any_of([vec[p] if p in vec else None for p in pred[nid]])
            if ups is not None: vec[nid], how[nid] = ups, "fallback: its producers"
    # where each node's statement runs: (frame, position)
    def places(nid):
        if nodes[nid]["kind"] == "process":
            for chain in pipe.frames(nid.split(":")):
                frames = [f for f in chain if len(f) == 4]
                yield frames[-1], chain[-1][1]
        for body, pos, _ in cands_of.get(nid, []):
            chains = [ch for ap, ch in chains_of[body.name] if any(p[:len(ap)] == list(ap) for p in near_of[nid])]                      or [ch for _, ch in chains_of[body.name]]
            # what the statement reads is the value before it: in `ch_x =
            # ch_x.mix(...)`, the ch_x of the statements above
            start = statement_span(body.c, pos)[0]
            for ch in chains:
                yield ch[-1], start

    def made_by(origin, uid):
        """Is the assignment at origin the statement that makes node uid?"""
        body = pipe.bodies[origin[0]]
        start = origin[1]
        end = statement_end(body.c, body.c.index("=", start) + 1)
        if nodes[uid]["kind"] == "process":
            return re.search(rf"(?<!\w){re.escape(uid.split(':')[-1])}(?!\w)", body.text[start:end]) is not None
        return any(b is body and start <= p <= end for b, p, _ in cands_of.get(uid, []))

    # assignments to variables assigned more than once: where a channel can
    # come from more than one place
    # (not accumulators, `ch_x = ch_x.mix(...)`: the union graph merges the
    # links of such a chain by position, so its edges do not map to statements)
    reassigned = {(b.name, a[0]) for b in pipe.bodies.values() for v, hist in b.assigns.items()
                  if sum(1 for a in hist if a[1] == "=") > 1
                  and not any(re.match(rf"{re.escape(v)}\b", a[2]) for a in hist)
                  for a in hist if a[1] == "="}
    places_of = {}

    def read_at(name, frame, pos, st):
        for nm in spellings(name):
            if nm in frame[0].takes or nm in frame[0].assigns:
                return interp.var(nm, pos, frame, st, 0)
        return None

    for e in model["edges"]:
        if e["from"] in vec and e["to"] in vec:
            vec[e["id"]] = A.AND(vec[e["from"]], vec[e["to"]]); how[e["id"]] = "both ends"
            # a variable assigned more than once: the edge is there only when
            # its producer made the value that reaches the consumer
            name, u = e.get("name"), e["from"]
            if not name or not (nodes[u]["kind"] == "process" or u in cands_of):
                continue
            if e["to"] not in places_of:
                places_of[e["to"]] = list(places(e["to"]))
            where = places_of[e["to"]]
            if not where:
                continue
            first = [read_at(name, f, p, default) for f, p in where]
            if not any(isinstance(v, Chan) and v.origins & reassigned for v in first):
                continue
            seen = {"match": False, "decided": False}
            def reaches(st, name=name, u=u, where=where, seen=seen):
                t = False
                for frame, pos in where:
                    v = read_at(name, frame, pos, st)
                    if not isinstance(v, Chan) or not v.origins:
                        return True                          # not known: no restriction
                    seen["decided"] = True
                    hit = any(made_by(o, u) for o in v.origins)
                    seen["match"] |= hit
                    t = t or hit
                return t
            r = A.lift(reaches)
            if seen["decided"] and seen["match"] and A.restricts(r):
                vec[e["id"]] = A.AND(vec[e["id"]], r); how[e["id"]] = "both ends, and the value reaching the consumer"

    return vec, how


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--source", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--profile-config")
    ap.add_argument("--report")
    a = ap.parse_args()
    model = json.load(open(a.model, encoding="utf-8"))
    dims = {d["id"]: d for d in model["dimensions"]}
    fixed = ((model.get("generated") or {}).get("evidence") or {}).get("fixed_args")
    base_params = baseline_params(a.source, a.profile_config, fixed)
    pipe = Pipeline(a.source)
    interp = Interp(pipe.bodies, dims, base_params, pipe.derived)
    allowed = [dict(zip(dims, c)) for c in itertools.product(*[domain(d) for d in dims.values()])]
    allowed = [s for s in allowed if _allowed(s, dims)]
    default = {k: d.get("default", domain(d)[0]) for k, d in dims.items()}

    vec, how = compute(model, pipe, interp, default, VectorAlgebra(interp, dims, default, allowed))

    want_cache = {}
    def want(x):
        k = json.dumps(x.get("when"), sort_keys=True)
        if k not in want_cache: want_cache[k] = [holds(x.get("when"), s, dims) for s in allowed]
        return want_cache[k]
    tally = collections.defaultdict(collections.Counter)
    by_how = collections.defaultdict(collections.Counter)
    results = {}
    for x in model["nodes"] + model["edges"]:
        kind = "edge" if "from" in x else x["kind"]
        if x["id"] not in vec:
            tally[kind]["not reached"] += 1; results[x["id"]] = {"status": "not reached"}; continue
        st, wrong, unknown = score(vec[x["id"]], want(x))
        tally[kind][st] += 1; by_how[how[x["id"]].split(" (")[0]][st] += 1
        results[x["id"]] = {"status": st, "how": how[x["id"]], "wrong": wrong, "unknown": unknown, "model_when": x.get("when")}
    total = collections.Counter()
    for k, c in tally.items():
        total.update(c)
        print(f"{k:9} " + ", ".join(f"{v} {s}" for s, v in c.most_common()))
    print(f"{'all':9} " + ", ".join(f"{v} {s}" for s, v in total.most_common()) + f"  (of {sum(total.values())}, over {len(allowed)} settings)")
    print("by method:")
    for k, c in by_how.items():
        print(f"  {k:32} " + ", ".join(f"{v} {s}" for s, v in c.most_common()))
    if a.report:
        with open(a.report, "w", encoding="utf-8", newline="\n") as f:
            json.dump({"tally": {k: dict(v) for k, v in tally.items()}, "elements": results}, f, indent=1, ensure_ascii=False)


if __name__ == "__main__":
    main()
