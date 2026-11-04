# Evaluation report — fill with official runs

**Status:** Template. Local scripted tests pass, but the official mid/final test sets are not yet available. No official scores are claimed here.

## Experimental setup

Record the date, team commit SHA, provider/model, dataset version and case count, Docker image digest, hardware, search availability, approval policy, and exact command. Preserve the original JSONL and machine-generated JSON report without editing the results.

## Quantitative results

| Set | Cases | Objective-check cases | Goal completion | Subtask completion | Mean time (s) | Total time (s) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Mid test | pending | pending | pending | pending | pending | pending |
| Final test | pending | pending | pending | pending | pending | pending |

Use `python3 -m evo eval official.jsonl --output results/official.json` to produce the measured values. State the exact denominator for each rate. Separate objectively checked cases from self-reported cases.

## Failure analysis

For each failure category, list case IDs, symptoms, root cause, and a concrete fix: planning error, wrong role assignment, tool failure, approval block, execution timeout, weak verification, missing source, or provider outage. Include at least one full trace with messages and tool observations; redact API keys and private data.

## Memory evolution and ablation

Compare a fresh state directory run with `--no-memory` against a warmed state directory run with memory enabled on the same tasks, model settings, and approval policy. Keep the test order fixed and record the exact commands and state histories. Report task pass rates, assignment changes, relevant recalled lessons, and whether a lesson led to a specific successful correction. Avoid claiming causal improvement if datasets or prompts differ or one run is too small to separate model variability from a memory effect.

## Commit history evidence

Insert screenshots from the real GitHub repository showing each team member's substantial commits across the half-semester. Record repository URL, contributors, and commit range. Do not fabricate or backdate commits.

## Reproducibility

Add the GitHub URL, install instructions, exact commands, test-set hash, result JSON paths, and known limitations. The week-13 presentation should use the same verified metrics.
