# A standalone channel viewer for any Nextflow pipeline: rationale and process

*2026-10-10. Exploration and outline only. Nothing built, no code written.
Follows on from
`rnaseq-flow/working_docs/channel-viewer-standalone-2026-10-09.md` (the design
note) and `rnaseq-flow/working_docs/channel-schematic-rationale-2026-09-14.md`
(why the channel level matters). The prototype lives in
`rnaseq-flow/working_docs/channel-schematic/`.*

## Rationale

**The problem is general, not specific to rnaseq-flow.** Every rnaseq-flow
bug from August and September 2026 (C3, H7, the dead MultiQC link, wiring
rMATS into the report) was about what a channel carries: tuple shape, meta
keys, or how many items. `-with-dag` shows none of that. Any DSL2 pipeline
built on `[meta, files]` tuples with `map`, `join` and `mix` between
processes has the same kind of bug. nf-core pipelines have more of those
operators, not fewer.

**The prototype has already proved the page is useful.** Building it found
M4, M21, M22 and M23. The page's value isn't the open question. The cost is:
829 hand-written lines of spec for a single pipeline. So the standalone tool
is mainly about cutting that cost.

**The bar is `-with-dag`, plus two things it lacks:**

- **Predicates:** which settings each element exists under, so the graph can
  be filtered to one route.
- **Contents:** what each channel carries.

With no annotations the tool can still deliver predicates. Contents are the
part you have to pay for.

## Two products on one engine (decided 2026-10-11)

After Phase 3 step 1 the user set out what most people should get: download
a Nextflow pipeline, run its test, open the page. No matrix of hundreds of
previews to get something viewable. The matrix approach built in Phase 2 is
kept, not replaced: it becomes a second mode for deeper analysis of a
pipeline. Both write the same channel model and use the same viewer.

| | **Explorer** (the default) | **Analyser** (the Phase 2 matrix) |
|---|---|---|
| For | anyone who wants to see a pipeline | maintainers, developers, reviewers who want to know the pipeline exactly |
| The user does | one command, e.g. `process-flow run nf-core/rnaseq -r 3.27.0 -profile test,docker` | proposes dimensions, declares `implies`, runs adaptive batches of previews, builds the model |
| Runs | one real test run; optionally a few previews, one per route value | hundreds of previews (fetchngs 14, nf-core/rnaseq 357) |
| Output | `results/pipeline_info/channels.html`, beside the MultiQC report | a model and page wherever the user writes them; can be published per release |
| Topology | the test run's route in full; other routes listed from the code's conditions, drawn if previewed or a published model is loaded | every route the matrix reached, as one union graph |
| Conditions | read from the `if` blocks around each call; unknown where the code is not plain (`branch` closures, helpers, one process called twice) | inferred from which previews each element appeared in; proven against every run |
| Contents | declared shapes plus what actually flowed: meta keys, item counts, real examples | declared shapes; runtime contents only if a real run is added |
| Exactness | approximate conditions, exact contents for the run | exact conditions over everything the matrix saw |

How they meet:

- **The Analyser is the Explorer's answer key.** Conditions read from source
  are scored against the matrix-built models of fetchngs and nf-core/rnaseq,
  as the hand-built fixtures scored Phase 2.
- **A published Analyser model upgrades an Explorer page.** If someone has
  run the matrix for a release, the Explorer can load that model for exact
  conditions on every route and overlay its own run's contents.
