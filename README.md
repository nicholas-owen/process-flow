# process-flow

![process-flow](assets/process-flow_logo.png)

See what a Nextflow pipeline's channels carry. Run the pipeline's test once,
and process-flow writes a single self-contained HTML page next to the
MultiQC report: every process, every operator and every channel between them,
with what actually went through each one in your run (the meta keys, the
items, the files and where they came from), filterable by the parameters
that change the graph, with routes coloured as a metro map.

It goes further than `nextflow run -with-dag`, which draws one run's graph
with nothing on its edges.

## Quick start

On Linux or WSL, with Nextflow 25.04 or later and Python 3:

```bash
/path/to/process-flow/bin/process-flow run nf-core/rnaseq -r 3.27.0 -profile test,docker --outdir results
```

Then open `results/pipeline_info/channels.html`.

That is an ordinary `nextflow run`: everything after `run` goes to Nextflow
as it is. process-flow only adds a config that switches on Nextflow's data
lineage and writes the run's DAG, then builds the page when the run ends. If
the run fails, fix it and rerun with `-resume`: cached tasks still count.
For a run already made with `lineage.enabled = true`, `process-flow explore`
builds the page from it.

To see what you get before running anything, open a page in
[examples/](examples/README.md): real test runs of nf-core/rnaseq and
nf-core/sarek.

## Documentation

| Document | For |
|---|---|
| [process-flow_User_Guide.docx](process-flow_User_Guide.docx) | The whole guide as a formatted Word document, for printing or circulating offline: installing, the one command, reading the page, where conditions come from, the Analyser, troubleshooting |
| [docs/guide.md](docs/guide.md) | The same in long form, with the Analyser walkthrough step by step |
| [examples/](examples/README.md) | Pages and published models to open without running anything |
| [schema/README.md](schema/README.md) | The channel model, field by field |
| [CHANGELOG.md](CHANGELOG.md) | What changed in each release |

## What you get

- Every process and operator, nested in its subworkflows (collapsible).
- **What your run carried**, on every channel into or out of a process: the
  meta keys, whether it was a queue per sample, a value or a collection, and
  real items (`[[id:WT_REP1, strandedness:reverse, ...], [WT_REP1_1.fastq.gz,
  ...]]`); on channels between operators, the files that passed and where
  they came from and went.
- Which processes ran how many tasks, and which were wired but received
  nothing.
- A filter for each parameter the code tests, and the condition under which
  each element exists, in words: `--aligner = star_salmon | star_rsem; no
  --skip_alignment`. "Show this run's settings" sets them to your run's.
- Route colouring, plumbing lanes (versions, MultiQC inputs) folded, a detail
  panel for every node and edge, and one HTML file that needs no server.

## Where the conditions come from

Two ways, and the page says which on every element:

- **Published by the pipeline's authors.** If the pipeline ships
  `assets/process-flow/channels.json` for that release, the page uses it.
  Its authors made it with the **Analyser**: hundreds of `nextflow run
  -preview` runs, each element's condition proven against all of them. It
  covers routes your run did not take, and the page checks your run against
  it and names any difference (for nf-core/rnaseq's test profile: the
  transcript FASTA the Analyser held unset).
- **Read from the code** otherwise: the `if` blocks around each call, and
  around each call above it, evaluated for every setting (marked *source*).
  Exact for processes wherever the code is plain; less sure for operators and
  channels, where a node does not always map to one statement.

| Read from the code, scored against an Analyser model | Exact | Wrong | Undecided |
|---|---|---|---|
| nf-core/fetchngs 1.13.0, every node and channel (117) | 117 | 0 | 0 |
| nf-core/rnaseq 3.27.0, processes (101) | 94 | 0 | 7 |
| nf-core/rnaseq 3.27.0, every node and channel (2,289) | 1,902 | 281 | 106 |

## For pipeline authors: the Analyser

To publish an exact model for your pipeline, run the preview matrix once per
release, then publish it into your repo:

```bash
PF=/path/to/process-flow
python3 $PF/tools/propose.py src/nextflow_schema.json --source src --profile-config src/conf/test.config -o .
python3 $PF/tools/adaptive.py --dims proposal.json --dags dags -o next.tsv          # repeat these two
bash $PF/tools/preview_matrix.sh -j 4 nf-core/fetchngs next.tsv dags -- -r 1.13.0 -profile test
python3 $PF/tools/generate.py --name nf-core/fetchngs --dims proposal.json --runs dags/runs.tsv --source src -o model.json
python3 $PF/tools/publish.py model.json --dims proposal.json -o src/assets/process-flow/channels.json
```

The walkthrough, including choosing dimensions, making a test profile
previewable, and what to do when a preview fails, is in
**[docs/guide.md](docs/guide.md)**.

| Analyser | Previews | Elements | Result |
|---|---|---|---|
| nf-core/fetchngs 1.13.0 | 14 | 117 | every process's condition matches the hand-built model |
| nf-core/rnaseq 3.27.0 | 357 | 2,289 | every condition agrees with every preview; published model 0.76 MB |
| rnaseq-flow (the prototype) | 13 | 566 | the viewer reproduces the hand-built prototype page, bar one intended difference |

## Repository layout

| Path | What |
|---|---|
| `bin/process-flow`, `tools/pf.py` | `run` and `explore`: the one command |
| `tools/harvest.py` | lays a real run (its Nextflow lineage) over a model: meta keys, items, provenance, and a check against the model |
| `tools/conditions.py` | reads when each process exists from the source's `if` blocks, for every setting; scores against a model |
| `tools/graph_conditions.py` | extends that to every operator and channel; scores against a model |
| `tools/propose.py` | proposes the dimensions (params that may change the graph) from `nextflow_schema.json` |
| `tools/localise_testdata.py` | downloads a test profile's remote files once, so previews never fetch |
| `tools/adaptive.py` | plans the next batch of preview runs from the DAGs so far |
| `tools/preview_matrix.sh` | runs a batch of previews in parallel, resumably |
| `tools/generate.py` | aligns the DAGs, infers every condition, writes the channel model |
| `tools/publish.py` | turns a full model into the slim, version-stamped form a pipeline ships |
| `viewer/build.py` | builds the HTML page from a channel model |
| `tools/align.py`, `infer.py`, `matrix.py`, `predicates.py`, `dot.py`, `modules.py`, `ports.py` | the parts the above are built from |
| `tools/test_*.py`, `tools/js_parity.py` | checks against the fixtures and the Analyser models |
| `schema/` | the channel model's JSON Schema and the reasoning behind it |
| `fixtures/` | hand-built models of rnaseq-flow and nf-core/fetchngs, the answer keys |
| `examples/` | pages and published models to look at without running anything |
| `docs/build_user_guide.js` | generates the Word user guide |
| `working_docs/` | the plan, findings and design history (working data there is not part of the repository) |

## Limits

- A run shows its own route. Elements of routes it did not take are drawn
  only from a published model.
- Lineage records process boundaries, so the items themselves between two
  operators (after a `map` or `join`) are not shown, only which files passed.
- Routing that happens per item inside a `branch` or `filter` closure (such
  as fetchngs choosing a download method for each sample) is not a condition
  on the settings, and two calls of one process in exclusive branches look
  like one. See [docs/guide.md](docs/guide.md#what-it-cannot-see).

## Licence and citing

process-flow is released under the GNU General Public License v3.0 or later
([LICENSE](LICENSE)). To cite it, see [CITATION.cff](CITATION.cff).
