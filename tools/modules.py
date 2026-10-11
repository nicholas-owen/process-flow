"""Read a pipeline's source for what a DAG does not say: module declarations,
include aliases and process call sites.

    from modules import Source
    src = Source("path/to/pipeline")
    src.process("NFCORE_FETCHNGS:FETCHNGS:FASTQ_DOWNLOAD_PREFETCH_FASTERQDUMP_SRATOOLS:SRATOOLS_PREFETCH")
    # -> {"name": "SRATOOLS_PREFETCH", "module": "modules/nf-core/sratools/prefetch/main.nf",
    #     "inputs":  [{"shape": "[meta, id]", ...}, {"shape": "ncbi_settings", ...}, ...],
    #     "outputs": [{"shape": "[meta, ${id}]", "emit": "sra", ...}, ...],
    #     "call": ["ch_sra_ids", "ch_ncbi_settings", "ch_dbgap_key"]}

    python tools/modules.py path/to/pipeline        # summary: what parsed, what did not

Declarations become shapes in the fixtures' notation: `tuple val(meta),
path(reads)` is `[meta, reads]`, a quoted pattern keeps its pattern
(`path("*.bam")` is `*.bam`), `eval(...)` is `eval`, and a bare `path fasta`
is `fasta`. Each also keeps its kind (val, path, tuple, ...), its names, and
for outputs `emit`, `optional` and `topic`.

A DAG names a process by its call path (`...:SRATOOLS_PREFETCH`), which may be
an alias (`include { GFFREAD as GFFREAD_TRANSCRIPTS }`). The alias is resolved
from the includes of the file that defines the enclosing workflow, then from
any file. The call site (`SRATOOLS_PREFETCH ( ch_sra_ids, ch_ncbi_settings,
ch_dbgap_key )`) gives the argument for each input position; the DAG labels an
input edge with that argument when it is a plain variable.
"""
import collections, os, re, sys

SECTION = re.compile(r"^\s*(input|output|when|script|shell|exec|stub|topic)\s*:\s*$")
DECL = re.compile(r"^\s*(tuple|path|val|env|stdin|eval|each|file)\b(.*)$")
PROCESS = re.compile(r"^\s*process\s+(\w+)\s*\{", re.M)
WORKFLOW = re.compile(r"^\s*workflow\s+(\w+)\s*\{", re.M)
INCLUDE = re.compile(r"include\s*\{([^}]*)\}\s*from\s*['\"]([^'\"]+)['\"]")


def strip_comment(line):
    q = None
    for i, ch in enumerate(line):
        if q:
            if ch == q: q = None
        elif ch in "'\"":
            q = ch
        elif line.startswith("//", i):
            return line[:i]
    return line


def split_top(s, sep=","):
    """Split on sep at bracket depth 0, outside quotes."""
    out, depth, q, cur = [], 0, None, ""
    for ch in s:
        if q:
            cur += ch
            if ch == q: q = None
            continue
        if ch in "'\"":
            q = ch
        elif ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        elif ch == sep and depth == 0:
            out.append(cur.strip()); cur = ""
            continue
        cur += ch
    if cur.strip():
        out.append(cur.strip())
    return out


def _element(item):
    """One element of a declaration: val(meta) -> ('val', 'meta')."""
    m = re.match(r"(val|path|env|eval|stdin|file|each)\s*\((.*)\)\s*$", item.strip(), re.S)
    if not m:
        return None
    kind, inner = m.group(1), m.group(2)
    if kind == "eval":
        return kind, "version" if "version" in inner else "eval"
    first = split_top(inner)[0] if inner.strip() else kind
    name = first.strip()
    # "${task.process}" -> task.process; 'salmon' stays a quoted literal
    interp = re.fullmatch(r"""["']\$\{([^}]+)\}["']""", name)
    if interp:
        name = interp.group(1)
    elif kind == "val" and re.fullmatch(r"'[^']*'", name):
        pass
    else:
        name = name.strip("'\"")
    return kind, name


def parse_decl(text):
    """`tuple val(meta), path(reads), emit: x, optional: true` -> dict."""
    m = DECL.match(text)
    kind, rest = m.group(1), m.group(2).strip()
    opts, elems = {}, []
    if kind == "tuple":
        parts = split_top(rest)
        for p in parts:
            o = re.match(r"(\w+)\s*:\s*(.+)$", p)
            if o and not re.match(r"(val|path|env|eval|file)\s*\(", p):
                opts[o.group(1)] = o.group(2).strip().strip("'\"")
            else:
                e = _element(p)
                if e: elems.append(e)
        shape = "[" + ", ".join(n for _, n in elems) + "]"
    else:
        if rest.startswith("("):            # path("x"), val(y)
            e = _element(kind + rest.split(")", 1)[0] + ")")
            tail = rest.split(")", 1)[1] if ")" in rest else ""
            name = e[1] if e else kind
        else:                               # path fasta, stageAs: ...
            bits = split_top(rest)
            name = bits[0].strip().strip("'\"") if bits else kind
            tail = "," + ",".join(bits[1:]) if len(bits) > 1 else ""
        for p in split_top(tail.lstrip(",")):
            o = re.match(r"(\w+)\s*:\s*(.+)$", p)
            if o: opts[o.group(1)] = o.group(2).strip().strip("'\"")
        elems = [(kind, name)]
        shape = "eval" if kind == "eval" else name
    return {"kind": kind, "shape": shape, "names": [n for _, n in elems], "elements": [k for k, _ in elems],
            "emit": opts.get("emit"), "optional": opts.get("optional") == "true", "topic": opts.get("topic")}


