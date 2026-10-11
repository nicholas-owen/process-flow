"""Which input does a DAG edge fill, and which emit does it carry?

    from ports import assign
    ins, outs = assign(proc, in_edges, out_edges, workflow_body)

A DAG edge into a process does not say which input it is, nor an edge out
which emit; the order of edges in the DOT file follows when channels were
created, not the declaration order. The evidence used, strongest first:

Inputs (proc["inputs"], with proc["call"] the call's arguments):
  1. the edge label is the call's argument at position i (`ch_sra_ids`)
  2. the edge label is input i's own name: Nextflow labels an edge with the
     input's name when the argument is not a channel variable (`certificate`,
     `user`, `fields`)
  3. the argument at i ends in an operator (`ch_x.filter { ... }`) whose type
     is the edge's source type
  4. the one input left, for the one edge left

Outputs (proc["outputs"]), from how the workflow body uses `ALIAS.out.EMIT`:
  1. the edge label is the emit's name, or a variable assigned from it
     (`ch_ncbi_settings = X.out.ncbi_settings`), or a workflow emit
     (`reads = X.out.reads`)
  2. the edge goes to an operator the code applies to that emit
     (`X.out.fastq.map`, `.mix(X.out.fastq)`) or to a process called with it
  3. an edge to a bare point (an output nothing reads) takes an emit the
     workflow never uses: `topic:` emits (versions) first, in order

in_edges / out_edges: lists of (edge key, other end's type, label, set of runs
it was seen in), the type
as tools/align.py writes it (a process name, `op:map`, `point`). Returns two
dicts edge key -> (index, declaration, evidence); edges with no evidence are
left out.
"""
import re


def _name(arg):
    return arg.strip() if re.fullmatch(r"[\w.]+", arg.strip() or "-") else None


def _last_op(arg):
    """`ch_x.map { ... }.filter { ... }` -> 'filter'; None if the argument ends
    in no operator."""
    ops = re.findall(r"\.(\w+)\s*(?:\(|\{)", arg)
    return ops[-1] if ops else None


def _uses(body, alias):
    """emit -> list of (kind, value): ('var', name) for an assignment,
    ('op', type) for an operator applied to it or taking it as an argument,
    ('call', process) for a process called with it."""
    uses = {}
    if not body:
        return uses
    # The process itself may be held in a variable, so one of several can be
    # used alike (nf-core/rnaseq's ALIGN_STAR: `ch_star_out = STAR_ALIGN`, then
    # `ch_star_out.out.fastq`).
    holders = [alias] + re.findall(rf"(?m)^\s*(\w+)\s*=\s*{alias}\s*(?://.*)?$", body)
    who = "|".join(map(re.escape, holders))
    for m in re.finditer(rf"(?<![\w.])(?:{who})\s*\.\s*out\s*\.\s*(\w+)", body):
        emit = m.group(1)
        u = uses.setdefault(emit, [])
        before = body[:m.start()]
        after = body[m.end():]
        line_start = before.rfind("\n") + 1
        lhs = re.match(r"\s*(\w+)\s*=\s*$", before[line_start:])
        if lhs:
            u.append(("var", lhs.group(1)))
        op = re.match(r"\s*\.\s*(\w+)\s*[({]", after)
        if op:
            u.append(("op", op.group(1)))
        inside = re.search(r"\.\s*(\w+)\s*\(\s*$", before[-200:])
        if inside:
            u.append(("op", inside.group(1)))
        call = re.search(r"(?<![\w.])([A-Z][A-Z0-9_]+)\s*\((?:[^()]|\([^()]*\))*$", before[-400:])
        if call and call.group(1) != alias:
            u.append(("call", call.group(1)))
    # Plain reassignments carry the emit along: `ch_y = ch_x` and, in a
    # workflow's emit block, `sample_mappings = ch_sample_mappings_yml`. The
    # DAG labels the edge with the last name in such a chain.
    assigns = re.findall(r"(?m)^\s*(\w+)\s*=\s*(\w+)\s*(?://.*)?$", body)
    changed = True
    while changed:
        changed = False
        for emit, us in uses.items():
            names = {v for k, v in us if k == "var"}
            for lhs, rhs in assigns:
                if rhs in names and ("var", lhs) not in us:
                    us.append(("var", lhs)); changed = True
    return uses


def _emit_block(body):
    """A workflow's emit block: workflow emit -> expression."""
    m = re.search(r"(?m)^\s*emit\s*:\s*$", body or "")
    if not m:
        return {}
    out = {}
    for line in body[m.end():].splitlines():
        a = re.match(r"\s*(\w+)\s*=\s*([^/]+?)\s*(?://.*)?$", line)
        if a:
            out[a.group(1)] = a.group(2).strip()
    return out


