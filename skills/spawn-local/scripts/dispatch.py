#!/usr/bin/env python3
"""Durable routing decisions. This program never contacts a model or starts a task."""
import argparse
import json
import os
import re
import sqlite3
import sys
import uuid
from decimal import Decimal
from pathlib import Path

sys.dont_write_bytecode = True

from profiles import describe, milestone_profile, target, writer_levels
from t3_metrics import capture

SCHEMA = """
CREATE TABLE IF NOT EXISTS milestone_config (id INTEGER PRIMARY KEY CHECK(id=1), profile TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS review_routes (token TEXT PRIMARY KEY, route TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS attempts (
    problem TEXT, slot INTEGER, token TEXT PRIMARY KEY, task TEXT UNIQUE,
    hypothesis TEXT NOT NULL, outcome TEXT, evidence TEXT, resumed INTEGER DEFAULT 0,
    revision TEXT);
CREATE TABLE IF NOT EXISTS attempt_routes (token TEXT PRIMARY KEY, route TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS review_rejections (
    review TEXT, attempt TEXT, PRIMARY KEY(review,attempt));
CREATE TABLE IF NOT EXISTS reviews (
    scope TEXT, revision TEXT, token TEXT PRIMARY KEY, task TEXT UNIQUE, report TEXT,
    infra TEXT);
CREATE UNIQUE INDEX IF NOT EXISTS review_active ON reviews(scope,revision) WHERE infra IS NULL;
"""
SCHEMA += Path(__file__).with_name("telemetry.sql").read_text(encoding="utf-8")
SHA = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")


def require(ok, message):
    if not ok:
        raise ValueError(message)


