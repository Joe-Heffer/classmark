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

TODO

```bash
pip install classmark
```
