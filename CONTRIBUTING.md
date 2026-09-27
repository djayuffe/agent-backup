# Contributing

Thanks for looking. This is a small, dependency-free tool, and the bar for a
change is that it keeps someone's backups intact.

## Getting set up

```bash
git clone https://github.com/djayuffe/agent-backup
cd agent-backup
pip install -e ".[dev]"
```

## Before you open a pull request

Run what CI runs:

```bash
ruff check .          # lint
mypy                  # types
python -m pytest      # 43 tests; warnings are errors
python -m pytest --cov && python -m coverage report --fail-under=90
```

CI repeats all of it on Python 3.10–3.13 across Linux, macOS and Windows, plus a
packaging check and a profile check. A red pipeline blocks a merge.

## What a good change looks like

- **Data safety comes first.** This tool exists so that state the agent has
  deleted still exists somewhere. A change that can overwrite, prune or drop
  something needs to be explicit, opt-in, and tested. See the guarantees section
  of the README; several of them exist because a bug ate real data.
- **Tests for the claim you are making.** Every guarantee in the README has a
  test behind it. Two genuine bugs were found precisely by writing those tests.
- **No runtime dependencies.** The standard library only. Development
  dependencies are fine.
- **Support a new agent with a profile, not with code.** If a JSON profile cannot
  express the format, say so in the issue — the engine may need a new field
  (that is how `type_field` arrived), but a special case for one agent is not the
  way in.
- **Match the surrounding style.** 120 columns, type hints on public functions,
  comments that explain *why*.

## Adding an agent

Write a JSON profile (see [`agent-profiles/example-agent.json`](agent-profiles/example-agent.json)
and the profile reference in the README), then prove it against real state:

```bash
python3 agent_backup.py audit --profile-file my-agent.json --agent my-agent
```

`audit` exits non-zero and names what it could not handle. A profile is ready
when it reports no unhandled block types, no duplicate ids and no output-name
collisions. Please include that output in the pull request.

## Reporting a bug

Say which agent and profile, what you ran, and what `audit` reports. Never paste
session content — it is your conversation history, and the tool exists to keep it
yours.
