"""Harvest what a real run carried from Nextflow's data lineage, and lay it
over a channel model.

    python tools/harvest.py MODEL --lineage RUN/.lineage --source SRC \\
        [--dag RUN/pf/dag.dot --dags PREVIEW_DAGS] -o model+run.json

Nextflow 25.04 and later record every task when the run has
`lineage.enabled = true`: a TaskRun with the task's inputs and a TaskOutput
with its outputs, each value kept as it was, meta maps included. Inputs and
outputs come flattened, one entry per tuple element in declaration order,
optional outputs that were not made as [] and `topic:` emits included; the
module's declarations (tools/modules.py) split them back into ports. A path
is a `lid://TASK/file` link, so every input names the task and emit that made
it.

For every process port seen in the run (`input N`, `emit X`, as the model's
edges name them):

  - meta keys: the union of the keys of the meta maps that crossed it
  - cardinality: queue (one item per task, `per` the meta id when items
    carry one), value (the same item in every task), single (one task)
  - a worked example: up to six distinct items, as a Groovy map would print,
    files by name, grouped by meta id
  - where its files came from: the producing processes and emits

and the model's edges at that port get them, marked `harvested`, the
examples keyed by the run's name. `generated.captured` records the run: its
name, revision, the dimension settings read from its params, task counts, and
the check below.

Edges between operators, which lineage does not see, get where their files
came from and went (`contents.files`): every edge on the way from a producing
emit to the process input its files reached.

The check: the run's settings put through every process's `when` give the
processes the model expects; the lineage gives those that ran; --dag (the
run's own DAG) gives those wired. With --dags (the previews the model was
built from) the run's DAG is aligned with them, and every node and edge it
has is compared with the elements the model expects under its settings.
Disagreements mean the model is stale for this revision, or wrong, or that
the run changed an arg the matrix held in every preview (a published model's
`fixed_args`): differences are grouped into connected pieces and each piece
is put down to the changed arg it names, if any. Processes wired but given no
task are recorded as starved in this run.
"""
import argparse, collections, glob, json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from modules import Source
from predicates import holds

LID = re.compile(r"^lid://([0-9a-f]+)/(.+)$")
MAX_ITEMS = 6


# ---- reading the lineage store --------------------------------------------------------
def read_lineage(root, session=None):
    """Tasks and the workflow record of one run in a lineage store. A launch
    folder's store keeps every run made there: the latest is taken (or the
    one whose session is given), with its own tasks, and the tasks a -resume
    took from the cache: those of earlier runs of its session whose name it
    did not run itself."""
    tasks, outputs, workflows = {}, {}, []
    for d in os.listdir(root):
        f = os.path.join(root, d, ".data.json")
        if not os.path.exists(f):
            continue
        rec = json.load(open(f, encoding="utf-8"))
        kind, spec = rec.get("kind"), rec.get("spec", {})
        if kind == "TaskRun":
            name = spec["name"]
            proc, _, tag = name.partition(" (")
            tasks[d] = {"hash": d, "name": name, "process": proc, "tag": tag[:-1] if tag else None,
                        "inputs": spec.get("input", []), "session": spec.get("sessionId"),
                        "workflow": (spec.get("workflowRun") or "").replace("lid://", "")}
        elif kind == "TaskOutput":
            outputs[d.split("#")[0]] = spec.get("output", [])
        elif kind == "WorkflowRun":
            workflows.append(dict(spec, _lid=d))
    if session:
        workflows = [w for w in workflows if w.get("sessionId") == session] or workflows
    workflow = max(workflows, key=lambda w: ((w.get("metadata") or {}).get("start") or ""), default=None)
    if workflow and len(workflows) > 1:
        # the run's own tasks; then, from earlier runs of its session (a
        # -resume), the tasks it took from the cache: those whose name it
        # does not run itself, the latest of each
        own = {h: t for h, t in tasks.items() if t["workflow"] == workflow["_lid"]}
        names = {t["name"] for t in own.values()}
        earlier = sorted((w for w in workflows if w is not workflow and w.get("sessionId") == workflow.get("sessionId")),
                         key=lambda w: ((w.get("metadata") or {}).get("start") or ""), reverse=True)
        for w in earlier:
            for h, t in tasks.items():
                if t["workflow"] == w["_lid"] and t["name"] not in names:
                    own[h] = t; names.add(t["name"])
        tasks = own
    for h, t in tasks.items():
        t["outputs"] = outputs.get(h)
    return tasks, workflow


