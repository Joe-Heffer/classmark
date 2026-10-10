# Security policy

## Supported versions

`classmark` is an experimental prototype. Only the latest commit on `main` receives fixes.

## Reporting a vulnerability

Please do not report security problems in public issues.

Report them privately through GitHub’s [private vulnerability reporting](https://github.com/Joe-Heffer/classmark/security/advisories/new).

Please include:

* A description of the problem and its impact
* Steps to reproduce it
* The affected commit or version

You should receive a reply within 14 days.

## Relevant risks

These are the areas where a security problem is most likely:

* **API keys.** The tool reads `TYPESAFE_API_KEY` and `ANTHROPIC_API_KEY` from the environment or a `.env` file. Any path by which a key could be written to `logs/`, `results/`, `cache/` or a report is a vulnerability.
* **Untrusted dataset content.** The profiler reads files from public repositories. A crafted file that causes code execution, excessive memory use or a path traversal is a vulnerability.
* **Prompt injection.** Dataset text is sent to a model. Text that makes a model ignore its instructions is a known limitation of the approach; please still report cases that change answers, as they matter for evaluation.

If you find that an API key has been committed, revoke it with the provider straight away, then report it.
