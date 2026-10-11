"""Generate a channel model from a pipeline's preview DAGs, with no annotations.

    python tools/generate.py --name nf-core/fetchngs --dims proposal.json \\
        --runs dags/runs.tsv --dags dags [--route download_method] -o model.json

    python tools/generate.py --from-model fixtures/rnaseq-flow.json -o draft.json

The floor the plan promises: for any pipeline, a filterable, route-coloured DAG.

  1. align the DAGs into one union graph (tools/align.py)
  2. infer a `when` for every node and edge from the runs it was seen in
     (tools/infer.py)
  3. subworkflow paths from process names, the prefix every process shares,
     an enclosing path for every other node from its nearest processes
  4. lanes: operators whose every downstream labelled channel is versions or
     MultiQC plumbing (ch_versions, ch_multiqc_files) form a lane, folded by
     default onto the node where it leaves for a process
  5. the route dimension: --route, or the enum dimension that the most
     process predicates name
  6. write a schema 0.1 model: channel contents empty, `when` marked as
     coming from the previews

Inputs: dimensions from tools/propose.py's proposal.json (those with
include: true), runs from tools/preview_matrix.sh's runs.tsv (name, status,
args), each run's settings worked out from its args over the dimension
defaults. --from-model takes dimensions and runs (settings and DAG paths)
from an existing model instead, and nothing else: that is how the generator
is tested against the hand-built fixtures.
"""
import argparse, collections, datetime, json, os, re, shlex, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from align import align
from infer import infer
from predicates import variables, holds

LANES = [("versions", re.compile(r"(^|_)versions?$", re.I), "software versions"),
         ("multiqc", re.compile(r"multiqc_files|_mqc$", re.I), "files collected for MultiQC")]
# Inputs that are scripts, templates or images staged into a task: a lane of
# their own, hidden by default (rnaseq-flow's r_script, qmd_template, logo).
ASSETS = re.compile(r"script|template|logo|\.(svg|png|qmd|rmd|r|py|sh)$", re.I)


def resolve(path, base):
    for b in (base, ROOT, os.path.dirname(ROOT)):
        p = os.path.join(b, path)
        if os.path.exists(p):
            return p
    raise FileNotFoundError(path)


# ---- inputs ------------------------------------------------------------------
def dims_from_proposal(path):
    rows = json.load(open(path, encoding="utf-8"))["params"]
    return [d for r in rows if r.get("include") for d in (r.get("dimensions") or [r.get("dimension")]) if d]


def settings_from_args(args, dims):
    """A run's settings: every dimension's default, overridden by --param value."""
    s = {}
    for d in dims:
        dv = d.get("default")
        if d["kind"] == "boolean":
            dv = bool(dv)
        elif d["kind"] == "presence":
            dv = dv or "absent"
        s[d["id"]] = dv
    toks = shlex.split(args or "")
    lists = collections.defaultdict(list)          # list param -> its per-value switches
    for d in dims:
        if d.get("list_value"):
            lists[d["param"]].append(d)
    byparam = {d.get("param") or d["id"]: d for d in dims if not d.get("list_value")}
    i = 0
    while i < len(toks):
        t = toks[i]
        if t.startswith("--") and t[2:] in lists:
            v = toks[i + 1] if i + 1 < len(toks) and not toks[i + 1].startswith("--") else ""
            given = set(v.split(",")) if v not in ("", "null", "false") else set()
            for d in lists[t[2:]]:
                s[d["id"]] = d["list_value"] in given
            i += 2 if v else 1
        elif t.startswith("--") and t[2:] in byparam:
            d = byparam[t[2:]]
            v = toks[i + 1] if i + 1 < len(toks) and not toks[i + 1].startswith("--") else "true"
            i += 1 if v == "true" and (i + 1 >= len(toks) or toks[i + 1].startswith("--")) else 2
            if d["kind"] == "boolean":
                s[d["id"]] = v.lower() not in ("false", "0", "")
            elif d["kind"] == "presence":
                s[d["id"]] = "absent" if v in ("", "false", "null") else "present"
            elif v in ("", "null") and "unset" in d.get("values", []):
                s[d["id"]] = "unset"
            else:
                s[d["id"]] = v
        else:
            i += 1
    return s


