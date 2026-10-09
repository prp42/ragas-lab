import pytest

from app.dify_client import InvalidLinkError, parse_share_link

BASE = "https://dify.example.com"


@pytest.mark.parametrize(
    "link",
    [
        "https://dify.example.com/chat/AbCdEfGh12345678",
        "https://dify.example.com/chat/AbCdEfGh12345678/",
        "  https://dify.example.com/chatbot/AbCdEfGh12345678?foo=1  ",
    ],
)
def test_parse_share_link_returns_app_code(link: str) -> None:
    assert parse_share_link(link, base_url=BASE) == "AbCdEfGh12345678"


@pytest.mark.parametrize(
    "link",
    [
        "https://evil.example.com/chat/AbCdEfGh12345678",
        "http://dify.example.com/chat/AbCdEfGh12345678",
        "https://dify.example.com.evil.com/chat/AbCdEfGh12345678",
        "https://dify.example.com:8443/chat/AbCdEfGh12345678",
        "https://dify.example.com/workflow/AbCdEfGh12345678",
        "https://dify.example.com/chat/short",
        "https://dify.example.com/chat/AbCdEfGh12345678/../../etc",
        "not a url",
        "",
    ],
)
def test_parse_share_link_rejects_other_hosts_and_shapes(link: str) -> None:
    with pytest.raises(InvalidLinkError):
        parse_share_link(link, base_url=BASE)


@pytest.mark.parametrize(
    ("base", "link"),
    [
        ("http://localhost", "http://localhost/chat/AbCdEfGh12345678"),
        ("http://localhost:8088", "http://localhost:8088/chat/AbCdEfGh12345678"),
        ("http://localhost/", "http://localhost/chatbot/AbCdEfGh12345678"),
        ("http://192.168.0.10", "http://192.168.0.10/chat/AbCdEfGh12345678"),
    ],
)
def test_parse_share_link_accepts_self_hosted_dify(base: str, link: str) -> None:
    assert parse_share_link(link, base_url=base) == "AbCdEfGh12345678"


def test_parse_share_link_requires_matching_port() -> None:
    with pytest.raises(InvalidLinkError):
        parse_share_link("http://localhost:3000/chat/AbCdEfGh12345678", base_url="http://localhost")
