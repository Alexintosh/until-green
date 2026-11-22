#!/usr/bin/env python3
"""Compare spawn-local work from local ledger receipts and optional T3 run metadata."""
import argparse
from collections import defaultdict
from contextlib import closing
import json
from pathlib import Path
import sqlite3
from statistics import median
import sys


sys.dont_write_bytecode = True
from t3_metrics import readonly, seconds, t3_receipt


def ledger_rows(path):
    with closing(readonly(path)) as db:
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        def indexed(name):
            return {r["token"]: dict(r) for r in db.execute("SELECT * FROM " + name)} if name in tables else {}
        routes = indexed("attempt_routes")
        routes.update(indexed("review_routes"))
        cached = indexed("telemetry_t3")
        labels = indexed("telemetry_labels")
        usage = indexed("telemetry_usage")
        events = defaultdict(dict)
        if "telemetry_events" in tables:
            for r in db.execute("SELECT * FROM telemetry_events"):
                events[r["token"]][r["event"]] = r["at_ms"]
        records = []
        for role, table in (("writer", "attempts"), ("reviewer", "reviews")):
            for r in db.execute("SELECT * FROM " + table + " ORDER BY rowid"):
                token = r["token"]
                label = labels.get(token, {})
                route = json.loads(routes.get(token, {}).get("route", "{}"))
                options = route.get("options", {})
                vote = json.loads(r["report"]) if role == "reviewer" and r["report"] else {}
                records.append(dict(token=token, task=r["task"], milestone=path.parent.name, role=role,
                    problem=r["problem"] if role == "writer" else None,
                    scope=r["scope"] if role == "reviewer" else None, sha=r["revision"],
                    outcome=r["outcome"] if role == "writer" else
                    ("infra" if r["infra"] else "reviewed" if vote else None),
                    verdict=vote.get("passed"), score=vote.get("weighted"), blockers=vote.get("blockers"),
                    checks=vote.get("checks"), dimensions=vote.get("scores"),
                    requested_model=route.get("model"), provider=route.get("providerInstanceId"),
                    effort=next(iter(options.values()), None),
                    kind=label.get("kind"), cohort=label.get("cohort"), base=label.get("base_sha"),
                    recorded_t3=json.loads(cached.get(token, {}).get("metadata", "{}")),
                    ledger_events=events[token], usage={k:v for k,v in usage.get(token, {}).items() if k!="token"}))
        return records


def identity(row):
    # Some historical multi-problem binds suffixed the same T3 task with an encoded fragment.
    task = row.get("task") or ""
    return task.split("%23", 1)[0] if task.startswith("node:delegated-task:") else row["token"]


def duration_stats(values):
    xs = [x for x in values if x is not None]
    return dict(n=len(xs), median_s=median(xs) if xs else None)


def historical_rows(path):
    """Optional explicit T3 task references predating the ledger; never synthesize votes."""
    if not path.exists():
        return []
    records = []
    seen = set()
    for ref in json.loads(path.read_text()):
        task = ref["task"]
        if not task.startswith("node:delegated-task:") or task in seen:
            raise ValueError("invalid or duplicate historical task")
        seen.add(task)
        records.append(dict(token=task, task=task, milestone=ref["milestone"], role="writer",
                            problem=None, scope=None, sha=None, outcome=None, verdict=None,
                            score=None, blockers=None, checks=None, dimensions=None,
                            kind=ref.get("kind"), cohort=ref.get("cohort"), base=ref.get("base"),
                            ledger_events={}, usage={}, historical=True))
    return records