def split_ports(flat, decls):
    """Flattened values -> one list per declaration, or None if the counts
    do not add up."""
    sizes = [max(1, len(d["elements"])) if d["kind"] == "tuple" else 1 for d in decls]
    if flat is None or sum(sizes) != len(flat):
        return None
    out, i = [], 0
    for n in sizes:
        out.append(flat[i:i + n]); i += n
    return out


# ---- rendering values the way a map closure would print them ---------------------------
def is_file(v):
    """A file staged from outside the run: lineage keeps its path and checksum."""
    return isinstance(v, dict) and "path" in v and "checksum" in v


def render(v):
    if is_file(v):
        return os.path.basename(v["path"])
    if isinstance(v, dict):
        return "[" + ", ".join(f"{k}:{render(x)}" for k, x in v.items()) + "]" if v else "[:]"
    if isinstance(v, list):
        return "[" + ", ".join(render(x) for x in v) + "]"
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, str):
        m = LID.match(v)
        return os.path.basename(m.group(2)) if m else (os.path.basename(v) if "/" in v else v)
    return str(v)


def item(port):
    vals = [e["value"] for e in port]
    return render(vals[0]) if len(vals) == 1 else render(vals)


def lids(v):
    """Producing task of each file in a value; None for a file from outside the run."""
    if is_file(v):
        return [None]
    if isinstance(v, str):
        m = LID.match(v)
        return [m.group(1)] if m else []
    if isinstance(v, list):
        return [h for x in v for h in lids(x)]
    return []


# ---- harvesting ---------------------------------------------------------------------------
def harvest(tasks, src):
    """(process, 'in', index) / (process, 'out', emit key) -> what crossed it."""
    decl_of, problems = {}, collections.Counter()
    ports = collections.defaultdict(lambda: {"items": [], "metas": [], "files": [], "from": collections.Counter(),
                                             "from_files": collections.defaultdict(list)})
    emit_of = {}                                    # (task hash, value id) -> emit key, for provenance
    split = {}
    for h, t in tasks.items():
        p = decl_of.setdefault(t["process"], src.process(t["process"]))
        if not p:
            problems["no module"] += 1; continue
        ins, outs = split_ports(t["inputs"], p["inputs"]), split_ports(t["outputs"], p["outputs"])
        if ins is None: problems["inputs do not match the declarations"] += 1
        if outs is None: problems["outputs do not match the declarations"] += 1
        split[h] = (p, ins, outs)
        for j, port in enumerate(outs or []):
            key = p["outputs"][j]["emit"] or str(j + 1)
            for e in port:
                for x in (e["value"] if isinstance(e["value"], list) else [e["value"]]):
                    if isinstance(x, str):
                        emit_of[(h, x)] = key
    for h, (p, ins, outs) in split.items():
        proc = tasks[h]["process"]
        for j, port in enumerate(ins or []):
            rec = ports[(proc, "in", j)]
            rec["items"].append(item(port))
            rec["files"].append(sum(len(lids(e["value"])) for e in port))
            rec["metas"] += [e["value"] for e in port if e["type"] == "val" and isinstance(e["value"], dict) and not is_file(e["value"])]
            for e in port:
                for x in (e["value"] if isinstance(e["value"], list) else [e["value"]]):
                    for src_hash in lids(x):
                        if src_hash is None:
                            rec["from"][("(input file)", "")] += 1
                        elif src_hash in tasks:
                            key = (tasks[src_hash]["process"], emit_of.get((src_hash, x), "?"))
                            rec["from"][key] += 1
                            rec["from_files"][key].append(render(x))
                        else:
                            rec["from"][("(outside the run)", "")] += 1
        for j, port in enumerate(outs or []):
            if all(e["type"] == "path" and e["value"] == [] for e in port):
                continue                                # an optional output not made
            if p["outputs"][j].get("topic"):
                continue                                # versions and the like: plumbing
            rec = ports[(proc, "out", p["outputs"][j]["emit"] or str(j + 1))]
            rec["items"].append(item(port))
            rec["metas"] += [e["value"] for e in port if e["type"] == "val" and isinstance(e["value"], dict) and not is_file(e["value"])]
    return ports, problems


