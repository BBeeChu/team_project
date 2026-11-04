# Changelog

## Unreleased

## 1.0.0 - 2026-10-30

First public release.

### Added

- Python package and command-line tool for a laboratory of AI agents directed by a principal investigator.
- Workflow stages for proposals, theory, computational verification, laboratory work, figures, manuscript review and delivery.
- OpenAI and Anthropic model clients, SSH execution for computational and instrument agents, and manual laboratory hand-off.
- Configurable safety review and human approval before instrument execution, both enabled by default.
- Saved decisions, conversations and run state; resume support and delivery manifests with SHA-256 checksums.
- Project scaffolding with 33 prompt templates and seven domain templates. Study prompts and the NV instrument description are not included.
- README, guides and references in `docs/`, and contribution, conduct and security policies.
- Four offline scenarios using mock models and agents, plus 66 offline tests.
- Dry runs cannot be resumed or approved; run `auctopus dry-run` again to repeat a scenario.
- CI checks on Ubuntu and Windows with Python 3.11, 3.12 and 3.13.
