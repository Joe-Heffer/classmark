# Contributing to classmark

Thank you for your interest in `classmark`. This is an experimental research prototype, so interfaces change often. Please open an issue before starting a large change, so we can agree the approach first.

By taking part you agree to follow the [Code of Conduct](CODE_OF_CONDUCT.md).

## Ways to contribute

* Report a bug or an incorrect classification using the issue templates
* Propose or improve a question set in `questions/`. Data stewards can do this without writing Python.
* Check gold labels in `data/<experiment>/handcheck.csv`
* Improve the documentation
* Fix a bug or add a feature

## Data policy

Use only public metadata and files, such as those from the Zenodo and DataCite APIs. Never send unpublished, private or sensitive data to a third-party API through this tool, and never attach such data to an issue or pull request.

Never commit API keys. Keep them in environment variables or in a git-ignored `.env` file.

## Development set-up

You need Python 3.12 or later and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/Joe-Heffer/classmark.git
cd classmark
uv sync --extra scientific
uv run pre-commit install   # optional: run the linters on every commit
```

## Checks

CI runs the same checks as these commands. Please run them before opening a pull request:

```bash
uv run ruff check .          # lint
uv run ruff format .         # format
uv run pytest --cov          # tests with coverage
```

The tests use no network and no API keys. If you add a feature, add a test for it. If you change a question set, `uv run pytest` validates every shipped question set.

If you change dependencies, edit `pyproject.toml` and run `uv lock`, then commit `uv.lock` with your change. CI fails if the lockfile is out of date.

## Pull requests

1. Fork the repository and create a branch from `main`.
2. Make your change, with tests and documentation.
3. Add a line under “Unreleased” in [CHANGELOG.md](CHANGELOG.md).
4. Open a pull request and fill in the template.

Keep each pull request to one change. Write commit messages in the imperative mood, for example “Add SPDX licence question set”.

### Experiment results

Results, audit logs and reports are research outputs. If a pull request changes them, say which commands produced them, with which backend and model version, and how much the run cost. Do not edit files in `logs/` by hand: they are the traceability record.

## Style

* Code follows [ruff](https://docs.astral.sh/ruff/)’s formatter and the lint rules in `pyproject.toml`.
* Documentation uses British English.
* Keep model names, prices, caps and thresholds in `src/classmark/config.py`.

## Releases

Maintainers release by:

1. Updating `version` in `pyproject.toml` and `CITATION.cff`, and moving the “Unreleased” entries in `CHANGELOG.md` under the new version.
2. Tagging the commit `vX.Y.Z` and publishing a GitHub release.

If the repository is linked to [Zenodo](https://zenodo.org/account/settings/github/), each GitHub release is archived with a DOI.