def uses_up(bodies, alias):
    """Like _uses, followed up the call path. bodies: [(workflow name, body)],
    the workflow that calls the process first, then its caller, and so on. A
    process emit that the enclosing workflow emits (`fastq = ch_fastq`) is
    used in the parent as `ALIGN_STAR.out.fastq`, perhaps assigned to
    `ch_unaligned_sequences`, which is what the DAG labels the edge with."""
    if not bodies:
        return {}
    uses = _uses(bodies[0][1], alias)
    carry = {e: {v for k, v in us if k == "var"} | {f"{alias}.out.{e}"} for e, us in uses.items()}
    for lvl in range(1, len(bodies)):
        child, child_body = bodies[lvl - 1]
        parent_body = bodies[lvl][1]
        emits = _emit_block(child_body)
        parent_uses = _uses(parent_body, child)
        new = {}
        for e, names in carry.items():
            wf_emits = [w for w, expr in emits.items() if expr in names]
            if not wf_emits:
                continue
            for w in wf_emits:
                uses[e].append(("var", w))                    # the DAG may label with the emit's own name
                uses[e].extend(parent_uses.get(w, []))
            new[e] = {v for w in wf_emits for k, v in parent_uses.get(w, []) if k == "var"} | \
                     {f"{child}.out.{w}" for w in wf_emits}
        carry = new
    return uses


def assign(proc, in_edges, out_edges, body):
    """body: the enclosing workflow's body, or a list of (workflow name, body)
    from the enclosing workflow up the call path."""
    alias = proc.get("alias") or proc["name"]
    inputs, outputs = proc["inputs"], proc["outputs"]
    call = proc.get("call") or []
    # An input can be filled by several union edges that never meet in one run
    # (KRAKEN2 reads trimmed, raw or unmapped reads, by setting); an edge may
    # take input i if no edge already on i shares a run with it.
    ins, runs_on = {}, {i: set() for i in range(len(inputs))}
    for evidence in ("argument", "input name", "operator"):
        for key, typ, label, obs in in_edges:
            if key in ins:
                continue
            for i in range(len(inputs)):
                if runs_on[i] & obs:
                    continue
                arg = call[i] if i < len(call) else ""
                if evidence == "argument" and label and _name(arg) and (label == arg or arg.endswith("." + label) or arg.split(".")[0] == label):
                    hit = True
                elif evidence == "input name" and label and inputs[i]["kind"] != "tuple" and label in inputs[i]["names"]:
                    hit = True
                elif evidence == "operator" and typ.startswith("op:") and _last_op(arg) == typ[3:]:
                    hit = True
                else:
                    hit = False
                if hit:
                    ins[key] = (i, inputs[i], evidence)
                    runs_on[i] |= obs
                    break
    # the input no edge has taken, per run: one edge left in a run fills it
    for key, typ, label, obs in in_edges:
        if key in ins:
            continue
        free = [i for i in range(len(inputs)) if not (runs_on[i] & obs)]
        if len(free) == 1:
            ins[key] = (free[0], inputs[free[0]], "last one left")
            runs_on[free[0]] |= obs

    uses = uses_up(body, alias) if isinstance(body, list) else _uses(body, alias)
    outs = {}
    emits = {o["emit"]: j for j, o in enumerate(outputs) if o["emit"]}
    # an emit can feed several consumers, in one run or across runs
    for key, typ, label, obs in out_edges:            # 1: names
        if not label:
            continue
        j = emits.get(label)
        if j is None:
            for e, us in uses.items():
                if ("var", label) in us and e in emits:
                    j = emits[e]
        if j is not None:
            outs[key] = (j, outputs[j], "label")
    for key, typ, label, obs in out_edges:            # 2: what the code does with it
        if key in outs or typ == "point":
            continue
        for e, us in uses.items():
            j = emits.get(e)
            if j is None:
                continue
            if (typ.startswith("op:") and ("op", typ[3:]) in us) or (not typ.startswith("op:") and ("call", typ.split(":")[-1]) in us):
                outs[key] = (j, outputs[j], "usage")
                break
    # 3: a bare point is an emit nothing reads in that run: topic emits first,
    # one point per emit per run
    unread = [j for j, o in enumerate(outputs) if o["emit"] not in uses]
    unread.sort(key=lambda j: (0 if outputs[j]["topic"] else 1, j))
    runs_on = {j: set() for j in unread}
    for key, typ, label, obs in out_edges:
        if key in outs or typ != "point":
            continue
        for j in unread:
            if not (runs_on[j] & obs):
                outs[key] = (j, outputs[j], "unused emit")
                runs_on[j] |= obs
                break
    return ins, outs
