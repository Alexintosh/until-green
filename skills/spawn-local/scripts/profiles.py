"""Resolve and freeze the routes for one milestone. No provider connections."""
import json
import os
from pathlib import Path


PRESETS = Path(__file__).resolve().parents[1] / "profiles"


def fields(obj, required, optional=()):
    if not isinstance(obj, dict):
        raise ValueError("expected a JSON object")
    missing = set(required) - obj.keys()
    extra = obj.keys() - (set(required) | set(optional))
    if missing or extra:
        raise ValueError(f"invalid profile fields: missing {sorted(missing)}, unexpected {sorted(extra)}")


def string(value, label):
    if not isinstance(value, str) or not value.strip() or value != value.strip() or not value.isprintable():
        raise ValueError(f"expected a nonempty identifier for {label}")
    return value


def target(profile, agent, effort):
    string(agent, "agent")
    if agent not in profile["agents"]:
        raise ValueError(f"unknown agent alias: {agent}")
    definition = profile["agents"][agent]
    options = {}
    if effort is not None:
        option = definition.get("effortOption")
        if not option:
            raise ValueError(f"missing effortOption for {agent}")
        options[option] = string(effort, "effort")
    return dict(driverKind=definition["driverKind"], providerInstanceId=definition["providerInstanceId"],
                model=definition["model"], options=options)


def validate(profile):
    fields(profile, ("version", "agents", "dispatcher", "reviewer", "writers", "attemptsPerLevel"))
    if type(profile["version"]) is not int or profile["version"] != 1:
        raise ValueError("unsupported profile version")
    attempts = profile["attemptsPerLevel"]
    if type(attempts) is not int or attempts < 1:
        raise ValueError("attemptsPerLevel must be a positive integer")
    if not isinstance(profile["agents"], dict) or not profile["agents"]:
        raise ValueError("agents must be a nonempty object")
    for name, definition in profile["agents"].items():
        string(name, "alias")
        fields(definition, ("driverKind", "providerInstanceId", "model"), ("effortOption",))
        for key, value in definition.items():
            if key != "effortOption" or value is not None:
                string(value, key)
    for role in ("dispatcher", "reviewer"):
        fields(profile[role], ("agent", "effort"))
        target(profile, **profile[role])
    if not isinstance(profile["writers"], list) or not profile["writers"]:
        raise ValueError("writers must be a nonempty ordered list")
    for stage in profile["writers"]:
        fields(stage, ("agent", "levels"))
        if not isinstance(stage["levels"], list) or not stage["levels"]:
            raise ValueError("each writer needs at least one level")
        for effort in stage["levels"]:
            target(profile, stage["agent"], effort)
    return profile


def read_object(path):
    try:
        with path.open(encoding="utf-8") as f:
            obj = json.load(f)
    except (OSError, ValueError) as exc:
        raise ValueError(f"could not read profile JSON from {path}: {exc}") from exc
    if not isinstance(obj, dict):
        raise ValueError(f"expected a JSON object in {path}")
    return obj


def merge(base, override):
    result = dict(base)
    for key, value in override.items():
        if isinstance(result.get(key), dict) and isinstance(value, dict):
            result[key] = merge(result[key], value)
        else:
            result[key] = value
    return result


def role_override(value, writer=False):
    alias, sep, levels = value.partition(":")
    if not sep or not levels:
        raise ValueError("expected AGENT:EFFORT or, for a writer, AGENT:EFFORT,EFFORT")
    efforts = [None if level == "-" else level for level in levels.split(",")]
    if writer:
        return {"agent": alias, "levels": efforts}
    if len(efforts) != 1:
        raise ValueError("a dispatcher or reviewer takes one effort")
    return {"agent": alias, "effort": efforts[0]}


def load_profile(name, override, roles):
    name = name or os.environ.get("SPAWN_LOCAL_PROFILE")
    if name in ("alpi", "codex", "default"):
        path = PRESETS / (name + ".json")
    elif name:
        path = Path(name).expanduser()
    else:
        config = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
        user = config / "spawn-local" / "profile.json"
        path = user if user.exists() else PRESETS / "default.json"
    profile = read_object(path)
    if override:
        profile = merge(profile, read_object(override))
    validate(profile)
    for role, value in roles.items():
        if role == "writer":
            profile["writers"][0] = role_override(value, writer=True)
        else:
            profile[role] = role_override(value)
    return validate(profile)


def milestone_profile(db, name, override, roles):
    saved = db.execute("SELECT profile FROM milestone_config WHERE id=1").fetchone()
    if saved:
        profile = json.loads(saved[0])
        if (name or override or roles) and load_profile(name, override, roles) != profile:
            raise ValueError("this milestone already has a different frozen profile")
        return profile
    if not name and db.execute("SELECT 1 FROM attempts UNION ALL SELECT 1 FROM reviews LIMIT 1").fetchone():
        raise ValueError("existing ledger: initialize explicitly with the matching --profile")
    profile = load_profile(name, override, roles)
    last_slot = db.execute("SELECT max(slot) FROM attempts").fetchone()[0] or 0
    if last_slot > len(writer_levels(profile)) * profile["attemptsPerLevel"]:
        raise ValueError("profile is too short for slots already recorded in this ledger")
    db.execute("INSERT INTO milestone_config VALUES(1,?)", (json.dumps(profile),))
    return profile


def writer_levels(profile):
    return [target(profile, stage["agent"], effort)
            for stage in profile["writers"] for effort in stage["levels"]]


def describe(profile):
    return dict(dispatcher=target(profile, **profile["dispatcher"]),
                reviewer=target(profile, **profile["reviewer"]),
                writerLevels=writer_levels(profile), attemptsPerLevel=profile["attemptsPerLevel"])