def summarise(rec, run):
    items, metas = rec["items"], rec["metas"]
    distinct = list(dict.fromkeys(items))
    keys = list(dict.fromkeys(k for m in metas for k in m))
    ids = [str(m.get("id")) for m in metas if "id" in m]
    if len(items) == 1 and rec["files"] and rec["files"][0] > 2:
        card = {"kind": "collected", "text": f"{rec['files'][0]} files in one item"}
    elif len(items) == 1:
        card = {"kind": "single"}
    elif len(distinct) == 1:
        card = {"kind": "value", "text": f"the same item in all {len(items)} tasks"}
    else:
        card = {"kind": "queue"}
        if ids and len(set(ids)) > 1:
            card["per"] = "meta.id"
    ex = {"kind": "collected" if card["kind"] == "collected" else "single" if len(items) == 1 else "per_item", "n": len(items),
          "items": distinct[:MAX_ITEMS] if card["kind"] != "value" else distinct[:1], "run": run}
    if card["kind"] == "collected":
        ex["n"] = rec["files"][0]
    if ids and len(ids) == len(items) and card["kind"] == "queue":
        first = {}
        for it, i in zip(items, ids):
            first.setdefault(i, it)
        ex["items"] = list(first.values())[:MAX_ITEMS]
        ex["group"] = {"key": "id", "values": list(first)[:MAX_ITEMS]}
    out = {"cardinality": card, "example": ex, "tasks": len(items)}
    if metas:
        out["meta_keys"] = keys
        if any(list(m) != keys for m in metas):
            out["meta_text"] = "keys differ between items"
    else:
        out["meta_keys"] = None
    out["from"] = [{"process": p, "emit": e, "items": n, "files": list(dict.fromkeys(rec["from_files"].get((p, e), [])))}
                   for (p, e), n in rec["from"].most_common()]
    return out


# ---- settings and the check ------------------------------------------------------------------
def settings_from_params(dims, params):
    s = {}
    for d in dims:
        v = params.get(d.get("param") or d["id"])
        if d.get("list_value"):
            s[d["id"]] = d["list_value"] in str(v).split(",") if v not in (None, "", False) else False
        elif d["kind"] == "presence":
            s[d["id"]] = "present" if v not in (None, "", False) else "absent"
        elif d["kind"] == "boolean":
            s[d["id"]] = bool(v)
        elif d["kind"] in ("enum", "ordinal"):
            s[d["id"]] = v if v is not None else ("unset" if "unset" in d.get("values", []) else d.get("default"))
        else:
            s[d["id"]] = v
    return s


def check_graph(model, dims, settings, dag, preview_dags):
    """Align the run's DAG with the previews; compare its elements with what
    the model's `when`s expect under its settings."""
    from align import align
    runs = {os.path.splitext(os.path.basename(p))[0]: p for p in glob.glob(os.path.join(preview_dags, "*.dot"))}
    runs["__run__"] = dag
    u = align(runs)
    rid = u.readable_ids()
    r = lambda x: rid.get(x, x)
    present = {r(uid) for uid, n in u.nodes.items() if "__run__" in n["observed"]}
    ends = {}
    for (a, b, l, k), obs in u.edges.items():
        if "__run__" in obs:
            i = f"{r(a)}->{r(b)}" + (f"[{l}]" if l else "") + (f"#{k}" if k else "")
            present.add(i); ends[i] = (r(a), r(b))
    elements = {x["id"]: x for x in model["nodes"] + model["edges"]}
    expected = {i for i, x in elements.items() if holds(x.get("when"), settings, dims) is not False}
    return {"run_elements": len(present), "expected": len(expected),
            "unexpected": sorted(present - expected), "missing": sorted(expected - present),
            "_ends": {i: ends[i] for i in present - expected if i in ends}}


