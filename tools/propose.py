"""Propose a pipeline's dimensions and its preview matrix from nextflow_schema.json.

    python tools/propose.py SCHEMA.json [--source DIR] [--profile-config conf/test.config] [-o OUTDIR]

--source points at the pipeline's code; --profile-config at the profile the
previews will run with, whose params become the baseline (a path the test
profile sets is "present" in the baseline, so its run unsets it).

Writes, into OUTDIR (default: the schema's folder):

  proposal.json   every param considered, with kind, values, whether it is
                  proposed as a dimension and why. Proposed ones are already
                  in channel-model dimension form. Edit `include` to confirm.
  runs.tsv        the preview matrix for tools/preview_matrix.sh: a baseline
                  with every default, then one run per non-default value of
                  each proposed dimension. Path params need a real path:
                  their rows carry a <PATH> placeholder to fill in.

Rules (from the fetchngs findings):

  - skipped: hidden params; the standard nf-core groups (institutional
    config, generic options, deprecated); output, resource and notification
    plumbing (outdir, email, max_*); required params (always set); an enum
    with a single value; numbers; free-text strings
  - enum            -> enum dimension, one run per non-default value; with no
                       default, 'unset' is added as a value and is the default
  - boolean         -> boolean dimension, one run with it flipped
  - path or a string with a file/directory format
                    -> presence dimension, one run set (or unset, if it has
                       a default)

Most params that pass these rules still only change a tool's arguments, not
the graph. With --source, each is checked against the workflow-level code
(main.nf, workflows/, subworkflows/; not modules/ or config, whose conditions change arguments and resources): a param never
tested in a condition (an if, a ternary, ==, a branch or filter closure) gets
one check run instead of one per value and is not proposed; a free-text string
that is tested (filter { x }) is proposed as set/unset. That is a hint for
choosing, not a decision: the preview matrix is what shows which params
actually branch the graph. Ordinal dimensions (stop_at) cannot be told from
the schema; change `kind` to ordinal by hand.
"""
import argparse, json, os, re, sys

SKIP_GROUPS = re.compile(r"institutional|generic|deprecated", re.I)
# Plumbing every pipeline has, never a branch of the graph.
PLUMBING = re.compile(r"^(outdir|tracedir|publish_dir_mode|email|email_on_fail|plaintext_email|monochrome_logs|"
                      r"max_cpus|max_memory|max_time|multiqc_title|multiqc_config|multiqc_logo|multiqc_methods_description)$")
PATH_FORMATS = {"file-path", "directory-path", "path", "file-path-pattern"}
# nf-core's comma-separated list: ^((a|b|c)?,?)*(?<!,)$
LIST = re.compile(r"^\^\(\(([\w|.-]+)\)\?,\?\)\*")
COND = re.compile(r"\bif\s*\(|\s\?\s|[=!]=|\.branch\b|\.filter\b|\bwhen\s*:")


def params(schema):
    """(group key, group title, name, spec, required) for every param."""
    defs = schema.get("$defs") or schema.get("definitions") or {}
    for gk, g in defs.items():
        req = set(g.get("required", []))
        for name, spec in g.get("properties", {}).items():
            yield gk, g.get("title", gk), name, spec, name in req
    for name, spec in schema.get("properties", {}).items():
        yield "", "", name, spec, name in set(schema.get("required", []))


def classify(group, title, name, spec, required):
    """(kind, values, reason): kind None means not proposed."""
    types = spec.get("type")
    types = types if isinstance(types, list) else [types]
    enum = spec.get("enum")
    if spec.get("hidden"):
        return None, None, "hidden"
    if SKIP_GROUPS.search(group) or SKIP_GROUPS.search(title):
        return None, None, f"standard nf-core group ({title or group})"
    if PLUMBING.match(name):
        return None, None, "output, resource or notification plumbing"
    if required:
        return None, None, "required: always set"
    if enum is not None:
        if len(enum) < 2:
            return None, None, "enum with one value"
        return "enum", list(enum), "enum"
    if "boolean" in types:
        return "boolean", None, "boolean"
    if spec.get("format") in PATH_FORMATS:
        return "presence", None, f"path ({spec.get('format')})"
    if "number" in types or "integer" in types:
        return None, None, "number: arguments only"
    return None, None, "free-text string: arguments only"


