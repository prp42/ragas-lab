"""HTTP API and static UI for the Week 14 RAGAS lab."""

import csv
import hmac
import io
import logging
import re
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any, Protocol

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.config import Settings, load_settings
from app.content import ATTACKS, SAMPLE_QUESTIONS, Question
from app.dify_client import AppInfo, DifyAppError, DifyWebClient, InvalidLinkError, parse_share_link
from app.store import KST, RunRow, Store

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
STUDENT_ID_RE = re.compile(r"^[A-Za-z0-9_-]{2,20}$")


class Runner(Protocol):
    def submit_eval(self, run_id: str, app_code: str, questions: list[Question]) -> None: ...
    def submit_attack(self, run_id: str, app_code: str) -> None: ...


class AppInfoSource(Protocol):
    def app_info(self) -> AppInfo: ...


class User(BaseModel):
    student_id: str
    is_teacher: bool


class LinkBody(BaseModel):
    link: str = Field(max_length=300)


class QuestionIn(BaseModel):
    question: str = Field(min_length=1, max_length=500)
    reference: str = Field(default="", max_length=2000)


class EvalBody(LinkBody):
    questions: list[QuestionIn] = Field(min_length=1)


def _public_run(run: RunRow) -> dict[str, Any]:
    return {k: v for k, v in run.items() if k != "payload"}


def create_app(
    settings: Settings, store: Store, runner: Runner, client_factory: Callable[[str, str], AppInfoSource]
) -> FastAPI:
    app = FastAPI(title="RAGAS 실험실", docs_url=None, redoc_url=None, openapi_url=None)

    def current_user(
        x_class_code: Annotated[str, Header()] = "",
        x_student_id: Annotated[str, Header()] = "",
    ) -> User:
        if settings.local_mode:
            return User(student_id="local", is_teacher=True)
        is_teacher = bool(settings.teacher_code) and hmac.compare_digest(x_class_code, settings.teacher_code)
        is_student = hmac.compare_digest(x_class_code, settings.class_code)
        if not (is_teacher or is_student) or not STUDENT_ID_RE.match(x_student_id):
            raise HTTPException(401, "수업 코드나 학번이 올바르지 않습니다.")
        return User(student_id=x_student_id, is_teacher=is_teacher)

    UserDep = Annotated[User, Depends(current_user)]

    def app_code_of(link: str) -> str:
        try:
            return parse_share_link(link, base_url=settings.dify_base_url)
        except InvalidLinkError as exc:
            raise HTTPException(400, str(exc)) from exc

    def quota(user: User, kind: str) -> dict[str, int | None]:
        used = store.runs_today(student_id=user.student_id, kind=kind, now=datetime.now(KST))
        return {"used": used, "limit": None if user.is_teacher else settings.runs_per_day}

    def check_quota(user: User, kind: str) -> None:
        q = quota(user, kind)
        if q["limit"] is not None and q["used"] >= q["limit"]:
            raise HTTPException(429, f"오늘 실행 횟수({q['limit']}회)를 모두 썼습니다. 내일 다시 시도하세요.")

    @app.get("/api/me")
    def me(user: UserDep) -> dict[str, Any]:
        return {
            "student_id": user.student_id,
            "is_teacher": user.is_teacher,
            "local_mode": settings.local_mode,
            "quota": {"eval": quota(user, "eval"), "attack": quota(user, "attack")},
            "max_questions": settings.max_questions,
            "judge_model": settings.judge_model,
            "dify_base_url": settings.dify_base_url,
        }

    @app.get("/api/sample")
    def sample(user: UserDep) -> dict[str, Any]:
        return {"questions": SAMPLE_QUESTIONS, "attacks": ATTACKS}

    @app.post("/api/check")
    def check(body: LinkBody, user: UserDep) -> AppInfo:
        code = app_code_of(body.link)
        try:
            return client_factory(settings.dify_base_url, code).app_info()
        except DifyAppError as exc:
            raise HTTPException(502, str(exc)) from exc

    @app.post("/api/runs")
    def start_eval(body: EvalBody, user: UserDep) -> dict[str, str]:
        if len(body.questions) > settings.max_questions:
            raise HTTPException(422, f"질문은 최대 {settings.max_questions}개까지입니다.")
        code = app_code_of(body.link)
        check_quota(user, "eval")
        questions = [Question(question=q.question.strip(), reference=q.reference.strip()) for q in body.questions]
        run_id = store.create_run(
            student_id=user.student_id,
            kind="eval",
            app_code=code,
            payload={"questions": questions},
            now=datetime.now(KST),
            total=len(questions),
        )
        runner.submit_eval(run_id, code, questions)
        return {"run_id": run_id}

    @app.post("/api/attacks")
    def start_attack(body: LinkBody, user: UserDep) -> dict[str, str]:
        code = app_code_of(body.link)
        check_quota(user, "attack")
        run_id = store.create_run(
            student_id=user.student_id, kind="attack", app_code=code, payload={}, now=datetime.now(KST), total=len(ATTACKS)
        )
        runner.submit_attack(run_id, code)
        return {"run_id": run_id}

    @app.get("/api/runs")
    def list_runs(user: UserDep) -> list[dict[str, Any]]:
        runs = store.list_runs(student_id=None if user.is_teacher else user.student_id)
        return [
            {**{k: r[k] for k in ("id", "student_id", "kind", "app_code", "status", "progress", "total", "created_at", "error")},
             "summary": (r["result"] or {}).get("summary")}
            for r in runs
        ]

    @app.get("/api/runs/{run_id}")
    def get_run(run_id: str, user: UserDep) -> dict[str, Any]:
        run = store.get_run(run_id, student_id=None if user.is_teacher else user.student_id)
        if run is None:
            raise HTTPException(404, "실행 기록을 찾을 수 없습니다.")
        return _public_run(run)

    @app.get("/api/runs/{run_id}/csv")
    def run_csv(run_id: str, user: UserDep) -> Response:
        run = store.get_run(run_id, student_id=None if user.is_teacher else user.student_id)
        if run is None or not run["result"] or "summary" not in run["result"]:
            raise HTTPException(404, "완료된 평가 실행이 아닙니다.")
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["question", "reference", "answer", "faithfulness", "answer_relevancy", "context_precision", "context_recall", "latency_s", "documents"])
        for item in run["result"]["items"]:
            s = item["scores"]
            writer.writerow([item["question"], item["reference"], item["answer"], s["faithfulness"], s["answer_relevancy"],
                             s["context_precision"], s["context_recall"], item["latency_s"], " | ".join(item["documents"])])
        return Response(
            content="﻿" + buf.getvalue(),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="ragas_{run_id[:8]}.csv"'},
        )

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app


def build() -> FastAPI:
    from app.jobs import JobRunner

    logging.basicConfig(level=logging.INFO)
    settings = load_settings()
    store = Store(settings.db_path)
    store.fail_unfinished_runs("서버가 재시작되어 중단됐습니다. 다시 실행하세요.")
    return create_app(settings, store, JobRunner(settings, store), DifyWebClient)
