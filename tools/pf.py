"""process-flow: run a Nextflow pipeline and see what its channels carried.

    process-flow run nf-core/rnaseq -r 3.27.0 -profile test,docker --outdir results
    process-flow explore [--run-dir DIR] [--outdir results] [--source SRC] [--model MODEL] [--dag DAG]

`run` runs the pipeline as given, adding a config that switches on
Nextflow's data lineage and writes the run's DAG to
OUTDIR/pipeline_info/process-flow/dag.dot, then explores it. Needs Nextflow
25.04 or later. Nothing else about the run changes.

`explore` builds the page for a run already made (with lineage on), and
writes OUTDIR/pipeline_info/channels.html and channels.json beside it:

  1. the run: its lineage store (DIR/.lineage), latest run (and its -resume
     cache); the pipeline's source (the projectDir Nextflow pulled, or
     --source), its DAG;
  2. the model: a published one, if the pipeline ships it
     (SOURCE/assets/process-flow/channels.json, or --model), made by an
     author with the Analyser and exact for every route it covers; else one
     built here, from the run's DAG and the conditions read from the code
     (tools/graph_conditions.py), every `when` marked `source`;
  3. the run laid over it (tools/harvest.py): meta keys, items, provenance,
     what ran and what was starved, and a check of the run against the
     model.
"""
import argparse, collections, glob, json, os, re, shlex, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "viewer"))

CAPTURE = """// added by process-flow: data lineage and the run's DAG
lineage.enabled = true
dag {{
    enabled = true
    overwrite = true
    file = '{dag}'
}}
"""
PALETTE = ["#c2255c", "#1c7ed6", "#7048e8", "#f08c00", "#0ca678", "#e8590c", "#5c940d", "#ae3ec9"]


def say(*a):
    print("process-flow:", *a, flush=True)


# ---- a model from the run and the code ------------------------------------------------------
def build_model(source, dag, run_name, params, meta):
    from propose import propose
    from generate import generate
    from harvest import settings_from_params
    from conditions import Pipeline, Interp
    from graph_conditions import compute, PredicateAlgebra
    from predicates import holds, variables

    schema_path = os.path.join(source, "nextflow_schema.json")
    dims = []
    if os.path.exists(schema_path):
        _, dims, _, _ = propose(json.load(open(schema_path, encoding="utf-8")), source)
    settings = settings_from_params(dims, params)
    run = {"id": run_name, "args": "", "status": "ok", "settings": settings, "dag": os.path.abspath(dag)}
    name = meta.get("projectName") or os.path.basename(source)
    model = generate(name, dims, [run], ".", None, meta.get("revision"), meta.get("commitId"),
                     (meta.get("nextflow") or {}).get("version"), keep_unused=True, source=source)
    model.pop("_dropped", None); model.pop("_untested", None)
    D = {d["id"]: d for d in model["dimensions"]}

    pipe = Pipeline(source)
    interp = Interp(pipe.bodies, D, params, pipe.derived)
    values, how = compute(model, pipe, interp, settings, PredicateAlgebra(interp, D, settings))

    tally = collections.Counter()
    for x in model["nodes"] + model["edges"]:
        x.pop("observed_in", None)
        p = values.get(x["id"])
        if p is None:
            x.pop("when", None); x["when_from"] = "unknown"; tally["not read"] += 1
            continue
        if p.pred is not None and holds(p.pred, settings, D) is False:
            # it is in this run's DAG, so it exists under this run's settings
            x.pop("when", None); x["when_from"] = "unknown"; tally["contradicted by the run"] += 1
            continue
        if p.pred is None: x.pop("when", None)
        else: x["when"] = p.pred
        x["when_from"] = "source"
        tally["read, some settings undecided" if p.unk else "read"] += 1
        if p.unk:
            x["notes"] = ((x.get("notes") or "") + " Read from the code; under some settings it could not be decided, "
                          "and is shown as present there.").strip()

    # keep the dimensions some condition uses; the route is the choice that
    # the most processes depend on
    used = set()
    for x in model["nodes"] + model["edges"]:
        variables(x.get("when"), used)
    model["dimensions"] = [d for d in model["dimensions"] if d["id"] in used]
    counts = collections.Counter(k for n in model["nodes"] if n["kind"] == "process"
                                 for k in variables(n.get("when")) if D[k]["kind"] == "enum")
    model.pop("routes", None)
    if counts:
        route = counts.most_common(1)[0][0]
        vals = [v for v in D[route].get("values", []) if v != "unset"]
        model["routes"] = {"dimension": route, "colours": {v: PALETTE[i % len(PALETTE)] for i, v in enumerate(vals)}}
    model.pop("runs", None)               # no preview matrix behind it: the run is recorded by the overlay
    model["generated"]["tool"] = "process-flow explore: one run's DAG, conditions read from the code"
    model["generated"]["sources"] = [os.path.basename(dag)]
    if meta.get("repository"): model["pipeline"]["repository"] = meta["repository"]
    return model, tally