def held_differences(model, params):
    """Args the model's matrix held in every run that this run sets
    differently: set where it was null, or null where it was set. A path set
    to another file counts as the same (the graph sees only whether it is set)."""
    ev = (model.get("generated") or {}).get("evidence") or {}
    out = []
    for f in ev.get("fixed_args", []):
        held, run = f["value"], params.get(f["param"])
        held_set = held not in ("null", "", "false")
        run_set = run not in (None, "", False)
        if held_set != run_set or (not ("." in held or "/" in str(run)) and held_set and str(run) != held):
            out.append({"param": f["param"], "held": held, "run": render(run) if run is not None else "null"})
    return out


def words(text):
    """Lower-case words, plurals folded: MAKE_TRANSCRIPTS_FASTA -> {make, transcript, fasta}."""
    return {w[:-1] if len(w) > 3 and w.endswith("s") else w for w in re.split(r"[^a-z0-9]+", text.lower()) if w}


def mentions(element_id, param):
    """Does an element's id name a param (every word of it)?"""
    return words(param) <= words(element_id)


def attribute(diff_ids, causes, ends):
    """Group the elements that differ into connected pieces, and name the held
    arg a piece mentions (its id names the param, e.g. point@start>transcript_fasta)."""
    parent = {}
    def find(x):
        while parent.setdefault(x, x) != x:
            parent[x] = parent[parent[x]]; x = parent[x]
        return x
    def union(a, b): parent[find(a)] = find(b)
    for i in diff_ids:
        find(i)
        if i in ends:
            union(i, ends[i][0]); union(i, ends[i][1])
    pieces = collections.defaultdict(list)
    for i in diff_ids:
        pieces[find(i)].append(i)
    attributed, unexplained = collections.defaultdict(list), []
    for members in pieces.values():
        names = tuple(c["param"] for c in causes if any(mentions(m, c["param"]) for m in members))
        if names:
            attributed[names] += members
        else:
            unexplained += members
    return [{"params": list(k), "elements": sorted(v)} for k, v in attributed.items()], sorted(unexplained)


def files_text(notes, cap=4):
    """'to Q input 1 from STAR_ALIGN bam (5 files: a.bam, b.bam, ...)', one
    clause per destination, at most `cap` sources named in each. The edge lies
    on a path from each source to the destination; which branch each file
    took is not recorded."""
    by_dest = collections.defaultdict(list)
    for dest, source, n, files in notes:
        if (source, n) not in [(x[0], x[1]) for x in by_dest[dest]]:
            by_dest[dest].append((source, n, files))
    out = []
    for dest, srcs in by_dest.items():
        total = sum(n for _, n, _ in srcs)
        if len(srcs) == 1:
            source, n, files = srcs[0]
            eg = f": {', '.join(files[:3])}{', ...' if len(files) > 3 else ''}" if files else ""
            out.append(f"to {dest} from {source} ({n} file{'s' if n != 1 else ''}{eg})")
        else:
            named = ", ".join(f"{src} ({n})" for src, n, _ in srcs[:cap])
            out.append(f"to {dest} from {len(srcs)} emits ({total} files): {named}"
                       + (f", +{len(srcs) - cap} more" if len(srcs) > cap else ""))
    return "; ".join(out)


def fill_chains(model, summary, settings, dims):
    """Edges between operators on the way from a producing emit to the
    process input its files reached (lineage links each input file to the
    task and emit that made it), through operators only. Lineage sees only
    process boundaries, so these edges get where their files came from and
    went, not the items as they were in between."""
    nodes = {n["id"]: n for n in model["nodes"]}
    live = [e for e in model["edges"] if holds(e.get("when"), settings, dims) is not False]
    succ, pred = collections.defaultdict(list), collections.defaultdict(list)
    for e in live:
        succ[e["from"]].append(e); pred[e["to"]].append(e)
    is_op = lambda i: nodes.get(i, {}).get("kind") != "process"
    notes = collections.defaultdict(list)
    for (q, d, j), got in summary.items():
        if d != "in":
            continue
        for f in got["from"]:
            p, emit = f["process"], f["emit"]
            if p not in nodes:
                continue
            starts = [e for e in succ[p] if re.search(rf"emit {re.escape(emit)}\b", e.get("port", "")) and is_op(e["to"])]
            ends = [e for e in pred[q] if re.search(rf"input {j + 1}\b", e.get("port", "")) and is_op(e["from"])]
            fwd, stack = set(), [e["to"] for e in starts]
            while stack:
                x = stack.pop()
                if x in fwd: continue
                fwd.add(x); stack += [e["to"] for e in succ[x] if is_op(e["to"])]
            back, stack = set(), [e["from"] for e in ends]
            while stack:
                x = stack.pop()
                if x in back: continue
                back.add(x); stack += [e["from"] for e in pred[x] if is_op(e["from"])]
            for e in live:
                if e["from"] in fwd and e["to"] in back and is_op(e["from"]) and is_op(e["to"]):
                    notes[e["id"]].append((f"{q.split(':')[-1]} input {j + 1}", f"{p.split(':')[-1]} {emit}", f["items"], f["files"]))
    n = 0
    for e in model["edges"]:
        if e["id"] in notes:
            c = e.setdefault("contents", {})
            c["files"] = files_text(notes[e["id"]])
            c.setdefault("from", {})["files"] = "harvested"
            n += 1
    return n


