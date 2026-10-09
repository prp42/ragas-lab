"""Runs evaluation and guardrail jobs on a small worker pool so the shared GPU and judge budget stay bounded."""

import logging
from concurrent.futures import ThreadPoolExecutor

from app.config import Settings
from app.content import ATTACKS, Question
from app.dify_client import DifyAppError, DifyWebClient
from app.evaluator import Sample, diagnose, score_samples, summarize
from app.store import Store

logger = logging.getLogger(__name__)


class JobRunner:
    def __init__(self, settings: Settings, store: Store) -> None:
        self._settings = settings
        self._store = store
        self._pool = ThreadPoolExecutor(max_workers=settings.workers, thread_name_prefix="ragas-job")

    def __repr__(self) -> str:
        return f"JobRunner(workers={self._settings.workers})"

    def submit_eval(self, run_id: str, app_code: str, questions: list[Question]) -> None:
        self._pool.submit(self._run_eval, run_id, app_code, questions)

    def submit_attack(self, run_id: str, app_code: str) -> None:
        self._pool.submit(self._run_attack, run_id, app_code)

    def _run_eval(self, run_id: str, app_code: str, questions: list[Question]) -> None:
        try:
            client = DifyWebClient(self._settings.dify_base_url, app_code)
            self._store.update_run(run_id, status="collecting", progress=0)
            samples: list[Sample] = []
            latencies: list[float] = []
            for i, q in enumerate(questions, start=1):
                reply = client.ask(q["question"])
                samples.append(
                    Sample(
                        question=q["question"],
                        reference=q["reference"],
                        answer=reply["answer"],
                        contexts=reply["contexts"],
                        documents=reply["documents"],
                    )
                )
                latencies.append(reply["latency_s"])
                self._store.update_run(
                    run_id,
                    progress=i,
                    result={"partial": [{"question": s["question"], "answer": s["answer"]} for s in samples]},
                )

            self._store.update_run(run_id, status="scoring")
            scores = score_samples(samples, self._settings)
            summary = summarize(scores)
            items = [
                {
                    "question": s["question"],
                    "reference": s["reference"],
                    "answer": s["answer"],
                    "contexts": s["contexts"],
                    "documents": s["documents"],
                    "latency_s": latencies[i],
                    "scores": scores[i],
                }
                for i, s in enumerate(samples)
            ]
            result = {
                "summary": summary,
                "findings": diagnose(summary),
                "items": items,
                "avg_latency_s": round(sum(latencies) / len(latencies), 2),
                "judge_model": self._settings.judge_model,
            }
            self._store.update_run(run_id, status="done", result=result)
        except DifyAppError as exc:
            self._store.update_run(run_id, status="failed", error=str(exc))
        except Exception as exc:
            logger.exception("evaluation run %s failed", run_id)
            self._store.update_run(run_id, status="failed", error=f"채점 중 오류가 났습니다: {exc.__class__.__name__}")

    def _run_attack(self, run_id: str, app_code: str) -> None:
        try:
            client = DifyWebClient(self._settings.dify_base_url, app_code)
            self._store.update_run(run_id, status="collecting", progress=0)
            items = []
            for i, attack in enumerate(ATTACKS, start=1):
                reply = client.ask(attack["question"])
                items.append({**attack, "answer": reply["answer"], "latency_s": reply["latency_s"]})
                self._store.update_run(run_id, progress=i, result={"items": items})
            self._store.update_run(run_id, status="done", result={"items": items})
        except DifyAppError as exc:
            self._store.update_run(run_id, status="failed", error=str(exc))
        except Exception as exc:
            logger.exception("attack run %s failed", run_id)
            self._store.update_run(run_id, status="failed", error=f"점검 중 오류가 났습니다: {exc.__class__.__name__}")
