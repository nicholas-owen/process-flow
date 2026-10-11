"""Does inference recover the true predicates, given a good matrix?

    python tools/test_infer_synthetic.py [fixtures/rnaseq-flow.json]

The preview DAGs we have come from hand-chosen matrices whose runs are
confounded (rnaseq-flow's optional flags were always switched on together),
so they cannot show whether tools/infer.py is right or the matrix is short.
This test takes alignment and the real matrix out of the question: the
fixture's hand-written `when` predicates are the truth, and runs are
synthesised as settings only, presence computed from the truth.

Three designs are compared:

  one at a time   a baseline and one run per other value of each dimension
  pairwise        every pair of values of every two dimensions in some run
                  (tools/matrix.py)
  + adaptive      pairwise, then while elements are ambiguous (several
                  different predicates fit), the candidate run that settles
                  the most of them

For each: how many elements were seen in at least one run (an element never
seen would be missing from a real union graph altogether), how many inferred
predicates fit every run, how many are ambiguous, and how many agree with the
truth on 1,500 random settings.
"""
import json, os, random, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from infer import infer
from matrix import pairwise
from predicates import holds, domain, given, implied

path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "fixtures", "rnaseq-flow.json")
model = json.load(open(path, encoding="utf-8"))
dims = {d["id"]: d for d in model["dimensions"]}
elements = [n for n in model["nodes"] if n["kind"] in ("process", "operator") and n.get("when")]
truth = {n["id"]: n["when"] for n in elements}


def default(d):
    if d.get("default") is not None:
        return d["default"]
    return {"boolean": False, "presence": "absent"}[d["kind"]] if d["kind"] in ("boolean", "presence") else d["values"][0]


base = {k: default(d) for k, d in dims.items()}
rng = random.Random(3)
space = []
while len(space) < 1500:                    # random settings the implications allow
    s = {k: rng.choice(domain(d)) for k, d in dims.items()}
    if all(holds(d["implies"], s, dims) is not False for k, d in dims.items() if d.get("implies")):
        space.append(s)


def present(eid, s):
    return holds(truth[eid], s, dims) is True


def evaluate(runs, label):
    rs = {f"r{i}": s for i, s in enumerate(runs)}
    seen = exact = fits = 0
    amb = {}
    for eid in truth:
        obs = {r for r, s in rs.items() if present(eid, s)}
        if not obs:
            continue
        seen += 1
        pred, ok, others = infer(obs, rs, dims, alternatives=True)
        fits += ok
        if others:
            amb[eid] = [pred] + others
        exact += all((holds(pred, s, dims) is True) == present(eid, s) for s in space)
    print(f"  {label:<16} {len(runs):>3} runs: seen {seen:>3}/{len(truth)}, fit {fits:>3}, "
          f"ambiguous {len(amb):>3}, exactly right {exact:>3}/{len(truth)}")
    return amb


print(f"{os.path.basename(path)}: {len(truth)} processes and operators with a when, {len(dims)} dimensions")
ofat = [base] + [dict(base, **{k: v}) for k, d in dims.items() for v in domain(d) if v != base[k]]
evaluate(ofat, "one at a time")
pw = pairwise(dims, base)
amb = evaluate(pw, "pairwise")
runs = list(pw)
for _ in range(25):
    if not amb:
        break
    cands = []
    for _ in range(1500):
        s = dict(rng.choice(runs))
        for k in rng.sample(list(dims), rng.randint(1, 3)):
            s[k] = rng.choice(domain(dims[k]))
        if all(holds(d["implies"], s, dims) is not False for k, d in dims.items() if d.get("implies")):
            cands.append(s)
    settles = lambda s: sum(len({holds(p, s, dims) is True for p in alts}) > 1 for alts in amb.values())
    best = max(cands, key=settles)
    if not settles(best):
        break
    runs.append(best)
    amb = {e: alts for e, alts in amb.items() if len({holds(p, best, dims) is True for p in alts}) > 1}
evaluate(runs, "+ adaptive")

# pairwise, then local probes around what has been seen, twice
from matrix import probes, next_batch
runs = list(pw)
for rnd in range(2):
    obs = {eid: {i for i, s in enumerate(runs) if present(eid, s)} for eid in truth}
    runs += probes(dims, runs, obs)
    evaluate(runs, f"+ probes x{rnd + 1}")

# adaptive (step 3): batches that probe only unsettled elements, until none are
for start_name, start in (("pairwise", pw), ("one at a time", ofat)):
    print(f"  adaptive from {start_name}:")
    runs = list(start)
    for rnd in range(12):
        obs = {eid: {i for i, s in enumerate(runs) if present(eid, s)} for eid in truth}
        batch = next_batch(dims, runs, obs)
        if not batch:
            break
        runs += batch
        evaluate(runs, f"  batch {rnd + 1} (+{len(batch)})")
