"""One-way copy of rnaseq-flow's prototype channels.json into schema 0.1.

Reads the rnaseq-flow repo and never writes to it. Writes
fixtures/rnaseq-flow.json in this repo, then checks the conversion:

  1. the output validates against schema/channels.schema.json (if jsonschema
     is installed);
  2. every `when` gives the same answer as the prototype's own holds()
     (ported from channels_template.html) under the 14 preview settings and
     20,000 random viewer settings;
  3. every process predicted by the new `when` for a preview run is in that
     run's DOT, and vice versa.

    python tools/convert_prototype.py [path/to/rnaseq-flow]

Exits non-zero if a check fails.
"""
import ast, datetime, glob, json, os, random, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from predicates import holds

SRC_REPO = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "..", "rnaseq-flow")
PROTO = os.path.join(SRC_REPO, "working_docs", "channel-schematic")
OUT = os.path.join(ROOT, "fixtures", "rnaseq-flow.json")

src = json.load(open(os.path.join(PROTO, "channels.json"), encoding="utf-8"))

# ---- dimensions ------------------------------------------------------------
STOP = src["dimensions"]["stop_at"]                     # name -> run level
LEVEL_NAME = {lvl: name for name, lvl in STOP.items()}
FLAGS = src["dimensions"]["flags"]
FLAG_PARAM_KIND = {"transcript_fasta": "path", "ctat_lib": "path", "gmt": "path"}

dimensions = [
    {"id": "workflow", "param": None, "kind": "enum", "values": src["dimensions"]["workflow"], "default": "RNASEQ",
     "derived_from": "--download_refs selects DOWNLOAD, --build_indices selects BUILD_INDICES, otherwise RNASEQ",
     "source": "main.nf:338-347"},
    {"id": "entry", "param": None, "kind": "enum", "values": src["dimensions"]["entry"], "default": "reads",
     "derived_from": "counts when --counts is set, otherwise reads", "source": "main.nf:89,353"},
    {"id": "input", "param": None, "kind": "enum", "values": src["dimensions"]["input"], "default": "samplesheet",
     "derived_from": "samplesheet when --input ends in .csv, otherwise a glob", "source": "main.nf:360,416"},
    {"id": "aligner", "param": "aligner", "kind": "enum", "values": src["dimensions"]["aligner"], "default": "star",
     # In RNASEQ an aligner means the reads entry. It says nothing about the
     # helper workflows, which the page draws as part of every route.
     "implies": {"any": [{"params": {"workflow": ["DOWNLOAD", "BUILD_INDICES"]}}, {"params": {"workflow": "RNASEQ", "entry": "reads"}}]},
     "source": "nextflow_schema.json"},
    {"id": "stop_at", "param": "stop_at", "kind": "ordinal", "values": list(STOP), "default": "none",
     "description": "Ordered by run level: " + ", ".join(f"{k} {v}" for k, v in STOP.items()) + ". 'none' is the param left unset.",
     "source": "nextflow_schema.json"},
    {"id": "gtf", "param": "gtf", "kind": "presence", "source": "nextflow_schema.json"},
    {"id": "strandedness", "param": None, "kind": "enum", "values": src["dimensions"]["strandedness"], "default": "auto",
     "derived_from": "auto when --strandedness auto, explicit for unstranded, forward or reverse",
     "source": "nextflow_schema.json"},
] + [
    {"id": f, "param": f, "kind": "presence" if FLAG_PARAM_KIND.get(f) == "path" else "boolean", "source": "nextflow_schema.json"}
    for f in FLAGS
]
DIMS = {d["id"]: d for d in dimensions}