def runs_from_tsv(path, dags_dir, dims):
    """One run per name: a later line (a rerun) replaces an earlier one."""
    runs = {}
    for line in open(path, encoding="utf-8"):
        if not line.strip() or line.startswith("#"):
            continue
        cols = line.rstrip("\n").split("\t")
        name = cols[0]
        status = cols[1] if len(cols) > 1 and cols[1] in ("ok", "FAILED") else "ok"
        args = cols[2] if len(cols) > 2 and cols[1] in ("ok", "FAILED") else (cols[1] if len(cols) > 1 else "")
        runs[name] = {"id": name, "args": args, "status": "ok" if status == "ok" else "failed",
                      "settings": settings_from_args(args, dims), "dag": os.path.join(dags_dir, f"{name}.dot")}
    return list(runs.values())


LOG_RUN = re.compile(r"\* (?:PREVIEW \* )?(\S+) \[[^\]]*\] - revision: ([0-9a-f]+)(?: \[([^\]]+)\])?")
LOG_NF = re.compile(r"N E X T F L O W\s+~\s+version (\S+)")


def stamp_from_logs(runs, base_dir="."):
    """Repository, revision, release and Nextflow version from the runs'
    Nextflow logs (beside each DOT file), when every log that names them
    agrees. Nextflow prints the revision abbreviated to 10 characters."""
    found = collections.defaultdict(set)
    for r in runs:
        log = os.path.splitext(resolve(r["dag"], base_dir))[0] + ".log"
        if not os.path.exists(log):
            continue
        with open(log, encoding="utf-8", errors="replace") as f:
            head = f.read(4000)
        m = LOG_RUN.search(head)
        if m:
            found["repository"].add(m.group(1)); found["revision"].add(m.group(2))
            if m.group(3): found["version"].add(m.group(3))
        m = LOG_NF.search(head)
        if m:
            found["nextflow_version"].add(m.group(1))
    return {k: next(iter(v)) for k, v in found.items() if len(v) == 1}


