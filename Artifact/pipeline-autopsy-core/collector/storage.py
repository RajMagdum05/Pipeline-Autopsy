"""
Storage — plain sqlite3, on purpose. This is a final-year project, not a
production data platform; a well-understood schema beats an ORM here.
"""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Optional

DB_PATH = Path(__file__).parent / "autopsy.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS executions (
    id          TEXT PRIMARY KEY,
    claim_id    TEXT NOT NULL,
    pipeline    TEXT NOT NULL,
    started_at  REAL NOT NULL,
    status      TEXT NOT NULL DEFAULT 'in_progress'
);

CREATE TABLE IF NOT EXISTS trace_events (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    execution_id TEXT NOT NULL,
    step         TEXT NOT NULL,
    step_index   INTEGER NOT NULL,
    started_at   REAL NOT NULL,
    ended_at     REAL NOT NULL,
    status       TEXT NOT NULL,
    error        TEXT,
    input_json   TEXT NOT NULL,
    output_json  TEXT NOT NULL,
    FOREIGN KEY (execution_id) REFERENCES executions (id)
);

CREATE TABLE IF NOT EXISTS diagnoses (
    execution_id     TEXT PRIMARY KEY,
    status           TEXT NOT NULL,
    root_cause_step  TEXT,
    confidence       REAL,
    rule             TEXT,
    evidence_json    TEXT NOT NULL,
    propagated_json  TEXT NOT NULL,
    computed_at      REAL NOT NULL,
    FOREIGN KEY (execution_id) REFERENCES executions (id)
);
"""


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript(SCHEMA)


def save_trace_event(event) -> None:
    with get_conn() as conn:
        conn.execute(
            """INSERT OR IGNORE INTO executions (id, claim_id, pipeline, started_at, status)
               VALUES (?, ?, ?, ?, 'in_progress')""",
            (event.execution_id, event.claim_id, event.pipeline, event.started_at),
        )
        conn.execute(
            """INSERT INTO trace_events
               (execution_id, step, step_index, started_at, ended_at, status, error, input_json, output_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                event.execution_id,
                event.step,
                event.step_index,
                event.started_at,
                event.ended_at,
                event.status,
                event.error,
                json.dumps(event.input),
                json.dumps(event.output),
            ),
        )


def get_execution(execution_id: str) -> Optional[dict[str, Any]]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM executions WHERE id = ?", (execution_id,)).fetchone()
        return dict(row) if row else None


def get_trace_events(execution_id: str) -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM trace_events WHERE execution_id = ? ORDER BY step_index ASC",
            (execution_id,),
        ).fetchall()
    events = []
    for row in rows:
        d = dict(row)
        d["input"] = json.loads(d.pop("input_json"))
        d["output"] = json.loads(d.pop("output_json"))
        events.append(d)
    return events


def list_executions() -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT e.*, d.status AS diagnosis_status, d.root_cause_step, d.confidence
               FROM executions e LEFT JOIN diagnoses d ON d.execution_id = e.id
               ORDER BY e.started_at DESC"""
        ).fetchall()
    return [dict(r) for r in rows]


def update_execution_status(execution_id: str, status: str) -> None:
    with get_conn() as conn:
        conn.execute("UPDATE executions SET status = ? WHERE id = ?", (status, execution_id))


def save_diagnosis(diagnosis) -> None:
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO diagnoses
               (execution_id, status, root_cause_step, confidence, rule, evidence_json, propagated_json, computed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(execution_id) DO UPDATE SET
                 status=excluded.status, root_cause_step=excluded.root_cause_step,
                 confidence=excluded.confidence, rule=excluded.rule,
                 evidence_json=excluded.evidence_json, propagated_json=excluded.propagated_json,
                 computed_at=excluded.computed_at""",
            (
                diagnosis.execution_id,
                diagnosis.status,
                diagnosis.root_cause_step,
                diagnosis.confidence,
                diagnosis.rule,
                json.dumps([e.model_dump() for e in diagnosis.evidence]),
                json.dumps(diagnosis.propagated_to),
                diagnosis.computed_at,
            ),
        )


def get_diagnosis(execution_id: str) -> Optional[dict[str, Any]]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM diagnoses WHERE execution_id = ?", (execution_id,)).fetchone()
    if not row:
        return None
    d = dict(row)
    d["evidence"] = json.loads(d.pop("evidence_json"))
    d["propagated_to"] = json.loads(d.pop("propagated_json"))
    return d