# ---- explore -----------------------------------------------------------------------------------
def explore(run_dir=".", outdir=None, source=None, model_path=None, dag=None, out_html=None, logo=None):
    from harvest import read_lineage, overlay, report
    from build import page, validate

    lineage = os.path.join(run_dir, ".lineage")
    if not os.path.isdir(lineage):
        sys.exit(f"process-flow: no lineage store at {lineage}: run the pipeline with `process-flow run`, "
                 "or with `lineage.enabled = true` in a config")
    tasks, wf = read_lineage(lineage)
    if not wf:
        sys.exit(f"process-flow: {lineage} has no workflow run")
    params = (wf.get("config") or {}).get("params") or {}
    meta = wf.get("metadata") or {}
    run_name = meta.get("runName") or wf.get("name") or "run"
    if not outdir:
        outdir = meta.get("outputDir") or params.get("outdir") or "results"
        if not os.path.isabs(outdir) and not os.path.isdir(outdir):
            outdir = os.path.join(run_dir, outdir)
    # the params as the pipeline used them: nf-core dumps them during
    # initialisation, after main.nf has filled genome attributes in
    # (`params.fasta = getGenomeAttribute('fasta')`); the lineage has them as
    # configured, before that
    dumps = sorted(glob.glob(os.path.join(outdir, "pipeline_info", "params_*.json")), key=os.path.getmtime)
    if dumps:
        try:
            effective = json.load(open(dumps[-1], encoding="utf-8"))
            params = dict(params, **{k: v for k, v in effective.items() if v is not None or k not in params})
            say(f"params as the run used them: {os.path.basename(dumps[-1])}")
        except (ValueError, OSError):
            pass
    source = source or meta.get("projectDir")
    if not source or not os.path.isdir(source):
        sys.exit(f"process-flow: the pipeline's source is not at {source!r}; give it with --source")
    dag = dag or os.path.join(outdir, "pipeline_info", "process-flow", "dag.dot")
    if not os.path.exists(dag):
        sys.exit(f"process-flow: no DAG at {dag}; give it with --dag")
    say(f"run {run_name}: {meta.get('projectName', '?')} {meta.get('revision', '')} "
        f"({(meta.get('commitId') or '')[:10]}), {len(tasks)} tasks")

    published = model_path or os.path.join(source, "assets", "process-flow", "channels.json")
    if os.path.exists(published):
        model = json.load(open(published, encoding="utf-8"))
        want = (model.get("pipeline") or {}).get("revision") or ""
        say(f"using the published model {published}")
        if want and meta.get("commitId") and not meta["commitId"].startswith(want):
            say(f"WARNING: it was built for {want[:10]}, this run is {meta['commitId'][:10]}: "
                "where they differ, the check below says so")
    else:
        say("no published model: building one from the run's DAG and the code")
        model, tally = build_model(source, dag, run_name, params, meta)
        say("conditions: " + ", ".join(f"{v} {k}" for k, v in tally.most_common()))

    info = overlay(model, lineage, source, dag, None, run_name)
    report(info)

    errs = validate(model)
    if errs:
        say(f"WARNING: the model has {len(errs)} schema errors, e.g. {errs[0]}")
    out_html = out_html or os.path.join(outdir, "pipeline_info", "channels.html")
    os.makedirs(os.path.dirname(os.path.abspath(out_html)), exist_ok=True)
    with open(out_html, "w", encoding="utf-8", newline="\n") as f:
        f.write(page(model, logo))
    with open(os.path.splitext(out_html)[0] + ".json", "w", encoding="utf-8", newline="\n") as f:
        json.dump(model, f, separators=(",", ":"), ensure_ascii=False); f.write("\n")
    say(f"wrote {out_html}")
    return out_html


# ---- run -------------------------------------------------------------------------------------------
def outdir_of(args):
    for i, a in enumerate(args):
        if a in ("--outdir", "--outdir=") and i + 1 < len(args):
            return args[i + 1]
        if a.startswith("--outdir="):
            return a.split("=", 1)[1]
    return None


def run(args):
    outdir = outdir_of(args)
    if not outdir:
        sys.exit("process-flow: give --outdir, so the page has somewhere to go")
    os.makedirs(".process-flow", exist_ok=True)
    cfg = os.path.join(".process-flow", "capture.config")
    dag = os.path.join(outdir, "pipeline_info", "process-flow", "dag.dot")
    with open(cfg, "w", encoding="utf-8", newline="\n") as f:
        f.write(CAPTURE.format(dag=os.path.abspath(dag).replace("\\", "/")))
    cmd = ["nextflow", "run", *args, "-c", cfg]
    say("running: " + " ".join(shlex.quote(c) for c in cmd))
    code = subprocess.call(cmd)
    if code != 0:
        sys.exit(f"process-flow: nextflow exited with {code}; nothing to explore. "
                 "Fix the run and rerun with -resume: cached tasks still count.")
    return explore(".", outdir)


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "run":
        run(sys.argv[2:]); return
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0], usage=__doc__.split("\n\n")[1])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("run", help="run a pipeline (everything after `run` goes to nextflow run), then explore it")
    e = sub.add_parser("explore", help="build the page for a run already made")
    e.add_argument("--run-dir", default=".", help="where the run was launched (holds .lineage)")
    e.add_argument("--outdir", help="the run's --outdir (default: from the run)")
    e.add_argument("--source", help="the pipeline's source (default: where Nextflow pulled it)")
    e.add_argument("--model", help="a published model to use instead of the pipeline's own")
    e.add_argument("--dag", help="the run's DAG (default: OUTDIR/pipeline_info/process-flow/dag.dot)")
    e.add_argument("-o", "--out", help="the page (default: OUTDIR/pipeline_info/channels.html)")
    e.add_argument("--logo", help="the pipeline's logo, shown top right")
    a = ap.parse_args()
    if a.cmd == "explore":
        explore(a.run_dir, a.outdir, a.source, a.model, a.dag, a.out, a.logo)


if __name__ == "__main__":
    main()
