from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from app.store import Store

KST = ZoneInfo("Asia/Seoul")


def test_quota_counts_runs_per_student_per_kind_per_day(tmp_path: Path) -> None:
    store = Store(tmp_path / "t.db")
    day1 = datetime(2026, 10, 9, 23, 0, tzinfo=KST)

    for _ in range(2):
        store.create_run(student_id="2026001", kind="eval", app_code="a" * 16, payload={}, now=day1)
    store.create_run(student_id="2026001", kind="attack", app_code="a" * 16, payload={}, now=day1)
    store.create_run(student_id="2026002", kind="eval", app_code="a" * 16, payload={}, now=day1)

    assert store.runs_today(student_id="2026001", kind="eval", now=day1) == 2
    assert store.runs_today(student_id="2026001", kind="attack", now=day1) == 1


def test_failed_runs_do_not_use_quota(tmp_path: Path) -> None:
    store = Store(tmp_path / "t.db")
    now = datetime(2026, 10, 9, 12, 0, tzinfo=KST)
    run_id = store.create_run(student_id="2026001", kind="eval", app_code="a" * 16, payload={}, now=now)
    store.update_run(run_id, status="failed", error="Dify 연결 실패")

    assert store.runs_today(student_id="2026001", kind="eval", now=now) == 0


def test_quota_resets_at_midnight_kst(tmp_path: Path) -> None:
    store = Store(tmp_path / "t.db")
    store.create_run(
        student_id="2026001", kind="eval", app_code="a" * 16, payload={}, now=datetime(2026, 10, 9, 23, 59, tzinfo=KST)
    )

    next_day = datetime(2026, 10, 10, 0, 1, tzinfo=KST)
    assert store.runs_today(student_id="2026001", kind="eval", now=next_day) == 0


def test_runs_are_listed_only_for_their_student(tmp_path: Path) -> None:
    store = Store(tmp_path / "t.db")
    now = datetime(2026, 10, 9, 12, 0, tzinfo=KST)
    mine = store.create_run(student_id="2026001", kind="eval", app_code="a" * 16, payload={}, now=now)
    store.create_run(student_id="2026002", kind="eval", app_code="b" * 16, payload={}, now=now)

    assert [r["id"] for r in store.list_runs(student_id="2026001")] == [mine]
    assert store.get_run(mine, student_id="2026002") is None


def test_update_and_fail_stale_runs(tmp_path: Path) -> None:
    store = Store(tmp_path / "t.db")
    now = datetime(2026, 10, 9, 12, 0, tzinfo=KST)
    run_id = store.create_run(student_id="2026001", kind="eval", app_code="a" * 16, payload={}, now=now)
    store.update_run(run_id, status="collecting", progress=3)

    assert store.fail_unfinished_runs("server restarted") == 1
    run = store.get_run(run_id, student_id="2026001")
    assert run is not None
    assert run["status"] == "failed"
    assert run["error"] == "server restarted"
