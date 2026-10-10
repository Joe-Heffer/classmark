# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html). Before version 1.0.0, any release may contain breaking changes.

## [Unreleased]

### Added

* Citation metadata (`CITATION.cff`), contributing guide, code of conduct, security policy and this changelog
* Continuous integration: lint, tests on Linux, macOS and Windows, package build and citation metadata validation
* Dependabot updates for GitHub Actions and Python dependencies
* Issue and pull request templates
* Pre-commit hooks and ruff configuration

### Fixed

* File names in states and the question-set path in run metadata now use `/` on every platform, so states are reproducible across operating systems
* Text files are read and written as UTF-8 on every platform

## [0.1.0]

### Added

* Jev evaluation prototype for the Data Director, with experiments E1 (resource type) and E2 (OECD Fields of Science)

[Unreleased]: https://github.com/Joe-Heffer/classmark/compare/838a163...HEAD
[0.1.0]: https://github.com/Joe-Heffer/classmark/tree/838a163
