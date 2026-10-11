"""Check tools/align.py against the hand-built fixtures.

    python tools/test_align.py [fixtures/fetchngs.json fixtures/rnaseq-flow.json]

No correspondence between union ids and fixture ids is needed. For each
process and operator, take (type, the set of runs it appears in): the union
graph gets that from alignment, the fixture from its `when` predicates under
each run's settings. If alignment neither splits one operator into two nor
merges two into one, the two multisets are equal. Points (inputs, outputs)
are left out: the fixtures model several DAG points as one node (a value
input feeding two processes, the versions topic).

Also reports, per run, whether the union reproduces the run's own DAG exactly
(it must, by construction: a failure here is a bug in align.py).
"""
import collections, json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import dot
from align import align
from predicates import given, implied

SOURCE_RE = re.compile(r"(channel|Channel)\.(\w+)")


def resolve(path):
    for base in (ROOT, os.path.dirname(ROOT)):
        p = os.path.join(base, path)
        if os.path.exists(p):
            return p
    raise FileNotFoundError(path)


def fixture_type(n):
    if n["kind"] == "process":
        return ":".join(n["path"])
    t = (n.get("operator") or {}).get("type")
    if t:
        return "op:" + t
    if n["kind"] == "source":
        m = SOURCE_RE.search(n["label"])
        if m and m.group(2) != "topic":           # a topic is a bare point in the DAG
            return "op:channel." + m.group(2)
    return None


def check(model_path):
    model = json.load(open(model_path, encoding="utf-8"))
    dims = {d["id"]: d for d in model["dimensions"]}
    runs = [r for r in model["runs"] if r["status"] == "ok"]
    paths = {r["id"]: resolve(r["dag"]) for r in runs}
    u = align(paths)
    print(f"== {os.path.basename(model_path)}: {len(runs)} runs -> union {len(u.nodes)} nodes, {len(u.edges)} edges")

    # 1. the union reproduces each run (sanity)
    bad = 0
    for r in runs:
        m = u.mapping[r["id"]]
        _, edges = dot.parse(paths[r["id"]])
        got = collections.Counter((m[a], m[b], l) for a, b, l in edges)
        want = collections.Counter((a, b, l) for (a, b, l, k), obs in u.edges.items() if r["id"] in obs)
        bad += got != want
    print(f"   union reproduces every run's edges: {'ok' if not bad else f'{bad} runs differ'}")

    # 2. presence multisets
    ours = collections.Counter((n["type"], frozenset(n["observed"])) for n in u.nodes.values() if n["kind"] != "point")
    theirs = collections.Counter()
    skipped = 0
    procs = collections.defaultdict(frozenset)   # a fixture may model one process as several nodes
    for n in model["nodes"]:
        t = fixture_type(n)
        if t is None:
            skipped += n["kind"] in ("operator", "process", "source")
            continue
        pres = frozenset(r["id"] for r in runs
                         if given(n.get("when"), r["settings"], dims, implied(r["settings"], dims)) is not False)
        if not pres:
            continue
        if n["kind"] == "process":
            procs[t] |= pres
        else:
            theirs[(t, pres)] += 1
    for t, pres in procs.items():
        theirs[(t, pres)] += 1
    # Types the fixture does not model at all are reported, not failed.
    modelled = {t for t, _ in theirs}
    unmodelled = collections.Counter(t for (t, _), c in ours.items() for _ in range(c) if t not in modelled)
    ours = collections.Counter({k: c for k, c in ours.items() if k[0] in modelled})
    if unmodelled:
        print(f"   not modelled by the fixture: {dict(unmodelled)}")
    only_u, only_f = ours - theirs, theirs - ours

    # 3. order sensitivity (reported, not failed): merge in 20 random orders
    import random
    from align import Run, Union
    R = [Run(r["id"], paths[r["id"]]) for r in runs]
    sig = lambda x: collections.Counter((n["type"], frozenset(n["observed"])) for n in x.nodes.values())
    base, moved = sig(u), collections.Counter()
    for i in range(20):
        x = Union()
        for r in random.Random(i).sample(R, len(R)): x.add(r)
        for (t, _), c in (sig(x) - base).items(): moved["point" if t == "point" else t] += 1
    print(f"   merge order: {'no effect over 20 random orders' if not moved else 'changes, over 20 random orders: ' + str(dict(moved))}")
    total = sum(ours.values())
    agree = total - sum(only_u.values())
    print(f"   processes and operators: {agree} of {total} agree with the fixture"
          + (f" ({skipped} fixture nodes without a DAG type skipped)" if skipped else ""))
    short = lambda s: "{" + ",".join(sorted(s)) + "}" if len(s) < len(runs) else "{all}"
    by_type = collections.defaultdict(lambda: [collections.Counter(), collections.Counter()])
    for (t, s), c in only_u.items(): by_type[t][0][short(s)] += c
    for (t, s), c in only_f.items(): by_type[t][1][short(s)] += c
    for t, (a, b) in sorted(by_type.items()):
        print(f"   {t}:\n      union only:   {dict(a)}\n      fixture only: {dict(b)}")
    return not only_u and not only_f and not bad


if __name__ == "__main__":
    paths = sys.argv[1:] or [os.path.join(ROOT, "fixtures", "fetchngs.json"), os.path.join(ROOT, "fixtures", "rnaseq-flow.json")]
    ok = all([check(p) for p in paths])
    sys.exit(0 if ok else 1)
