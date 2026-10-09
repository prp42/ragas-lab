from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.dify_client import AppInfo
from app.main import create_app
from app.store import Store


class FakeRunner:
    def __init__(self) -> None:
        self.eval_calls: list[tuple[str, str, list]] = []
        self.attack_calls: list[tuple[str, str]] = []

    def submit_eval(self, run_id: str, app_code: str, questions: list) -> None:
        self.eval_calls.append((run_id, app_code, questions))

    def submit_attack(self, run_id: str, app_code: str) -> None:
        self.attack_calls.append((run_id, app_code))


class FakeDify:
    def __init__(self, host: str, app_code: str) -> None:
        self.app_code = app_code

    def app_info(self) -> AppInfo:
        return AppInfo(app_code=self.app_code, app_name="My RAG", citations_enabled=True, required_inputs=[])


LINK = "https://dify.example.com/chat/AbCdEfGh12345678"
STUDENT = {"X-Class-Code": "week14", "X-Student-Id": "2026001"}
TEACHER = {"X-Class-Code": "teach-me", "X-Student-Id": "teacher"}


def make_settings(tmp_path: Path, class_code: str = "week14") -> Settings:
    return Settings(
        class_code=class_code,
        teacher_code="teach-me",
        dify_base_url="https://dify.example.com",
        judge_base_url="http://judge",
        judge_api_key="k",
        judge_model="judge-model",
        embed_base_url="http://embed",
        embed_api_key="none",
        embed_model="e",
        max_questions=3,
        runs_per_day=2,
        workers=1,
        db_path=tmp_path / "t.db",
    )


@pytest.fixture
def ctx(tmp_path: Path):
    settings = make_settings(tmp_path)
    runner = FakeRunner()
    app = create_app(settings, Store(settings.db_path), runner, FakeDify)
    return TestClient(app), runner


@pytest.fixture
def local_ctx(tmp_path: Path):
    settings = make_settings(tmp_path, class_code="")
    runner = FakeRunner()
    app = create_app(settings, Store(settings.db_path), runner, FakeDify)
    return TestClient(app), runner


def test_local_mode_needs_no_codes_and_has_no_daily_limit(local_ctx) -> None:
    client, runner = local_ctx
    me = client.get("/api/me").json()
    assert me["local_mode"] is True
    assert me["quota"]["eval"]["limit"] is None
    for _ in range(3):
        resp = client.post("/api/runs", json={"link": LINK, "questions": [{"question": "q", "reference": ""}]})
        assert resp.status_code == 200
    assert len(runner.eval_calls) == 3


def test_class_mode_reports_not_local(ctx) -> None:
    client, _ = ctx
    assert client.get("/api/me", headers=STUDENT).json()["local_mode"] is False


def questions(n: int) -> list[dict]:
    return [{"question": f"질문 {i}", "reference": ""} for i in range(n)]


def test_rejects_wrong_class_code(ctx) -> None:
    client, _ = ctx
    resp = client.get("/api/me", headers={"X-Class-Code": "nope", "X-Student-Id": "2026001"})
    assert resp.status_code == 401


def test_rejects_malformed_student_id(ctx) -> None:
    client, _ = ctx
    resp = client.get("/api/me", headers={"X-Class-Code": "week14", "X-Student-Id": "<script>"})
    assert resp.status_code == 401


def test_check_rejects_link_on_other_host(ctx) -> None:
    client, _ = ctx
    resp = client.post("/api/check", json={"link": "https://evil.example.com/chat/AbCdEfGh12345678"}, headers=STUDENT)
    assert resp.status_code == 400


def test_check_returns_app_info(ctx) -> None:
    client, _ = ctx
    resp = client.post("/api/check", json={"link": LINK}, headers=STUDENT)
    assert resp.status_code == 200
    assert resp.json()["app_name"] == "My RAG"


def test_eval_rejects_too_many_questions(ctx) -> None:
    client, runner = ctx
    resp = client.post("/api/runs", json={"link": LINK, "questions": questions(4)}, headers=STUDENT)
    assert resp.status_code == 422
    assert runner.eval_calls == []


def test_eval_enforces_daily_quota_but_not_for_teacher(ctx) -> None:
    client, runner = ctx
    for _ in range(2):
        assert client.post("/api/runs", json={"link": LINK, "questions": questions(2)}, headers=STUDENT).status_code == 200
    resp = client.post("/api/runs", json={"link": LINK, "questions": questions(2)}, headers=STUDENT)
    assert resp.status_code == 429
    assert len(runner.eval_calls) == 2

    for _ in range(3):
        assert client.post("/api/runs", json={"link": LINK, "questions": questions(2)}, headers=TEACHER).status_code == 200


def test_student_sees_only_own_runs(ctx) -> None:
    client, _ = ctx
    run_id = client.post("/api/runs", json={"link": LINK, "questions": questions(1)}, headers=STUDENT).json()["run_id"]
    other = {"X-Class-Code": "week14", "X-Student-Id": "2026002"}
    assert client.get(f"/api/runs/{run_id}", headers=other).status_code == 404
    assert client.get(f"/api/runs/{run_id}", headers=STUDENT).status_code == 200
    assert client.get("/api/runs", headers=other).json() == []


def test_attack_run_is_queued(ctx) -> None:
    client, runner = ctx
    resp = client.post("/api/attacks", json={"link": LINK}, headers=STUDENT)
    assert resp.status_code == 200
    assert runner.attack_calls[0][1] == "AbCdEfGh12345678"