- **Shared parts:** DAG alignment, the viewer, module and port parsing,
  inference (also used by the Explorer's optional extra previews).

### Published models: authors analyse, users explore

The Analyser's output is meant to be shared, not only read by whoever ran it.
A pipeline's author runs the matrix once per release and commits the model to
the pipeline's own repo. Every Explorer run of that release then starts from
exact conditions, for the cost of one test run.

1. The author runs the Analyser for a release.
2. They commit a **published model** at an agreed path, e.g.
   `assets/process-flow/channels.json`.
3. A user runs `process-flow run <pipeline> -r <release> -profile test,...`.
   Nextflow has already pulled the repo, so the Explorer looks for the file
   in the pulled copy.
4. **Found and matching:** the page takes topology and conditions for every
   route from the published model and overlays the user's run: what flowed,
   meta keys, item counts, examples.
5. **Missing:** the Explorer falls back to conditions read from the code.

What this needs:

- **A published form of the model.** The nf-core/rnaseq model is 5.6 MB,
  mostly `observed_in` run lists. The published form keeps dimensions,
  `implies`, topology, `when`/`flows_when`, shapes and ports, and drops
  per-run evidence (expected well under 1 MB). The full model stays with the
  author. Same schema, with a flag saying which form it is.
- **A version stamp.** Pipeline name, release, commit, Nextflow version and
  process-flow version the model was built with. On a different release or
  commit the Explorer does not use it silently: either it refuses or it
  loads it with a visible warning.
- **A check on every user run, for free.** The user's run is one more
  observation. Any element present when the model says it should be absent
  under those settings, or the reverse, is flagged on the page as a
  disagreement: the model is stale or wrong, and can be reported to the
  author.
- **How the model was built.** The fixed args and declared `implies` used
  (e.g. nf-core/rnaseq's `--transcript_fasta null`), the dimensions left out,
  the elements left unsettled, so users know which settings it is proven
  under.
- **Optional CI for authors.** A GitHub Action that reruns the Analyser on
  each release and commits the new published model, so it never goes stale.

**Step 1, the published form: done 2026-10-11.**
`tools/publish.py MODEL --dims proposal.json -o channels.json` writes it, with
the schema additions in `schema/README.md`. The viewer reads it: the footer
gives the evidence summary, and the panel says "proven over N runs" or "fits
all N runs, but the matrix did not settle it". `tools/generate.py` now
stamps the repository, revision, release and Nextflow version from the runs'
Nextflow logs.

| | Full model | Published | Page | Stamp | Evidence |
|---|---|---|---|---|---|
| nf-core/rnaseq 3.27.0 | 8.5 MB | 0.76 MB | 5.7 MB to 1.1 MB | `a1fcdddd3b`, from the logs | 357 ok, 3 failed, 0 disagreements, 2 unsettled (the MultiQC bundle edges), 12 fixed args, 66 params not varied |
| nf-core/fetchngs 1.13.0 | 0.08 MB | 0.04 MB | 0.39 MB | `955c892d80`, given (no logs beside those DOTs) | 14 ok, 0 disagreements, 0 unsettled |

A dimension no run varied counts as a param held fixed, not as making every
element unsettled. fetchngs' current proposal has `ena_metadata_fields`,
which the proposer gained after its matrix ran; it moves to "not varied" and
its filter is dropped.

**Step 2, capturing a real run: started 2026-10-11.** First a probe, before
choosing how to capture: one ordinary `-profile test,docker` run of
nf-core/rnaseq 3.27.0 with three things switched on through a `-c` config,
none needing a plugin or a change to the pipeline:

- **Nextflow's data lineage** (`lineage.enabled`, Nextflow 25.04 and later).
  It records every task's inputs and outputs. The question is whether `val`
  inputs, the meta maps, are kept as values. If they are, meta keys and
  example values at every process input come for free.
- **A trace file** with process, tag, status and work folder for each task.
  This gives item counts per process.
- **The real run's DAG**, to align against the published model's union graph
  and check the run against it.

What the probe should settle: whether lineage carries meta maps (if not, the
fallback is a small trace-observer plugin, or nf-prov); how many items crossed
each process boundary; and whether the real run's DAG aligns with the preview
DAGs (it should: same code, same settings as the baseline preview).

**Probe result, 2026-10-11: lineage is enough; no plugin needed.** The run
(`reverent_poitras`, 234 tasks, 65 processes, about 18 minutes, memory capped
at 12 GB) left a 3.5 MB `.lineage` store:

- **Meta maps are kept as values,** at every process input and output.
- **Ports split cleanly.** Inputs and outputs are flattened in declaration
  order, with unmade optional outputs as `[]` and `topic:` emits included. The
  module declarations split all 234 tasks into ports with no mismatch.
- **Provenance is exact.** Each file is `lid://TASK/name`, so every input
  names the task and emit that made it (STAR_ALIGN's reads: BBSPLIT
  `all_fastq`). Files from outside the run are `{path, checksum}`.
- **The run records itself:** full commit, release, repository and every
  param.

`tools/harvest.py MODEL --lineage .lineage --source SRC --dag dag.dot [--dags
PREVIEWS]` lays this over a model. On the published nf-core/rnaseq model:

- 140 input ports and 175 emits harvested, 330 edges filled: meta keys,
  cardinality (queue per `meta.id` 149, single 117, value 41, collected 8)
  and up to six real items, keyed by run name.
- The viewer gains a "This run" box: the run, the check result, and a button
  that sets the filters to the run's settings, read from its params.
- Content the matrix could never show is now visible. For example,
  `salmon_strand_analysis` joins the meta only for samples whose strandedness
  was `auto` (WT_REP1), so keys differ between items on STAR_ALIGN's reads.

**The check caught a real limit of the published model.** Of 68 processes
expected under the run's settings, 67 were wired and 65 ran. The difference
is MAKE_TRANSCRIPTS_FASTA, and 22 nodes and edges around it. The matrix held
`--transcript_fasta null` (the workaround that made the test profile
previewable), but the real test profile supplies one. It is listed in the
model's `params_not_varied`, so the check confirms that caveat rather than
finding a new error. The Explorer should say so directly: name the held
param a difference touches (next).

PRESEQ_LCEXTRAP and SAMTOOLS_INDEX were wired but ran no task: starved in
this run, which a preview cannot tell.

**The three follow-ups: done 2026-10-11.**

- **Differences put down to held args.** The run's params are compared with
  the published model's `fixed_args`, counting a path only as set or unset.
  This run changed `--transcript_fasta` (null in every preview, set here) and
  `--sylph_db`/`--sylph_taxonomy` (dummies in the previews, unset here).
  The differing elements are grouped into connected pieces. Each piece is put
  down to the changed arg its ids name (`point@start>transcript_fasta`). All
  22 differences are explained by `--transcript_fasta`; none are unexplained.
  The "This run" box says so, and would flag in bold any piece left
  unexplained, which would mean a stale or wrong model.
- **Starved in the run.** `captured.starved` (wired, no task) and
  `captured.tasks_per_process`. The process panel says "5 tasks in
  reverent_poitras", "wired, but it received nothing", or "not in" the run.
  The box links the starved processes (PRESEQ_LCEXTRAP, SAMTOOLS_INDEX).
- **Operator edges.** Lineage links each input file to the emit that made it,
  so every edge on the way between them, through operators only, gets
  `contents.files`, marked harvested. For example: "to PICARD_MARKDUPLICATES
  input 1 from SAMTOOLS_SORT bam (5 files: ...)". This covers 163 of the
  run's 410 operator-to-operator edges (116 of 341 in the main lane, 47 of 54
  MultiQC). It says where files came from and went, not the tuple as it was
  in between, and not which branch each file took where paths split.

Coverage of the run's 836 edges: 324 of 426 process-boundary edges have real
examples, and 163 operator edges have their files. The rest are operator
edges fed by params or `channel.of` (no task made them), versions plumbing,
and edges whose files came from outside the run.

Still open for the Explorer:

- items between operators, which lineage cannot see;
- an arg the matrix did not vary and did not fix (`params_not_varied`)
  cannot be checked, because its held value is not recorded. Recording the
  test profile's values in the published model would fix that.

**Step 3, conditions read from source: done 2026-10-11 for processes.**
`tools/conditions.py` does not translate `if` conditions into formulas. It
interprets the code once for each combination of settings:

- `params.x` is the setting for a dimension, otherwise its baseline value.
  The baseline comes from the schema, then `nextflow.config`'s params, then
  the profile, then the Analyser's fixed args, so the comparison is like for
  like.
- A `take:` input is the caller's argument, evaluated at the call. This
  follows `params.skip_fastqc || params.skip_qc` down two levels.
- A local variable replays its assignments and list appends, each under its
  own `if`s. This is how `'sortmerna' in prepare_tool_indices` works.
- Simple closures (`findAll`, `collect`) are supported, and a channel counts
  as true.
- Anything else is unknown, three-valued.

Each process is evaluated only over the params its conditions read, and the
truth table goes through `tools/infer.py` for a compact `when`.

Scored against the Analyser models (`tools/test_conditions.py`), over every
allowed setting:

| | Exact | Unknown | Wrong |
|---|---|---|---|
| nf-core/fetchngs 1.13.0 (9 processes) | 9 | 0 | 0 |
| nf-core/rnaseq 3.27.0 (101 processes) | 94 | 7 | 0 |

The 7 unknowns are the RSeQC modules. They are picked in
`defineQcTools(params)`, a helper that mutates a list (`removeAll`,
`remove`), builds `"rseqc_${mod}"` in an `.each`, and calls another helper
that reads the GTF file. That is past a one-expression interpreter, and
saying "unknown" is right.

Getting there took four fixes, each found by the score:

- appends written after `{` on the same line;
- comments carried into call arguments;
- nf-core defaults living in `nextflow.config`, not the schema;
- channel truthiness (`if (ch_transcript_fasta)`).

The first run scored 15 exact, 7 wrong and 79 unknown: without the Analyser
as an answer key these bugs would have shipped.

**The Explorer's case.** With `--dims proposal.json` (all 69 proposed
params) and the real run's DAG, 60 of 67 processes get a `when` in 5.7 s.
The largest truth table is 6,144 rows (11 params). The conditions cover
what the matrix never varied. For example, STAR_ALIGN needs `aligner ∈
{star_salmon, star_rsem}`, not `skip_alignment`, not
`use_parabricks_star` and not `use_sentieon_star`. Those parts cannot be
scored against the matrix, which held them, but the same interpreter is
exact wherever it can be checked.

**Operators and edges: done 2026-10-11** (`tools/graph_conditions.py`, same
interpreter). The DAG does not say which statement makes an operator, so it
is located by its readable id's anchors. The candidates are statements with
that operator (`.map`) that name the anchors (also with nf-core's `ch_`
prefix, and counting the process whose argument list holds the statement),
ranked by how close their workflow is to the node's processes. The node
exists when the statement's `if`s hold, through the call paths that lead to
its processes.

The rest follows from how the union graph is built:

- One statement becomes a node per producer, so an operator also needs a
  producer.