def overlay(model, lineage, source, dag=None, dags=None, run_name=None):
    """Lay a run (its .lineage folder) over a model, in place. Returns what
    was found: run name, tasks, the port-by-port harvest, problems, the check."""
    tasks, wf = read_lineage(lineage)
    run = run_name or (wf or {}).get("name") or "run"
    params = ((wf or {}).get("config") or {}).get("params") or {}
    meta = (wf or {}).get("metadata") or {}
    src = Source(source)
    ports, problems = harvest(tasks, src)
    summary = {k: summarise(v, run) for k, v in ports.items()}

    dims = {d["id"]: d for d in model["dimensions"]}
    settings = settings_from_params(model["dimensions"], params)
    procs_model = {n["id"] for n in model["nodes"] if n["kind"] == "process"}
    expected = {i for i in procs_model if holds(next(n for n in model["nodes"] if n["id"] == i).get("when"), settings, dims) is not False}
    ran = {t["process"] for t in tasks.values()}
    check = {"processes_expected": len(expected), "processes_ran": len(ran),
             "ran_not_expected": sorted(ran - expected), "ran_not_in_model": sorted(ran - procs_model)}
    if dag:
        from dot import parse
        wired = {n["label"] for n in parse(dag)[0].values() if n["kind"] == "process"}
        check["processes_wired"] = len(wired)
        check["expected_not_wired"] = sorted(expected - wired)
        check["wired_not_expected"] = sorted(wired - expected)
        check["wired_not_run"] = sorted(wired - ran)
        if dags:
            check["graph"] = check_graph(model, dims, settings, dag, dags)

    # name the held args behind the differences
    causes = held_differences(model, params)
    check["held_args_changed"] = causes
    diff = set(check.get("ran_not_expected", []) + check.get("expected_not_wired", []) + check.get("wired_not_expected", []))
    if "graph" in check:
        diff |= set(check["graph"]["unexpected"]) | set(check["graph"]["missing"])
    ends = {e["id"]: (e["from"], e["to"]) for e in model["edges"]}
    ends.update(check.get("graph", {}).pop("_ends", {}))
    check["explained"], check["unexplained"] = attribute(sorted(diff), causes, ends)

    # lay the harvest over the model's edges
    nodes = {n["id"]: n for n in model["nodes"]}
    filled = collections.Counter()
    for e in model["edges"]:
        port = e.get("port", "")
        got = None
        m_in = re.search(r"input (\d+)", port)
        m_out = re.search(r"emit (\S+)", port)
        if m_in and nodes.get(e["to"], {}).get("kind") == "process":
            got = summary.get((e["to"], "in", int(m_in.group(1)) - 1))
        if got is None and m_out and nodes.get(e["from"], {}).get("kind") == "process":
            got = summary.get((e["from"], "out", m_out.group(1)))
        if not got:
            continue
        c = e.setdefault("contents", {})
        c.setdefault("from", {})
        if got["meta_keys"] is not None:
            c["meta"] = {"keys": got["meta_keys"]}
            if got.get("meta_text"): c["meta"]["text"] = got["meta_text"]
            c["from"]["meta"] = "harvested"
        c["cardinality"] = got["cardinality"]; c["from"]["cardinality"] = "harvested"
        e.setdefault("examples", {})[run] = got["example"]
        filled["edges"] += 1
    filled["chains"] = fill_chains(model, summary, settings, dims)

    model.setdefault("generated", {})["captured"] = {
        "run": run, "revision": meta.get("commitId"), "release": meta.get("revision"),
        "repository": meta.get("repository"), "started": meta.get("start"),
        "settings": settings, "tasks": len(tasks), "processes": len(ran),
        "tasks_per_process": dict(collections.Counter(t["process"] for t in tasks.values()).most_common()),
        "starved": check.get("wired_not_run", []), "check": check}
    want = model.get("pipeline", {}).get("revision")
    if want and meta.get("commitId") and not meta["commitId"].startswith(want):
        check["model_revision_differs"] = {"model": want, "run": meta["commitId"]}
    return {"run": run, "tasks": tasks, "ran": ran, "summary": summary, "problems": problems,
            "check": check, "filled": filled, "settings": settings}


