# Requirements mapping: Data Director Blueprint v1.0 → judgement types

Source: *Data Director Agentic AI Tool Blueprint* v1.0 (RDA, September 2026, DOI [10.15497/RDA00157](https://doi.org/10.15497/RDA00157)), Section 7.1 (Table 3, functional requirements R1–R12), Section 7.2 (Table 4, non-functional requirements C1–C17), Section 6 (Table 2, architecture principles P1–P14) and Section 5.4 (AI behaviour and automation).

This document breaks each functional requirement into the individual judgements an implementation must make, and assigns each judgement to one of five mechanisms:

| Mechanism | Meaning | Example |
| - | - | - |
| **Choice** | Pick one option from a closed, enumerable set (Jev supports up to 255 options) | DataCite `resourceTypeGeneral` |
| **Score** | Place something on an ordered rubric of described levels | Description quality, 0–4 |
| **Noul** | Probability that a stated proposition is true | "The README states the units of measurement" |
| **Deterministic** | Lookup, parsing, validation, arithmetic, date handling, API calls | JSON Schema validation, DOI regex |
| **Generative LLM** | Produce new free text, or extract an open-ended value | Draft README, title, abstract |

Two hybrid patterns recur and are noted where they apply:

* **Shortlist then choose.** Deterministic code retrieves candidates (from re3data, FAIRsharing, OLS, a regex), and a Choice selects among them. This is how a closed-set model can handle open vocabularies.
* **Flag then route.** A Noul or Score gives a probability. Code compares it with a threshold that was tuned on labelled data, and decides whether a human must review the item. The model never approves or blocks anything itself (P4, C13).

The **Experiment** column links each judgement to this prototype's experiments (E1–E6). A dash means the judgement is out of scope.

## Functional requirements (Table 3)

### R1 Recommend and select repositories (SHOULD; MUST where repository recommendation is a mandated service)

| Judgement | Mechanism | Notes | Experiment |
| - | - | - | - |
| Retrieve candidate repositories by subject, data type and access conditions | Deterministic | re3data / FAIRsharing API filtering | – |
| Which candidate best fits this dataset's discipline and data type? | Choice (shortlist then choose) | Options are the shortlisted repositories, each with its scope as the description | – (depends on E2 subject quality) |
| Does repository *X* accept this kind of data (for example, sensitive or large files)? | Noul, one per candidate | State combines the repository policy text with the dataset profile | – |
| Flag conflicts between funder, journal and institutional requirements | Deterministic, then Noul for anything left unclear | Machine-readable policies are compared in code. Where a policy is only free text, use a Noul such as "Policy text requires deposit in a domain repository" | – |
| Commercial vs open repository; surface deposit fees | Deterministic | Registry metadata | – |
| Affiliation-based suggestions | Deterministic | ROR affiliation, then a lookup in the institutional configuration | – |
| Explain the recommendation (P8) | Generative LLM, or a template | Jev gives no rationale. A templated explanation built from the probabilities is a possible partial substitute | – |

### R2 Generate FAIR-aligned metadata using controlled vocabularies (MUST)

| Judgement | Mechanism | Notes | Experiment |
| - | - | - | - |
| Extract file inventory, formats, sizes, variables | Deterministic | Profiler | Profiler |
| Resource type (DataCite `resourceTypeGeneral`) | Choice | Closed set of about 30 values | **E1** |
| Subject classification (OECD FoS, or another hierarchical scheme) | Chained Choice with beam search | Two levels; fan-out in a single request | **E2** |
| Licence identification from README or LICENCE text | Choice over SPDX subset + `other` + `none_found` | | **E3** |
| Domain-specific vocabulary terms (OLS, BioPortal, etc.) | Choice (shortlist then choose) | A term service returns candidates. For very large vocabularies, use hierarchical Choice | – |
| Is there no suitable controlled vocabulary for this domain? (Section 5.4: "state the absence openly") | Noul or a `none_of_these` Choice option | Must be logged in provenance | – |
| CARE applicability (does this concern Indigenous peoples or community-held knowledge?) | Noul, **routing only** | P1: "cannot be reduced to a checklist assessment". The flag only triggers human engagement | **E6** |
| Title, description, keywords | Generative LLM | Outside Jev's scope | – |
| Creator names, dates, grant numbers | Deterministic extraction (regex/parsers), optionally with Choice to select among candidate spans | Do not have Jev generate values | – |

### R3 Suggest appropriate vocabularies, ontologies and open data formats (MUST)

| Judgement | Mechanism | Notes | Experiment |
| - | - | - | - |
| Detect current file formats and field formats (for example, date strings) | Deterministic | MIME/magic bytes; regex for ISO 8601 | Profiler |
| Is the format open and preferred for long-term preservation? | Deterministic | Lookup table (for example, a preservation format registry) | – |
| Which open target format suits these files? | Choice (shortlist then choose) | Candidates come from the format registry | – |
| Which community standard or vocabulary applies? | Choice over a FAIRsharing shortlist | Must keep ontology alignment and vocabulary concept linkage as separate questions | – |
| Field-level crosswalk proposals for new mappings | Generative LLM, with Noul to verify | | – |

### R4 Validate metadata quality against community standards (MUST)

| Judgement | Mechanism | Notes | Experiment |
| - | - | - | - |
| Schema completeness and correctness | Deterministic | JSON Schema, SHACL, RO-Crate validator, F-UJI | – |
| Does the description match the files? | Noul | Negatives built by swapping descriptions between records | **E4** |
| Description quality against a FAIR rubric (purpose, methods, coverage, units, reuse) | Score, one per rubric dimension (composite scoring) | Weights belong in code, not in the model | **E5** |
| Generic or boilerplate text detection (C15) | Noul | "The description is generic and could apply to many datasets" | E5 (secondary) |
| Validation outputs traceable via R10 | Deterministic | Audit log | Runner |

### R5 Draft data documentation: READMEs and data dictionaries (MUST)

| Judgement | Mechanism | Notes | Experiment |
| - | - | - | - |
| Infer file structure and field names | Deterministic | Profiler | Profiler |
| Draft README text and basic field descriptions | Generative LLM | | – |
| Does the existing README cover units, missing-value codes, methods? | Noul, one per element | Lists what a human must still supply (the Blueprint says these elements need researcher input) | E5 (related) |
| Human-reviewed version before submission | Human | P4 | – |

### R6 Interoperable metadata across schemas and instances (MUST)

| Judgement | Mechanism | Notes | Experiment |
| - | - | - | - |
| Schema-to-schema mapping (DataCite, DCAT, schema.org, Croissant) | Deterministic crosswalk | | – |
| Ambiguous field mapping (which target field does this source field mean?) | Choice | Options are the target schema's fields | – |
| Show original metadata alongside the mapped version | Deterministic | | – |
| Instance synchronisation | Deterministic | | – |

### R7 Support PID assignment at publication (MUST)

| Judgement | Mechanism | Notes | Experiment |
| - | - | - | - |
| Produce PID-ready metadata; report the repository's PID capability and costs | Deterministic | Registry lookup; no model needed | – |

### R8 Verify data sharing against DMP commitments (SHOULD; MUST where audited)

| Judgement | Mechanism | Notes | Experiment |
| - | - | - | - |
| Parse a machine-actionable DMP | Deterministic | maDMP JSON | – |
| For each commitment in a free-text DMP, is it met by the deposit? | Noul, one per commitment | **Flags discrepancies for human review only; never enforces** | – |
| Licence in the DMP versus licence in the deposit | Choice (E3) on both, then a deterministic comparison | | E3 (reused) |
| Embargo status confirmation | Human | Section 5.2 | – |

### R9 Retrofit FAIR metadata for published datasets (SHOULD)

| Judgement | Mechanism | Notes | Experiment |
| - | - | - | - |
| Find gaps in existing metadata | Deterministic (missing fields), Score and Noul (weak fields) | Same judgements as R4/E5 on legacy records | E1–E5 on Zenodo records |
| Suggest improved values for controlled fields | Choice | For example, resource type or subject where a field is missing or wrong | E1, E2 |
| Suggest improved free text | Generative LLM | | – |
| Submit changes to the repository | Human | Out of scope for the tool | – |

### R10 Track provenance of AI agent actions (MUST)

| Judgement | Mechanism | Notes | Experiment |
| - | - | - | - |
| Record every request, response, model version, input hash, tokens and latency | Deterministic | JSONL audit log; PROV-O export is future work | Runner |

### R11 Link datasets to related outputs, people, grants and software (SHOULD)

| Judgement | Mechanism | Notes | Experiment |
| - | - | - | - |
| Extract candidate DOIs, ORCIDs, ROR IDs, grant numbers | Deterministic (regex + resolvers) | | – |
| Which DataCite `relationType` links this dataset to the candidate? | Choice | For example, `IsSupplementTo`, `IsDerivedFrom`, `IsDocumentedBy` | – |
| Is the candidate actually related? | Noul | | – |

### R12 Discover related datasets (MAY)

| Judgement | Mechanism | Notes | Experiment |
| - | - | - | - |
| Search registries | Deterministic | DataCite / OpenAIRE APIs | – |
| Re-rank results by relevance to the project | Noul or Score, one per candidate | Re-ranking cookbook pattern | – |

## Coverage summary

Counting the rows in the tables above by their primary mechanism (approximate, because how finely a requirement is split is a judgement call; mixed rows are counted under the mechanism listed first):

| Mechanism | Judgements | Share of non-human rows |
| - | - | - |
| Deterministic | 20 | 43 % |
| Choice (including shortlist then choose) | 11 | 24 % |
| Noul | 9 | 20 % |
| Score | 1 (rubric with several dimensions) | 2 % |
| Generative LLM | 5 | 11 % |
| Human only | 3 | – |

So the mapping suggests that a closed-set judgement model could handle about 45 % of all judgements, or about 80 % of those that need a model at all. Generation is a minority, and much of the system is ordinary deterministic code. The experiments test whether that is true in practice.

## Architecture principles and non-functional requirements

| ID | Requirement (abridged) | Implication for this prototype |
| - | - | - |
| **P4** Human in the loop | Agents may draft and suggest; no consequential action without explicit human approval. Human-in-the-loop vs human-on-the-loop must be documented for each workflow. | No model output is applied automatically. The coverage–accuracy curves measure the share of items that **could** be auto-accepted under a given policy; deciding that policy is a governance decision, not a model property. |
| **P5** Full traceability | Every action traceable to inputs, agent version and prompts; PROV-O recommended. | Every request and response is logged to JSONL with the input hash, the versioned model ID (for example `jev-1.13.0`), request ID, token usage, latency and cost. Question sets are version-controlled YAML. |
| **P8** Explainable AI | Human-readable explanation for every AI output; "black-box outputs are not acceptable"; prompts must be public. | **Gap for Jev:** it returns probabilities but no rationale. The prompts (question YAML) are public, which partly meets the requirement. The report must discuss whether a probability distribution plus the evidence in the state counts as an explanation, or whether a generative LLM must add one. |
| **P9** Locally adaptable | Configurable vocabularies, thresholds and policies. | Question sets and thresholds live in YAML that data stewards can edit. |
| **P10 / C4** Sovereignty | Prompts, logs and derived artefacts must stay in the required jurisdictions. | Both backends are third-party cloud APIs. The prototype uses public data only. Deployment would need jurisdiction review. |
| **P14** Low impact | Minimise environmental footprint; energy footprint should be captured in provenance. | Neither API reports energy use. Token counts and latency are logged as proxies. Jev bills input tokens only and emits no output tokens. The report compares tokens per record across backends. |
| **C2** Privacy | Detect and flag; pause sharing; never anonymise autonomously. | E6 sensitivity Nouls only **route to human review**; they never block or approve. A synthetic test set only; no real personal data is sent. |
| **C13** AI governance | All AI actions logged and attributable; irreversible actions blocked without human confirmation. | Audit log; the tool has no write actions. |
| **C14** Explainability | Log of reasoning steps and decision points kept alongside metadata. | Per-question probabilities and the confidence are logged. The beam search path records each step of the hierarchical decision. |
| **C15** Data and metadata quality | Quality checks on own outputs; low-quality or generic outputs flagged; human review mandatory. | E4 and E5 test whether these checks can be automated as flags. |
| **C16** Measurability | Collect usage and cost data. | Per-record tokens, latency and cost are in every report. |
| **C17** Affordability | Avoid duplicated work; reuse outputs; remain accessible to low-resource institutions. | A content-addressed cache means no request is ever sent twice. Per-record cost is reported for both backends. |
| Section 5.4 | State openly when no vocabulary fits; flag generic output; pause on sensitive data; automate only where governance conditions are met. | `none_of_these` / `other` options; routing-only flags. |

## Notes

* **Confidence is not independent of probability.** Jev's Choice confidence is a fixed function of the top probability and the number of options, `(n·p_max − 1)/(n − 1)`. Confidence and top probability therefore give the same ranking within a question, and calibration analysis uses the probabilities.
* **Label noise.** Depositors enter the metadata used as "ground truth", so a model may be marked wrong when the label is wrong. Every experiment reports results on a hand-checked subset as well as on the full sample.
