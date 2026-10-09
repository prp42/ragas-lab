"""SQLite persistence for runs and daily quotas."""

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, TypedDict
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")
UNFINISHED = ("queued", "collecting", "scoring")


class RunRow(TypedDict):
    id: str
    student_id: str
    kind: str
    app_code: str
    app_name: str
    status: str
    progress: int
    total: int
    error: str
    created_at: str
    payload: dict[str, Any]
    result: dict[str, Any] | None


class Store:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock, self._conn:
            self._conn.execute(
                """create table if not exists runs (
                    id text primary key, student_id text not null, kind text not null, app_code text not null,
                    app_name text not null default '', status text not null, progress integer not null default 0,
                    total integer not null default 0, error text not null default '', created_at text not null,
                    payload text not null, result text)"""
            )
            self._conn.execute("create index if not exists runs_student on runs(student_id, kind, created_at)")

    def __repr__(self) -> str:
        return "Store(sqlite)"

    def create_run(
        self, *, student_id: str, kind: str, app_code: str, payload: dict[str, Any], now: datetime, app_name: str = "", total: int = 0
    ) -> str:
        run_id = uuid.uuid4().hex
        with self._lock, self._conn:
            self._conn.execute(
                "insert into runs (id, student_id, kind, app_code, app_name, status, total, created_at, payload) "
                "values (?, ?, ?, ?, ?, 'queued', ?, ?, ?)",
                (run_id, student_id, kind, app_code, app_name, total, now.astimezone(KST).isoformat(), json.dumps(payload, ensure_ascii=False)),
            )
        return run_id

    def runs_today(self, *, student_id: str, kind: str, now: datetime) -> int:
        start = now.astimezone(KST).replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)
        with self._lock:
            row = self._conn.execute(
                "select count(*) from runs where student_id = ? and kind = ? and created_at >= ? and created_at < ? and status != 'failed'",
                (student_id, kind, start.isoformat(), end.isoformat()),
            ).fetchone()
        return int(row[0])

    def update_run(self, run_id: str, **fields: Any) -> None:
        if "result" in fields:
            fields["result"] = json.dumps(fields["result"], ensure_ascii=False)
        cols = ", ".join(f"{k} = ?" for k in fields)
        with self._lock, self._conn:
            self._conn.execute(f"update runs set {cols} where id = ?", (*fields.values(), run_id))

    def fail_unfinished_runs(self, reason: str) -> int:
        with self._lock, self._conn:
            cur = self._conn.execute(
                f"update runs set status = 'failed', error = ? where status in ({','.join('?' * len(UNFINISHED))})",
                (reason, *UNFINISHED),
            )
        return cur.rowcount

    def get_run(self, run_id: str, *, student_id: str | None) -> RunRow | None:
        with self._lock:
            row = self._conn.execute("select * from runs where id = ?", (run_id,)).fetchone()
        if row is None or (student_id is not None and row["student_id"] != student_id):
            return None
        return self._to_row(row)

    def list_runs(self, *, student_id: str | None, limit: int = 50) -> list[RunRow]:
        with self._lock:
            if student_id is None:
                rows = self._conn.execute("select * from runs order by created_at desc limit ?", (limit,)).fetchall()
            else:
                rows = self._conn.execute(
                    "select * from runs where student_id = ? order by created_at desc limit ?", (student_id, limit)
                ).fetchall()
        return [self._to_row(r) for r in rows]

    @staticmethod
    def _to_row(row: sqlite3.Row) -> RunRow:
        return RunRow(
            id=row["id"],
            student_id=row["student_id"],
            kind=row["kind"],
            app_code=row["app_code"],
            app_name=row["app_name"],
            status=row["status"],
            progress=row["progress"],
            total=row["total"],
            error=row["error"],
            created_at=row["created_at"],
            payload=json.loads(row["payload"]),
            result=json.loads(row["result"]) if row["result"] else None,
        )
