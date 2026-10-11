# Changelog

## 0.1.0 (2026-10-12)

First release.

### The Explorer: one command

- `process-flow run <nextflow args>` runs a pipeline as given, with a config
  that switches on Nextflow's data lineage and writes the run's DAG, then
  writes `<outdir>/pipeline_info/channels.html` and `channels.json`.
- `process-flow explore` builds the page for a run already made with
  `lineage.enabled = true`.
- What a run carried, from its lineage: meta keys, queue / value /
  collection, real items per channel at every process boundary, the files
  that passed between operators and where they came from, tasks per
  process, and processes wired but given nothing.
- Conditions from a published model when the pipeline ships one
  (`assets/process-flow/channels.json`), checked against the run, with any
  difference put down to the arg that explains it; otherwise read from the
  code: the `if` blocks around each call, interpreted for every setting.
- The run's effective params from nf-core's `params_*.json`, and nf-core's
  `getGenomeAttribute` understood; comma-separated list params (`--tools`)
  as one switch per value.
- Tested end to end on nf-core/rnaseq 3.27.0 and nf-core/sarek 3.10.0.

### The Analyser: for pipeline authors

- A preview matrix (`nextflow run -preview -with-dag`), planned adaptively,
  run in parallel and resumably, aligned into one union graph; every
  element's condition inferred and proven against every preview.
- `tools/publish.py`: the slim, version-stamped model a pipeline commits.
- nf-core/rnaseq 3.27.0 (357 previews, 2,289 elements, every condition
  agreeing with every preview) and nf-core/fetchngs 1.13.0 published in
  `examples/published/`.

### The viewer

- One self-contained HTML page: subworkflows (collapsible), route
  colouring as a metro map, plumbing lanes folded, a detail panel for every
  node and channel, filters grouped by schema section and ranked by how
  many processes they decide.

### Known limits

- A run shows its own route; other routes are drawn only from a published
  model.
- Read from the code, conditions are exact for processes where the code is
  plain (nf-core/rnaseq: 94 of 101 exact, none wrong) and less sure for
  operators and channels (83% exact).
- Items between two operators are not recorded by lineage; routing inside
  `branch` and `filter` closures is not a condition on the settings.