def report(info):
    """Print what overlay() found."""
    run, tasks, ran, summary, problems, check, filled = (info[k] for k in ("run", "tasks", "ran", "summary", "problems", "check", "filled"))
    n_in = sum(1 for k in summary if k[1] == "in"); n_out = len(summary) - n_in
    print(f"{run}: {len(tasks)} tasks in {len(ran)} processes; {n_in} input ports and {n_out} emits harvested; "
          f"{filled['edges']} process-boundary edges filled, {filled['chains']} operator edges given their files")
    if problems: print("  problems:", dict(problems))
    print(f"  processes: {check['processes_expected']} expected under the run's settings, {check['processes_ran']} ran"
          + (f", {check['processes_wired']} wired" if "processes_wired" in check else ""))
    for k in ("ran_not_expected", "ran_not_in_model", "expected_not_wired", "wired_not_expected"):
        if check.get(k): print(f"  {k.replace('_', ' ')}: {', '.join(x.split(':')[-1] for x in check[k])}")
    if check.get("wired_not_run"):
        print(f"  wired but no task ran ({len(check['wired_not_run'])}): {', '.join(x.split(':')[-1] for x in check['wired_not_run'])}")
    if "graph" in check:
        g = check["graph"]
        print(f"  graph: {g['run_elements']} elements in the run's DAG, {g['expected']} expected; "
              f"{len(g['unexpected'])} unexpected, {len(g['missing'])} missing")
    for c in check["held_args_changed"]:
        print(f"  held arg changed: --{c['param']} was {c['held']} in every preview, this run: {c['run']}")
    for x in check["explained"]:
        print(f"  {len(x['elements'])} differences explained by --{', --'.join(x['params'])}")
    if check["unexplained"]:
        print(f"  {len(check['unexplained'])} differences unexplained: {', '.join(check['unexplained'][:6])}")

    if check.get("model_revision_differs"):
        print(f"  WARNING: the model was built from {check['model_revision_differs']['model']}, "
              f"the run is {check['model_revision_differs']['run'][:10]}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("model")
    ap.add_argument("--lineage", required=True, help="the run's .lineage folder")
    ap.add_argument("--source", required=True, help="the pipeline's source at the run's revision")
    ap.add_argument("--dag", help="the run's own DAG (-with-dag), for the process and graph checks")
    ap.add_argument("--dags", help="the preview DOT files the model was built from, to align the run's DAG with")
    ap.add_argument("--run-name", help="key for the examples (default: the run's Nextflow name)")
    ap.add_argument("--report", help="write the full harvest, port by port, as JSON")
    ap.add_argument("-o", "--out", required=True)
    a = ap.parse_args()

    model = json.load(open(a.model, encoding="utf-8"))
    info = overlay(model, a.lineage, a.source, a.dag, a.dags, a.run_name)
    run, summary, problems, check = info["run"], info["summary"], info["problems"], info["check"]
    with open(a.out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(model, f, separators=(",", ":"), ensure_ascii=False); f.write("\n")
    if a.report:
        rep = {f"{p} {d} {k}": v for (p, d, k), v in sorted(summary.items(), key=lambda kv: (kv[0][0], kv[0][1], str(kv[0][2])))}
        with open(a.report, "w", encoding="utf-8", newline="\n") as f:
            json.dump({"run": run, "problems": problems, "check": check, "ports": rep}, f, indent=1, ensure_ascii=False)

    report(info)


if __name__ == "__main__":
    main()