def conditions(source_dir):
    """Every line of workflow-level code that tests something. Only workflow
    code can change the graph: conditions inside process scripts (modules/)
    and config files change arguments and resources. nf-core's utils_*
    subworkflows are included: besides help and validation they hold helpers
    that decide what runs (nf-core/rnaseq builds its QC tool list there from
    --skip_preseq and friends)."""
    lines = []
    for root, _, files in os.walk(source_dir):
        parts = root.replace("\\", "/").split("/")
        if any(p in parts for p in ("tests", ".git", "work", "modules")):
            continue
        for f in files:
            if f.endswith(".nf"):
                for i, line in enumerate(open(os.path.join(root, f), encoding="utf-8", errors="replace"), 1):
                    code = line.split("//")[0]
                    if COND.search(code) and "?:" not in code.replace(" ", ""):
                        lines.append((os.path.relpath(os.path.join(root, f), source_dir).replace("\\", "/"), i, code.strip()))
                    elif COND.search(code):
                        # an Elvis default (x ?: y) is not a branch; keep the line only if it tests something else too
                        stripped = re.sub(r"\?\s*:", "", code)
                        if COND.search(stripped):
                            lines.append((os.path.relpath(os.path.join(root, f), source_dir).replace("\\", "/"), i, code.strip()))
    return lines


ASSIGN = re.compile(r"^\s*(?:params\.)?(\w+)\s*=\s*(.+?)\s*$")


def strip_comment(line):
    """Drop a // comment, but not // inside a quoted string (a URL)."""
    q = None
    for i, ch in enumerate(line):
        if q:
            if ch == q: q = None
        elif ch in "'\"":
            q = ch
        elif line.startswith("//", i):
            return line[:i]
    return line

def profile_params(path):
    """Params a profile config sets, read from `params { x = ... }` blocks and
    `params.x = ...` lines. Values are Groovy; quoted strings are unquoted,
    true/false become booleans, anything else is kept as text."""
    out, depth, in_params = {}, 0, False
    for line in open(path, encoding="utf-8"):
        code = strip_comment(line)
        if re.match(r"^\s*params\s*\{", code):
            in_params, depth = True, 0
        if in_params or re.match(r"^\s*params\.\w+\s*=", code):
            m = ASSIGN.match(code)
            if m and m.group(1) != "params":
                v = m.group(2).strip().rstrip(",")
                if v in ("true", "false"): v = v == "true"
                elif v in ("null", "''", '""'): v = None
                elif len(v) > 1 and v[0] == v[-1] and v[0] in "'\"": v = v[1:-1]
                out[m.group(1)] = v
        if in_params:
            depth += code.count("{") - code.count("}")
            if depth <= 0 and "}" in code:
                in_params = False
    return out


