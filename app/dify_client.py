"""Talks to a Dify chat app through its public share link, exactly like the browser chat does."""

import re
import time
from typing import TypedDict
from urllib.parse import urlparse

import requests

APP_CODE_RE = re.compile(r"^[A-Za-z0-9]{16}$")
SHARE_PATHS = ("chat", "chatbot")
USER_AGENT = "ragas-lab/1.0 (+week14 class)"


class InvalidLinkError(ValueError):
    """The text is not a share link of a chat app on the allowed Dify host."""


class DifyAppError(RuntimeError):
    """The Dify app could not be reached or refused the request."""


class AppInfo(TypedDict):
    app_code: str
    app_name: str
    citations_enabled: bool
    required_inputs: list[str]


class Reply(TypedDict):
    answer: str
    contexts: list[str]
    documents: list[str]
    latency_s: float


def parse_share_link(link: str, *, base_url: str) -> str:
    """Accept only share links on the configured Dify origin, so the server never fetches arbitrary URLs."""
    base = urlparse(base_url.strip().rstrip("/"))
    parsed = urlparse(link.strip())
    try:
        same_origin = (parsed.scheme, parsed.hostname, parsed.port) == (base.scheme, base.hostname, base.port)
    except ValueError:
        same_origin = False
    if not same_origin:
        raise InvalidLinkError(f"{base.scheme}://{base.netloc}/chat/... 형식의 공유 링크만 사용할 수 있습니다.")
    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) != 2 or parts[0] not in SHARE_PATHS or not APP_CODE_RE.match(parts[1]):
        raise InvalidLinkError("채팅 앱의 공유 링크가 아닙니다. Dify 앱 → 게시 → 웹앱 열기의 주소를 붙여넣으세요.")
    return parts[1]


class DifyWebClient:
    def __init__(self, base_url: str, app_code: str, timeout_s: int = 180) -> None:
        self._base = base_url.rstrip("/") + "/api"
        self._app_code = app_code
        self._timeout_s = timeout_s
        self._session = requests.Session()
        self._session.headers.update({"X-App-Code": app_code, "User-Agent": USER_AGENT})
        self._passport: str | None = None

    def __repr__(self) -> str:
        return f"DifyWebClient(app_code={self._app_code!r})"

    def _request(self, method: str, path: str, json_body: dict | None = None) -> dict:
        headers = {"X-App-Passport": self._passport} if self._passport else {}
        try:
            resp = self._session.request(method, self._base + path, json=json_body, headers=headers, timeout=self._timeout_s)
        except requests.RequestException as exc:
            raise DifyAppError(f"Dify 앱에 연결하지 못했습니다: {exc.__class__.__name__}") from exc
        if resp.status_code == 404:
            raise DifyAppError("앱을 찾을 수 없습니다. 웹앱 공개(게시)가 켜져 있는지 확인하세요.")
        if resp.status_code >= 400:
            message = resp.json().get("message", "") if resp.headers.get("content-type", "").startswith("application/json") else ""
            raise DifyAppError(f"Dify가 요청을 거부했습니다 ({resp.status_code}) {message}".strip())
        return resp.json()

    def _ensure_passport(self) -> None:
        if not self._passport:
            self._passport = self._request("GET", "/passport")["access_token"]

    def app_info(self) -> AppInfo:
        self._ensure_passport()
        site = self._request("GET", "/site")
        params = self._request("GET", "/parameters")
        required: list[str] = []
        for field in params.get("user_input_form", []):
            spec = next(iter(field.values()), {})
            if spec.get("required"):
                required.append(spec.get("label") or spec.get("variable", ""))
        return AppInfo(
            app_code=self._app_code,
            app_name=site.get("site", {}).get("title", ""),
            citations_enabled=bool(params.get("retriever_resource", {}).get("enabled")),
            required_inputs=required,
        )

    def ask(self, query: str) -> Reply:
        """One fresh conversation per question so earlier turns never leak into the context."""
        self._ensure_passport()
        started = time.monotonic()
        body = self._request(
            "POST", "/chat-messages", {"inputs": {}, "query": query, "response_mode": "blocking", "conversation_id": ""}
        )
        resources = body.get("metadata", {}).get("retriever_resources") or []
        return Reply(
            answer=body.get("answer", ""),
            contexts=[r.get("content", "") for r in resources],
            documents=[r.get("document_name", "") for r in resources],
            latency_s=round(time.monotonic() - started, 2),
        )
