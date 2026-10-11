# Using process-flow on a Nextflow pipeline

## Seeing a pipeline: one command

```bash
/path/to/process-flow/bin/process-flow run nf-core/rnaseq -r 3.27.0 -profile test,docker --outdir results
```

Open `results/pipeline_info/channels.html`. You need Nextflow 25.04 or later
(for data lineage) and Python 3; nothing else, and no change to the pipeline.

What happens:

1. The pipeline runs as you asked, with one extra config
   (`.process-flow/capture.config`) that turns on `lineage.enabled` and
   writes the run's DAG to `results/pipeline_info/process-flow/dag.dot`.
   Lineage records every task's inputs and outputs, meta maps included, in
   `.lineage` in the launch folder.
2. The model: the pipeline's published one if it ships
   `assets/process-flow/channels.json` (see below), else one built from the
   run's DAG and the conditions read from the code. For nf-core/rnaseq that
   takes about a minute.
3. The run laid over it: meta keys, items, files and where they came from,
   tasks per process, and a check of the run against the model.
4. `channels.html` and `channels.json` in `results/pipeline_info/`.

If the run fails, nothing is explored: fix it and rerun with `-resume`. If a
run was made without process-flow but with `lineage.enabled = true` and
`-with-dag dag.dot`, build the page from it:

```bash
process-flow explore --run-dir . --dag dag.dot
```

On a machine where a task cannot have what the test profile asks for, cap it
in a config (`process.resourceLimits = [cpus: 4, memory: 12.GB, time:
6.h]`) and pass it with `-c`: it changes no channel.

The rest of this guide is **the Analyser**, for pipeline authors who want
exact conditions for every route, published with their pipeline.

## The Analyser

This takes a pipeline from nothing to a published model. It uses
nf-core/fetchngs for the short example and notes what nf-core/rnaseq needed on
top, since that is the harder case.

The idea in one paragraph: a preview (`nextflow run -preview -with-dag`)
draws the graph a run would build, without running anything. One preview shows
one combination of settings. process-flow previews many combinations, lines the
resulting graphs up so the same operator is recognised in every one of them,
and works out for each node and edge the condition on the settings under which
it exists. The viewer then lets you set those settings and see the graph a run
would have.

## Contents

