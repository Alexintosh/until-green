---
name: until-green
description: Coordinate a coding milestone through one event-driven T3 dispatcher, configurable implementation models and independent reviewers. Use when the user invokes $until-green to delegate implementation with durable retries, thinking and model escalation, and local telemetry.
---

# Until Green

## Resolve the routes

Use the scripts and profiles relative to this skill directory. Create a private milestone directory outside the repository, normally under `~/.local/state/until-green/<milestone>/`. Keep its brief, `dispatch.sqlite`, evidence and handoff together. Pick stable problem IDs based on acceptance criteria.

Run `python3 scripts/dispatch.py --db "$db" init` before delegation. Profiles configure the dispatcher, first writer, escalation ladder and independent reviewer. The built-in profiles are `default` (OpenCode first), `codex` (Codex only) and `alpi` (Codex with local GLM first). Select one with `--profile NAME` or use a full JSON file. A saved personal default lives at `${XDG_CONFIG_HOME:-$HOME/.config}/until-green/profile.json`. An explicit profile takes precedence over `UNTIL_GREEN_PROFILE`, the personal file and the bundled default, in that order.

Translate role assignments in the user's prompt into milestone overrides. For a known alias, pass `--dispatcher ALIAS:EFFORT`, `--writer ALIAS:LEVEL,LEVEL` or `--reviewer ALIAS:EFFORT`. The writer shortcut replaces only the first stage. For a new model, harness or custom ladder, write a small `--override FILE` in private milestone state; use the provider instance, model and option IDs advertised on this host. Merge objects, replace arrays, then apply the role shortcuts. The effective configuration is frozen in SQLite; `routes` reads it on resume. Keep personal and bundled defaults intact when the user requests a one-off override.

## Launch one dispatcher

Agree on outcome, acceptance checks, repository/base, write scope, allowed actions, resource limits and any deferred checks. Give the dispatcher the absolute paths to the skill, checkout, brief and database. Check that the selected environment can read them. Use one active writer per owned area. Keep large logs and patches on disk.

Use T3 capability discovery as required in the delegating thread. Confirm that each returned target's driver, provider instance, model and options are available before use. Surface an unavailable route and retain its reservation. Never silently switch providers or change effort. For a previously unqualified host/route, obtain authorization for a small routing test of nested delegation, completion wakeups, idle behavior, cancellation and edit preservation. Record observed results and limitations.

The root launches **one** dispatcher using the exact `dispatcher` target returned by `init`. Explicitly authorize it to create implementation and independent review children for this milestone. Children have no subdelegation authority. Use async delegation, bind the returned task IDs, follow the host's `next` and yield on pending work. The root receives the final handoff, a genuine external decision, or a takeover. Target zero routine root wakeups; investigate routing overhead if root calls approach ten per milestone. Record actual resource use when available.

## Implement, escalate and review

Use `python3 scripts/dispatch.py --db "$db" COMMAND ...`. The script records decisions; the dispatcher calls T3.

1. Read `status PROBLEM` and reserve with `reserve PROBLEM "specific hypothesis" --kind repair --cohort FAMILY --base FULL_SHA`. Supply known labels; kind may also be `implementation` or `verification`. Pass the reservation's driver, provider, model and options as the T3 target and its token as the client request ID. Run `bind TOKEN TASK_ID`. Reconcile a lost acknowledgement using the same request ID. An existing bound reservation refers to its original child.
2. Give the writer its requirement, checkout, files, hypothesis, previous evidence and checks. It implements, tests, and makes a scoped local commit when authorized. Use `finish TOKEN technical EVIDENCE` for a failed engineering attempt. Retry the same problem ID with a different hypothesis. Record a candidate with `finish TOKEN candidate EVIDENCE --revision FULL_SHA`.
3. Reserve a review with `review-start SCOPE FULL_SHA`. Use the returned reviewer route for a **fresh, read-only, independent child**, including when writer and reviewer use the same model. Bind with `review-bind TOKEN TASK_ID`. Store the report with `review-finish TOKEN REPORT_PATH --scores C S M T --blockers N --checks pass|incomplete`. Score correctness/lifecycle, security/trust boundaries, maintainability/simplicity and tests/evidence on a 1–10 scale, weighted 30%, 30%, 25% and 15%.
4. A failed review reopens a unique matching candidate. With several candidates on the same revision, use `link-rejection REVIEW_TOKEN ATTEMPT_TOKEN` for affected attempts. For an integrated SHA that differs from the contributing candidate, use `reject ATTEMPT_TOKEN REPORT_PATH` on the evidenced candidate. Keep recurring findings on the original problem and ledger. The route of an existing writer reservation remains fixed.
5. Escalate **the writer** after the configured number of technical failures per level. The same number of failed scored votes in one scope also raises the milestone's minimum writer tier, capped at its last tier. Distinct component and final votes do not count twice toward that floor. After exhausting the writer ladder, return a `takeover` receipt. The root takes responsibility for implementation and verification within the user's authorization. Include the failing check, exact SHA, attempts and remaining hypothesis. Continue review on repaired candidates until the affected component and the separate `final` scope pass on the delivered revision. Acceptance requires an unrounded weighted score strictly above 9.5, zero blockers and complete required checks. There is no limit on scored reviews of successive repaired revisions.
6. Infrastructure errors, unavailable hardware and cancellations have a separate outcome. After a confirmed terminal infrastructure failure use `finish TOKEN infra EVIDENCE` or `review-infra TOKEN EVIDENCE`. After recovery and confirmed settlement, `resume TOKEN` releases a writer slot; reserve a fresh reviewer after a retired review. Keep queued or ambiguously alive children bound. On a user pause, stop scheduling, cancel known outstanding tasks via T3, verify descendant settlement, and preserve edits, evidence and ledger.

## Report the result

Return a short milestone receipt with disposition, frozen SHA, checks actually run, outstanding limits, attempts, review counts and evidence paths. At handoff run `python3 scripts/model_report.py`; use its JSON output for a private point-in-time snapshot. Use `measure TOKEN` when provider counters are available. Compare runs within the same kind, cohort and starting revision. See [metric definitions and examples](references/model-telemetry.md).