# ---- predicates ------------------------------------------------------------
def conv_pred(w):
    """Prototype when -> schema predicate. Drops `previewed`, which is not a condition."""
    if not w:
        return None
    params = {}
    for k, v in w.items():
        if k in ("any", "previewed"):
            continue
        if k == "level_min":
            params["stop_at"] = {"min": LEVEL_NAME[v]}
        elif k == "gtf":
            params["gtf"] = {"present": bool(v)}
        elif k == "flags":
            for f in v:
                params[f] = {"present": True} if DIMS[f]["kind"] == "presence" else True
        elif k in ("workflow", "entry", "input", "strandedness"):
            params[k] = v
        elif k == "aligner":
            params["aligner"] = list(v)
        else:
            raise ValueError(f"unknown when key {k!r}")
    p = {}
    if params: p["params"] = params
    if "any" in w: p["any"] = [conv_pred(a) or {} for a in w["any"]]
    return p or None

# ---- ids, paths ------------------------------------------------------------
PROC_RE = re.compile(r"^(DOWNLOAD|BUILD_INDICES|RNASEQ)\.([A-Z0-9_]+(?:_exon|_transcript)?)$")
idmap = {}
for n in src["nodes"]:
    m = PROC_RE.match(n["id"]) if n["kind"] == "process" else None
    idmap[n["id"]] = f"{m.group(1)}:{m.group(2)}" if m else n["id"]

def proc_name(n):
    return re.sub(r" \(.*\)$", "", n["label"])           # "DIFFSPLICE (exon)" -> DIFFSPLICE

OPS = ["collectFile", "collect", "combine", "branch", "filter", "flatten", "groupTuple", "ifEmpty",
       "join", "mix", "first", "map", "unique", "toList", "splitCsv", "transpose", "multiMap", "set"]
def op_type(label):
    for op in OPS:
        if re.search(rf"\b{op}\b", label):
            return op
    return None

# ---- cardinality, meta -----------------------------------------------------
def conv_card(c):
    if c == "per-sample": return {"kind": "queue", "per": "sample"}
    if c in ("single", "value", "queue", "mixed"): return {"kind": c}
    if c == "value items mixed into a queue": return {"kind": "mixed", "text": c}
    if c == "single|value": return {"kind": "value", "text": "a one-item queue or a value channel, depending on route (prototype: single|value)"}
    raise ValueError(f"unknown cardinality {c!r}")

IDENT_LIST = re.compile(r"^[a-z_]+(, [a-z_]+)*$")
def conv_meta(m):
    if m in ("n/a", "n/a (not yet a meta)"):
        return None
    if IDENT_LIST.match(m):
        return {"keys": m.split(", ")}
    return {"text": m}

# ---- nodes -----------------------------------------------------------------
nodes = []
for n in src["nodes"]:
    out = {"id": idmap[n["id"]], "kind": n["kind"], "label": n["label"]}
    if n["kind"] == "process":
        out["path"] = [n["workflow"], proc_name(n)]
        out["module"] = n["source"]
    elif n["workflow"] != "shared":
        out["path"] = [n["workflow"]]
    if n["kind"] == "operator":
        t = op_type(n["label"])
        out["operator"] = {"type": t, "closure": n["label"]} if t else {"closure": n["label"]}
    out["source"] = n["source"]
    w = conv_pred(n["when"])
    if w: out["when"] = w
    out["when_from"] = "annotated"
    if n.get("starved"):
        out["flows_when"] = {"not": conv_pred(n["starved"])}
        out["flows_when_from"] = "annotated"
    if n["when"].get("previewed") is False:
        out["observed_in"] = []
    out["lane"] = n["lane"]
    out["category"] = n["category"]
    notes = n["notes"]
    if n.get("starved_when"):
        notes = (notes + " " if notes else "") + f"Starved when {n['starved_when']}."
    if notes: out["notes"] = notes
    nodes.append(out)