def propose(schema, source=None, profile_config=None):
    """(rows, dims, runs, conds) for a schema dict: every param with whether it
    is proposed and why, the proposed dimensions, the one-change preview runs,
    and the conditions found in the source (None without one)."""
    conds = conditions(source) if source else None
    profile = profile_params(profile_config) if profile_config else {}

    rows, dims, runs = [], [], [("baseline", "", "")]
    for group, title, name, spec, required in params(schema):
        kind, values, reason = classify(group, title, name, spec, required)
        row = {"param": name, "group": title or group, "include": kind is not None, "reason": reason}
        lst = LIST.match(spec.get("pattern") or "") if spec.get("type") == "string" else None
        if lst and not spec.get("hidden"):
            # a comma-separated list (sarek's --tools strelka,mutect2): one switch per
            # value the code tests, since `tools.split(',').contains('strelka')` asks
            # about one value, not whether the param is set
            allowed = lst.group(1).split("|")
            tested = [v for v in allowed if conds is None or any(re.search(rf"['\"]{re.escape(v)}['\"]", c) for _, _, c in conds)]
            default = str(profile.get(name, spec.get("default")) or "")
            on = set(default.split(",")) if default else set()
            row["include"] = bool(tested)
            row["reason"] = f"comma-separated list of {len(allowed)} values: one switch for each of the {len(tested)} the code tests"
            row["dimensions"] = [{"id": f"{name}:{v}", "param": name, "kind": "boolean", "list_value": v,
                                  "default": v in on, "description": f"--{name} includes {v}",
                                  "group": title or group} for v in tested]
            rows.append(row)
            dims.extend(row["dimensions"])
            for v in tested:
                if v not in on:
                    runs.append((f"{name}_{v}", f"--{name} {','.join(sorted(on | {v}))}", ""))
            continue
        check_only = False
        if conds is not None:
            word = re.compile(rf"\b(params\.)?{re.escape(name)}\b")
            hits = [f"{f}:{i}" for f, i, c in conds if word.search(c)]
            row["tested_in"] = hits[:6] + ([f"+{len(hits) - 6} more"] if len(hits) > 6 else [])
            if kind and not hits:
                # One run is enough to confirm it leaves the graph alone.
                check_only = True
                row["include"] = False
                row["reason"] += "; never tested in a condition: probably arguments only, one check run"
            elif not kind and hits and reason.startswith("free-text") and not PLUMBING.match(name):
                # A string the code tests for truth (filter { x }, if (x)) acts as set/unset.
                kind, row["include"] = "presence", True
                row["reason"] = "string tested in a condition: proposed as set/unset"
        rows.append(row)
        if not kind:
            continue
        default = spec.get("default")
        if name in profile:                     # the run's baseline is the profile's value
            default = profile[name]
            row["profile_sets"] = profile[name]
        d = {"id": name, "param": name, "kind": kind, "group": title or group}
        if kind == "enum" and default is None:
            # Not set is a state of its own (for --stop_at, the run-everything one).
            values, default = values + ["unset"], "unset"
            row["reason"] += "; no default, so 'unset' is added as a value"
        if values: d["values"] = values
        if kind == "presence":
            d["default"] = "present" if default not in (None, "") else "absent"
        elif default is not None:
            d["default"] = default
        elif kind == "boolean":
            d["default"] = False
        if spec.get("description"): d["description"] = spec["description"]
        d["source"] = "nextflow_schema.json"
        row["dimension"] = d
        if not check_only:
            dims.append(d)
        # one-at-a-time runs from the baseline
        if kind == "enum":
            others = [v for v in values if v != default]
            for v in (others[:1] if check_only else others):
                runs.append((f"{name}_{v}", f"--{name} {v}", "check: probably arguments only" if check_only else ""))
        elif kind == "boolean":
            runs.append((f"{name}_{'off' if d['default'] else 'on'}", f"--{name} {'false' if d['default'] else 'true'}",
                         "check: probably arguments only" if check_only else ""))
        elif kind == "presence":
            note = "check: probably arguments only; " if check_only else ""
            if d["default"] == "present":
                runs.append((f"{name}_unset", f"--{name} ''", note.rstrip("; ")))
            elif spec.get("format") in PATH_FORMATS:
                runs.append((f"{name}_set", f"--{name} <PATH>", note + "needs a real path"))
            else:
                runs.append((f"{name}_set", f"--{name} <VALUE>", note + "needs a value"))

    return rows, dims, runs, conds


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("schema")
    ap.add_argument("--source", help="pipeline source folder, to mark params tested in conditions")
    ap.add_argument("--profile-config", help="a profile's config (e.g. conf/test.config): its params become the baseline")
    ap.add_argument("-o", "--outdir")
    a = ap.parse_args()
    schema = json.load(open(a.schema, encoding="utf-8"))
    outdir = a.outdir or os.path.dirname(os.path.abspath(a.schema))
    rows, dims, runs, conds = propose(schema, a.source, a.profile_config)
    os.makedirs(outdir, exist_ok=True)
    with open(os.path.join(outdir, "proposal.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump({"schema": os.path.basename(a.schema), "params": rows}, f, indent=1)
    with open(os.path.join(outdir, "runs.tsv"), "w", encoding="utf-8", newline="\n") as f:
        f.write("# name\targs\t(notes)  baseline first; edit, then: bash tools/preview_matrix.sh PIPELINE runs.tsv dags -- <common args>\n")
        for n, args, note in runs:
            f.write(f"{re.sub(r'[^A-Za-z0-9_.-]', '_', n)}\t{args}" + (f"\t# {note}" if note else "") + "\n")

    inc = [r for r in rows if r["include"]]
    print(f"{len(rows)} params, {len(inc)} proposed as dimensions, {len(runs)} preview runs")
    w = max(len(r["param"]) for r in rows)
    for r in rows:
        mark = "+" if r["include"] else " "
        tested = ""
        if conds is not None:
            tested = f"  tested: {', '.join(r['tested_in'])}" if r.get("tested_in") else "  tested: never"
        print(f"  {mark} {r['param']:<{w}}  {r['reason']}{tested if r['include'] else ''}")
    print(f"wrote {os.path.join(outdir, 'proposal.json')} and runs.tsv")


if __name__ == "__main__":
    main()