def compile_report(rows, t3, cohort=None, base=None):
    runs = {}
    for r in rows:
        key = identity(r)
        if key not in runs:
            runs[key] = t3_receipt(t3, key)
        observed = dict(r.pop("recorded_t3", {}))
        observed.update({k:v for k,v in runs[key].items() if v is not None})
        for field, value in observed.items():
            if value is not None:
                r[field] = value
        r["review_stage"] = ("final" if r["scope"] == "final" else "component") if r["role"] == "reviewer" else None
        r["model_basis"] = "executed" if r.get("executed_model") else "requested" if r.get("requested_model") else "unknown"
        r["queue_s"] = seconds(r.get("requested_ms"), r.get("started_ms"))
        r["wall_s"] = seconds(r.get("started_ms"), r.get("ended_ms"))
        e = r.get("ledger_events", {})
        r["bound_to_receipt_s"] = seconds(e.get("bound"), e.get("finished"))
        u = r.get("usage", {})
        if u.get("input_tokens") is not None and u.get("cached_tokens") is not None:
            u["uncached_input_tokens"] = u["input_tokens"] - u["cached_tokens"]
    by_revision = defaultdict(list)
    for r in rows:
        if r["role"] == "writer" and r["sha"]:
            by_revision[r["milestone"],r["sha"]].append(r)
    for r in rows:
        if r["role"] == "reviewer":
            writers = by_revision[r["milestone"],r["sha"]]
            for key in ("base","cohort"):
                labels = {w.get(key) for w in writers}
                if len(labels) == 1:
                    r[key] = labels.pop()
    groups = defaultdict(dict)
    milestones = defaultdict(list)
    for r in rows:
        milestones[r["milestone"]].append(r)
        if (cohort and r.get("cohort") != cohort) or (base and r.get("base") != base):
            continue
        k = (r["role"], r.get("provider"), r.get("executed_model") or r.get("requested_model"),
             r["model_basis"], r.get("effort"), r.get("kind"), r.get("cohort"), r["review_stage"])
        groups[k].setdefault(identity(r), []).append(r)
    writer_votes = defaultdict(list)
    multi_author = 0
    results = []
    for milestone, items in milestones.items():
        writers = [r for r in items if r["role"] == "writer"]
        votes = [r for r in items if r["role"] == "reviewer" and r["verdict"] is not None]
        for vote in votes:
            if vote["scope"] == "final":
                continue
            authors = {identity(w) for w in writers if w["sha"] == vote["sha"]}
            if len(authors) == 1:
                writer_votes[milestone, next(iter(authors))].append(vote)
            elif len(authors) > 1:
                multi_author += 1
        latest = {}
        for item in items:
            if item["role"] == "reviewer" and item["outcome"] != "infra":
                latest[item["scope"]] = item
        final = latest.get("final")
        accepted = bool(final and len(latest) > 1 and all(
            v["sha"] == final["sha"] and v["verdict"] is True for v in latest.values()))
        # Lead time starts with the first tracked milestone assignment. References
        # to pre-ledger work describe a different phase and stay in the timing groups.
        tracked = [w for w in writers if not w.get("historical")]
        starts = [w.get("requested_ms") for w in tracked]
        ends = [v.get("ended_ms") for v in latest.values()] if accepted else []
        lead_source = "t3"
        if not starts or None in starts or not ends or None in ends:
            starts = [w["ledger_events"].get("reserved") for w in tracked]
            ends = [v["ledger_events"].get("finished") for v in latest.values()] if accepted else []
            lead_source = "ledger"
        lead = seconds(min(starts),max(ends)) if starts and ends and None not in starts+ends else None
        finals = [v for v in votes if v["scope"] == "final"]
        results.append(dict(milestone=milestone, accepted_sha=final["sha"] if accepted else None,
                            tracked_start_to_accept_s=lead, lead_time_basis=lead_source if lead is not None else None,
                            writer_tasks=len({identity(w) for w in writers}),
                            technical_receipts=sum(w["outcome"]=="technical" for w in writers),
                            infra_receipts=sum(w["outcome"]=="infra" for w in writers),
                            component_votes=sum(v["scope"]!="final" for v in votes), final_votes=len(finals)))
    summary = []
    for k, tasks in groups.items():
        entries = [items[0] for items in tasks.values()]
        if k[0] == "writer":
            scored = [v for task, items in tasks.items() for v in writer_votes[items[0]["milestone"], task]]
        else:
            scored = [e for items in tasks.values() for e in items if e["verdict"] is not None]
        m = dict(zip(("role","provider","model","model_basis","effort","kind","cohort","review_stage"),k))
        first_votes = [writer_votes[items[0]["milestone"],task][0] for task,items in tasks.items()
                       if k[0] == "writer" and writer_votes[items[0]["milestone"],task]]
        m.update(first_component_votes=len(first_votes),
                 first_component_passes=sum(v["verdict"] for v in first_votes),
                 infra_tasks=sum(any(e["outcome"]=="infra" for e in items) for items in tasks.values()),
                 tasks=len(tasks), wall=duration_stats(e["wall_s"] for e in entries),
                 queue=duration_stats(e["queue_s"] for e in entries),
                 ledger_elapsed=duration_stats(e["bound_to_receipt_s"] for e in entries),
                 votes=len(scored), passed_votes=sum(v["verdict"] for v in scored),
                 median_score=median(float(v["score"]) for v in scored) if scored else None,
                 blockers=sum(v["blockers"] for v in scored) if scored else None)
        for field in ("input_tokens","cached_tokens","uncached_input_tokens","output_tokens","inference_ms"):
            vals = []
            for items in tasks.values():
                known = {e.get("usage",{}).get(field) for e in items} - {None}
                if len(known) == 1:
                    vals.append(known.pop())
            m[field] = {"n":len(vals),"sum":sum(vals) if vals else None}
        summary.append(m)
    return dict(schema_version=1, groups=summary, milestones=results,
                ambiguous_component_votes=multi_author, receipts=rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root",type=Path,default=Path.home()/".local/state/spawn-local")
    parser.add_argument("--t3-db",type=Path,default=Path.home()/".t3/userdata/statev2.sqlite")
    parser.add_argument("--ledger-only",action="store_true")
    parser.add_argument("--format",choices=("json","table"),default="table")
    parser.add_argument("--cohort")
    parser.add_argument("--base",help="exact starting revision")
    args = parser.parse_args()
    paths = sorted(args.root.glob("*/dispatch.sqlite"))
    if not paths:
        parser.error("no milestone ledgers found under --root")
    rows = [r for p in paths for r in ledger_rows(p)]
    linked = {identity(r) for r in rows}
    rows.extend(r for r in historical_rows(args.root/"telemetry-history.json") if identity(r) not in linked)
    t3 = None
    try:
        if not args.ledger_only and args.t3_db.exists():
            t3 = readonly(args.t3_db)
            t3_receipt(t3, "node:delegated-task:schema-check")
    except sqlite3.Error:
        if t3:
            t3.close()
        t3 = None
        print("T3 metadata unavailable; using ledger receipts.",file=sys.stderr)
    try:
        data = compile_report(rows,t3,args.cohort,args.base)
    finally:
        if t3:
            t3.close()
    if args.cohort or args.base:
        data["receipts"] = [r for r in data["receipts"]
                            if (not args.cohort or r.get("cohort")==args.cohort)
                            and (not args.base or r.get("base")==args.base)]
        # Milestone lead times use the full population; a cohort slice cannot represent it.
        data.pop("milestones")
        data.pop("ambiguous_component_votes")
    if args.format == "json":
        print(json.dumps(data,indent=2,ensure_ascii=False))
        return
    print("role | provider/model (basis) | effort | kind/cohort | tasks | median wall min (n) | passed/votes | median score")
    for g in data["groups"]:
        w=g["wall"]
        elapsed=f"{w['median_s']/60:.1f} ({w['n']})" if w["n"] else "— (0)"
        print(" | ".join(str(x) for x in (g["role"] + ("/" + g["review_stage"] if g["review_stage"] else ""),f"{g['provider'] or '?'}/{g['model'] or '?'} ({g['model_basis']})",
                         g["effort"] or "?",f"{g['kind'] or '?'}/{g['cohort'] or '?'}",
                         g["tasks"],elapsed,f"{g['passed_votes']}/{g['votes']}",round(g["median_score"], 3) if g["median_score"] is not None else "—")))
    for m in data.get("milestones", []):
        t = m["tracked_start_to_accept_s"]
        print(f"{m['milestone']}  accepted SHA {m['accepted_sha'] or '—'}  tracked start to acceptance: "
              + (f"{t/60:.1f} min" if t is not None else "—"))


if __name__=="__main__":
    main()
