"""Check the declared shapes generate.py puts on process-boundary edges.

    python tools/test_contents.py

fetchngs: every edge the hand-built fixture marks as having a declared shape
is looked for in the model generated from the real preview runs with
--source: an edge on the same process, in the same direction, with the same
shape. nf-core/rnaseq (no fixture): coverage, i.e. how many process-boundary
edges got a port, and by what evidence.
"""
import collections, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from generate import dims_from_proposal, runs_from_tsv, generate


def build(name, proposal, dags, source):
    dims = dims_from_proposal(os.path.join(ROOT, proposal))
    runs = runs_from_tsv(os.path.join(ROOT, dags, "runs.tsv"), os.path.join(ROOT, dags), dims)
    return generate(name, dims, runs, ROOT, source=os.path.join(ROOT, source))


def boundary(model):
    """(process path, 'in'|'out', shape) for every edge touching a process, and
    the edges that touch one but got no shape."""
    procs = {n["id"]: ":".join(n["path"]) for n in model["nodes"] if n["kind"] == "process"}
    got, missing = collections.Counter(), []
    for e in model["edges"]:
        for end, d in ((e["to"], "in"), (e["from"], "out")):
            if end in procs:
                shape = (e.get("contents") or {}).get("shape")
                if shape:
                    got[(procs[end], d, shape)] += 1
                else:
                    missing.append((procs[end].split(":")[-1], d, e.get("name", "")))
    return got, missing


def evidence(model):
    c = collections.Counter()
    for e in model["edges"]:
        if e.get("port"):
            c[e["port"].split(" ")[0]] += 1
    return c


# ---- fetchngs against the fixture -----------------------------------------
m = build("nf-core/fetchngs", "out/propose-fetchngs/proposal.json", "out/adaptive-fetchngs/dags", "working_docs/fetchngs-src")
fx = json.load(open(os.path.join(ROOT, "fixtures", "fetchngs.json"), encoding="utf-8"))
fprocs = {n["id"]: ":".join(n["path"]) for n in fx["nodes"] if n["kind"] == "process"}
want = collections.Counter()
for e in fx["edges"]:
    c = e.get("contents") or {}
    if (c.get("from") or {}).get("shape") != "declared":
        continue
    if e["to"] in fprocs:
        want[(fprocs[e["to"]], "in", c["shape"])] += 1
    elif e["from"] in fprocs:
        want[(fprocs[e["from"]], "out", c["shape"])] += 1
got, missing = boundary(m)


def form(shape):
    """What notation cannot change: a tuple's arity and whether it starts with
    meta; otherwise a single value. The fixture wrote `path` and
    `[process, tool, version]` where the parser gives the declared names."""
    if shape.startswith("["):
        parts = [p.strip() for p in shape.strip("[]").split(",")]
        return f"tuple/{len(parts)}" + ("/meta" if parts[0].startswith("meta") else "")
    return "single"


def by(c, f):
    out = collections.Counter()
    for (p, d, s), n in c.items():
        out[(p, d, f(s))] += n
    return out


exact = sum(min(n, got[k]) for k, n in want.items())
fw, fg = by(want, form), by(got, form)
same_form = sum(min(n, fg[k]) for k, n in fw.items())
print(f"fetchngs: of {sum(want.values())} declared shapes in the fixture, {same_form} found on the generated model with the "
      f"same port and form (arity, meta), {exact} with identical text")
for k, n in sorted((fw - fg).items()):
    alts = sorted({s for (p, d, s) in got if p == k[0] and d == k[1]})
    print(f"   wrong or missing: {k[0].split(':')[-1]} {k[1]} {k[2]}; generated there: {alts}")
print(f"   process-boundary edges with no shape: {len(missing)} {missing[:6]}")
print(f"   ports by evidence: {dict(evidence(m))}")

# ---- nf-core/rnaseq coverage -----------------------------------------------
m = build("nf-core/rnaseq", "out/propose-rnaseq/proposal-enums.json", "out/adaptive-rnaseq3/dags", "working_docs/rnaseq-src")
got, missing = boundary(m)
procs = [n for n in m["nodes"] if n["kind"] == "process"]
print(f"\nnf-core/rnaseq: {sum(1 for n in procs if n.get('module'))} of {len(procs)} processes matched to a module; "
      f"{sum(got.values())} process-boundary edge ends shaped, {len(missing)} not")
for k, n in collections.Counter((p, d) for p, d, _ in missing).most_common(8):
    print(f"   unshaped: {k[0]} {k[1]} x{n}")