def review_floor(db, step, level_count):
    # Each DB belongs to one milestone. Use the largest completed rejection
    # count across its scopes; component and final votes must not double charge.
    counts = {}
    for scope, report in db.execute("SELECT scope,report FROM reviews WHERE report IS NOT NULL"):
        if not json.loads(report)["passed"]:
            counts[scope] = counts.get(scope, 0) + 1
    count = max(counts.values(), default=0)
    return 1 + min(count // step, level_count - 1) * step


def current(db, problem, profile):
    levels = writer_levels(profile)
    step = profile["attemptsPerLevel"]
    rows = db.execute("SELECT * FROM attempts WHERE problem=? ORDER BY rowid",
                      (problem,)).fetchall()
    failures = sum(r["outcome"] == "technical" for r in rows)
    last = rows[-1] if rows else None
    if last and last["outcome"] != "technical" and not last["resumed"]:
        state = {None: "reserved", "candidate": "candidate", "infra": "blocked"}[last["outcome"]]
        stored = db.execute("SELECT route FROM attempt_routes WHERE token=?", (last["token"],)).fetchone()
        selected = json.loads(stored[0]) if stored else levels[(last["slot"] - 1) // step]
        return dict(state=state, failures=failures, **dict(last), **selected)
    spent = [r["slot"] for r in rows if r["outcome"] == "technical"]
    slot = max(max(spent, default=0) + 1, review_floor(db, step, len(levels)))
    if slot > step * len(levels):
        return dict(state="takeover", failures=failures, problem=problem)
    return dict(state="ready", failures=failures, slot=slot, **levels[(slot - 1) // step])


def run(db, a):
    roles = {role: getattr(a, role) for role in ("dispatcher", "writer", "reviewer") if getattr(a, role, None)}
    profile = milestone_profile(db, getattr(a, "profile", None), getattr(a, "override", None), roles)
    if a.cmd in ("init", "routes"):
        return describe(profile)
    if a.cmd == "measure":
        require(db.execute("SELECT token FROM attempts WHERE token=? UNION ALL "
                           "SELECT token FROM reviews WHERE token=?", (a.token, a.token)).fetchone(),
                "unknown reservation token")
        keys = ("input_tokens", "cached_tokens", "output_tokens", "inference_ms")
        values = [getattr(a, k) for k in keys]
        require(any(v is not None for v in values), "supply at least one measured value")
        old = db.execute("SELECT * FROM telemetry_usage WHERE token=?", (a.token,)).fetchone()
        for i, k in enumerate(keys):
            if old and old[k] is not None:
                require(values[i] in (None, old[k]), "conflicting measurement")
                values[i] = old[k]
        require(all(v is None or 0 <= v < 2**63 for v in values), "invalid counter")
        total, cached = values[:2]
        require(total is None or cached is None or cached <= total, "cached exceeds total input")
        db.execute("INSERT OR REPLACE INTO telemetry_usage VALUES(?,?,?,?,?)", (a.token, *values))
        return dict(zip(keys, values))
    if a.cmd == "history":
        return [dict(r) for r in db.execute("SELECT * FROM attempts WHERE problem=? ORDER BY rowid",
                                            (a.problem,))]
    if a.cmd == "status":
        return current(db, a.problem, profile)
    if a.cmd == "reserve":
        state = current(db, a.problem, profile)
        if state["state"] == "reserved" and state["hypothesis"] == a.hypothesis:
            return state
        require(state["state"] == "ready", "problem is not ready for another attempt")
        require(not db.execute("SELECT 1 FROM attempts WHERE problem=? AND hypothesis=? "
                               "AND outcome='technical'", (a.problem, a.hypothesis)).fetchone(),
                "record a different hypothesis")
        token = str(uuid.uuid4())
        db.execute("INSERT INTO attempts(problem,slot,token,hypothesis) VALUES(?,?,?,?)",
                   (a.problem, state["slot"], token, a.hypothesis))
        require(not a.base or SHA.fullmatch(a.base), "base must be a full commit SHA")
        db.execute("INSERT INTO telemetry_labels VALUES(?,?,?,?)", (token, a.kind, a.cohort, a.base))
        db.execute("INSERT INTO attempt_routes VALUES (?,?)",
                   (token, json.dumps({k:state[k] for k in ("driverKind", "providerInstanceId", "model", "options")})))
        return current(db, a.problem, profile)
    if a.cmd == "link-rejection":
        review = db.execute("SELECT * FROM reviews WHERE token=?", (a.review,)).fetchone()
        attempt = db.execute("SELECT * FROM attempts WHERE token=?", (a.attempt,)).fetchone()
        require(review and review["report"] and not json.loads(review["report"])["passed"],
                "expected a scored unsuccessful review")
        require(attempt and attempt["revision"] == review["revision"] and
                attempt["outcome"] in ("candidate","technical"), "candidate revision mismatch")
        db.execute("INSERT OR IGNORE INTO review_rejections VALUES (?,?)", (a.review, a.attempt))
        db.execute("UPDATE attempts SET outcome='technical' WHERE token=?", (a.attempt,))
        return current(db, attempt["problem"], profile)
    if a.cmd == "review-start":
        require(SHA.fullmatch(a.revision), "expected a full immutable git SHA")
        row = db.execute("SELECT * FROM reviews WHERE scope=? AND revision=? AND infra IS NULL",
                         (a.scope, a.revision)).fetchone()
        reviewer = target(profile, **profile["reviewer"])
        if row:
            stored = db.execute("SELECT route FROM review_routes WHERE token=?", (row["token"],)).fetchone()
            return dict(**dict(row), **(json.loads(stored[0]) if stored else reviewer))
        rows = db.execute("SELECT report FROM reviews WHERE scope=? AND infra IS NULL", (a.scope,)).fetchall()
        require(all(r["report"] for r in rows), "previous review has no recorded result")
        token = str(uuid.uuid4())
        db.execute("INSERT INTO reviews(scope,revision,token) VALUES(?,?,?)",
                   (a.scope, a.revision, token))
        db.execute("INSERT INTO review_routes VALUES(?,?)", (token, json.dumps(reviewer)))
        return dict(token=token, scope=a.scope, revision=a.revision, task=None, report=None, infra=None, **reviewer)
    if a.cmd == "review-show":
        return [dict(r) for r in db.execute("SELECT * FROM reviews WHERE scope=? ORDER BY rowid",
                                            (a.scope,))]
    table = "reviews" if a.cmd in ("review-finish", "review-bind", "review-infra") else "attempts"
    row = db.execute(f"SELECT * FROM {table} WHERE token=?", (a.token,)).fetchone()
    require(row, "unknown reservation token")
    if a.cmd == "review-infra":
        require(not row["report"] and row["infra"] in (None, a.evidence), "conflicting review result")
        db.execute("UPDATE reviews SET infra=? WHERE token=?", (a.evidence, a.token))
        return dict(state="blocked", evidence=a.evidence)
    if table == "reviews":
        require(not row["infra"], "review reservation retired")
    if a.cmd in ("bind", "review-bind"):
        require(row["task"] in (None, a.task), "reservation already bound to another task")
        db.execute(f"UPDATE {table} SET task=? WHERE token=?", (a.task, a.token))
        return dict(token=a.token, task=a.task)
    if a.cmd == "review-finish":
        require(row["task"], "bind the independent reviewer first")
        require(all(1 <= n <= 10 for n in a.scores) and a.blockers >= 0, "invalid rubric")
        score = sum(Decimal(str(n)) * w for n, w in zip(a.scores, (30, 30, 25, 15))) / 100
        passed = score > Decimal("9.5") and a.blockers == 0 and a.checks == "pass"
        report = dict(scores=a.scores, weighted=str(score), blockers=a.blockers,
                      checks=a.checks, passed=passed, evidence=a.evidence)
        encoded = json.dumps(report, sort_keys=True)
        require(row["report"] in (None, encoded), "conflicting review outcome")
        db.execute("UPDATE reviews SET report=? WHERE token=?", (encoded, a.token))
        if not passed and row["report"] is None:
            candidates = db.execute("SELECT token FROM attempts WHERE revision=? AND outcome='candidate'",
                                    (row["revision"],)).fetchall()
            if len(candidates) == 1:
                token = candidates[0]["token"]
                db.execute("INSERT OR IGNORE INTO review_rejections VALUES (?,?)", (a.token, token))
                db.execute("UPDATE attempts SET outcome='technical' WHERE token=?", (token,))
        return report
    outcome = row["outcome"]
    if a.cmd == "resume":
        require(outcome == "infra", "only an infrastructure stop can be resumed")
        db.execute("UPDATE attempts SET resumed=1 WHERE token=?", (a.token,))
    elif a.cmd == "reject":
        require(outcome == "candidate" or
                (outcome == "technical" and row["evidence"] == a.evidence),
                "expected an unresolved candidate")
        db.execute("UPDATE attempts SET outcome='technical', evidence=? WHERE token=?",
                   (a.evidence, a.token))
    else:
        require(row["task"] or a.outcome == "infra", "bind worker before recording its result")
        if a.outcome == "candidate":
            require(a.revision and SHA.fullmatch(a.revision), "candidate requires frozen SHA")
        else:
            require(not a.revision, "revision applies only to a candidate")
        require(outcome is None or (outcome, row["evidence"], row["revision"]) ==
                (a.outcome, a.evidence, a.revision), "conflicting attempt result")
        db.execute("UPDATE attempts SET outcome=?,evidence=?,revision=? WHERE token=?",
                   (a.outcome, a.evidence, a.revision, a.token))
    return current(db, row["problem"], profile)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, type=Path, help="one private database per milestone")
    commands = parser.add_subparsers(dest="cmd", required=True)
    for cmd, keys in {
        "init": [], "routes": [], "measure": ["token"], "history": ["problem"], "status": ["problem"], "reserve": ["problem", "hypothesis"], "bind": ["token", "task"],
        "finish": ["token", "outcome", "evidence"], "resume": ["token"],
        "link-rejection": ["review", "attempt"], "reject": ["token", "evidence"], "review-start": ["scope", "revision"],
        "review-infra": ["token", "evidence"], "review-show": ["scope"], "review-bind": ["token", "task"],
        "review-finish": ["token", "evidence"],
    }.items():
        sub = commands.add_parser(cmd)
        for key in keys:
            sub.add_argument(key, **({"choices": ["technical", "infra", "candidate"]}
                                      if key == "outcome" else {}))
        if cmd == "init":
            sub.add_argument("--profile", help="preset name (default, codex or alpi) or path to a full JSON profile")
            for role in ("dispatcher", "writer", "reviewer"):
                sub.add_argument("--" + role, metavar="AGENT:EFFORT", help="use a profile alias for this milestone")
            sub.add_argument("--override", type=Path, help="one-milestone JSON overrides")
        if cmd == "reserve":
            sub.add_argument("--kind", choices=("implementation", "repair", "verification"))
            sub.add_argument("--cohort", help="shared task or benchmark family")
            sub.add_argument("--base", help="starting commit SHA")
        if cmd == "measure":
            for k in ("input-tokens", "cached-tokens", "output-tokens", "inference-ms"):
                sub.add_argument("--" + k, type=int)
        if cmd == "finish":
            sub.add_argument("--revision")
        if cmd == "review-finish":
            sub.add_argument("--scores", required=True, nargs=4, type=float)
            sub.add_argument("--blockers", required=True, type=int)
            sub.add_argument("--checks", required=True, choices=("pass", "incomplete"))
    args = parser.parse_args()
    for value in vars(args).values():
        if isinstance(value, str):
            require(value.strip() and len(value) <= 2048, "empty or oversized field")
    os.umask(0o077)
    args.db.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with sqlite3.connect(args.db, timeout=10) as db:
        db.row_factory = sqlite3.Row
        db.executescript(SCHEMA)
        db.execute("BEGIN IMMEDIATE")
        result = run(db, args)
        if args.cmd in ("bind", "finish", "review-bind", "review-finish", "review-infra"):
            capture(db, args.token)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, sqlite3.Error) as exc:
        sys.exit(str(exc))