- A `channel.empty()` is drawn only if something consumes it.
- Points go with their node, and an edge with both its ends.
- A channel replaced under an `if` (fetchngs' `ch_sra_metadata`) is
  handled by giving channel values the assignment that made them. An edge
  then needs its producer's value to be the one that reaches the consumer.

Each rule was scored before it was kept:

| | Exact | Wrong | Unknown |
|---|---|---|---|
| nf-core/fetchngs 1.13.0 (117 elements) | 117 | 0 | 0 |
| nf-core/rnaseq 3.27.0 (2,289 elements) | 1,902 (83%) | 281 | 106 |

For nf-core/rnaseq, the main lane is 84% exact and MultiQC plumbing 74%.
Across all elements and settings, 5.7% of answers are wrong.

Two rules lost on the score and were dropped:

- Requiring a consumer as well as a producer took away 54 exact elements.
- The "reaches the emit" check for `channel.empty()` placeholders took away
  203.

The reaching-value rule is limited to variables replaced outright. On
accumulators (`ch_x = ch_x.mix(...)`, repeated under `if`s) it was wrong 20
times in 25, because the union graph merges the links of such a chain by
position. That is the limit behind most of what is left: alignment merges
structurally alike operators that the code makes in different places
(`mix` chains into `ch_multiqc_files`, the per-sample MultiQC `join`s, and
the parallel trimgalore and fastp subworkflows' placeholders). So one node
does not map to one statement, and no reading of the source can fix that
from this side. The Analyser does not have this problem, because it never
needs a node's statement.

For the Explorer this is good enough to draw: every process is right
where the code is plain, 83% of everything is exact, and wrong answers
are concentrated in folded plumbing. Edges and operators read from source
should still be marked as such on the page (a `source` provenance), so a
reader knows they are less sure than a matrix-proven model.

Not yet done in step 3: writing the source `when`s into a model
(`when_from: "source"`, a new provenance value). That belongs with the
step 4 wrapper, which builds the Explorer's model.

**Step 4, the one command: built 2026-10-11; the real `run` path is still
to be tried in WSL.** `bin/process-flow` (`tools/pf.py`):

- `run ARGS...` passes everything to `nextflow run` and adds
  `-c .process-flow/capture.config` (`lineage.enabled`, and the DAG written
  to `OUTDIR/pipeline_info/process-flow/dag.dot`). When the run succeeds it
  goes on to `explore`.
- `explore` reads the lineage store's latest run, with every task of its
  session, so `-resume` cache hits count. The record gives it the source
  (`projectDir`), the outdir, the commit and the params.
  - With a published model (`SOURCE/assets/process-flow/channels.json`, or
    `--model`) it uses that, warning if the model was built from another
    commit.
  - Otherwise it builds one: dimensions from the proposer, topology,
    modules, ports and shapes from `generate --source` on the run's DAG,
    and every `when` from `graph_conditions.compute` in a new
    `PredicateAlgebra`.
  - Then `harvest.overlay` lays the run over the model. It writes
    `OUTDIR/pipeline_info/channels.html` and `channels.json`.

The predicate algebra:

- Each truth table covers only the params an expression reads, and drops
  any param that never changes the answer.
- `infer` reduces the table to a compact `when`.
- AND and OR are combined through small truth tables, falling back to
  symbolic forms past 20,000 rows (none needed on nf-core/rnaseq).

Scored on the Analyser's dimensions it gives 1,992 exact, against 1,902
for vectors, because undecided settings count as present.

**Checked on the real nf-core/rnaseq run**, from Windows with `explore
--source`:

| | Published model | Built from the code |
|---|---|---|
| Time | 1.8 s | 75 s (3 min before dropping irrelevant params) |
| Conditions | the Analyser's | 1,353 read, 213 read but partly undecided, 43 contradicted by the run and so marked unknown (an element in the run's DAG must exist under its settings) |
| Check | 1 difference, put down to `--transcript_fasta` | none |
| Page | as before | 26 filters (every param the code tests), aligner as the route, STAR_ALIGN `--aligner = star_salmon \| star_rsem; no --skip_alignment; no --use_parabricks_star; no --use_sentieon_star`, *source* marked in the panel and counted in the footer |

Ticking `--skip_alignment` on that page dims the STAR route's seven
processes. Library entry points were added along the way:
`propose.propose()`, `harvest.overlay()` and `report()`, `build.page()`
and `validate()`, and `graph_conditions.compute()`. Each tool's command
line is unchanged and was checked byte for byte. Two smaller changes:

- The schema gained the `source` provenance.
- Matching a changed arg to a difference now compares words and folds
  plurals, so `MAKE_TRANSCRIPTS_FASTA` names `--transcript_fasta`. Without
  this, a published model checked with no preview DAGs left it unexplained.

The README and guide now lead with the one command, and the matrix
walkthrough is "The Analyser", for pipeline authors, with a new "Publish
the model" step.

**The real `run` path in WSL, 2026-10-11:** `process-flow run nf-core/rnaseq
-r 3.27.0 -profile test,docker --outdir results -c capture.config -resume`
worked end to end. The pipeline took 10 minutes, all 234 tasks re-ran (the
work folder was gone), and `channels.html` was written with the same
conditions as on Windows.

One bug: it reported 454 tasks. `-resume` keeps the session, so taking
every task of the session took both runs. `read_lineage` now takes the
latest run's own tasks (`workflowRun`). From earlier runs of the session
it adds only tasks whose name the latest run did not run itself, which are
its cache hits. Checked on a synthetic two-run store: 234 tasks, 233 own
and 1 from the cache.

### Phase 5: outside RNA-seq (started 2026-10-12)

**nf-core/methylseq 4.2.0 could not be run at all.** Its `nextflow.config`
includes `conf/aws/batch/nextflow.config`, which the release does not ship.
Nextflow 26's config parser checks every include, even in an unused
profile, so parsing fails. It is a packaging bug in the release, not
process-flow's. Lesson: check with `nextflow config PIPELINE -r REV
-profile test,docker` before a run.

**nf-core/sarek 3.10.0** (test profile, 23 tasks, 7 minutes): `process-flow
run` worked first time, and the page was written. The first build had 134 of
1,878 elements contradicted by the run (7%, against nf-core/rnaseq's 2.6%).
That traced to four processes read as "never", from three things
nf-core/rnaseq never exercised:

- **The contents of a string or path param.** `tools.split(',')
  .contains('strelka')` and `intervals.endsWith('.interval_list')` read the
  value, and a set/unset param stood for `<path>`. Now it is the run's real
  value; failing that, true and nothing else known.
- **Params filled in by main.nf at run time.** `params.intervals =
  getGenomeAttribute('intervals')` (36 such in sarek, 14 in nf-core/rnaseq)
  is applied by Nextflow only where the config leaves the param unset. The
  lineage records params as configured, before that line. Two fixes:
  - `explore` reads the effective params from nf-core's
    `pipeline_info/params_*.json`;
  - the interpreter evaluates nf-core's standard `getGenomeAttribute`
    (null with no `--genome`, else the attribute from `params.genomes`),
    and any other script-level assignment is unknown.
- **Comma-separated list params** (`--tools`, `--skip_tools`,
  `--use_gatk_spark`): one set/unset dimension cannot answer "contains
  strelka".
  - The proposer now recognises nf-core's list pattern
    `^((a|b|c)?,?)*(?<!,)$` and makes one boolean dimension per value the
    code tests (`tools:strelka`, with `list_value`). That is 28 for
    `tools`.
  - Settings from args and from params map lists onto the switches.
  - The interpreter reads a list lazily: `contains('x')` reads one switch,
    and truth reads the switches that are on. Otherwise every condition
    touching `tools` would read 28 switches, a table of 2^28 rows. `&&`
    and `||` now evaluate both sides, so the reads of each are found (the
    three-valued result is the same).

After these fixes: 58 contradicted (3%), no process among them, 167 partly
undecided, 33 s to build. The nf-core/rnaseq and fetchngs scores are
unchanged. What remains is operators matched to a look-alike statement in
another tool's or aligner's block, the known weakness. The page puts the
aligner as the route, with 25 filters (the `tools` switches among them).
Turning `tools:strelka` off dims STRELKA_SOMATIC and its merges.

Not decidable from settings, and correctly shown as such: sarek wires
aligners and germline Strelka unconditionally and routes data to them with
channel filters. So BWAMEM2_MEM, DRAGMAP_ALIGN, SENTIEON_BWAMEM and
STRELKA_SINGLE exist under every setting, and the run shows which ones
received nothing (25 processes wired but given no task).

**Page polish for code-built models: done 2026-10-12.** Both real
pipelines gave 25 to 26 filters in one flat list. The filter panel now has:

- **Route first,** then the choice params ordered by how many processes
  each one decides. That count is shown as a small badge on every filter
  (`--pseudo_aligner 7`).
- **On/off and set/unset options grouped by the schema section** the param
  comes from. Dimensions now carry `group`, written by the proposer and
  added to the schema. The sections are ordered by their busiest option and
  fold, with the busiest open.
- **A list param's switches together** under the list (`--tools`, one
  switch per value).
- **A search box** once there are more than 8 options.
- **A count per section of options set away from the pipeline's default,**
  kept current, so "Show this run's settings" shows at a glance where the
  run differs (for nf-core/rnaseq's test: 6 reference files and 1 skip
  option).
- **Long names break only at underscores.**

Models without groups (the Analyser's) render as before. Checked on the
sarek and nf-core/rnaseq code-built pages and the published nf-core/rnaseq
page.

**Repository ready to publish, 2026-10-12 (no git yet, by choice).**

- **Layout and ignore list.** `.gitignore` leaves out `out/`, the working
  data in `working_docs/` (pulled pipeline sources, run bundles, preview
  DAGs; the plan stays), run state, `docs/node_modules/` and `.claude/`.
- **`examples/`:**
  - three pages (nf-core/rnaseq and nf-core/sarek test runs, nf-core/fetchngs);
  - the two published models, which `tools/test_conditions.py` now reads.
  - Checked: no local paths or usernames in them.
- **Licence and history:** GPL-3.0 `LICENSE` (as rnaseq-flow and
  refdata-flow), `CHANGELOG.md` and `CITATION.cff`. The citation's
  repository URL assumes github.com/nicholas-owen/process-flow, not yet
  created. Version 0.1.0.
- **The Word user guide,** `process-flow_User_Guide.docx`, built by
  `docs/build_user_guide.js` on rnaseq-flow's pattern (`docx` 9.6.1, same
  helpers and styles):
  - the logo is rendered from the viewer's own SVG at build time (resvg),
    also written as `assets/process-flow_logo.png`;
  - the version is read from `tools/version.py`;
  - 10 sections, 26 subsections, 10 tables;
  - checked: every XML part well-formed (no LibreOffice here to render it).

The README now shows the logo, a documentation table, the examples, the
licence and the citation.

Limit: a published model cannot know what the Analyser cannot see (routing
inside `branch` closures, one process called from two exclusive places). The
Explorer's own run and code reading can fill in some of that.

Order of work from here: runtime capture from a real test run (Phase 3 step
2) becomes the centre, then conditions read from source validated against the
Analyser models, then the `process-flow run` wrapper (later perhaps a
Nextflow plugin). The docs lead with the Explorer; today's `docs/guide.md`
walkthrough becomes the Analyser section.

## What the prototype shows that the design note understates

**1. Diffing the node sets is harder than the note implies.** In the DOT
output, operators are anonymous nodes with a type label and a position-based
id: `v2 [shape=circle, xlabel="map"]`. `star_full.dot` alone has 91 `mix`,
27 `collect`, 20 `first` and 12 `map` nodes. A `v17` in one preview is not
the same node as a `v17` in another.

Process names are stable across previews; operators are not. Before you can
say "this `map` appears in 7 of 13 previews", you have to know it is the same
`map` each time. That needs a fingerprint for each operator, for example:

- the nearest named process or channel upstream and downstream,
- the edge label,
- the operator type,
- its position in the chain.

This is also why check 4 settled for counting operators by type. It is the
core algorithm of Tier B, and it doesn't exist yet.

**2. The predicate format is rnaseq-flow's own.** `when` uses keys like
`level_min`, `aligner`, `gtf: true` and `entry`. Some of these are values
derived from params, not params. The generic form has to be keyed on params,
with a few types:

- an enum param maps to a set of allowed values,
- a boolean to true or false,
- a path param to present or absent,
- an ordered enum (like `stop_at`) to a minimum level,
- plus the existing `any` for OR.

The `holds()` function in the template and the one in `check_channels.py`
then become identical and fully data-driven.

**3. Some of Tier C is cheaper than the note suggests.** Module `input:` and
`output:` declarations (`tuple val(meta), path("*.bam")`) can be parsed
without running anything, and check 2 already parses `input:`. That gives the
tuple shape at both ends of every process edge with no run and no
annotations.

Between two processes, the chain of operators is then pinned by known shapes
at each end. If the chain is only `mix`, `filter` or `first`, the shape
passes through unchanged and can be filled in automatically. Annotations are
only needed where a `map`, `join` or `groupTuple` changes the shape. Those
are also where the bugs lived.

**4. A Nextflow plugin may beat parsing the work directory for runtime
contents.** A plugin's trace observer sees each task's actual input values,
meta maps included, which the work directory doesn't keep (it only shows
staged files). The existing nf-prov plugin records task inputs and outputs,
so it is worth evaluating before writing a harvester. Either way, runtime
data only covers process boundaries, not the edges between operators.

**5. Annotations need ids that survive edits to the pipeline.** Annotation
files must be keyed to graph elements, but DOT has no source line numbers
and operator ids are positional. Whatever fingerprint solves point 1 also has
to work as the annotation key. Otherwise annotations go stale silently the
first time someone adds a `map`. The checker has to report annotations that
no longer match anything.

**6. Lanes need to be detected, not hard-coded.** The template hard-codes
`RNASEQ.ch_versions` and `RNASEQ.ch_multiqc_files` as lane hubs. In general,
a lane is a node with high fan-in, fed by a long chain of `mix` or `collect`.
Newer nf-core modules use topic channels for versions, so their DOT will look
different again.

## Findings from the fetchngs previews (2026-10-10)

nf-core/fetchngs 1.13.0 (revision `955c892d80`), Nextflow 26.04.6, run in
WSL. Eight `-preview -with-dag` runs on the `test` profile; DOT files and logs
in `working_docs/fetchngs-preview/`.

| Run | Args | Result |
|---|---|---|
| `baseline` | (ftp, the default) | 9 processes, 24 operators, 59 edges |
| `dl_aspera` | `--download_method aspera` | identical to baseline |
| `dl_fastqdl` | `--download_method fastq-dl` | identical |
| `dl_sratools` | `--download_method sratools` | identical |
| `dl_sratools_dbgap` | sratools plus `--dbgap_key` | identical |
| `dl_ftp_dbgap` | `--dbgap_key` | identical |
| `nfcore_rnaseq` | `--nf_core_pipeline rnaseq` | identical |
| `skip_download` | `--skip_fastq_download` | 3 processes, 18 operators, 27 edges |

"Identical" means the same set of DOT lines once sorted; the order of blocks
in the file varies between runs, so a raw diff or hash is useless and the
parser has to canonicalise.

**Timing is not a constraint.** About 10 seconds per preview. A hundred runs
is under 20 minutes, so the size of the preview matrix is not a reason to cut
corners.

**Nesting is four levels deep:**
`NFCORE_FETCHNGS:FETCHNGS:FASTQ_DOWNLOAD_PREFETCH_FASTERQDUMP_SRATOOLS:SRATOOLS_PREFETCH`.
The first two levels wrap everything and carry no information. The viewer
strips the prefix every process shares and shows subworkflows from the level
where the graph actually divides.

**Node ids are renumbered when the structure changes.**
`MULTIQC_MAPPINGS_CONFIG` is `v48` in the baseline and `v21` in
`skip_download`. Between runs with identical structure the ids happen to
match; as soon as anything is removed upstream they don't. This is the
operator-identity problem from point 1 above, now confirmed on real data. It
applies to processes as well as operators, though processes can fall back on
their name.

**Only `skip_fastq_download` changes the structure.** It is an ordinary
`if (!skip_fastq_download)` in `workflows/fetchngs.nf:60`, and removing it
drops six processes (SRA_FASTQ_FTP, ASPERA_CLI, FASTQDL and the three sratools
processes) and six operators (the `branch`, a `collect`, a `map` and three
`mix`). Comparing DAGs recovers this as a normal `when`.

**`download_method` routes item by item, inside a `branch` closure.** All four
download routes are wired in every DAG. The closure
(`workflows/fetchngs.nf:62-84`) picks a method for each sample, with later
`if`s overriding earlier ones:

| Route | Receives a sample when | Shape it emits |
|---|---|---|
| aspera | `download_method == aspera` and the sample has an Aspera link | `[meta, [link1, link2]]` |
| fastq-dl | `download_method == fastq-dl` and the sample has an Aspera or FTP link | `[meta, run_accession]` |
| ftp | (`download_method == ftp`, or aspera with no Aspera link) and the sample has an FTP or Aspera link | `[meta, [fastq_1, fastq_2]]` |
| sratools | `download_method == sratools`, or the sample has no Aspera and no FTP link, under any method | `[meta, run_accession]` |

Comparing DAGs recovers none of this. Consequences:

- **Two kinds of predicate.** `when`: the element exists in the graph, from
  comparing DAGs. `flows_when`: the element receives items, from `branch` and
  `filter` closures, runtime evidence or annotations. rnaseq-flow's
  `starved_when` is the special case of the second. Both are first-class in
  the schema.
- **`flows_when` has a data clause.** The aspera route needs a param value and
  a per-sample field. Under a given param setting a route is in one of three
  states: never receives items (dimmed), may receive items depending on the
  samples (dashed), receives items (solid). The filter controls drive the
  param clause; the data clause is shown in the panel.
- **Routes are not exclusive within a run.** Under `ftp`, samples with no links
  fall back to sratools, so one run can use two routes. Route colouring cannot
  assume a run takes exactly one.
- **`branch` changes shape.** Each branch's `return` gives a different tuple.
  Add it to the shape-changing operators in point 3 above. The shapes are in
  the source and can be read without running anything.
- **Simple closures can be evaluated mechanically.** This one depends on one
  param and on whether two meta fields are set: 4 × 4 = 16 cases. Extract the
  closure, run it once per case with stand-in values, and reduce the results
  to the table above. Closures too complex for that fall back to annotations.
  Reproducing this table is an acceptance test for the fetchngs fixture.
- **Conditions read workflow inputs, not params.** `download_method` and
  `skip_fastq_download` arrive through the workflow's `take:` block. Anything
  that reads conditions from the source has to follow them back through
  `main.nf` to the params.

**`dbgap_key` and `nf_core_pipeline` don't change the graph.** The expected
`dbgap_key` × sratools interaction does not exist structurally. Both are
argument-only params, and the dimension proposer should be able to discover
that from a single preview each.

**Rules for the dimension proposer**, from the fetchngs schema:

- Exclude `hidden: true` params and the standard nf-core groups
  (`institutional_config_options`, `generic_options`, `deprecated_options`).
- Handle `type` given as a list (`help` is `["boolean","string"]`).
- Skip an enum with a single value (`force_sratools_download: enum [false]`).
- String params with no enum get no proposed values; path params get
  present/absent.

**Syntax drift.** fetchngs has branches named `dsl3`, `native-process` and
`preview-26-04`; nf-core is using it to try new Nextflow syntax. Always pin a
release with `-r`, and expect static parsing of module declarations to need
both the old and new process syntax.

## The process

### Phase 0: data model and gold fixtures

A gold fixture is a hand-checked model that every automated tier gets scored
against. Phase 0 uses two pipelines, for different jobs.

**rnaseq-flow is fixture #1, the answer key.**

- **It's done and checked.** It has 218 nodes and 301 edges, compared against
  13 preview DAGs. Check 3 caught five transcription errors, and they're
  fixed. Converting it to the new schema takes days.
- **It's hard enough to be a real test.** It has four routes, an OR predicate
  (DE), an ordered dimension (`stop_at`), path params that are either present
  or absent (`--gtf`), wired-but-starved nodes, two lanes to fold, and 103
  edges with worked examples. Matching it in Phase 2 means something.
- **You can check it.** You know the code well enough to tell whether a
  difference is a tool bug or a spec error.

**nf-core/fetchngs is fixture #2, the check that stops the schema being
shaped only by rnaseq-flow.**

- **Nesting.** rnaseq-flow ids are flat (`RNASEQ:STAR_ALIGN`). nf-core uses
  deeper paths, with modules aliased in more than one place. The `path` field
  has to be designed against a real nf-core preview, not guessed at.
- **nf-core conventions.** Things like `nextflow_schema.json` as the source of
  dimensions, versions collected through topic channels, and nf-core
  subworkflow wrappers. None of these come up in rnaseq-flow.
- **Independence.** A fixture written by the same person with the same
  assumptions as the tool won't catch shared blind spots.

fetchngs is small enough to read in full and model by hand in a day or two.
What it doesn't solve: it has few branches and not many channel-shape
changes. It tests the format of the model (nesting, ids, naming). It won't
test the hard parts: predicate recovery, OR, lane folding. Those still need
rnaseq-flow, and later nf-core/rnaseq.

**Steps:**

1. ~~Run `-preview -with-dag` on fetchngs with its `test` profile, and on a
   few `download_method` values or whatever its main branching params are.
   This settles the nesting and label format.~~ Done 2026-10-10; see the
   findings above.
2. Write a versioned JSON schema for `channels.json` using both pipelines:
   rnaseq-flow for depth, the fetchngs DAGs for nf-core structure. It
   includes:
   - `path` for subworkflow nesting,
   - predicates keyed on params, in two kinds: `when` (exists) and
     `flows_when` (receives items, with an optional data clause),
   - per-field provenance for contents: inferred / harvested / annotated /
     unknown,
   - operator fingerprints as ids.

   Draft 0.1 done 2026-10-10: `schema/channels.schema.json`, with the
   reasoning and the prototype conversion table in `schema/README.md`.
3. Convert rnaseq-flow's `channels.json` into it. This is fixture #1.
   **Constraint (2026-10-10): the rnaseq-flow repo is not changed until the
   viewer is complete.** Its `channel-schematic/` files are read only. Any
   converted copy is written to `process-flow/fixtures/`, never back into
   rnaseq-flow; moving rnaseq-flow itself onto the new schema is a
   separate step after the viewer ships.

   Done 2026-10-10: `tools/convert_prototype.py` writes
   `fixtures/rnaseq-flow.json` (218 nodes, 301 edges, 14 runs, one failed).
   It validates against the schema; every converted `when` matches the
   prototype's own `holds()` on the 14 preview settings plus 20,000 random
   viewer settings; starvation matches on the preview settings; and the
   processes each `when` predicts match all 13 preview DAGs. The reference
   predicate evaluator is `tools/predicates.py`.
4. Hand-model fetchngs in the same schema. This is fixture #2.

   Done 2026-10-10: `fixtures/fetchngs_spec.py` builds `fixtures/fetchngs.json`
   (44 nodes, 61 edges, 8 runs) from the 1.13.0 source copied to
   `working_docs/fetchngs-src/`. It validates, and for all 8 preview runs the
   predicted processes, operators and edges equal the DAG's as multisets,
   with edges matched on endpoint kind plus edge label (a first, crude answer
   to the matching problem, enough at this size). `tools/dot.py` is the DOT
   reader. Three more findings from the modelling:

   - **Topic channels are not wired in the DAG.** Versions go through
     `channel.topic('versions')`; each process's versions emit is a loose
     point and the topic is a separate source point. The versions lane exists
     in the code but not in the DAG, so it can only be modelled from source.
   - **A reassigned channel moves an edge.** `ch_sra_metadata` is reassigned
     inside `if (!skip_fastq_download)`, so `CHANNEL_SRA_CREATE_CSV` reads
     from a different upstream node depending on the setting: two edges exist
     only when downloads are skipped, two only when they are not. Comparing
     DAGs recovers this correctly as long as edges are matched by endpoints.
   - **A subworkflow with no processes is invisible.** `CHANNEL_SRA_CREATE_CSV`
     is eight operators and no process, and nothing in the DAG says so.
     Operator paths, and so subworkflow grouping for operators, have to come
     from the source.

   The spec also prints each process's display state under each
   `download_method`. It is the acceptance table for Phase 2's closure
   evaluator.

Practical check before step 1: the fetchngs test samplesheet is a remote URL.
`-preview` doesn't run any processes, but reading the samplesheet in the main
script may still need the network, so do that first preview somewhere with
network access.

### Phase 1: Tier A, a generic viewer

- Build the filter controls from `dimensions`.
- Generic `holds()`.
- Colouring driven by a "route dimension" the user names, with a palette
  assigned automatically when none is given.
- Lanes read from data.
- Collapsible subworkflow groups.
- Done when the rnaseq-flow page is unchanged when built from the generic
  template, and the same template draws fetchngs. Verified by reading
  `getComputedStyle`, as the earlier colour bug taught, not by reading back
  the attributes the code set.

**Status 2026-10-10: built, one open decision.**
`viewer/template.html` + `viewer/build.py` (`python viewer/build.py
fixtures/<model>.json` writes `out/<model>.html`, self-contained, dagre
inlined). Filters, lanes, subworkflow boxes and collapsing, colours, legend
and the detail panel are all driven by the model; nothing in the template
names a pipeline. Verification:

- **JS against Python.** `tools/js_parity.py` writes random settings with the
  state `tools/predicates.py` gives every element; the page's `window.PF`
  agrees on all 207,600 (rnaseq-flow) and 42,000 (fetchngs) checks.
- **Against the prototype, by computed style.** Both pages loaded side by side
  from one origin, driven through 14 filter scenarios (routes, `--gtf`,
  `--stop_at` in hide mode, `--counts`, flags, the helper workflows, glob
  input), every drawn node and edge compared on computed stroke colours, dim
  and starved: 3,955 comparisons, identical in 13 scenarios. Default view
  draws 124 nodes and 205 edges, as the prototype does.
- **fetchngs routing.** Ticking each download method gives the states in the
  acceptance table above; `--skip_fastq_download` dims the four routes;
  unsetting `--sample_mapping_fields` starves MULTIQC_MAPPINGS_CONFIG;
  collapsing the sra-tools subworkflow folds its four nodes into one.

Three bugs found by the comparison and fixed: the folded hub-to-target edge
needs the target's predicate as well as the hub's; starved elements must keep
their route colour when another setting starves them; and fetchngs had to use
the reserved `shared` category for its trunk.

**Decided 2026-10-10: starvation under "any" (option 3, `implies`).** With
STAR ticked and `--gtf absent` but `entry` left at "any", the prototype marks
DESEQ2 and EDGER starved; the first version of the viewer did not, because
under `entry = counts` they would run. Resolved by letting a dimension declare
what it implies (an aligner implies `entry = reads` in RNASEQ), making
evaluation exact over the remaining "any" settings, and judging starvation
only where the element exists; see `schema/README.md`. The same mechanism
covers nf-core/rnaseq's `skip_alignment` masking `aligner`.

Re-verified after the change: parity 0 mismatches on both fixtures;
against the prototype, 14 scenarios and 3,955 comparisons, identical except
one intended difference. Ticking any aligner now dims the `--counts` entry
chain (`--counts`, its `fromPath`, two edges), since an aligner run never
takes `--counts`; the prototype left it lit. A first attempt that also had
`entry`, `input`, `stop_at` and `strandedness` imply `workflow = RNASEQ`
dimmed the helper workflows whenever any of those was set, which contradicts
the prototype's decision to draw the helpers as part of every route; those
implications were removed. A restyle on rnaseq-flow takes about 250 ms.

### Phase 2: Tier B, topology and predicates

**Step 1, operator matching: done 2026-10-10.** `tools/align.py` merges a
pipeline's preview DAGs into one union graph in which every node and edge
records the runs it was seen in; `tools/test_align.py` checks it against both
fixtures. How it matches, since DOT ids are positional:

- Processes are anchors, matched by name.
- Every other node is matched to a union node of the same type by evidence:
  neighbours already matched through an edge with the same label, an equal
  upstream signature (a hash of the chain above it, out to the nearest
  processes), an equal downstream signature. Strongest pairs first, round by
  round, so matches spread out from the processes. Signatures of nodes with no
  inputs (or no outputs) are shared by every such node and do not count.
- A conflict rule keeps apart what never meets in one run: two nodes whose
  inputs (or outputs) anchor to different processes, following single-input
  chains (`first`, `map`, `collect`) up to the process, are different
  operators. Without it, the four per-aligner `collect`s and the per-route
  versions `mix`es were merged into one node each.
- Readable ids from the nearest anchors, e.g. `map@sra_metadata>samplesheet#0`.

Results. **fetchngs: 33 of 33** processes and operators have exactly the
presence the fixture predicts; the union has the fixture's 61 edges; merge
order has no effect. **rnaseq-flow: 112 of 115**, and every difference traced
to the code:

- One `collect` in the fixture is two in the code (`rnaseq.nf:488` and `:514`);
  the union has two. The union is right, the fixture coarser.
- DIFFSPLICE is called from two mutually exclusive places (genome and
  pseudo-aligner routes). A DAG shows both as one process, so the union has
  one DIFFSPLICE and one versions `mix` for it where the fixture, reading the
  code, has two. **A limit of working from DAGs:** two call sites of one
  process in exclusive branches cannot be told apart.
- `channel.empty` sources (24) are in the DAGs but not modelled by the fixture.

Known weaknesses: runs are merged in a canonical order (widest first, then by
name), so the output is deterministic, but it is not fully order-independent.
Over 20 random orders rnaseq-flow's result moves for 26 output points (the
anonymous points of unconsumed emits, matched by position only) and one
`join`. Neither affects the processes or the routes; both are reported by the
test rather than hidden.

