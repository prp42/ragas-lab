"""RAGAS scoring plus the slide-18 symptom → diagnosis → prescription matrix."""

import math
from typing import TypedDict

from app.config import Settings

METRICS = ("faithfulness", "answer_relevancy", "context_precision", "context_recall")
RAGAS_COLUMN = {
    "faithfulness": "faithfulness",
    "answer_relevancy": "answer_relevancy",
    "context_precision": "llm_context_precision_with_reference",
    "context_recall": "context_recall",
}


class Sample(TypedDict):
    question: str
    reference: str
    answer: str
    contexts: list[str]
    documents: list[str]


class Finding(TypedDict):
    metric: str
    score: float
    stage: str
    diagnosis: str
    prescription: str


# Ordered retrieval first: if retrieval fails, generation cannot be rescued (slide 10).
RULES: list[tuple[str, float, str, str, str]] = [
    ("context_recall", 0.5, "검색", "필요한 근거를 못 가져옴", "Top K 늘리기(지식베이스 설정) · 청크 크기·overlap 조정 · 하이브리드 검색"),
    ("context_precision", 0.5, "검색", "관련 청크가 밀리고 잡음이 많음", "리랭커 추가 · Top K 줄이기 · 청크 정제(참고문헌 등 제거)"),
    ("faithfulness", 0.8, "생성", "근거 밖 내용을 지어냄", "근거만 사용하라는 규칙 · '모른다' 허용 · 근거 인용 강제 · temperature 낮추기"),
    ("answer_relevancy", 0.7, "생성", "질문 초점에서 벗어남 또는 정직한 거절", "답변 형식·범위를 프롬프트에 명시 · 낮은 문항을 열어 거절인지 확인"),
]


def _clean(value: object) -> float | None:
    if value is None:
        return None
    number = float(value)  # type: ignore[arg-type]
    return None if math.isnan(number) else round(number, 3)


def summarize(rows: list[dict[str, float | None]]) -> dict[str, float | None]:
    summary: dict[str, float | None] = {}
    for metric in METRICS:
        values = [r[metric] for r in rows if r.get(metric) is not None]
        summary[metric] = round(sum(values) / len(values), 3) if values else None  # type: ignore[arg-type]
    return summary


def diagnose(summary: dict[str, float | None]) -> list[Finding]:
    findings: list[Finding] = []
    for metric, threshold, stage, diagnosis, prescription in RULES:
        score = summary.get(metric)
        if score is not None and score < threshold:
            findings.append(Finding(metric=metric, score=score, stage=stage, diagnosis=diagnosis, prescription=prescription))
    return findings


def score_samples(samples: list[Sample], settings: Settings) -> list[dict[str, float | None]]:
    """Faithfulness and relevancy for every sample; the two context metrics only where a reference exists."""
    from langchain_openai import ChatOpenAI, OpenAIEmbeddings
    from ragas import EvaluationDataset, RunConfig, evaluate
    from ragas.embeddings import LangchainEmbeddingsWrapper
    from ragas.llms import LangchainLLMWrapper
    from ragas.metrics import AnswerRelevancy, Faithfulness, LLMContextPrecisionWithReference, LLMContextRecall

    llm = LangchainLLMWrapper(
        ChatOpenAI(base_url=settings.judge_base_url, api_key=settings.judge_api_key, model=settings.judge_model, temperature=0)
    )
    embeddings = LangchainEmbeddingsWrapper(
        OpenAIEmbeddings(
            base_url=settings.embed_base_url,
            api_key=settings.embed_api_key,
            model=settings.embed_model,
            check_embedding_ctx_length=False,
        )
    )
    run_config = RunConfig(max_workers=4, timeout=180, max_retries=3)

    def as_record(s: Sample) -> dict:
        record = {"user_input": s["question"], "response": s["answer"], "retrieved_contexts": s["contexts"] or [""]}
        if s["reference"]:
            record["reference"] = s["reference"]
        return record

    scores: list[dict[str, float | None]] = [{m: None for m in METRICS} for _ in samples]

    base = evaluate(
        dataset=EvaluationDataset.from_list([as_record(s) for s in samples]),
        metrics=[Faithfulness(), AnswerRelevancy()],
        llm=llm,
        embeddings=embeddings,
        run_config=run_config,
        show_progress=False,
    ).to_pandas()
    for i in range(len(samples)):
        scores[i]["faithfulness"] = _clean(base.iloc[i]["faithfulness"])
        scores[i]["answer_relevancy"] = _clean(base.iloc[i]["answer_relevancy"])

    with_ref = [i for i, s in enumerate(samples) if s["reference"]]
    if with_ref:
        ctx = evaluate(
            dataset=EvaluationDataset.from_list([as_record(samples[i]) for i in with_ref]),
            metrics=[LLMContextPrecisionWithReference(), LLMContextRecall()],
            llm=llm,
            run_config=run_config,
            show_progress=False,
        ).to_pandas()
        for row, i in enumerate(with_ref):
            scores[i]["context_precision"] = _clean(ctx.iloc[row][RAGAS_COLUMN["context_precision"]])
            scores[i]["context_recall"] = _clean(ctx.iloc[row][RAGAS_COLUMN["context_recall"]])
    return scores