# ---- edges -----------------------------------------------------------------
edges = []
for e in src["edges"]:
    out = {"id": e["id"], "from": idmap[e["from"]], "to": idmap[e["to"]], "name": e["name"]}
    if e["operator"]: out["operator"] = e["operator"]
    c = {"shape": e["shape"], "meta": conv_meta(e["meta"]), "cardinality": conv_card(e["cardinality"])}
    if e["files"]: c["files"] = e["files"]
    c["from"] = {k: "annotated" for k in ("shape", "meta", "cardinality", "files") if k in c}
    out["contents"] = c
    w = conv_pred(e["when"])
    if w: out["when"] = w
    out["when_from"] = "annotated"
    if e["when"].get("previewed") is False:
        out["observed_in"] = []
    out["lane"] = e["lane"]
    if e.get("examples"):
        out["examples"] = {}
        for k, x in e["examples"].items():
            x = dict(x)
            if x["kind"] == "per_sample": x["kind"] = "per_item"
            out["examples"][k] = x
    if e["notes"]: out["notes"] = e["notes"]
    edges.append(out)

# ---- runs (the 14 preview DAGs) and observed_in for processes ---------------
def preview_settings():
    tree = ast.parse(open(os.path.join(PROTO, "check_channels.py"), encoding="utf-8").read())
    for node in tree.body:
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", None) == "PREVIEWS":
            return eval(compile(ast.Expression(node.value), "PREVIEWS", "eval"),
                        {"__builtins__": {}, "dict": dict, "set": set})
    raise SystemExit("PREVIEWS not found in check_channels.py")

PREVIEWS = preview_settings()
# Dropped from preview_dags.sh after it failed (M21); its partial DOT and log
# remain. Kept here as the failed run the matrix driver is meant to record.
FAILED = {"star_minimal": dict(workflow="RNASEQ", entry="reads", input="samplesheet", aligner="star",
                               level=100, gtf=False, strandedness="auto", flags=set())}

def run_settings(s):
    """Prototype preview settings -> dimension settings. Unset means 'any' (None)."""
    out = {d: None for d in DIMS}
    out["workflow"] = s.get("workflow")
    if out["workflow"] == "RNASEQ":
        out.update(entry=s["entry"], input=s["input"], strandedness=s["strandedness"],
                   stop_at=LEVEL_NAME[s["level"]], gtf="present" if s["gtf"] else "absent")
        for f in FLAGS:
            on = f in s["flags"]
            out[f] = ("present" if on else "absent") if DIMS[f]["kind"] == "presence" else on
    elif out["workflow"] == "DOWNLOAD":
        out["download_gmt"] = "download_gmt" in s.get("flags", set())
    a = s.get("aligner")
    out["aligner"] = None if a in (None, "all") else a
    return out

def dot_processes(path):
    labels = set(re.findall(r'label="((?:DOWNLOAD|BUILD_INDICES|RNASEQ):[A-Z0-9_]+)"', open(path, encoding="utf-8").read()))
    return labels

runs, dot_procs = [], {}
for name, s in {**PREVIEWS, **FAILED}.items():
    dot = os.path.join(PROTO, "dags", f"{name}.dot")
    ok = name not in FAILED and os.path.exists(dot) and os.path.getsize(dot) > 0
    r = {"id": name, "status": "ok" if ok else "failed", "settings": run_settings(s),
         "dag": f"rnaseq-flow/working_docs/channel-schematic/dags/{name}.dot", "date": "2026-09-14"}
    if name == "star_minimal":
        r["error"] = "STAR cannot run without a GTF: null file(params.gtf) at rnaseq.nf:460 (to-fix M21)"
        r["args"] = "--aligner star, no --gtf"
    runs.append(r)
    if ok:
        dot_procs[name] = dot_processes(dot)

for n in nodes:
    if n["kind"] == "process" and "observed_in" not in n:
        label = ":".join(n["path"])
        n["observed_in"] = [r for r, procs in dot_procs.items() if label in procs]