**Step 2, proposing dimensions and the matrix: done 2026-10-10.**
`tools/propose.py SCHEMA --source DIR [--profile-config conf/test.config]`
writes `proposal.json` (every param, proposed or not and why, proposed ones
already in dimension form, an `include` flag to edit) and `runs.tsv` for
`tools/preview_matrix.sh` (baseline plus one run per non-default value). Rules
as listed in the fetchngs findings, plus: output, resource and notification
plumbing is skipped; an enum with no default gets an explicit `unset` value;
the test profile's params become the baseline. With `--source`, only
workflow-level code counts as a condition (not modules/, not config, not
nf-core's `utils_*` subworkflows): a param never tested gets one check run
instead of one per value, and a free-text string that is tested
(`filter { sample_mapping_fields }`) is proposed as set/unset.

Against the fixtures: for fetchngs it proposes exactly the fixture's three
dimensions plus `dbgap_key` (tested, but the earlier matrix showed it leaves the
graph alone) and a check run for `nf_core_pipeline`: 8 runs, the matrix run by
hand on 2026-10-10. For rnaseq-flow it proposes every dimension the prototype
chose (stop_at, aligner, strandedness, gtf, the seven flags, download_refs and
build_indices for the workflow, counts for the entry) plus index paths and
`design`, which the code tests only to raise an error: 31 runs. It cannot see
CSV against glob `--input`, which is the shape of a value rather than a param,
or that `stop_at` is ordered.

1. Read `nextflow_schema.json` and propose dimensions. The user confirms which
   params actually change the graph.
2. Design the set of preview runs. A full factorial design is impossible for
   nf-core/rnaseq. Use:
   - a baseline run,
   - one run per value of each dimension,
   - pairwise runs only where the one-at-a-time results suggest the
     dimensions interact.
3. A matrix driver runs `-preview -with-dag`, records any failed run and
   carries on.
4. Parse the DOT files, align them across runs using the fingerprints, and
   recover extensional predicates ("present in these runs").
5. Reduce them to intensional predicates where possible. With a
   one-at-a-time design that is mostly direct; logic minimisation handles the
   rest. This mostly settles the open question in the design note.
6. **Validate against the gold fixtures:** the regenerated topology and
   predicates must match the hand-built models. Any difference is either a
   bug in the tool or a transcription error in the spec.
7. Then fetchngs as the smoke test, then nf-core/rnaseq.

**Step 4, inferring `when` from observations: done 2026-10-10.**
`tools/infer.py`: for each element, the runs it was seen in and every run's
settings give a predicate true in exactly those runs. Start from the most
specific conjunction the positive runs allow, then drop or widen conditions
one at a time, each step the move that keeps every negative run excluded and
covers the most positives; ordinal lists become upper ranges where no
negative contradicts it (`stop_at >= postQC`, taking in GSEA, which no run
tried). If no single conjunction fits, an `any` of such terms, each grown from
an uncovered positive run, with terms the others cover dropped. Every result
is checked against every run; repeating the generalisation in several orders
gives the alternatives that fit equally well, i.e. the ambiguity, and
`tools/test_infer.py` proposes the run that settles most of it.

Results on the real preview DAGs (`tools/test_infer.py`): fetchngs, all 117
elements fit every run and all 9 processes match the fixture on 5,000 random
settings. rnaseq-flow, all 566 fit every run, but only 7 of 30 processes
generalise as the code does: the prototype's 13-run matrix switched the
optional flags on together, so "TXIMPORT needs `--dtu`" fits the runs as well
as the truth. No inference can separate confounded dimensions; 127 elements
are flagged ambiguous, and one extra run (Kallisto with `--diffsplice` and a
transcript FASTA) would settle 114 of them.

To test the inference apart from the matrix (`tools/test_infer_synthetic.py`):
the rnaseq-flow fixture's hand-written predicates as truth, runs synthesised
as settings, presence computed from the truth. 118 processes and operators,
14 dimensions:

| Design | Runs | Seen | Exactly right on random settings |
|---|---|---|---|
| one change at a time from a baseline | 21 | 94 | 40 |
| pairwise covering (`tools/matrix.py`) | 22 | 87 | 35 |
| pairwise + runs chosen to settle ambiguity | 47 | 87 | 38 |
| pairwise + local probes, one round | 189 | 113 | 81 |
| pairwise + local probes, two rounds | 256 | 115 | 109 |

fetchngs (3 dimensions) is exact under every design. What this decides for
step 3:

- **One change at a time is not enough.** An element that needs two or more
  non-default settings together is never seen (DOWNLOAD_GMT needs the DOWNLOAD
  workflow and `--download_gmt`), and a real union graph would not even know it
  exists.
- **Pairwise is not enough either.** Many rnaseq-flow elements need three to
  seven settings at once (ISOFORM_SWITCH: reads, Salmon, a GTF, a transcript
  FASTA, `--isoform_switch`, `stop_at >= GSEA`); and to learn that a condition
  matters, a run is needed where every other condition holds and that one
  fails.
- **Local probes do it:** once an element has been seen, change every
  dimension one at a time around a run it was seen in (seeds chosen to cover
  every element seen so far), and repeat with what the probes reveal. Two
  rounds see 115 of 118 and get 109 exactly right.
- **The cost is the problem:** 256 previews at 10 to 30 seconds is one to two
  hours in WSL. Step 3 has to cut it, by probing only around elements whose
  predicate is not yet settled and stopping when nothing is ambiguous.

Remaining weaknesses: predicates that are a genuine `any` of several terms
(GSEA, GPROFILER: counts entry, or a genome aligner, or a pseudo-aligner with a
GTF) are approximated, not recovered; an extra condition can survive when the
probes that would remove it share a seed with it (DTU picks up "no
`--isoform_switch`"); and elements needing many settings at once (3 of 118
here) can stay unseen. The rnaseq-flow fixture's BUILD_INDICES predicates use
`aligner = all`, which is not one of the dimension's values: a prototype quirk.

**Step 5, the draft model with no annotations: done 2026-10-10.**
`tools/generate.py` goes from preview DAGs to a schema-valid channel model the
viewer builds directly, the floor the plan promises:

    python tools/generate.py --name NAME --dims proposal.json --runs dags/runs.tsv -o model.json
    python viewer/build.py model.json

It aligns the DAGs (step 1), infers a `when` for every node and edge (step 4),
takes process paths from the DAG labels and finds the prefix every process
shares, gives every other node the group most of its nearest processes sit
in, and detects lanes: operators whose every downstream labelled channel is
versions or MultiQC plumbing (`ch_versions`, `ch_multiqc_files`) form a folded
lane with its hub where the lane leaves for a process; inputs that are
scripts, templates or images (`r_script`, `qmd_template`) a hidden one. The
route dimension is `--route`, or the enum that splits processes into the most
distinct groups (`aligner`: six; `workflow`, which every process names: three).
Channel contents are left empty.

Generated from the DAGs alone (`--from-model` takes only dimensions and run
settings from the fixtures):

- **fetchngs:** 56 nodes, 61 edges, prefix `NFCORE_FETCHNGS:FETCHNGS` found,
  versions lane found; `--skip_fastq_download` dims exactly the six download
  processes. No route: the download method routes inside a `branch`, which no
  DAG shows.
- **rnaseq-flow:** 255 nodes, 311 edges, route `aligner`, lanes versions (37
  nodes; the prototype 42), MultiQC (17; the prototype 34, counting its
  hand-added channel nodes) and assets (19; the prototype 20). Ticking STAR
  lights the STAR line and dims the other aligners' processes. It draws 184
  nodes by default to the prototype's 124: the extra are anonymous output
  points (emits nothing reads) and `channel.empty` placeholders. DTU, TXIMPORT
  and ISOFORM_SWITCH stay lit on the STAR route because the prototype's runs
  never separated `--dtu` and friends from the pseudo-aligners; that is for the
  step 3 matrix to fix.

One inference fix came out of it: when generalisation moves tie, the condition
that rules out the fewest negative runs on its own is dropped first, so the
informative one survives (KALLISTO_QUANT, seen in one run, keeps
`aligner = kallisto` instead of `dtu`). On the real rnaseq-flow DAGs this took
processes that generalise like the code from 7 to 10 of 30 and ambiguous
elements from 127 to 21; on the synthetic test, two probe rounds now get 111
of 118 exactly right, none ambiguous.

**Step 3, the preview matrix: built 2026-10-10; first real batch to run.**
An adaptive design in batches, because real runs happen in batches in WSL:

    python tools/adaptive.py --dims proposal.json --dags dags [--values values.json] -o next.tsv
    bash tools/preview_matrix.sh -j 4 PIPELINE next.tsv dags -- -r REV -profile test
    ... repeat until the planner says nothing is left, then tools/generate.py

- **First batch:** the baseline and 10 random runs leaning towards enabling
  values (flags on, paths set), which reveal most elements at once.
- **Later batches** (`next_batch` in `tools/matrix.py`): an element (node or
  edge) is settled when a run it appears in has had every one-change
  neighbour run (a fully probed seed), and every other run it appears in fits
  what that seed showed (else it is another branch of an `any` and needs its
  own seed). Seeds are chosen greedily to settle the most unsettled elements;
  only neighbours not yet run are added.
- **The driver** (`tools/preview_matrix.sh`) now runs previews in parallel
  (`-j N`, each in its own launch folder so Nextflow's locks do not collide),
  skips runs already made (resumable; batches share one folder), appends to
  `runs.tsv`, and evaluates each run's args so `--x ''` passes an empty value.
- **Path params** need a real file when a run sets them: `--values` maps each
  to one.

On the synthetic rnaseq-flow test, the cost/accuracy trade-off:

| Design | Runs | Seen of 118 | Exactly right |
|---|---|---|---|
| fixed: pairwise + two rounds of probes | 256 | 115 | 111 |
| adaptive from pairwise | 269 | 115 | 115 |
| random runs only, leaning towards enabling values | 80 to 120 | 112 to 118 | 38 to 75 |
| **adaptive from 10 such random runs** | **229 to 261** | **118** | **118** |

The adaptive design from a random start sees every element and gets every
predicate exactly right. It does not use fewer runs: exact predicates need
"everything the same but one setting" contrasts, about 20 around each of the
eight or so seeds rnaseq-flow needs (one per aligner, the counts entry, each
helper workflow, the low `stop_at` and no-GTF variants). Smarter probing would
save perhaps a third, not most. So the answer to "256 runs is an hour or two"
is to make runs cheap rather than few: four previews at a time is about
fifteen minutes, in three or four batches. Random runs alone are good for
discovery but poor for exactness, because they rarely give the one-setting
contrasts.

On the real fetchngs DAGs the planner asks for six runs: the baseline with
`--sample_mapping_fields ''` (the last unrun neighbour of the baseline), and
five neighbours of the skip run, which settle the samplesheet edges that only
exist when downloads are skipped.

**First real loop, 2026-10-10: converged.** The six runs ran in WSL four at a
time. Two failed at first: Nextflow reads `--param ''` as `true`, so nf-schema
rejected `--sample_mapping_fields (true): Value is [boolean] but should be
[string]`. An empty string cannot be passed on the command line at all; the
driver now turns every `--param ''` into an entry in a per-run
`-params-file`, where JSON keeps it a string, and the two reran clean. The
planner then reported nothing left to run after 14 runs. `tools/generate.py`
from the proposal, `runs.tsv` and the DAGs alone gives 117 predicates of three
shapes (`no skip_fastq_download` 61, always 54, `skip_fastq_download` 2, the
samplesheet edges fed from the runinfo), every process agreeing with the
fixture.

Two generator changes from it: a rerun replaces an earlier attempt in
`runs.tsv`; and a dimension no predicate uses is dropped from the model only
when the matrix has shown it changes nothing (some pair of runs differs in it
alone with identical graphs). fetchngs drops `download_method` (routes inside
a `branch`), `dbgap_key` and `sample_mapping_fields` (a run-time `filter`),
leaving `skip_fastq_download` as the page's one filter. The generated
rnaseq-flow model, from the prototype's confounded matrix, keeps
`isoform_switch`, `ctat_lib`, `download_gmt` and `input`, which no predicate
uses but no run varied alone, and says so.

**nf-core/rnaseq end to end: done 2026-10-11. Phase 2 complete.**

Release 3.27.0 (the first attempt picked 3.9 by sorting tags as text; 3.9's
config defines `check_max()`, which Nextflow 26's config parser rejects, so old
nf-core releases cannot be previewed on current Nextflow at all). Baseline
preview: 67 processes, 407 operators, 832 edges, nested six levels deep.

- **Dimensions.** The proposer found 69 candidates (136 params); 79
  neighbour runs per seed was too many, so the user chose the eight choice
  (enum) dimensions for this matrix. It also exposed a blind spot: nf-core
  builds its QC tool list in `utils_nfcore_rnaseq_pipeline` from
  `--skip_preseq` and friends, so `utils_*` subworkflows are now scanned.
- **Making the test profile previewable.** With `--fixed`, the same args in
  every run: `--transcript_fasta null` (with spike-ins and no Kallisto index,
  3.27 refuses to build one, issue #1450) and dummy `--sylph_db` and
  `--sylph_taxonomy` files. An empty string cannot be used for a path
  (nf-schema rejects it), so the driver turns `--x null` into JSON `null` in a
  per-run params file. `tools/localise_testdata.py` downloads the profile's
  remote files once (22 files, including the samplesheet's FASTQs, rewritten
  to local paths), so previews never fetch.
- **The "stalls" were the terminal.** Nextflow runs `stty -echo < /dev/tty`;
  a background job that touches the controlling terminal is stopped by the
  shell (state `T`), and frozen previews held 10 GB. Each preview now runs
  under `setsid` with no terminal, `-ansi-log false`, stdin from /dev/null,
  and a `PREVIEW_TIMEOUT`. No stall since.
- **A real constraint:** screening `unmapped` reads needs an aligner that
  makes them (runs r099, r153, r165 failed on it). Declared as an `implies` on
  `contaminant_screening`, so the planner stops proposing it; and a value
  forbidden at a seed now counts as unknown, not as the element vanishing
  (counting it taught false conditions and kept the planner asking for runs).
- **Speed at this scale.** Alignment of 170 runs went from over an hour to
  6.6 s (a tie-break re-sorted nodes for every comparison; plus a fast path
  for nodes whose type and both signatures were seen on exactly one union
  node). Inference runs once per distinct run set: 2,289 elements, 63 sets,
  the model in 18 s. The viewer repaints in place instead of re-laying out
  on a filter change: 7.7 s to 16 ms on ~1,000 nodes, checked identical to a
  full render.

The matrix: batches of 11, 162, 142, 34 and 11 runs, 357 succeeded, 3 failed
on the constraint, about 50 to 65 s per preview, six at a time. The union
graph stopped growing after batch 2 (1,064 nodes, 1,225 edges). The final
model: 2,289 elements, every inferred predicate agreeing with every run (no
disagreement in 2,289 × 357). `umi_dedup_tool` dropped as proven to change
nothing with `--with_umi` off. 101 processes: 51 always, the rest by aligner
(`star_rsem` 8, `hisat2` 8, `bowtie2_salmon` 7, STAR either way 7, Salmon
after an aligner 6, any aligner that makes unmapped reads 1), trimmer,
pseudo-aligner and screening tool. Route `aligner`, prefix `NFCORE_RNASEQ`.

Left open: two MultiQC bundle edges stay unsettled (an `any` branch seen in
three runs; a 10-run batch to confirm it is planned), and one `join` in the
same bundle chain has a noisy four-branch predicate using
`ribo_removal_tool` and `umitools_grouping_method`, almost certainly an
alignment ambiguity in a chain of near-identical joins. Both are folded MultiQC
plumbing. The page is 5.6 MB, mostly `observed_in` lists, and takes about six
seconds to lay out on first load.

**Documentation: written 2026-10-11.** `README.md` (what it is, quick start,
results, layout, limits) and `docs/guide.md` (the full workflow on any
Nextflow pipeline: working folder and pinned release, choosing dimensions and
declaring `implies`, making a test profile previewable with fixed args and
local test data, the batch loop, building the page, reading it, a
troubleshooting table drawn from the real failures, and what a DAG cannot
show).

### Phase 3: Tier C, contents in layers

**Step 1, static contents: done 2026-10-11.** `tools/generate.py --source DIR`
reads the pipeline's code (`tools/modules.py`): every process's input and
output declarations as shapes (`tuple val(meta), path(reads)` is
`[meta, reads]`), `include ... as` aliases, and each process call's
arguments. `tools/ports.py` then works out which input each DAG edge fills
and which emit it carries, since the DAG does not say and its edge order
follows channel creation, not declarations:

- inputs: the edge label is the call's argument there, or (for a non-channel
  argument) the input's own name; else the argument's last operator matches
  the edge's source; else the one input left in that run. An input can be
  filled by several union edges that never meet in one run (KRAKEN2 reads
  trimmed, raw or unaligned reads, by setting).
- outputs: the label is the emit's name or a variable it flows into, followed
  through reassignments, through a variable holding the process itself
  (`ch_star_out = STAR_ALIGN`, then `ch_star_out.out.fastq`), and up the call
  path through each workflow's `emit:` block (`ch_unaligned_sequences =
  ALIGN_STAR.out.fastq`, two levels up); else an operator or process the code
  applies to it; else a bare point takes an emit nothing reads, `topic:`
  emits first.

Each process node gets its module, each boundary edge its port
(`emit tsv -> input 1`) and the declared shape, marked `declared`; the
producer's names unless they are an unresolved `${...}`, then the consumer's.
Shapes then pass through operators that do not change them (`filter`,
`unique`, `first`, `mix` of like shapes, ...), forwards and backwards, marked
`inferred`. The viewer's edge panel shows the port.

Results (`tools/test_contents.py`): fetchngs, all 31 declared shapes in the
hand-built fixture are on the right port with the right form (11 with
identical text; the rest differ in notation, the parser keeping declared names
where the fixture wrote `path`). nf-core/rnaseq, all 101 processes matched to
a module, 671 of 697 process-boundary edge ends shaped (96%). Over all edges:
fetchngs 39 of 61 shaped (36 declared, 3 inferred), nf-core/rnaseq 662 of
1,225 (639 declared, 23 inferred). The rest sit between operators whose output
depends on a closure (`map`, `join`, `combine`, `collect`): steps 2 and 3.

Bugs found on the way: the brace matcher read an apostrophe in a `//`
comment as a string and cut nf-core/rnaseq's RNASEQ workflow short (KRAKEN2's
call was not found); and a port could take only one edge.


1. Static: parse module declarations to get shapes at process boundaries,
   then fill operator chains that don't change shape.
2. Runtime: the plugin or work-directory harvest gives meta keys, item counts
   and worked examples. This replaces the 103 rules in `harvest_examples.py`.
3. An annotation file for what is left, keyed by fingerprint, with
   stale-key detection.
4. A coverage report, e.g. "212/301 edges have shape; 41 unknown, listed".
   This keeps the prototype's rule that an unknown edge is a finding, not a
   gap.

### Phase 4: checks become generator and linter

- Generalise checks 1 to 4.
- Tighten check 4 to compare operator positions instead of counts.
- Make the tool usable in a pipeline's CI to catch drift.

### Phase 5: prove it works outside RNA-seq

- Run it on nf-core/sarek or nf-core/methylseq.
- Package it as a CLI with a pinned Nextflow version range, since the DOT
  format is internal and can change between releases.
- Ship rnaseq-flow's annotations as the fully annotated example.

## Risks and open questions

- **Operator identity (Tier B):** if fingerprints are unstable, both predicate
  recovery and annotations fail. Prototype this in the first week, against
  the 14 DOT files already in `channel-schematic/dags/`.
- **Number of preview runs:** no longer a risk. fetchngs previews take about
  10 seconds; nf-core/rnaseq will be slower but not by an order of magnitude.
- **Routing done with `branch`:** comparing DAGs cannot see it (see the
  fetchngs findings). Checked against nf-core/rnaseq on 2026-10-10
  (`workflows/rnaseq/main.nf`): the aligner routes are ordinary `if` blocks
  (`params.aligner == 'star_salmon'`, `'star_rsem'`, `'hisat2'`,
  `params.aligner.contains('star')`, `params.pseudo_aligner == 'salmon'`),
  each combined with `!params.skip_alignment`. So comparing DAGs carries the
  main routes, and closure evaluation is a secondary feature, built after it.
  The one `branch` in that file (line 390) splits STAR output on mapping
  rate: a `flows_when` with a data clause and no param clause at all. Two
  further points for Phase 2: `skip_alignment` masks `aligner`, so the matrix
  needs that pair; and line 132 gates on a derived variable
  (`salmon_index_available`) built from three params, which comparing DAGs
  handles but reading the source would have to trace. Subworkflows were not
  searched; there may be more `branch` routing below the top level.
- **Previews that need real files:** nf-core `test` profiles provide them,
  but some branches won't resolve. STAR_FUSION needed a CTAT library in
  rnaseq-flow. The schema needs a "not previewed" flag (the prototype already
  has `previewed: false`).
- **The language server:** the Nextflow VS Code extension can preview a
  workflow's DAG straight from source, without running it. It's worth
  checking how it shows `if` blocks. If it keeps the conditions, it would give
  predicates directly in the readable `aligner=star` form, without running a
  matrix of previews. One afternoon of looking before committing to Phase 2.

Phases 0 and 1 are low-risk refactoring of code that already works. The real
research is the fingerprint problem at the start of Phase 2, so test it
against the existing DOT files before committing to the rest.
