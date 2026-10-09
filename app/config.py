import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    class_code: str
    teacher_code: str
    dify_base_url: str
    judge_base_url: str
    judge_api_key: str
    judge_model: str
    embed_base_url: str
    embed_api_key: str
    embed_model: str
    max_questions: int
    runs_per_day: int
    workers: int
    db_path: Path

    @property
    def local_mode(self) -> bool:
        """Without a class code the lab runs for one person: no login screen, no daily limit."""
        return not self.class_code

    def __repr__(self) -> str:
        return f"Settings(dify_base_url={self.dify_base_url!r}, judge_model={self.judge_model!r}, local_mode={self.local_mode})"


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Environment variable {name} is required (see .env.example)")
    return value


def _dify_base_url() -> str:
    base = os.environ.get("DIFY_BASE_URL", "").strip()
    if base:
        return base.rstrip("/")
    legacy_host = os.environ.get("DIFY_HOST", "").strip()
    if legacy_host:
        return f"https://{legacy_host}"
    return "http://localhost"


def load_settings() -> Settings:
    return Settings(
        class_code=os.environ.get("CLASS_CODE", "").strip(),
        teacher_code=os.environ.get("TEACHER_CODE", "").strip(),
        dify_base_url=_dify_base_url(),
        judge_base_url=os.environ.get("JUDGE_BASE_URL", "https://openrouter.ai/api/v1"),
        judge_api_key=_required("JUDGE_API_KEY"),
        judge_model=os.environ.get("JUDGE_MODEL", "anthropic/claude-sonnet-5"),
        embed_base_url=os.environ.get("EMBED_BASE_URL", "http://localhost:11434/v1"),
        embed_api_key=os.environ.get("EMBED_API_KEY", "none"),
        embed_model=os.environ.get("EMBED_MODEL", "bge-m3"),
        max_questions=int(os.environ.get("MAX_QUESTIONS", "10")),
        runs_per_day=int(os.environ.get("RUNS_PER_DAY", "3")),
        workers=int(os.environ.get("WORKERS", "2")),
        db_path=Path(os.environ.get("DB_PATH", "data/ragas_lab.db")),
    )
