# classmark

Classify research datasets against controlled vocabularies and metadata standards, with calibrated confidence so uncertain answers go to a person.

> **Status:** experimental. This is a research prototype for evaluating AI models as components of the [Data Director](https://doi.org/10.15497/RDA00157). Interfaces will change.

## What it does

`classmark` takes a dataset (a local folder or a public repository record), builds a compact text profile of it, and asks a set of typed questions about that profile:

* **Classification** into controlled vocabularies, such as DataCite resource types, OECD Fields of Science and Technology, or SPDX licence identifiers
* **Quality scoring** of existing metadata against a rubric
* **Consistency checks**, such as whether a description matches the files it describes
* **Sensitivity flags** for personal data, health data, or data concerning Indigenous peoples and communities

Every answer comes with a probability distribution and a confidence value. Your code decides what to auto-accept and what to send for human review.

## What it does not do

* Generate free-text metadata (titles, descriptions, keywords)
* Extract values such as author names, dates or grant numbers
* Make final decisions about sensitive data. Sensitivity flags only route records to human review.

These tasks belong to deterministic code or a generative model elsewhere in a pipeline.

## Backends

`classmark` is backend-agnostic. The initial backends are:

* [TypeSafe Jev](https://docs.typesafe.ai), a model that answers typed questions with calibrated probabilities
* A general-purpose LLM using structured output, as a baseline

## Relationship to the Data Director

The [Data Director Agentic AI Tool Blueprint](https://doi.org/10.15497/RDA00157) (RDA, 2026) is a vendor-agnostic specification for an agentic AI tool that helps researchers prepare, document and deposit research data in line with the FAIR and CARE principles. It has no reference implementation.

This project tests one component of a possible implementation: the classification, validation and routing judgements involved in metadata generation, metadata remediation, repository recommendation and DMP verification. Its results are intended to inform the working group, not to stand in for the Blueprint.

## Planned experiments

| ID | Task | Question type |
| - | - | - |
| E1 | Resource type | Choice |
| E2 | Subject classification (hierarchical) | Chained Choice |
| E3 | Licence identification | Choice |
| E4 | Description–file consistency | Noul |
| E5 | Metadata quality | Score |
| E6 | Sensitivity flags | Noul |

Each experiment reports accuracy, calibration, coverage at a target accuracy, latency and cost, for each backend.

## Data policy

The evaluation uses public metadata and files from the Zenodo and DataCite APIs only. Do not send unpublished, private or sensitive data to any third-party API through this tool.

All requests and responses are logged with model version and token usage, so every answer can be traced.

## Installation

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```bash
git clone <this repository> && cd classmark
uv sync --extra scientific   # the extra adds netCDF4/h5py for reading scientific file headers
```

Set API keys as environment variables. Never commit them:

```bash
export TYPESAFE_API_KEY=...    # https://console.typesafe.ai/keys
export ANTHROPIC_API_KEY=...   # baseline only
```

Alternatively, put the same `KEY=value` lines in a `.env` file in the repository root. It is git-ignored, and variables already set in the environment take precedence.

## Running an experiment

Each experiment is a question set in `questions/`. The steps are the same for every experiment; E1 is shown here.

```bash
# 1. Draw a stratified sample of public Zenodo records with DataCite labels.
#    Writes data/e1_resource_type/{records.jsonl,query.json,handcheck.csv}
uv run classmark sample e1 --n 20

# 2. Build states and requests without calling any model API, and print a worst-case cost estimate.
#    States are cached in data/<experiment>/states/; requests go to results/<experiment>/dryrun/
uv run classmark run e1 --backend jev --dry-run
uv run classmark run e1 --backend claude --dry-run

# 3. Run each backend. --budget is a hard limit in US$ per run (default 2).
uv run classmark run e1 --backend jev
uv run classmark run e1 --backend claude --budget 1

# Optional: ask again with Choice options in reverse order, to measure position bias.
uv run classmark run e1 --backend jev --reverse-options

# 4. Evaluate and write reports/e1_resource_type/report.md with PNG plots.
uv run classmark report e1
```

E2 (`e2`) works the same way. Its subject hierarchy is asked as one request per record: one broad-field question plus a question per field, with beam search over the answers. Use `--n` on `run` to process only the first N sampled records.

To see the state that would be built for a local folder, without sending anything anywhere:

```bash
uv run classmark profile path/to/dataset --title "My dataset" --description "..."
```

### What gets written where

| Path | Contents | In git? |
| - | - | - |
| `data/<experiment>/records.jsonl` | The sampled records, depositor labels and noise flags | yes |
| `data/<experiment>/query.json` | The queries, filters and date of the sample | yes |
| `data/<experiment>/handcheck.csv` | Records for manual labelling (flagged records first) | yes |
| `data/<experiment>/states/` | The state built for each record, with truncation notes | yes |
| `results/<experiment>/<backend>.jsonl` | Answers, tokens, latency and cost per record | yes |
| `logs/<run_id>.jsonl` | Audit log: every request and response, model version, request id, tokens, latency, cost, git commit, question-set hash | yes |
| `cache/<backend>.jsonl` | Responses keyed by a SHA-256 of the request; a request is never sent twice | no |
| `reports/<experiment>/` | Markdown report and plots | yes |

### Hand-checking labels

Gold labels are whatever depositors entered, and some are wrong. To score against checked labels, fill in the `checked_label` column of `data/<experiment>/handcheck.csv` and run `classmark report` again. For E1, enter a DataCite `resourceTypeGeneral` value. For E2, enter OECD subfield names (or broad-field names when no subfield fits), separated by `;`.

## Adding a question set

Create `questions/<id>_<name>.yaml`. The id prefix (for example `e3`) is the name you use on the command line. Here is a minimal Choice question set:

```yaml
experiment: e3_licence
title: Licence
label: licence                 # key in each record's "labels" holding the gold answer
exclude_from_state: []         # state sections to leave out, for example [licence_file]

questions:
  licence:
    type: choice
    instructions: >
      Which licence does the README or LICENCE text grant for this dataset?
    options:
      CC-BY-4.0: Creative Commons Attribution 4.0. Requires attribution only.
      CC0-1.0: Public domain dedication; no conditions.
      other: A licence that is none of the above.
      none_found: The text states no licence.
```

Rules for writing questions:

* **Option descriptions are sent to the model.** Use them to say how an option differs from its neighbours, and state boundary cases explicitly. Jev reads instructions literally.
* Add an `other` or `none_found` option whenever the list might not cover every case.
* `type: score` takes `levels:`, a list of level descriptions, lowest first. `type: noul` takes only `instructions:`, phrased so that "yes" is the condition you are testing.
* For a taxonomy, use `hierarchy:` instead of `questions:`. See `questions/e2_oecd_fos.yaml`.
* Run `uv run pytest` after editing: a test loads every shipped question set, and validation errors name the field at fault.

A new experiment also needs a sampling stratum and labels (`classmark/sample.py`) and an evaluation item builder (`classmark/report.py`). These are short functions keyed by the id prefix.

## Human oversight

No answer from this tool is applied automatically. Coverage–accuracy curves show the share of records that *could* be auto-accepted at a target accuracy. Whether to auto-accept anything is a governance decision (Blueprint P4), and any threshold must be set on held-out data. Sensitivity flags (E6, not yet built) will only route records to human review: they must never block or approve a deposit.

## Tests

```bash
uv run pytest
```

The tests cover the profiler, the evaluation metrics, beam search, question-set validation and report generation. They use no network and no API keys.

## Repository map

* `questions/`: question sets (YAML, editable by data stewards)
* `src/classmark/config.py`: models, prices, caps and thresholds, all in one place
* `src/classmark/sources.py`: read-only Zenodo and DataCite API access
* `src/classmark/sample.py`: stratified sampler and label-noise heuristics
* `src/classmark/profile.py`: deterministic profiler that builds the state
* `src/classmark/backends/`: Jev and Claude backends behind one interface
* `src/classmark/run.py`: runner, with cache, audit log, budget guard and dry run
* `src/classmark/hierarchy.py`: beam search over chained Choice answers
* `src/classmark/metrics.py`, `report.py`: evaluation and reports
* `docs/requirements-mapping.md`: how the Blueprint's requirements map to judgement types
