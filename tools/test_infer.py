"""Check tools/infer.py on the aligned preview DAGs of both fixtures.

    python tools/test_infer.py [-v]

For every node and edge of the union graph: infer a `when` from the runs it
was observed in, and check it reproduces every run. For processes, also
compare the inferred predicate with the fixture's hand-written one, on the
preview runs (must agree) and on 5,000 random complete settings (how far the
inference generalises the way a reader of the code would).
"""
import collections, json, os, random, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from align import align
from infer import infer
from predicates import holds, domain
from test_align import resolve

VERBOSE = "-v" in sys.argv


def text(p, dims):
    if not p:
        return "always"
    parts = []
    for d, c in p.get("params", {}).items():
        if isinstance(c, dict) and "present" in c: parts.append(f"{d} {'set' if c['present'] else 'unset'}")
        elif isinstance(c, dict): parts.append(f"{d} >= {c['min']}")
        elif isinstance(c, list): parts.append(f"{d} = {'|'.join(map(str, c))}")
        elif dims[d]["kind"] == "boolean": parts.append(d if c else f"no {d}")
        else: parts.append(f"{d} = {c}")
    if p.get("any"):
        parts.append("(" + " OR ".join(text(a, dims) for a in p["any"]) + ")")
    return "; ".join(parts)


def check(model_path):
    model = json.load(open(model_path, encoding="utf-8"))
    dims = {d["id"]: d for d in model["dimensions"]}
    runs = [r for r in model["runs"] if r["status"] == "ok"]
    settings = {r["id"]: r["settings"] for r in runs}
    u = align({r["id"]: resolve(r["dag"]) for r in runs})
    print(f"== {os.path.basename(model_path)}: {len(runs)} runs, {len(u.nodes)} nodes, {len(u.edges)} edges")

    elements = [(uid, n["kind"], set(n["observed"])) for uid, n in u.nodes.items()] + \
               [(f"{a}->{b}[{l}]", "edge", set(obs)) for (a, b, l, k), obs in u.edges.items()]
    results, bad, ambiguous = {}, [], {}
    shapes = collections.Counter()
    for eid, kind, obs in elements:
        pred, ok, others = infer(obs, settings, dims, alternatives=True)
        results[eid] = pred
        if not ok: bad.append((eid, kind, sorted(obs)))
        if others: ambiguous[eid] = [pred] + others
        shapes["always" if pred is None else ("any" if pred.get("any") else f"{len(pred.get('params', {}))} conditions")] += 1
    print(f"   inferred for {len(elements)} elements: {dict(shapes)}")
    print(f"   reproduces every run: {len(elements) - len(bad)} of {len(elements)}")
    for eid, kind, obs in bad[:8]:
        print(f"      cannot fit: {kind} {eid} seen in {obs}")
    print(f"   ambiguous (several equally small predicates fit): {len(ambiguous)}")

    # Which new runs would settle the most ambiguity? A run settles an element
    # when its alternatives disagree on it. Greedy, from random candidates
    # built by changing one to three dimensions of an existing run.
    rng = random.Random(2)
    cands = []
    for _ in range(3000):
        base = dict(settings[rng.choice(list(settings))])
        for d in rng.sample(list(dims), rng.randint(1, 3)):
            base[d] = rng.choice(domain(dims[d]))
        cands.append(base)
    open_ = dict(ambiguous)
    picks = []
    while open_ and len(picks) < 5:
        best = max(cands, key=lambda s: sum(len({holds(p, s, dims) is True for p in alts}) > 1 for alts in open_.values()))
        n = sum(len({holds(p, best, dims) is True for p in alts}) > 1 for alts in open_.values())
        if not n:
            break
        picks.append((n, best))
        open_ = {e: alts for e, alts in open_.items() if len({holds(p, best, dims) is True for p in alts}) == 1}
    for n, s in picks:
        diff = ", ".join(f"{d}={v}" for d, v in s.items() if v not in (None, False, "absent") and d != "workflow")
        print(f"      a run that settles {n}: {diff}")

    # processes against the fixture
    rng = random.Random(1)
    space = [{d: rng.choice(domain(dim)) for d, dim in dims.items()} for _ in range(5000)]
    fixture = {":".join(n["path"]): n for n in model["nodes"] if n["kind"] == "process"}
    agree_runs = agree_space = 0
    rows = []
    for uid, n in u.nodes.items():
        if n["kind"] != "process":
            continue
        mine = results[uid]
        # the fixture may model one process as several nodes (DIFFSPLICE): any of them
        theirs = [f.get("when") for k, f in fixture.items() if k == uid] or \
                 [f.get("when") for f in model["nodes"] if f["kind"] == "process" and ":".join(f["path"]) == uid]
        if not theirs:
            continue
        fx = lambda s: any(holds(w, s, dims) is True for w in theirs)
        agree_runs += all((holds(mine, settings[r], dims) is True) == fx(settings[r]) for r in settings)
        same = sum((holds(mine, s, dims) is True) == fx(s) for s in space) / len(space)
        agree_space += same == 1.0
        rows.append((same, uid.split(":")[-1], text(mine, dims)))
    print(f"   processes: {agree_runs} of {len(rows)} agree with the fixture on every preview run; "
          f"{agree_space} of {len(rows)} on all 5,000 random settings")
    for same, name, t in sorted(rows):
        if VERBOSE or same < 1:
            print(f"      {same:6.1%}  {name:<28} {t}")
    return not bad


if __name__ == "__main__":
    ok = all([check(os.path.join(ROOT, "fixtures", f)) for f in ("fetchngs.json", "rnaseq-flow.json")])
    sys.exit(0 if ok else 1)