1. [What you need](#what-you-need)
2. [Set up a working folder](#1-set-up-a-working-folder)
3. [Choose the dimensions](#2-choose-the-dimensions)
4. [Make the test profile previewable](#3-make-the-test-profile-previewable)
5. [Run the preview matrix](#4-run-the-preview-matrix)
6. [Build the page](#5-build-the-page)
7. [Publish the model](#6-publish-the-model)
8. [Reading the page](#reading-the-page)
9. [When something goes wrong](#when-something-goes-wrong)
10. [What it cannot see](#what-it-cannot-see)

## What you need

- **Linux or WSL** for the previews. Everything else is plain Python and can
  run in the same place, which is simplest.
- **Nextflow**, recent enough for the pipeline release. Old releases may not
  even parse on current Nextflow (nf-core/rnaseq 3.9's config fails on
  Nextflow 26). Pin a recent release.
- **Python 3.8 or later.** The tools use only the standard library.
  `pip install jsonschema` is optional: with it, every model is validated
  against `schema/channels.schema.json` when the page is built.
- **The pipeline's `nextflow_schema.json`** (every nf-core pipeline has one)
  and ideally a `test` profile, so that a preview has inputs to resolve.

Throughout, `PF` is where process-flow lives and `W` is a working folder for
one pipeline:

```bash
PF=/path/to/process-flow
W=~/pf-work/fetchngs
```

Keep `W` on the Linux filesystem, not on a synced drive: every preview writes
a `.nextflow` folder and a log.

## 1. Set up a working folder

Pull the pipeline at a fixed release, and copy that release's source into
`$W/src`. The source is read to see which params the workflow code tests; the
release is pinned so every preview, and the source, are the same code.

```bash
nextflow pull nf-core/fetchngs
nextflow info nf-core/fetchngs | grep -oE '^\s+[0-9]+\.[0-9]+(\.[0-9]+)?' | tr -d ' ' | sort -V | tail -3
REV=1.13.0
```

Sort the tags with `sort -V`. Sorted as text, `3.9` comes after `3.19`.

```bash
mkdir -p $W/src && git -C ~/.nextflow/assets/.repos/nf-core/fetchngs/bare archive "$REV" main.nf nextflow.config nextflow_schema.json conf workflows subworkflows modules | tar -x -C $W/src --exclude='*/tests/*'
```

(Older Nextflow versions keep the clone at `~/.nextflow/assets/nf-core/fetchngs`
instead; `git -C` that folder works the same.)

Then one preview by hand, to see that the test profile resolves at all:

```bash
cd $W && nextflow run nf-core/fetchngs -r "$REV" -profile test -preview -with-dag baseline.dot --outdir out
```

If it fails, fix that before going further: see
[step 3](#3-make-the-test-profile-previewable) and
[When something goes wrong](#when-something-goes-wrong).

## 2. Choose the dimensions

A dimension is a parameter that may change the graph: an aligner choice, a
skip flag, an optional input. Most params only change a tool's arguments, and
each dimension costs preview runs, so the choice matters.

```bash
python3 $PF/tools/propose.py $W/src/nextflow_schema.json --source $W/src --profile-config $W/src/conf/test.config -o $W
```

It writes `$W/proposal.json` and prints every param with its verdict:

```
  + download_method       enum  tested: workflows/fetchngs.nf:67, ...
  + skip_fastq_download   boolean  tested: workflows/fetchngs.nf:60
  + sample_mapping_fields string tested in a condition: proposed as set/unset
    nf_core_pipeline      enum; never tested in a condition: probably arguments only, one check run
    outdir                output, resource or notification plumbing
```

How it decides:

- **Skipped:** hidden params, the standard nf-core groups (institutional
  config, generic options, deprecated), plumbing (`outdir`, `email`,
  `max_*`), required params, enums with one value, numbers and free text.
- **Proposed:** enums, booleans and paths. An enum with no default gets an
  `unset` value of its own.
- **With `--source`:** only workflow code counts as a test (`main.nf`,
  `workflows/`, `subworkflows/`; not `modules/` or config, whose conditions
  change arguments and resources). A param no condition tests is not
  proposed. A free-text string the code tests (`filter { sample_mapping_fields }`)
  is proposed as set/unset.
- **With `--profile-config`:** the profile's params become the baseline. A
  path the test profile sets is "present" in the baseline, so its run unsets
  it.

**Review the proposal.** Set `"include": true` or `false` on each param in
`proposal.json`. Things only you know:

- **How many is affordable.** The planner probes around each "seed" run by
  changing every dimension one value at a time, so one seed costs one run per
  alternative value: a boolean or a path adds 1, an enum with four values
  adds 3. A pipeline needs a handful of seeds (one per major route, roughly).
  nf-core/rnaseq proposes 69 dimensions, about 79 runs per seed; choosing just
  its eight enums (18 runs per seed) gave a 357-run matrix.
- **Ordered choices.** A param like `--stop_at preQC|postQC|DE` is ordered;
  change its `kind` to `ordinal` so conditions read `stop_at >= postQC`.
- **Combinations the pipeline refuses.** If a pipeline rejects some
  combinations, declare them, so they are never proposed. Add an `implies` to
  the dimension: a condition that holds whenever it is set. nf-core/rnaseq
  screens unmapped reads only with aligners that produce them:

  ```json
  "implies": {"any": [
    {"params": {"contaminant_screening": "unset"}},
    {"params": {"contaminant_screening_input": ["trimmed", "trim_only", "raw"]}},
    {"params": {"aligner": ["star_salmon", "star_rsem", "hisat2"]}}]}
  ```

  You usually find these when a run fails (step 4). The predicate format is
  described in [schema/README.md](../schema/README.md).

## 3. Make the test profile previewable

Three things commonly stop a test profile from previewing cleanly. Deal with
them once, as **fixed args**: the same args added to every run, so they can
never be mistaken for an effect of a dimension.

**Remote test data.** A preview checks that its input files exist while it
builds the graph. With a test profile's remote files that is dozens of HTTP
requests per preview, slow and occasionally stuck. Download them once:

```bash
python3 $PF/tools/localise_testdata.py $W/src/conf/test.config $W/testdata
```

It downloads every `param = 'https://...'` in the profile, and the files a
samplesheet or a list file points to, rewriting those to local paths. It
writes `$W/testdata/fixed_args.txt` with a `--param /local/path` for each.

**A combination the test data cannot support.** nf-core/rnaseq 3.27's test
profile gives a transcript FASTA and spike-ins but only a Salmon index, and the
pipeline refuses to build a Kallisto index from that. Unsetting the
transcript FASTA, in every run, fixes it:

```bash
python3 $PF/tools/localise_testdata.py $W/src/conf/test.config $W/testdata --extra "--transcript_fasta null --sylph_db $W/dummy.syldb --sylph_taxonomy $W/dummy.tax.tsv"
```

A param named in `--extra` is not downloaded, so the extra wins.

**Inputs a value needs.** Some values need a file that the test profile does
not provide (sylph needs a database and a taxonomy). A preview never reads
them, so an empty file is enough: `touch $W/dummy.syldb $W/dummy.tax.tsv`. If
a dimension is itself a path param, give the planner a real path to use when
a run sets it, in a JSON file passed as `--values`:

```json
{"dbgap_key": "/home/me/pf-work/fetchngs/dummy.ngc"}
```

Use absolute paths: each preview runs in its own folder.

**Unsetting a param.** On the command line, Nextflow reads `--param ''` as
`true`, and nf-schema rejects an empty string for a path. So in fixed args and
runs files, write `--param null` to unset it, or `--param ''` for a string
that should be empty. The driver passes both through a params file, where they
keep their type.

## 4. Run the preview matrix

The matrix is built in batches. Each time: plan, run, repeat until the planner
says nothing is left.

```bash
cd $W
python3 $PF/tools/adaptive.py --dims proposal.json --dags dags --fixed-file testdata/fixed_args.txt -o next.tsv
bash $PF/tools/preview_matrix.sh -j 4 nf-core/fetchngs next.tsv dags -- -r "$REV" -profile test
```

Omit `--fixed-file` if you needed no fixed args, and add `--values values.json`
if a path dimension needs one.

**The first batch** is the baseline (every dimension at its default) and ten
random runs leaning towards the enabling values (flags on, paths set), which
show most of the graph at once.

**Every later batch** aligns all the DAGs so far and finds the elements (nodes
and edges) whose condition is not yet settled. An element is settled when some
run it appears in has had every one-change neighbour run (a fully probed
seed), which shows exactly which settings it needs, and every other run it
appears in agrees with that. Seeds are chosen to settle the most elements at
once, and only neighbours not yet run are added. The planner says where it
stands:

```
312 runs so far (3 failed), 1064 nodes and 1225 edges aligned, 8 of 2289 elements not yet settled.
next batch: 34 runs -> next.tsv
```

and, at the end, `nothing left to run: every element seen so far is settled`.

**The driver**, `preview_matrix.sh`:

- runs `-j N` previews at once, each in its own launch folder under
  `dags/launch/`. About 1 GB of memory each; on a 12-core, 16 GB machine six
  at a time was fine for nf-core/rnaseq.
- is resumable: a run whose DOT file exists and succeeded is skipped, so a
  batch can be stopped with Ctrl+C and started again, and all batches share
  one `dags/` folder.
- records every attempt in `dags/runs.tsv` (name, ok or FAILED, args,
  seconds). A rerun replaces an earlier attempt everywhere it is read.
- stops any preview that takes longer than `PREVIEW_TIMEOUT` seconds (600 by
  default) and records it as failed.
- runs each preview with no terminal (`setsid`), no ANSI console and no stdin.
  Without that, Nextflow's `stty` call on the terminal freezes background
  previews.

**When runs fail,** read the log: `dags/<run>.log`. A failure is information,
not a reason to stop: the matrix carries on with the runs that succeeded.
Common causes are in [When something goes wrong](#when-something-goes-wrong).
If it is a combination the pipeline rejects, add an `implies` (step 2) and
plan again; the planner never retries a combination already tried.

**What it costs.** fetchngs settled in 14 runs. nf-core/rnaseq, with eight
enum dimensions, took five batches and 357 runs at about a minute each, six at
a time: roughly an hour and a half of machine time. Exact conditions need
"everything the same but one setting" comparisons, about one per alternative
value around each of the handful of seeds a pipeline needs, so the run count
does not shrink much; running previews in parallel is what keeps it
practical.

## 5. Build the page

```bash
python3 $PF/tools/generate.py --name nf-core/fetchngs --version "$REV" --dims proposal.json --runs dags/runs.tsv --source src -o fetchngs.json
python3 $PF/viewer/build.py fetchngs.json -o fetchngs.html
```

`--source src` is optional but worth it: it reads the pipeline's code for
what the DAG does not say. Each process gets its module file, and each edge
into or out of a process gets its **port** (`emit tsv -> input 1`) and the
**shape** the module declares there (`[meta, *.fastq.gz]`). Shapes are then
carried through operators that do not change them (`filter`, `unique`,
`first`, a `mix` of like channels). On nf-core/rnaseq that shapes 96% of the
edge ends at processes and over half of all edges; the rest sit between
operators such as `map` and `join`, whose output depends on their closure.

`generate.py` aligns every successful preview, infers each element's
condition, and writes a channel model (schema 0.1). It reports:

- the **route**: the dimension drawn as metro lines, the one that splits the
  processes into the most distinct groups (`aligner` for nf-core/rnaseq).
  Override it with `--route`.
- the **prefix** every process shares (`NFCORE_RNASEQ`), hidden in the page.
- the **lanes** it found: versions and MultiQC plumbing (folded), and staged
  scripts and templates (hidden).
- **dimensions dropped**: those the matrix showed change nothing, because some
  pair of runs differs in them alone and produced the same graph (a
  run-time `filter`, a tool argument). A dimension no condition uses but no
  pair of runs ever varied alone is kept, and reported, since the runs may
  simply not have separated it from another. `--keep-unused` keeps them all.

`build.py` inlines the model, the layout library and the logos into one file.
Add `--logo pipeline-logo.svg` to show the pipeline's own logo in the header.
Open the HTML directly in a browser. A large pipeline takes a few seconds to
lay out on first load (nf-core/rnaseq: about 1,000 nodes, six seconds);
filtering afterwards is immediate.

## 6. Publish the model

```bash
python3 $PF/tools/publish.py fetchngs.json --dims proposal.json -o src/assets/process-flow/channels.json
```

Commit it with the release. Every `process-flow run` of that release then
uses it instead of reading conditions from the code. The published form
drops the per-run evidence (nf-core/rnaseq: 8.5 MB to 0.76 MB) and keeps a
summary of it instead: runs that worked and failed, the args fixed in every
run, the params the code tests that the matrix held, anything left
unsettled, and the count of disagreements (0). It is stamped with the
repository, commit, release and Nextflow version; a run of another commit
still uses it, with a warning, and the page names where they differ.

## Reading the page

**Filters** (left) are the dimensions. Leave one at "any" to see every
possibility, or set it to see one run. The route dimension appears as
checkboxes: with none ticked, every element is drawn in the colour of the one
or two routes that use it; tick a route to light its whole line, tick two to
see where they share track.

**States.** Under the current filters each element is:

| State | Drawn | Means |
|---|---|---|
| present | normally | it exists under these settings |
| absent | faded | it does not exist under these settings |
| wired but starved | hatched | it exists but receives nothing (models with flow annotations) |
| may receive items | dotted | it depends on the data, not the settings (models with flow annotations) |

A filter left at "any" counts as every value it could take. An element is
only faded when no remaining combination includes it.

**Lanes** (versions, MultiQC, staged assets) can be folded to one edge per
process, shown in full, or hidden. **Subworkflows** are drawn as boxes and can
be collapsed to a single node each. **Filtered-out elements** can be faded in
place (the layout stays put) or hidden (the graph is laid out again).

**Click** any node or edge for its record: the condition it exists under, in
words; which preview runs it was seen in; where it is defined, when known;
and, for each value, where it came from (`preview` for everything a generated
model infers). **Hover** a node to trace everything upstream and downstream
of it.

## When something goes wrong

| Symptom | Cause | Fix |
|---|---|---|
| `Config parsing failed`, `Unexpected input` at a `def` in `nextflow.config` | the release is too old for your Nextflow | pin a recent release (`sort -V` the tags) |
| `Value is [boolean] but should be [string]` | `--param ''` given on the command line | use the driver; write `--param ''` or `--param null` in runs and fixed args, never on Nextflow's command line |
| `could not validate file format of ''` | an empty string for a path | unset paths with `--param null` |
| previews that never finish; `ps` shows `java` in state `T` | Nextflow touched the terminal from a background job | use the current driver (it runs previews under `setsid`); kill the stopped ones: `kill -9 $(ps -o pid= -o stat= -u "$USER" \| awk '$2 ~ /^T/ {print $1}')` |
| previews slow, `HTTP error=404` retries in `launch/<run>/.nextflow.log` | remote test data fetched by every preview | `localise_testdata.py`, then plan with its fixed args |
| one value always fails with a message about a missing option (`--sylph_db`) | the value needs an input the profile lacks | an empty dummy file in the fixed args |
| a value fails only with certain others (`... is only supported with '--aligner ...'`) | a combination the pipeline rejects | an `implies` on the dimension (step 2), then plan again |
| the planner keeps asking for runs that settle nothing | an element whose condition is an `any` of several branches, each needing its own seed; or an alignment ambiguity | check what is unsettled; a few unsettled plumbing edges can be left, the model is still exact on every run made |
| a dimension you expected was dropped | the runs showed it changes nothing under the other settings (nf-core/rnaseq's `umi_dedup_tool` with `--with_umi` off) | include the switch that unlocks it as a dimension too |

Changing the fixed args changes every run, so start a new `dags/` folder when
you do.

## What it cannot see

process-flow learns from preview graphs, so it sees what a preview sees.

- **Routing inside a closure.** fetchngs chooses a download method for each
  sample inside a `branch`; every route is in every graph, so the previews
  cannot tell when each is used. The generated model has no condition for
  them, and drops `download_method` as changing nothing. A hand-annotated
  model can say it, with `flows_when` (see
  [schema/README.md](../schema/README.md)); `fixtures/fetchngs.json` does.
- **Run-time filters.** `filter { sample_mapping_fields }` passes everything
  or nothing while the pipeline runs; the graph is the same either way.
- **Two calls of one process in exclusive branches.** A DAG shows both under
  one name, so they are one node.
- **Most of what flows between operators.** With `--source`, shapes are
  known at processes and through shape-preserving operators; after a `map`,
  `join` or `collect` they are not, and meta keys and cardinality are not
  known anywhere yet. They can be annotated by hand (`fixtures/*.json` show
  how); reading them from real runs is the next step.
- **Anonymous outputs.** An output nothing reads is a bare point in the DAG,
  matched between runs by position only, so a few of them may be paired
  differently from run to run. Processes and routes are not affected.

The plan, findings and design decisions behind all of this are in
[working_docs/channel-viewer-plan-2026-10-10.md](../working_docs/channel-viewer-plan-2026-10-10.md).
