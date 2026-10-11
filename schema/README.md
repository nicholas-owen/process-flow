# The channel model schema, draft 0.1

*2026-10-10. Phase 0, step 2 of
[the plan](../working_docs/channel-viewer-plan-2026-10-10.md). Drafted from
the rnaseq-flow prototype's `channels.json` and the fetchngs 1.13.0 previews.
Not yet tested against a full conversion of either fixture; expect changes
when that happens.*

- [channels.schema.json](channels.schema.json): JSON Schema, draft 2020-12.
- [examples/fetchngs-branch.json](examples/fetchngs-branch.json): a
  hand-written excerpt covering the hardest case found so far, the fetchngs
  `branch` closure. It validates.

## What changed from the prototype, and why

**Predicates are keyed on dimensions, never on bare keys.** The prototype's
`when` mixed dimension ids (`aligner`), derived values (`entry`), a suffix
convention (`level_min`) and a flag list (`flags`) at one level. Now:

```json
{ "params": { "aligner": ["star", "hisat2"], "stop_at": { "min": "postQC" }, "gtf": { "present": true } },
  "any": [ ... ], "not": { ... }, "data": [ ... ] }
```

Everything under `params` names a declared dimension. A list is "one of", a
scalar is "equals", `{min}`/`{max}` work on ordinal dimensions, and
`{present}` on presence dimensions. Parts are ANDed; an empty predicate always
holds. Keeping `params` separate from `any`/`not`/`data` means a pipeline with
a param called `any` or `data` cannot collide with the structure.

**Two predicates per element.** `when`: the element exists in the graph.
`flows_when`: it receives items. fetchngs showed that a pipeline can route
entirely inside a `branch` closure, with every route present in every DAG, so
existence alone says nothing. The prototype's `starved` and `starved_when`
become a `flows_when` with a `not`.

**`data` clauses.** A `flows_when` can depend on the items as well as the
settings (`meta.fastq_aspera`: the sample has an Aspera link). The viewer
cannot filter on these. They decide the third display state.

**Display state**, computed by the viewer for the current settings:

| `when` | `flows_when`, param part | `data` part | State | Drawn |
|---|---|---|---|---|
| false | | | absent | dimmed or hidden |
| true | false | | starved: wired, gets nothing | starved marker |
| true | true | present | may receive items, depending on the samples | dashed |
| true | true (or absent) | none | receives items | solid |

Evaluation is three-valued (true, false, unknown), implemented in
[tools/predicates.py](../tools/predicates.py). A setting left at "any", a
setting with several values ticked that only partly match, or a `data` clause
all give unknown. `when` is drawn unless definitely false; starved is shown
only when `flows_when` is definitely false. The JavaScript viewer has to agree
with that file, and `tools/js_parity.py` checks that it does.

"Definitely" is exact, not just Kleene logic. When the quick evaluation says
unknown, `given()` enumerates the settings still at "any" that the predicate
mentions and answers true or false only if every combination agrees. Two
things narrow the combinations:

- **`implies` on a dimension** (added 2026-10-10): what setting it
  explicitly implies about the others. rnaseq-flow declares that an aligner
  means the reads entry in RNASEQ (`implies: any[{workflow: DOWNLOAD |
  BUILD_INDICES}, {workflow: RNASEQ, entry: reads}]`), so ticking STAR rules
  out the `--counts` entry without touching the helper workflows. fetchngs
  declares that a download method implies downloads are not skipped.
  Implications are not chained, and only explicitly set dimensions bring
  theirs in.
- **Existence, for starvation.** `flows_when` is judged only among the
  combinations where the element's `when` holds: DESEQ2 cannot count as
  "receiving items" in a combination where it does not exist.

Together these mean STAR ticked with `--gtf` absent marks DESEQ2 and EDGER
starved even with the entry left at "any", as the prototype did; the
prototype got there by treating "any" as a match key by key, which this
generalises.

A `data` clause inside an `any` makes that alternative "may" rather than
false: under `download_method ftp`, SRATOOLS_PREFETCH is dashed (fallback for
samples with no links), not dimmed.

**Provenance on everything derived.** `when_from`, `flows_when_from` and
`contents.from` record where each value came from: `preview`, `inferred`,
`declared`, `evaluated`, `harvested`, `annotated` or `unknown`. The coverage
report in Phase 3 counts these, and the panel shows them, so a reader knows
whether a shape was read from a module declaration or guessed.

**`observed_in` replaces `previewed`.** The prototype put `previewed: false`
inside `when`, where it is not a condition. It is now a list of run ids per
element, pointing into `runs`, the record of the preview matrix with each
run's full settings. An element transcribed from code alone has an empty list.
This is also the raw material for recovering `when`.

**Ids are never DOT ids.** `v48` in one run is `v21` in another (fetchngs,
`MULTIQC_MAPPINGS_CONFIG`). Process ids are the colon path. Operator ids come
from a `fingerprint`, whose form is a placeholder until the matching algorithm
exists. The example uses
`NFCORE_FETCHNGS:FETCHNGS/op:branch@ch_sra_metadata#0`.

**Nesting.** `path` on every node, outermost first. `pipeline.prefix` names
the segments every process shares (`NFCORE_FETCHNGS`, `FETCHNGS`), which the
viewer hides. `groups` only decorates subworkflows; membership comes from
`path`. `module` and `alias_of` handle one module included in several places.