# ---- generation ----------------------------------------------------------------
def generate(name, dims, runs, base_dir, route=None, version=None, revision=None, nextflow_version=None, keep_unused=False, source=None):
    D = {d["id"]: d for d in dims}
    ok_runs = [r for r in runs if r["status"] == "ok"]
    settings = {r["id"]: r["settings"] for r in ok_runs}
    u = align({r["id"]: resolve(r["dag"], base_dir) for r in ok_runs})
    rid = u.readable_ids()
    rid_of = lambda x: rid.get(x, x)

    # paths and the shared prefix
    proc_paths = {uid: n["label"].split(":") for uid, n in u.nodes.items() if n["kind"] == "process"}
    groups = [p[:-1] for p in proc_paths.values()]
    prefix = []
    if groups:
        for i in range(min(len(g) for g in groups)):
            if len({g[i] for g in groups}) == 1:
                prefix.append(groups[0][i])
            else:
                break

    def near_procs(uid, direction):
        adj = u.preds if direction == "up" else u.succs
        seen, stack, out = {uid}, [uid], []
        while stack:
            cur = stack.pop()
            for nxt, _ in adj[cur]:
                if u.nodes[nxt]["kind"] == "process":
                    out.append(nxt)
                elif nxt not in seen:
                    seen.add(nxt); stack.append(nxt)
        return out

    def enclosing(uid):
        """The group most of a node's nearest processes sit in."""
        ps = near_procs(uid, "up") + near_procs(uid, "down")
        if not ps:
            return prefix or None
        c = collections.Counter(tuple(proc_paths[p][:-1]) for p in ps)
        return list(c.most_common(1)[0][0]) or prefix or None

    # lanes: every labelled channel an operator eventually feeds is plumbing
    def down_labels(uid):
        """Labels of the first labelled channels reached downstream, through
        operators only."""
        seen, stack, out = {uid}, [uid], set()
        while stack:
            cur = stack.pop()
            for nxt, l in u.succs[cur]:
                if l:
                    out.add(l)
                elif u.nodes[nxt]["kind"] != "process" and nxt not in seen:
                    seen.add(nxt); stack.append(nxt)
        return out

    def lane_of(uid):
        if u.nodes[uid]["kind"] == "process":
            return "main"
        if u.nodes[uid]["kind"] == "point" and not u.preds[uid]:
            out = [l for _, l in u.succs[uid]]
            if out and all(l and ASSETS.search(l) for l in out):
                return "assets"
        labels = down_labels(uid)
        if not labels:
            return "main"
        for lid, rx, _ in LANES:
            if all(rx.search(l) for l in labels):
                return lid
        return "main"

    lane = {uid: lane_of(uid) for uid in u.nodes}

    # inferred predicates
    # Inferred once per distinct set of runs: elements on the same stretch of
    # a route share theirs (nf-core/rnaseq: 2,289 elements, far fewer sets).
    memo = {}

    def pred_for(observed):
        key = frozenset(observed)
        if key not in memo:
            memo[key] = infer(set(observed), settings, D)[0]
        return memo[key]

    # Contents, layer 1 (Phase 3): with the pipeline's source, each process
    # gets its module, and each edge at a process boundary its port and the
    # shape the module declares there (tools/modules.py, tools/ports.py).
    proc_info, edge_port = {}, {}
    if source:
        from modules import Source
        from ports import assign
        src = Source(source)
        for uid, path in proc_paths.items():
            info = src.process(":".join(path))
            if not info:
                continue
            proc_info[uid] = info
            info["alias"] = path[-1]
            ins = [(key, u.nodes[key[0]]["type"], key[2], set(u.edges[key])) for key in u.edges if key[1] == uid]
            outs = [(key, u.nodes[key[1]]["type"], key[2], set(u.edges[key])) for key in u.edges if key[0] == uid]
            # the workflows from the one calling the process up to the top
            bodies = [(w, src.workflows[w][1]) for w in reversed(path[:-1]) if w in src.workflows]
            a_in, a_out = assign(info, ins, outs, bodies)
            for key, (i, decl, ev) in a_in.items():
                edge_port.setdefault(key, {})["in"] = (i, decl, ev)
            for key, (j, decl, ev) in a_out.items():
                edge_port.setdefault(key, {})["out"] = (j, decl, ev)

    nodes = []
    for uid, n in u.nodes.items():
        kind = n["kind"]
        if kind == "operator":
            kind = "source" if not u.preds[uid] else "operator"
        elif kind == "point":
            kind = "input" if not u.preds[uid] else "output"
        rec = {"id": rid_of(uid), "kind": kind}
        if kind == "process":
            rec["label"] = proc_paths[uid][-1]
            rec["path"] = proc_paths[uid]
            if uid in proc_info:
                rec["module"] = proc_info[uid]["module"]
                rec["source"] = proc_info[uid]["module"]
                if proc_info[uid].get("alias_of"):
                    rec["alias_of"] = proc_info[uid]["alias_of"]
        else:
            if kind in ("operator", "source"):
                t = n["type"][3:]
                rec["label"] = t
                rec["operator"] = {"type": t}
            else:
                lab = sorted({l for _, l in (u.succs[uid] if kind == "input" else u.preds[uid]) if l})
                rec["label"] = lab[0] if lab else kind
            p = enclosing(uid)
            if p:
                rec["path"] = p
        w = pred_for(n["observed"])
        if w:
            rec["when"] = w
        rec["when_from"] = "preview"
        rec["observed_in"] = sorted(n["observed"])
        rec["lane"] = lane[uid]
        rec["category"] = "input" if kind in ("input", "source") and not u.preds[uid] and kind == "input" else "shared"
        nodes.append(rec)

    edges = []
    for (a, b, l, k), obs in u.edges.items():
        e = {"id": f"{rid_of(a)}->{rid_of(b)}" + (f"[{l}]" if l else "") + (f"#{k}" if k else ""),
             "from": rid_of(a), "to": rid_of(b)}
        if l:
            e["name"] = l
        pt = edge_port.get((a, b, l, k))
        if pt:
            # the producer's emit names the files (*.bam); the consumer's input
            # is the fallback when the edge leaves an operator
            port, decl = [], None
            if "out" in pt:
                port.append(f"emit {pt['out'][1]['emit'] or pt['out'][0] + 1}")
                decl = pt["out"][1]
            if "in" in pt:
                port.append(f"input {pt['in'][0] + 1}")
                # an emit named by an unresolved expression ([meta, ${id}]) reads
                # worse than the consumer's names ([meta, sra])
                if decl is None or "${" in decl["shape"]:
                    decl = pt["in"][1]
            e["port"] = " -> ".join(port)
            c = {"shape": decl["shape"], "from": {"shape": "declared"}}
            if decl["kind"] == "tuple" and decl["names"] and decl["names"][0].startswith("meta"):
                c["meta"] = {"text": "a meta map; its keys are not declared"}
                c["from"]["meta"] = "declared"
            elif decl["kind"] == "path":
                c["meta"] = None
                c["from"]["meta"] = "declared"
            e["contents"] = c
            if not e.get("name") and "out" in pt and pt["out"][1]["emit"]:
                e["name"] = pt["out"][1]["emit"]
        w = pred_for(obs)
        if w:
            e["when"] = w
        e["when_from"] = "preview"
        e["observed_in"] = sorted(obs)
        # an edge is in a lane if either end is (processes feeding a lane, the lane leaving)
        la, lb = lane[a], lane[b]
        e["lane"] = la if la != "main" else (lb if u.nodes[a]["kind"] == "process" and lb != "assets" else "main")
        edges.append(e)

    # lanes: hub is where the lane leaves for a non-lane node; target the first process after it
    lanes = [{"id": "main", "label": "data flow", "mode": "expanded"}]
    if any(v == "assets" for v in lane.values()):
        lanes.append({"id": "assets", "label": "scripts and templates staged into tasks", "mode": "hidden", "detected": True})
    for lid, _, label in LANES:
        members = [uid for uid in u.nodes if lane[uid] == lid]
        if not members:
            continue
        exits = [uid for uid in members if any(lane[s] != lid for s, _ in u.succs[uid])]
        hub = max(exits or members, key=lambda x: (len(u.preds[x]), rid_of(x)))
        targets = near_procs(hub, "down")
        rec = {"id": lid, "label": label, "hub": rid_of(hub), "mode": "folded", "detected": True}
        if targets:
            rec["target"] = sorted(targets)[0]
        lanes.append(rec)

    # Contents, layer 1 continued: operators that do not change a channel's
    # shape pass it through, so a shape declared at a process boundary fills
    # the chain beside it. Forwards (out-edge from an op whose in-edges all
    # agree) and backwards (in-edges of an op whose out-edges agree), to a
    # fixed point. Marked `inferred`, not `declared`.
    if source:
        KEEP = {"filter", "unique", "distinct", "first", "last", "take", "until", "randomSample",
                "mix", "concat", "ifEmpty", "view", "dump", "set", "tap"}
        by_from, by_to = collections.defaultdict(list), collections.defaultdict(list)
        id_of = {}
        for rec in nodes:
            id_of[rec["id"]] = rec
        for e in edges:
            by_from[e["from"]].append(e); by_to[e["to"]].append(e)
        shape = lambda e: (e.get("contents") or {}).get("shape")
        changed = True
        while changed:
            changed = False
            for rec in nodes:
                if rec["kind"] != "operator" or rec.get("operator", {}).get("type") not in KEEP:
                    continue
                ins, outs = by_to[rec["id"]], by_from[rec["id"]]
                known_in = {shape(e) for e in ins if shape(e)}
                known_out = {shape(e) for e in outs if shape(e)}
                # mix and concat need every input known and alike; the rest have one input
                if len(known_in) == 1 and all(shape(e) for e in ins):
                    s = known_in.pop()
                    for e in outs:
                        if not shape(e):
                            e["contents"] = {"shape": s, "from": {"shape": "inferred"}}; changed = True
                elif len(known_out) == 1 and len(ins) == 1 and not shape(ins[0]):
                    ins[0]["contents"] = {"shape": known_out.pop(), "from": {"shape": "inferred"}}; changed = True

    # route dimension: given, or the enum that splits processes into the most
    # distinct groups (aligner: star, hisat2, salmon, kallisto, star|hisat2,
    # salmon|kallisto) rather than the one named most often (workflow, which
    # every process mentions but which only makes three groups)
    if route is None:
        diversity = {}
        for d, dim in D.items():
            if dim["kind"] != "enum" or len(dim.get("values", [])) < 3:
                continue
            seen = set()
            for rec in nodes:
                if rec["kind"] == "process" and rec.get("when") and d in variables(rec["when"]):
                    allowed = frozenset(v for v in dim["values"] if holds(rec["when"], {d: v}, D) is not False)
                    if 0 < len(allowed) < len(dim["values"]):
                        seen.add(allowed)
            if seen:
                diversity[d] = len(seen)
        route = max(sorted(diversity), key=lambda d: diversity[d]) if diversity else None
    # A dimension no predicate uses, and which the matrix has shown changes
    # nothing (some pair of runs differs in it alone and their graphs are the
    # same), changes nothing a preview can see: an argument, or a filter that
    # acts at run time. It would only clutter the viewer's filters, so it is
    # dropped unless kept. One no predicate uses but never varied alone is
    # kept: the matrix may simply have confounded it with another (the
    # prototype's rnaseq-flow runs always switched --isoform_switch on with
    # Salmon).
    used = set()
    for rec in nodes + edges:
        used |= variables(rec.get("when"))
    for d in dims:
        if d.get("implies") and d["id"] in used:
            used |= variables(d["implies"])
    graph_of = collections.defaultdict(set)
    for uid, n in u.nodes.items():
        for r in n["observed"]:
            graph_of[r].add(uid)
    for key, obs in u.edges.items():
        for r in obs:
            graph_of[r].add(key)
    tested = collections.defaultdict(list)          # dimension -> [graphs equal?] over pairs differing in it alone
    ids = sorted(settings)
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            diff = [k for k in D if settings[a].get(k) != settings[b].get(k)]
            if len(diff) == 1:
                tested[diff[0]].append(graph_of[a] == graph_of[b])
    dropped = [d["id"] for d in dims if d["id"] not in used and d["id"] != route
               and tested[d["id"]] and all(tested[d["id"]])]
    untested = [d["id"] for d in dims if d["id"] not in used and d["id"] not in dropped and d["id"] != route]
    if not keep_unused:
        dims = [d for d in dims if d["id"] not in dropped]
    palette_cycle = ["#c2255c", "#1c7ed6", "#7048e8", "#f08c00", "#0ca678", "#e8590c", "#5c940d", "#ae3ec9"]
    model = {
        "schema_version": "0.1",
        "pipeline": {"name": name, "revision": revision or "unrecorded", "prefix": prefix},
        "generated": {"tool": "process-flow tools/generate.py (no annotations)", "date": datetime.date.today().isoformat(),
                      "sources": sorted({r["dag"] for r in ok_runs})},
        "dimensions": dims,
    }
    logged = stamp_from_logs(ok_runs, base_dir)
    if not revision and logged.get("revision"): model["pipeline"]["revision"] = logged["revision"]
    if logged.get("repository"): model["pipeline"]["repository"] = logged["repository"]
    version = version or logged.get("version")
    nextflow_version = nextflow_version or logged.get("nextflow_version")
    if version: model["pipeline"]["version"] = version
    if nextflow_version: model["pipeline"]["nextflow_version"] = nextflow_version
    if route:
        vals = [v for v in D[route].get("values", []) if v != "unset"]
        model["routes"] = {"dimension": route, "colours": {v: palette_cycle[i % len(palette_cycle)] for i, v in enumerate(vals)}}
    model["palette"] = {"shared": "#495057", "input": "#9aa3ad"}
    model["lanes"] = lanes
    model["runs"] = runs
    model["nodes"] = nodes
    model["edges"] = edges
    model["_dropped"] = dropped if not keep_unused else []
    model["_untested"] = untested
    return model


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--from-model", help="take dimensions and runs from an existing model")
    ap.add_argument("--name")
    ap.add_argument("--dims", help="tools/propose.py proposal.json")
    ap.add_argument("--runs", help="tools/preview_matrix.sh runs.tsv")
    ap.add_argument("--dags", help="folder with the DOT files (default: beside runs.tsv)")
    ap.add_argument("--route", help="dimension drawn as metro lines")
    ap.add_argument("--version"); ap.add_argument("--revision"); ap.add_argument("--nextflow-version")
    ap.add_argument("--keep-unused", action="store_true", help="keep dimensions no predicate uses")
    ap.add_argument("--source", help="the pipeline's source, for modules, ports and declared shapes")
    ap.add_argument("-o", "--out", required=True)
    a = ap.parse_args()
    if a.from_model:
        src = json.load(open(a.from_model, encoding="utf-8"))
        dims, runs = src["dimensions"], src["runs"]
        name = a.name or src["pipeline"]["name"] + " (generated)"
        base = os.path.dirname(os.path.abspath(a.from_model))
        version, revision = a.version or src["pipeline"].get("version"), a.revision or src["pipeline"].get("revision")
        nfv = a.nextflow_version or src["pipeline"].get("nextflow_version")
    else:
        if not (a.name and a.dims and a.runs):
            ap.error("--name, --dims and --runs are needed without --from-model")
        dims = dims_from_proposal(a.dims)
        dags = a.dags or os.path.dirname(os.path.abspath(a.runs))
        runs = runs_from_tsv(a.runs, dags, dims)
        name, base = a.name, os.getcwd()
        version, revision, nfv = a.version, a.revision, a.nextflow_version
    model = generate(name, dims, runs, base, a.route, version, revision, nfv, a.keep_unused, a.source)
    dropped, untested = model.pop("_dropped"), model.pop("_untested")
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(model, f, indent=1, ensure_ascii=False)
        f.write("\n")
    kinds = collections.Counter(n["kind"] for n in model["nodes"])
    lanes = {l["id"]: sum(n["lane"] == l["id"] for n in model["nodes"]) for l in model["lanes"]}
    print(f"wrote {a.out}: {len(model['nodes'])} nodes {dict(kinds)}, {len(model['edges'])} edges; "
          f"route: {model.get('routes', {}).get('dimension')}; prefix: {':'.join(model['pipeline']['prefix']) or '-'}; lanes: {lanes}")
    if dropped:
        print(f"dimensions dropped, shown by the matrix to change nothing a preview shows: {', '.join(dropped)}")
    if untested:
        print(f"kept, unused by any predicate but never varied alone (possibly confounded; the matrix should test them): {', '.join(untested)}")


if __name__ == "__main__":
    main()
