from app.evaluator import diagnose, summarize


def test_summarize_averages_ignoring_missing_scores() -> None:
    rows = [
        {"faithfulness": 1.0, "answer_relevancy": 0.5, "context_precision": None, "context_recall": None},
        {"faithfulness": 0.5, "answer_relevancy": None, "context_precision": 0.2, "context_recall": 0.4},
    ]
    assert summarize(rows) == {
        "faithfulness": 0.75,
        "answer_relevancy": 0.5,
        "context_precision": 0.2,
        "context_recall": 0.4,
    }


def test_summarize_returns_none_when_metric_never_measured() -> None:
    rows = [{"faithfulness": 0.9, "answer_relevancy": 0.8, "context_precision": None, "context_recall": None}]
    assert summarize(rows)["context_recall"] is None


def test_diagnose_flags_retrieval_first_when_recall_is_low() -> None:
    findings = diagnose(
        {"faithfulness": 0.9, "answer_relevancy": 0.8, "context_precision": 0.3, "context_recall": 0.2}
    )
    assert [f["metric"] for f in findings] == ["context_recall", "context_precision"]
    assert findings[0]["stage"] == "검색"


def test_diagnose_reports_healthy_system() -> None:
    findings = diagnose(
        {"faithfulness": 0.95, "answer_relevancy": 0.85, "context_precision": 0.8, "context_recall": 0.9}
    )
    assert findings == []


def test_diagnose_skips_unmeasured_metrics() -> None:
    findings = diagnose({"faithfulness": 0.5, "answer_relevancy": 0.9, "context_precision": None, "context_recall": None})
    assert [f["metric"] for f in findings] == ["faithfulness"]
