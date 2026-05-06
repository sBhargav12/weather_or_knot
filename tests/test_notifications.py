from __future__ import annotations

from unittest.mock import Mock

from dashboard import notifications


def test_notify_phone_sends_when_topic_configured(monkeypatch):
    monkeypatch.setattr(notifications.config, "NTFY_TOPIC", "topic")
    monkeypatch.setattr(notifications.config, "NTFY_URL", "https://ntfy.example")
    post = Mock()
    post.return_value.status_code = 200
    post.return_value.raise_for_status.return_value = None
    monkeypatch.setattr(notifications.requests, "post", post)

    notifications.notify_phone("Paper trade entered", "body", priority="high", tags="tag")

    post.assert_called_once_with(
        "https://ntfy.example/topic",
        data=b"body",
        headers={"Title": "Paper trade entered", "Priority": "high", "Tags": "tag"},
        timeout=10,
    )


def test_notify_phone_noops_without_topic(monkeypatch):
    monkeypatch.setattr(notifications.config, "NTFY_TOPIC", "")
    post = Mock()
    monkeypatch.setattr(notifications.requests, "post", post)

    notifications.notify_phone("Paper trade entered", "body")

    post.assert_not_called()
