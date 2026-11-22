# Until Green

Delegate a coding milestone to one dispatcher. The dispatcher assigns implementation to a writer, sends each candidate to a fresh reviewer, and increases the writer's thinking effort or changes its model when fixes keep failing. A local SQLite ledger remembers the chosen routes, attempts and review results across restarts.

Use it when you want an expensive root model to define the task and receive the result while other models handle the implementation and repair loop. You can choose the dispatcher, writers and reviewer independently.

## Install

Use Python 3.9+ with SQLite. The ledger, telemetry and tests use the Python standard library. Live delegation uses a T3 Code host with nested asynchronous tasks and completion notifications. Configure your model providers in that host. The included profiles are starting configurations; available provider instances, model names and thinking options depend on your setup.

From the root of your local clone, install the skill into Codex with a symlink:

```sh
skills_dir="${CODEX_HOME:-$HOME/.codex}/skills"
mkdir -p "$skills_dir"
if [ -e "$skills_dir/until-green" ] || [ -L "$skills_dir/until-green" ]; then
  echo "An until-green skill already exists. Choose which installation to use."
else
  ln -s "$PWD/skills/until-green" "$skills_dir/until-green"
fi
```

You can also copy the entire `skills/until-green/` directory into a supported skill search path. Start a fresh session that discovers the skill. Each agent that uses the ledger needs access to the same milestone directory and skill scripts.

## Use it from a prompt

```text
Use $until-green with the codex profile to fix the parser's handling of empty
fields. Keep the public API stable. Run the parser tests and review the fix.
```

```text
Use $until-green with the alpi profile. Keep GLM as dispatcher, start the
writer at max, and use GPT-6.2 Sol high as the independent reviewer for
this milestone only.
```

The skill translates the second prompt into `init --profile alpi --writer local:max --reviewer sol2:high`. This changes new writer assignments and the reviewer for that milestone. Future milestones retain your saved defaults.

| Profile | Dispatcher and first writer | Escalation and review |
| --- | --- | --- |
| [default](skills/until-green/profiles/default.json) | OpenCode / DeepSeek, starting at low | DeepSeek high/max, then Codex Sol writers. Independent Sol 6.1 high reviewer. |
| [codex](skills/until-green/profiles/codex.json) | Codex / GPT-6.1 Sol, starting at low | Higher thinking on Sol 6.1, then Sol 6.2. Fresh Sol 6.1 high reviewer. |
| [alpi](skills/until-green/profiles/alpi.json) | Codex / GLM-5.3-Flash on the `codex_tensorfold` instance, starting at high | GLM max, Sol 6.1 high/max, then Sol 6.2 high/max. Independent Sol 6.1 high reviewer. |

“Local” describes the orchestration and ledger. Inference runs wherever the selected provider is configured to run; the Sol routes in these examples may use a hosted provider.

## Configure your models

For a saved personal default, copy a profile and edit it with your provider IDs:

```sh
config_dir="${XDG_CONFIG_HOME:-$HOME/.config}/until-green"
mkdir -p "$config_dir"
# Run once, before editing your own profile.
test -e "$config_dir/profile.json" || cp skills/until-green/profiles/default.json "$config_dir/profile.json"
```

The `agents` object maps a friendly alias to a T3 driver, provider instance, model and thinking option. For example, OpenCode commonly uses `variant` and Codex uses `reasoningEffort`. The `dispatcher` and `reviewer` each choose an alias and one effort. The ordered `writers` array selects aliases and their successive thinking levels. `attemptsPerLevel` defaults to three in the shipped profiles. Use JSON `null` as an effort on a route without a thinking option.

**Precedence for a new milestone.** An explicit `--profile NAME_OR_FILE` wins over `UNTIL_GREEN_PROFILE`, then the personal default, then the bundled default. A JSON `--override FILE` merges objects and replaces arrays. Finally, role switches (`--dispatcher`, `--writer`, `--reviewer`) override those choices. The writer switch changes the first stage and preserves the rest of the ladder. Use an override with a `writers` array to replace the full ladder.

For example, this one-run override introduces a new writer without changing the dispatcher. Replace the example instance and model IDs with values from your host:

```json
{
  "agents": {
    "trial": {
      "driverKind": "codex",
      "providerInstanceId": "my-local-provider",
      "model": "my-model",
      "effortOption": "reasoningEffort"
    }
  },
  "writers": [
    {"agent": "trial", "levels": ["low", "high"]},
    {"agent": "sol2", "levels": ["high", "max"]}
  ]
}
```

## Inspect a route without starting inference

From the repository root:

```sh
skill="$PWD/skills/until-green"
db="$HOME/.local/state/until-green/parser-repair/dispatch.sqlite"

python3 "$skill/scripts/dispatch.py" --db "$db" init --profile alpi \
  --writer local:max --reviewer sol2:high
python3 "$skill/scripts/dispatch.py" --db "$db" routes
python3 "$skill/scripts/dispatch.py" --db "$db" status parser-empty-fields
```

`init` stores the effective profile in that milestone's database. Resume by using the same database. Changes to saved preferences affect new milestones. The root takes over if the writer ladder is exhausted; negative reviews continue the repair loop. See the [skill instructions](skills/until-green/SKILL.md) for reservation, cancellation, fault recovery and the independent component and final gates.

## Compare model runs

```sh
python3 "$skill/scripts/model_report.py"
python3 "$skill/scripts/model_report.py" --cohort parser-repairs --format json
```

Label tasks by work type, cohort and starting Git SHA. The report separates queue time, writer wall time, review verdicts, blockers and time to acceptance. It distinguishes requested and confirmed models and reports coverage for measured values. Provider counters can be attached when available. Reports can run with ledger data alone using `--ledger-only`. See [telemetry definitions](skills/until-green/references/model-telemetry.md) for interpretation, data sources and export fields.

## Verify locally

```sh
python3 -m unittest discover -s tests -v
```

The tests use temporary directories, synthetic task receipts and no model inference. Qualify nested routing on your T3 host before running the first live milestone.
