import base64
from email import policy
from email.parser import BytesParser
from email.utils import parseaddr, parsedate_to_datetime
from pathlib import Path

import pytest
from scripts import seed_google_e2e as seed


def test_send_fixture__display_name__preserves_authenticated_sender_address() -> None:
    args = seed.parser().parse_args([
        "--tag", "closure31-person", "mail-send", "--to", seed.TEST_ACCOUNTS[0],
        "--sender-name", "김철수 대리 (GWA 테스트)",
        "--subject", "박람회 참석", "--body", "9월 3일",
    ])
    url, payload = seed.build_fixture(args)
    assert url.endswith("/messages/send")
    assert "sender" not in payload
    encoded = seed.encode_mail_payload(payload, account=seed.TEST_ACCOUNTS[0], fingerprint="test")
    message = BytesParser(policy=policy.default).parsebytes(
        base64.urlsafe_b64decode(encoded["raw"]),
    )
    assert parseaddr(str(message["From"])) == ("김철수 대리 (GWA 테스트)", seed.TEST_ACCOUNTS[0])
    assert message["Date"] is None
    assert "[GWA E2E closure31-person]" in str(message["Subject"])


def test_send_fixture__display_name_header_injection__rejects() -> None:
    args = seed.parser().parse_args([
        "--tag", "closure31-person", "mail-send", "--to", seed.TEST_ACCOUNTS[0],
        "--sender-name", "이름\nBcc: other@example.com", "--subject", "test", "--body", "test",
    ])
    with pytest.raises(ValueError, match="줄바꿈"):
        seed.build_fixture(args)


@pytest.mark.parametrize("received_at", ["2026-08-20T10:00:00+09:00", "2026-08-20T10:00:00"])
def test_import_fixture__sender_and_date__preserves_without_sending(received_at: str) -> None:
    args = seed.parser().parse_args([
        "--tag", "closure31", "mail-import", "--to", seed.TEST_ACCOUNTS[0],
        "--sender", seed.TEST_ACCOUNTS[1], "--sender-name", "김철수 대리 (테스트)",
        "--received-at", received_at, "--subject", "체육대회", "--body", "9월 3일 개최",
    ])
    assert not args.execute
    if "+09:00" not in received_at:
        with pytest.raises(ValueError, match="UTC offset"):
            seed.build_fixture(args)
        return
    url, payload = seed.build_fixture(args)
    assert "/messages/import?internalDateSource=dateHeader" in url
    assert "processForCalendar=false" in url
    encoded = seed.encode_mail_payload(payload, account=seed.TEST_ACCOUNTS[0], fingerprint="test")
    message = BytesParser(policy=policy.default).parsebytes(
        base64.urlsafe_b64decode(encoded["raw"]),
    )
    assert parseaddr(str(message["From"])) == ("김철수 대리 (테스트)", seed.TEST_ACCOUNTS[1])
    assert parsedate_to_datetime(message["Date"]).isoformat() == received_at
    assert "[GWA E2E closure31]" in message["Subject"]
    assert "가져온 테스트 자료" in message.get_content()


def test_task_fixture__notes_and_planned_date__preserves() -> None:
    args = seed.parser().parse_args([
        "--tag", "closure4", "task-upload", "--title", "보고서",
        "--notes", "자료 정리", "--scheduled-date", "2026-09-07",
    ])
    _, payload = seed.build_fixture(args)
    assert args.execute is False
    assert payload == {
        "title": "[GWA E2E closure4] 보고서", "notes": "자료 정리",
        "due": "2026-09-07T00:00:00Z",
    }


def test_calendar_fixture__timezone_less_input__rejects() -> None:
    args = seed.parser().parse_args([
        "--tag", "closure4", "calendar-upload", "--title", "회의",
        "--start", "2026-09-08T14:00:00", "--end", "2026-09-08T14:30:00",
    ])
    with pytest.raises(ValueError, match="UTC offset"):
        seed.build_fixture(args)


def test_mail_fixture__other_recipients__rejects() -> None:
    with pytest.raises(SystemExit):
        seed.parser().parse_args([
            "--tag", "closure4", "mail-send", "--to", "other@example.com",
            "--subject", "회의", "--body", "내용",
        ])


@pytest.mark.parametrize("uncertain", [False, True])
@pytest.mark.parametrize("command", ["task-upload", "mail-import"])
def test_fixture_write__completed_or_uncertain__does_not_repeat(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, uncertain: bool,
    command: str,
) -> None:
    from google_work_agent.adapters.connectors.google.workspace.mcp_server import (
        credential_provider,
    )

    class Credential:
        account_email = seed.TEST_ACCOUNTS[0]

        def ensure_access_token(self) -> None:
            pass

    calls = []

    def write(*args: object, **kwargs: object) -> dict[str, str]:
        calls.append((args, kwargs))
        if uncertain:
            raise TimeoutError()
        return {"id": "created-1"}

    monkeypatch.setattr(seed, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(credential_provider, "GoogleWorkspaceCredentialProvider", Credential)
    monkeypatch.setattr(credential_provider, "_google_api_call", write)
    arguments = ["--tag", "closure-test", command]
    arguments += (
        ["--title", "보고서"] if command == "task-upload" else [
            "--to", seed.TEST_ACCOUNTS[0], "--sender", seed.TEST_ACCOUNTS[1],
            "--sender-name", "김철수 대리", "--received-at", "2026-08-20T10:00:00+09:00",
            "--subject", "체육대회", "--body", "9월 3일 행사",
        ]
    )
    url, payload = seed.build_fixture(seed.parser().parse_args(arguments))
    if uncertain:
        with pytest.raises(TimeoutError):
            seed.execute_fixture(url, payload)
    else:
        assert seed.execute_fixture(url, payload)["id"] == "created-1"
    with pytest.raises(ValueError, match="재전송하지 않습니다"):
        seed.execute_fixture(url, payload)
    assert len(calls) == 1
