"""Google Chat通知経路のテスト（ロープレ通知は個別DM専用）。"""
from services import google_chat


def _clear_chat_env(monkeypatch):
    for key in (
        "CHAT_SA_JSON",
        "CHAT_SA_FILE",
        "CHAT_ADMIN_SUBJECT",
        "CHAT_WEBHOOK_URL",
    ):
        monkeypatch.delenv(key, raising=False)


def test_individual_notify_never_falls_back_to_webhook(monkeypatch):
    _clear_chat_env(monkeypatch)
    monkeypatch.setenv("CHAT_WEBHOOK_URL", "https://example.invalid/webhook")
    monkeypatch.setattr(
        google_chat,
        "_post_webhook",
        lambda _text: (_ for _ in ()).throw(AssertionError("Webhookを呼んではならない")),
    )

    result = google_chat.notify_individually({"a@example.com": "message"})

    assert result["skipped"] is True
    assert result["mode"] == ""
    assert result["sent"] == []


def test_individual_notify_sends_each_person_separately(monkeypatch):
    _clear_chat_env(monkeypatch)
    monkeypatch.setenv("CHAT_SA_JSON", "{}")
    monkeypatch.setenv("CHAT_ADMIN_SUBJECT", "admin@example.com")
    sent = []
    monkeypatch.setattr(
        google_chat,
        "_send_dm",
        lambda email, text: sent.append((email, text)),
    )

    result = google_chat.notify_individually(
        {
            "a@example.com": "message-a",
            "b@example.com": "message-b",
        }
    )

    assert result["skipped"] is False
    assert result["mode"] == "dm"
    assert result["sent"] == ["a@example.com", "b@example.com"]
    assert sent == [
        ("a@example.com", "message-a"),
        ("b@example.com", "message-b"),
    ]


def test_direct_message_exists_returns_false_for_404(monkeypatch):
    class _Response:
        status = 404

    class _NotFoundError(Exception):
        resp = _Response()

    monkeypatch.setattr(
        google_chat,
        "_find_direct_message",
        lambda _email: (_ for _ in ()).throw(_NotFoundError("not found")),
    )

    assert google_chat.direct_message_exists("a@example.com") is False


def test_direct_message_exists_does_not_hide_other_errors(monkeypatch):
    monkeypatch.setattr(
        google_chat,
        "_find_direct_message",
        lambda _email: (_ for _ in ()).throw(RuntimeError("permission denied")),
    )

    try:
        google_chat.direct_message_exists("a@example.com")
    except RuntimeError as e:
        assert str(e) == "permission denied"
    else:
        raise AssertionError("404以外のエラーは呼び出し側へ返す必要がある")
