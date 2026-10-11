"""Test vectors for the viewer's JavaScript predicate port.

    python tools/js_parity.py fixtures/fetchngs.json [N]

Writes out/parity-<model>.json: N random viewer settings (filters at "any",
single values, several route values ticked) with the state tools/predicates.py
gives every node and edge under each. The built page exposes window.PF; the
browser check runs PF.state over the same settings and counts disagreements.
"""
import json, os, random, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from predicates import state

path = sys.argv[1]
n = int(sys.argv[2]) if len(sys.argv) > 2 else 400
model = json.load(open(path, encoding="utf-8"))
dims = {d["id"]: d for d in model["dimensions"]}
route = (model.get("routes") or {}).get("dimension")
rng = random.Random(20261010)

def value(d):
    if rng.random() < 0.35: return None
    if d["kind"] == "boolean": return rng.choice([True, False])
    if d["kind"] == "presence": return rng.choice(["present", "absent"])
    if d["id"] == route and rng.random() < 0.4:
        return rng.sample(d["values"], rng.randint(2, len(d["values"])))
    return rng.choice(d["values"])

cases = []
for _ in range(n):
    s = {k: value(d) for k, d in dims.items()}
    cases.append({"settings": s, "states": {x["id"]: state(x, s, dims) for x in model["nodes"] + model["edges"]}})

out = os.path.join(ROOT, "out", "parity-" + os.path.splitext(os.path.basename(path))[0] + ".json")
os.makedirs(os.path.dirname(out), exist_ok=True)
json.dump(cases, open(out, "w", encoding="utf-8"))
print(f"wrote {os.path.relpath(out, ROOT)}: {n} settings x {len(model['nodes']) + len(model['edges'])} elements")