# ---- assemble --------------------------------------------------------------
model = {
    "schema_version": "0.1",
    "pipeline": {"name": src["meta"]["pipeline"], "version": src["meta"]["version"],
                 "revision": "unrecorded (prototype of 2026-09-14)", "prefix": []},
    "generated": {"tool": "process-flow tools/convert_prototype.py", "date": datetime.date.today().isoformat(),
                  "sources": ["rnaseq-flow/working_docs/channel-schematic/channels.json"] + src["meta"]["sources"]},
    "dimensions": dimensions,
    "routes": {"dimension": "aligner", "colours": {a: src["palette"][a] for a in src["dimensions"]["aligner"]}},
    "palette": {k: v for k, v in src["palette"].items() if k not in src["dimensions"]["aligner"]},
    "lanes": [
        {"id": "main", "label": src["lanes"]["main"], "mode": "expanded"},
        {"id": "versions", "label": src["lanes"]["versions"], "hub": "RNASEQ.ch_versions", "target": "RNASEQ:MULTIQC", "mode": "folded"},
        {"id": "multiqc", "label": src["lanes"]["multiqc"], "hub": "RNASEQ.ch_multiqc_files", "target": "RNASEQ:MULTIQC", "mode": "folded"},
        {"id": "scripts", "label": src["lanes"]["scripts"], "mode": "hidden"},
    ],
    "groups": [{"path": ["DOWNLOAD"], "label": "DOWNLOAD"}, {"path": ["BUILD_INDICES"], "label": "BUILD_INDICES"},
               {"path": ["RNASEQ"], "label": "RNASEQ"}],
    "runs": runs,
    "nodes": nodes,
    "edges": edges,
}
os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, "w", encoding="utf-8", newline="\n") as f:
    json.dump(model, f, indent=1, ensure_ascii=False)
    f.write("\n")
print(f"wrote {os.path.relpath(OUT, ROOT)}: {len(nodes)} nodes, {len(edges)} edges, {len(runs)} runs")

# ---- checks ----------------------------------------------------------------
failed = False

try:
    import jsonschema
    schema = json.load(open(os.path.join(ROOT, "schema", "channels.schema.json"), encoding="utf-8"))
    errs = list(jsonschema.Draft202012Validator(schema).iter_errors(model))
    print(f"schema: {'ok' if not errs else f'{len(errs)} errors'}")
    for e in errs[:10]: print("  ", e.json_path, e.message[:150])
    failed |= bool(errs)
except ImportError:
    print("schema: skipped (pip install jsonschema)")

def old_holds(when, s):
    """channels_template.html holds(), in Python. s uses the template's setting names."""
    if not when: return True
    if "any" in when:
        rest = {k: v for k, v in when.items() if k != "any"}
        return old_holds(rest, s) and any(old_holds(a, s) for a in when["any"])
    if when.get("workflow") and s["workflow"] and when["workflow"] != s["workflow"]: return False
    if when.get("entry") and s["entry"] and when["entry"] != s["entry"]: return False
    if when.get("input") and s["input"] and when["input"] != s["input"]: return False
    if when.get("aligner") and s["aligners"] and not any(a in s["aligners"] for a in when["aligner"]): return False
    if when.get("level_min") and s["level"] is not None and s["level"] < when["level_min"]: return False
    if when.get("gtf") is True and s["gtf"] == "absent": return False
    if when.get("gtf") is False and s["gtf"] != "absent": return False
    if when.get("strandedness") and s["strand"] and when["strandedness"] != s["strand"]: return False
    if when.get("flags"):
        for f in when["flags"]:
            if s["flags"].get(f) == "off": return False
    return True

def to_new(s):
    """Template settings -> dimension settings."""
    out = {"workflow": s["workflow"], "entry": s["entry"], "input": s["input"],
           "aligner": (s["aligners"][0] if len(s["aligners"]) == 1 else s["aligners"]) or None,
           "stop_at": LEVEL_NAME[s["level"]] if s["level"] is not None else None,
           "gtf": s["gtf"], "strandedness": s["strand"]}
    for f in FLAGS:
        v = s["flags"].get(f)
        on = None if v is None else v == "on"
        out[f] = on if DIMS[f]["kind"] == "boolean" or on is None else ("present" if on else "absent")
    return out

