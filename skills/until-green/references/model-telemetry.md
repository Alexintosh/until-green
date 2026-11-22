# Comparing model runs

The dispatch ledger records timestamps on first reserve, bind and terminal receipt for every new writer and reviewer. Replays preserve these timestamps. Bind and finish also save available T3 route and timing fields in the milestone ledger. The model report reads ledgers and optional local T3 run metadata using read-only connections. Run on demand or at milestone handoff; there is no background polling or extra inference.

## Record comparable work

Reserve with `--kind implementation|repair|verification --cohort LABEL --base FULL_GIT_SHA`. Choose a stable cohort for similar tasks across models and milestones. A/B trials should share a base revision, brief, tests and review rubric, and start with independent checkouts when separately authorized. Record harness/provider and effort separately. Legacy classification can remain unknown. A milestone's dispatch route stays under its existing configuration.

When provider counters are exposed, attach the totals for **that entire bound task** (writer or reviewer):
```sh
python3 dispatch.py --db "$db" measure "$token" --input-tokens 1800 --cached-tokens 1200 --output-tokens 310
```
Supply fields independently. Input includes cached input. Use `--inference-ms` only for provider-measured inference time. Missing counters remain null; supply zero only for a measured zero. Repeating the same measurement is safe; a conflicting total is rejected. Run ledger commands through the same installed dispatcher for the entire milestone.

## Read the results

```sh
python3 ~/.codex/skills/until-green/scripts/model_report.py
python3 ~/.codex/skills/until-green/scripts/model_report.py --cohort parser-repairs
python3 ~/.codex/skills/until-green/scripts/model_report.py --format json
```

By default the script reads immediate child milestone directories of `~/.local/state/until-green` and T3's local run projection in `~/.t3/userdata/statev2.sqlite`. Use `--root DIR`, `--t3-db FILE`, or `--ledger-only` elsewhere. Combine `--cohort LABEL --base FULL_SHA` to select the same starting revision. Ledger-only mode includes previously saved T3 metadata; it makes no live T3 queries. To retain a point-in-time export, redirect the JSON to a dated file in private milestone evidence. The exported fields contain task IDs, model metadata, labels, SHAs, timings, resource counters and review measurements. Prompt text, chat, patches, raw errors, hypotheses and review bodies are excluded. Old untracked T3 writer jobs may be explicitly listed in optional `ROOT/telemetry-history.json` as objects in an array with `task` (exact T3 task ID), `milestone`, `kind` and `cohort`. These references provide historical timings without creating dispatch attempts or attributing later integrated review scores to those jobs.

## Interpret the measurements

- Groups separate role, review stage, route, requested versus confirmed executed model, effort, kind and cohort. A run with no executed-model field is labelled requested. Check sample size and number of known values before deciding. Same-cohort comparisons still require comparable scope and hardware.
- Queue time is T3 request to start; wall time is T3 start to completion, including tool use and waits. One unambiguous bound T3 run is required. Ledger bind-to-terminal receipt is reported independently with its own coverage. Shared-task aliases are counted once per group. Median values use only known observations.
- JSON includes explicit test/evidence gate, blockers, four rubric dimensions, exact weighted score, and component versus final review outcomes. First component pass counts are per scored writer task, not a denominator of all dispatched tasks. A writer score requires a unique tracked task on that milestone and exact revision. Shared-SHA, unscored and integration outcomes are not counted as individual writer scores. See `ambiguous_component_votes`. Coordinator implementation, escalation, tests and budget limits can influence the milestone result.
- Milestone time to acceptance is from first tracked writer request to the last required positive verdict on the same frozen SHA. Both the latest component vote(s) and final vote must pass. For a complete ledger-only timestamp window the report can instead give reserve-to-receipt duration. Missing endpoints, pending decisions and different SHAs leave duration unknown. Historical pre-ledger work and total project lead time are separate populations. Rework, infrastructure outcomes, attempts and review counts remain visible.
- Start a comparison with time to accepted change, fraction of first component reviews passed, remaining blockers and number of repair attempts. Use queue, wall, token and inference measurements to explain differences. Keep open milestones visible to avoid selecting only successes.