**Contents are grouped and all optional.** Shape, meta, cardinality and files
move under `contents`, so a zero-annotation model is valid with no contents at
all. `meta` becomes `{keys, added, dropped}` or `null` for items with no meta
map, instead of free text with "n/a". Cardinality becomes
`{kind, per, text}` with a fixed `kind`.

**Routes and palette are separate.** `routes` names the dimension drawn as
metro lines and colours its values. `palette` colours categories that keep
their colour whatever is selected (QC, reporting). The prototype had both in
one `palette` object, and the template knew which keys were aligners.
`palette.shared` is reserved: it is the trunk colour, and elements in the
`shared` category (or with no category) are coloured by the routes they sit
on, like route categories. Every other palette key is fixed.

**Route membership, for colouring.** An element is on a route when it exists
under that route and the route value alone does not starve it. Starved by
another setting (no GTF on a STAR run) it stays on the route, drawn in the
route colour with the starved hatching; starved by the route choice itself
(ASPERA_CLI when the method is ftp) it is not on that route.

**Lanes declare their hub, target and starting mode.** This removes the
hard-coded `RNASEQ.ch_versions` and `RNASEQ.ch_multiqc_files` from the
template. `mode` is `folded`, `expanded` or `hidden` on first load (the
prototype's staged-assets lane starts hidden). `detected` marks lanes found by
fan-in heuristics rather than declared.

**`meta.text`** carries what a key list can't: "dropped", keys that differ by
route, "as bare values". Six prototype edges need it.

**Two forms: `full` and `published` (added 2026-10-11).** A full model, as
`tools/generate.py` writes it, carries its evidence: the `runs` table and
every element's `observed_in`. That is most of its size (8.5 MB of
nf-core/rnaseq's model) and holds the author's local paths. The published
form, written by `tools/publish.py`, is what a pipeline ships for the
Explorer. It drops both, and summarises them in `generated.evidence`:

- runs that worked and failed, with each failure's settings and error;
- args fixed in every run, with paths reduced to file names;
- dimensions dropped, dimensions never varied alone, and params the code
  tests but the matrix held fixed;
- elements left unsettled, also marked `settled: false`;
- disagreements between each `when` and the runs.

It also gains a stamp: `pipeline.repository`, `revision` and `version`, and
`generated.process_flow_version`. A missing `form` means `full`.

## Converting the rnaseq-flow prototype

Done by [tools/convert_prototype.py](../tools/convert_prototype.py), which
reads rnaseq-flow and writes `fixtures/rnaseq-flow.json` here; rnaseq-flow
itself is not changed. The table is what it does.

| Prototype | Schema 0.1 |
|---|---|
| `meta` | `pipeline` + `generated` |
| `dimensions` (dict of lists) | `dimensions` (list of objects with `kind`); `stop_at` becomes `ordinal`, `gtf` becomes `presence`, each entry of `flags` becomes its own `boolean` |
| `palette` | split into `routes` (star, hisat2, salmon, kallisto) and `palette` (the rest) |
| `lanes` (id to label) | `lanes` list with `hub` and `target` |
| node `workflow` | `path` |
| node `starved`, `starved_when` | `flows_when` with `not`; the text into `notes` |
| `when.workflow`, `when.entry`, `when.input`, `when.strandedness` | `params` entries on the matching dimensions |
| `when.aligner` | `params.aligner` |
| `when.level_min: 2` | `params.stop_at: {min: "postQC"}` |
| `when.gtf: true` | `params.gtf: {present: true}` |
| `when.flags: [...]` | one `params` entry per flag: `true` |
| `when.any` | `any`, each alternative converted the same way |
| `when.previewed: false` | removed; `observed_in: []` |
| edge `shape`, `meta`, `cardinality`, `files` | `contents.*` |
| edge `meta: "n/a"` | `contents.meta: null` |
| `cardinality` free text | `contents.cardinality`: per-sample → `{queue, per: sample}`; single → `single`; value → `value`; mixed and "value items mixed into a queue" → `mixed`; queue → `queue`; "single\|value" → `value` with `text` (check each of the 8 by hand) |
| `examples[route].kind: per_sample` | `per_item` |

`entry`, `input` and `workflow` are derived or dispatch dimensions in
rnaseq-flow. Declare them with `param` set (or `null` plus `derived_from`)
rather than pretending they are plain params.

## Open questions

1. **Fingerprint form.** Placeholder until the operator-matching algorithm is
   prototyped against the 14 rnaseq-flow DOT files and the 8 fetchngs ones.
2. **`data` clauses as text.** `expr` is the source expression as written. If
   closure evaluation (Phase 2) needs something structured, it changes here.
3. **Per-route contents.** A shape that differs by route (STAR BAM names
   against HISAT2 ones) is currently expressed through `examples` keyed by
   route. If shapes themselves differ by route on the same edge, `contents`
   may need the same keying.
4. **Ordinal values that are numbers.** rnaseq-flow's `stop_at` maps names to
   run levels (preQC 1 … none 100). The schema orders `values` by position, so
   the numbers are dropped. Fine unless something reads the numbers.