def random_settings(rng):
    pick = lambda xs: rng.choice([None] + list(xs))
    return {"workflow": pick(src["dimensions"]["workflow"]), "entry": pick(src["dimensions"]["entry"]),
            "input": pick(src["dimensions"]["input"]),
            "aligners": rng.sample(src["dimensions"]["aligner"], rng.choice([0, 0, 1, 1, 2, 3])),
            "level": pick(STOP.values()), "gtf": pick(["present", "absent"]),
            "strand": pick(src["dimensions"]["strandedness"]),
            "flags": {f: pick(["on", "off"]) for f in FLAGS if rng.random() < 0.7}}

def template_settings(s):
    """A preview's settings in the template's terms."""
    if s.get("workflow") != "RNASEQ":
        a = s.get("aligner")
        return {"workflow": s.get("workflow"), "entry": None, "input": None, "aligners": [] if a in (None, "all") else [a],
                "level": None, "gtf": None, "strand": None, "flags": {f: "on" for f in s.get("flags", set())}}
    return {"workflow": "RNASEQ", "entry": s["entry"], "input": s["input"], "aligners": [s["aligner"]] if s["aligner"] else [],
            "level": s["level"], "gtf": "present" if s["gtf"] else "absent", "strand": s["strandedness"],
            "flags": {f: ("on" if f in s["flags"] else "off") for f in FLAGS}}

rng = random.Random(20261010)
cases = [template_settings(s) for s in PREVIEWS.values()] + [random_settings(rng) for _ in range(20000)]
elements = [(n, nn) for n, nn in zip(src["nodes"], nodes)] + [(e, ee) for e, ee in zip(src["edges"], edges)]
mismatch = []
for s in cases:
    ns = to_new(s)
    for old, new in elements:
        a = old_holds({k: v for k, v in old["when"].items() if k != "previewed"}, s)
        b = holds(new.get("when"), ns, DIMS) is not False
        if a != b:
            mismatch.append((old["id"], s, a, b))
print(f"when equivalence: {len(cases)} settings x {len(elements)} elements, "
      f"{'ok' if not mismatch else f'{len(mismatch)} mismatches'}")
for m in mismatch[:5]: print("  ", m)
failed |= bool(mismatch)

# starved: the template marks starved when holds(starved) and holds(when); the
# new model, when flows_when is definitely False. Compared on complete settings
# only, where both are two-valued.
smis = 0
for s in [template_settings(s) for s in PREVIEWS.values() if s.get("workflow") == "RNASEQ"]:
    for old, new in elements:
        if not old.get("starved"): continue
        a = old_holds(old["starved"], s) and old_holds(old["when"], s)
        ns = to_new(s)
        b = holds(new.get("when"), ns, DIMS) is True and holds(new.get("flows_when"), ns, DIMS) is False
        smis += a != b
print(f"starved equivalence on preview settings: {'ok' if not smis else f'{smis} mismatches'}")
failed |= bool(smis)

dmis = []
for r in runs:
    if r["status"] != "ok": continue
    predicted = {":".join(n["path"]) for n in nodes if n["kind"] == "process" and n.get("observed_in") != []
                 and holds(n.get("when"), r["settings"], DIMS) is not False}
    actual = dot_procs[r["id"]]
    if predicted != actual:
        dmis.append((r["id"], sorted(predicted - actual), sorted(actual - predicted)))
print(f"processes vs preview DAGs: {'ok' if not dmis else f'{len(dmis)} runs differ'}")
for d in dmis: print(f"   {d[0]}: predicted only {d[1]}; DAG only {d[2]}")

sys.exit(1 if failed else 0)
