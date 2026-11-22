"""Read a single bound T3 task's timing and route metadata without reading messages."""
import json
import sqlite3
from datetime import datetime
from pathlib import Path

def readonly(path):
    db = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=5)
    db.row_factory = sqlite3.Row
    db.execute("BEGIN")
    return db


def millis(value):
    if not value:
        return None
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return round(stamp.timestamp() * 1000) if stamp.tzinfo else None
    except (ValueError, TypeError, AttributeError):
        return None


def seconds(start, end):
    if start is None or end is None or end < start:
        return None
    return round((end - start) / 1000, 3)


def t3_receipt(db, task):
    if not db or not task.startswith("node:delegated-task:"):
        return {}
    thread = "thread:" + task[len("node:"):]
    # Select only telemetry fields. Messages and tool arguments stay outside this query.
    rows = db.execute("""
        SELECT provider_instance_id, requested_at, completed_at,
               json_extract(payload_json,'$.startedAt') AS started,
               json_extract(payload_json,'$.executedModel') AS executed,
               json_extract(payload_json,'$.modelSelection') AS selection
        FROM orchestration_v2_projection_runs WHERE thread_id=? LIMIT 2
    """, (thread,)).fetchall()
    if len(rows) != 1:
        return {}
    r = rows[0]
    selection = json.loads(r["selection"] or "{}")
    options = {v["id"]: v.get("value") for v in selection.get("options", [])}
    return dict(provider=r["provider_instance_id"], requested_model=selection.get("model"),
                executed_model=r["executed"], effort=options.get("reasoningEffort", options.get("variant")),
                requested_ms=millis(r["requested_at"]), started_ms=millis(r["started"]),
                ended_ms=millis(r["completed_at"]))


def capture(db, token):
    row = db.execute("SELECT task FROM attempts WHERE token=? UNION ALL SELECT task FROM reviews WHERE token=?",
                     (token,token)).fetchone()
    if not row or not row[0]:
        return
    path = Path.home()/".t3/userdata/statev2.sqlite"
    if not path.is_file():
        return
    source = None
    try:
        source = readonly(path)
        source.execute("PRAGMA busy_timeout=50")
        observed = t3_receipt(source,row[0].split("%23",1)[0])
    except (OSError, sqlite3.Error, ValueError, TypeError, KeyError):
        return  # T3 is an optional data source; collection never controls routing.
    finally:
        if source:
            source.close()
    if observed:
        old = db.execute("SELECT metadata FROM telemetry_t3 WHERE token=?", (token,)).fetchone()
        merged = json.loads(old[0]) if old else {}
        merged.update({k:v for k,v in observed.items() if v is not None})
        db.execute("INSERT OR REPLACE INTO telemetry_t3 VALUES (?,?)", (token,json.dumps(merged)))
