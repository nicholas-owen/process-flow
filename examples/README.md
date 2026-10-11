# Examples

Pages and models made with process-flow, so you can see what it produces
before running anything. Each page is one self-contained HTML file: download
it and open it in a browser.

## Pages

| Page | Made from | What to try |
|---|---|---|
| [nf-core-rnaseq-3.27.0-test-run.html](pages/nf-core-rnaseq-3.27.0-test-run.html) | the published nf-core/rnaseq 3.27.0 model below, with a real `-profile test,docker` run laid over it | "Show this run's settings"; click any channel into STAR_ALIGN for the meta keys and the run's items; the "This run" box names the one difference from the model (`--transcript_fasta`) |
| [nf-core-sarek-3.10.0-test-run.html](pages/nf-core-sarek-3.10.0-test-run.html) | `process-flow run nf-core/sarek -r 3.10.0 -profile test,docker`, no published model: every condition read from the code | the `--tools` switches; untick `tools:strelka`; click BWAMEM2_MEM, wired in every run but given data only when chosen |
| [nf-core-fetchngs-1.13.0.html](pages/nf-core-fetchngs-1.13.0.html) | the published nf-core/fetchngs 1.13.0 model, no run | `--skip_fastq_download` dims the six download processes |

## Published models

What a pipeline author commits as `assets/process-flow/channels.json`, made
with the Analyser (see the user guide). `process-flow explore --model FILE`
uses one in place of the pipeline's own.

| Model | Previews behind it | Size |
|---|---|---|
| [nf-core-rnaseq-3.27.0.json](published/nf-core-rnaseq-3.27.0.json) | 357, every condition agreeing with every preview | 0.76 MB |
| [nf-core-fetchngs-1.13.0.json](published/nf-core-fetchngs-1.13.0.json) | 14 | 0.04 MB |

The test-run pages show sample names and file names from the nf-core test
datasets, which are public.
