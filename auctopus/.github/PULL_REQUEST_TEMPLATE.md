## Problem

Describe the problem, who it affects and the expected behaviour. Link a related issue if one exists.

## Changes

Summarise the changes and any effects on configuration, saved files, decision rules or recovery. Note relevant limitations.

## Checks

List commands, results and any checks you could not run. Write **Not applicable** if no tests apply. For code changes, run these offline checks from the repository root:

```bash
python -W error::ResourceWarning -m unittest discover -s tests
auctopus dry-run --scenario lab-redo
```

Add a focused regression test when behaviour changes.

## Documentation and templates

List related documentation, prompt templates or example configuration updated, or write **Not applicable**.

## Checklist

Minimal synthetic prompts, data, example hostnames and redacted configuration excerpts are welcome.

- [ ] The diff and excerpts contain no secrets or private material, including the authors' unpublished study prompts and private instrument descriptions.
- [ ] I have checked related documentation and templates, or marked them Not applicable.
- [ ] I have recorded applicable checks and their results.