def parse_process(body):
    """input and output declarations of one process body."""
    sec, buf, out = None, "", {"inputs": [], "outputs": []}

    def flush():
        nonlocal buf
        if buf.strip() and sec in ("input", "output") and DECL.match(buf):
            out["inputs" if sec == "input" else "outputs"].append(parse_decl(buf.strip()))
        buf = ""
    for raw in body.splitlines():
        line = strip_comment(raw)
        s = SECTION.match(line)
        if s:
            flush(); sec = s.group(1); continue
        if sec not in ("input", "output"):
            continue
        if DECL.match(line) and buf and buf.count("(") == buf.count(")"):
            flush()
        if line.strip():
            buf += " " + line.strip()
    flush()
    return out


def block(text, start):
    """The text of the {...} block whose opening brace is at or after start."""
    i = text.index("{", start)
    depth, q, j = 0, None, i - 1
    while j + 1 < len(text):
        j += 1
        ch = text[j]
        if q:
            if ch == q and text[j - 1] != "\\": q = None
            continue
        # comments, so an apostrophe in "the user's" does not open a string
        if text.startswith("//", j):
            nl = text.find("\n", j)
            j = (nl if nl >= 0 else len(text)) - 1
            continue
        if text.startswith("/*", j):
            end = text.find("*/", j + 2)
            j = (end + 1 if end >= 0 else len(text))
            continue
        if ch in "'\"":
            q = ch
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[i + 1:j]
    return text[i + 1:]


class Source:
    def __init__(self, root):
        self.root = os.path.abspath(root)
        self.processes = {}      # name -> {module, inputs, outputs}
        self.workflows = {}      # name -> (file, body)
        self.includes = collections.defaultdict(dict)   # file -> {alias: (name, target file)}
        for dirpath, _, files in os.walk(self.root):
            if "/tests" in dirpath.replace("\\", "/"):
                continue
            for f in files:
                if not f.endswith(".nf"):
                    continue
                path = os.path.join(dirpath, f)
                rel = os.path.relpath(path, self.root).replace("\\", "/")
                text = open(path, encoding="utf-8", errors="replace").read()
                for m in PROCESS.finditer(text):
                    p = parse_process(block(text, m.end() - 1))
                    p["module"] = rel
                    self.processes.setdefault(m.group(1), p)
                for m in WORKFLOW.finditer(text):
                    self.workflows.setdefault(m.group(1), (rel, block(text, m.end() - 1)))
                for m in INCLUDE.finditer(text):
                    target = os.path.normpath(os.path.join(os.path.dirname(rel), m.group(2))).replace("\\", "/")
                    for item in m.group(1).split(";"):
                        item = item.strip()
                        if not item:
                            continue
                        a = re.match(r"(\w+)(?:\s+as\s+(\w+))?$", item)
                        if a:
                            self.includes[rel][a.group(2) or a.group(1)] = (a.group(1), target)

    def resolve(self, path):
        """DAG process path -> (process name in its module, alias or None)."""
        alias = path[-1]
        files = []
        if len(path) > 1 and path[-2] in self.workflows:
            files.append(self.workflows[path[-2]][0])
        files += [f for f in self.includes if f not in files]
        for f in files:
            if alias in self.includes[f]:
                name = self.includes[f][alias][0]
                if name in self.processes:
                    return name, (alias if name != alias else None)
        return (alias, None) if alias in self.processes else (None, None)

    def call(self, path):
        """Arguments of the call to this process in its enclosing workflow."""
        alias = path[-1]
        wf = path[-2] if len(path) > 1 else None
        bodies = [self.workflows[wf][1]] if wf in self.workflows else []
        bodies += [b for _, b in self.workflows.values()]
        for body in bodies:
            m = re.search(rf"(?<![\w.]){alias}\s*\(", body)
            if not m:
                continue
            depth, j = 0, m.end() - 1
            for k in range(j, len(body)):
                if body[k] == "(": depth += 1
                elif body[k] == ")":
                    depth -= 1
                    if depth == 0:
                        args = body[j + 1:k]
                        args = "\n".join(strip_comment(l) for l in args.splitlines())
                        return split_top(args)
        return None

    def process(self, label):
        path = label.split(":")
        name, alias = self.resolve(path)
        if not name:
            return None
        p = dict(self.processes[name])
        p["name"] = name
        if alias:
            p["alias_of"] = name
        p["call"] = self.call(path)
        return p


if __name__ == "__main__":
    s = Source(sys.argv[1])
    n_in = sum(len(p["inputs"]) for p in s.processes.values())
    n_out = sum(len(p["outputs"]) for p in s.processes.values())
    empty = [k for k, p in s.processes.items() if not p["inputs"] and not p["outputs"]]
    print(f"{len(s.processes)} processes, {n_in} inputs, {n_out} outputs; {len(s.workflows)} workflows; "
          f"{sum(len(v) for v in s.includes.values())} includes")
    if empty:
        print("no declarations parsed:", empty[:10])
    for k in list(s.processes)[:3]:
        p = s.processes[k]
        print(f"\n{k} ({p['module']})")
        for d in p["inputs"]: print("   in ", d["shape"])
        for d in p["outputs"]: print("   out", d["shape"], "emit:", d["emit"], "topic:" if d["topic"] else "", d["topic"] or "")
