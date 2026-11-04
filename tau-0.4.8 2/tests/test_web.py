from collections.abc import AsyncIterator
from dataclasses import replace
from functools import partial
from json import dumps
from pathlib import Path

import anyio
import httpx
import pytest
from typer.testing import CliRunner

from pi_event_helpers import assistant_done
from tau_agent.messages import AssistantMessage
from tau_agent.provider import CancellationToken
from tau_agent.provider_events import AssistantStartEvent, TextDeltaEvent
from tau_agent.session import JsonlSessionStorage
from tau_ai import FakeProvider
from tau_coding import CodingSession, CodingSessionConfig, cli
from tau_coding.cli import app
from tau_coding.paths import TauPaths
from tau_coding.session_manager import SessionManager
from tau_coding.web.server import WebApi, _transcript_preview, frontend_root, serve_web


class _PausingProvider:
    def __init__(self) -> None:
        self.release = anyio.Event()

    def stream_response(
        self,
        *,
        model: str,
        system: str,
        messages: list[object],
        tools: list[object],
        signal: CancellationToken | None = None,
        session_id: str | None = None,
    ) -> AsyncIterator[object]:
        del system, messages, tools, session_id
        release = self.release

        async def iterator() -> AsyncIterator[object]:
            partial = AssistantMessage(content="hi", model=model)
            yield AssistantStartEvent(partial=AssistantMessage(model=model))
            yield TextDeltaEvent(content_index=0, delta="hi", partial=partial)
            while not release.is_set():
                if signal is not None and signal.is_cancelled():
                    return
                await anyio.sleep(0.01)
            yield assistant_done(partial)

        return iterator()


def _session(tmp_path: Path, provider: object) -> CodingSessionConfig:
    return CodingSessionConfig(
        provider=provider,  # type: ignore[arg-type]
        model="fake",
        system="You are Tau.",
        storage=JsonlSessionStorage(tmp_path / "session.jsonl"),
        cwd=tmp_path,
        extensions_enabled=False,
    )


@pytest.mark.anyio
async def test_web_api_streams_and_serves_frontend(tmp_path: Path) -> None:
    provider = _PausingProvider()
    session = await CodingSession.load(_session(tmp_path, provider))
    ready = anyio.Event()
    urls: list[str] = []

    async with anyio.create_task_group() as tasks:
        tasks.start_soon(
            partial(
                serve_web,
                session,
                host="127.0.0.1",
                port=0,
                ready=ready,
                on_ready=urls.append,
            )
        )
        await ready.wait()
        url = urls[0]
        async with httpx.AsyncClient(timeout=5) as client:
            index = await client.get(url)
            assert index.status_code == 200
            assert "app.js" in index.text
            assert index.headers["access-control-allow-origin"] == "*"
            async with httpx.AsyncClient(timeout=5) as anonymous:
                missing_user = await anonymous.post(url + "api/sessions", json={})
                assert missing_user.status_code == 400
            script = await client.get(url + "app.js")
            assert script.status_code == 200
            assert 'action: "prompt"' in script.text
            assert '"/api/sessions"' in script.text
            missing = await client.get(url + "not-a-frontend-file")
            assert missing.status_code == 404
            opened = await client.post(
                url + "api/sessions", json={"userId": "local", "create": True}
            )
            assert opened.status_code == 200
            session_id = opened.json()["sessionId"]
            assert isinstance(session_id, str) and session_id
            missing_session = await client.post(
                url + "api/session",
                json={"userId": "local", "action": "prompt", "message": "hello"},
            )
            assert missing_session.status_code == 400

            async with client.stream(
                "POST",
                url + "api/events",
                json={"userId": "local", "sessionId": session_id},
            ) as events:
                assert events.status_code == 200
                assert events.headers["content-type"].startswith("text/event-stream")
                streamed = ""

                async def read_until_token() -> None:
                    nonlocal streamed
                    async for chunk in events.aiter_text():
                        streamed += chunk
                        if "event: message_update" in streamed and "hi" in streamed:
                            return

                async with anyio.create_task_group() as readers:
                    readers.start_soon(read_until_token)
                    started = await client.post(
                        url + "api/session",
                        json={
                            "userId": "local",
                            "action": "prompt",
                            "sessionId": session_id,
                            "message": "hello",
                        },
                    )
                    assert started.status_code == 204
                    with anyio.fail_after(5):
                        while "event: message_update" not in streamed or "hi" not in streamed:
                            await anyio.sleep(0.02)
                    readers.cancel_scope.cancel()
                assert "event: message_update" in streamed
            busy = await client.post(
                url + "api/session",
                json={
                    "userId": "local",
                    "action": "prompt",
                    "sessionId": session_id,
                    "message": "again",
                },
            )
            assert busy.status_code == 409

            cancelled = await client.post(
                url + "api/session",
                json={"userId": "local", "action": "abort", "sessionId": session_id},
            )
            assert cancelled.status_code == 204
            streaming = True
            for _ in range(50):
                streaming = (
                    await client.post(
                        url + "api/session",
                        json={"userId": "local", "action": "state", "sessionId": session_id},
                    )
                ).json()["isStreaming"]
                if not streaming:
                    break
                await anyio.sleep(0.02)
            assert streaming is False

            empty = await client.post(
                url + "api/session",
                json={
                    "userId": "local",
                    "action": "prompt",
                    "sessionId": session_id,
                    "message": "  ",
                },
            )
            assert empty.status_code == 400
        tasks.cancel_scope.cancel()


@pytest.mark.anyio
async def test_web_api_records_completed_turn_and_command(tmp_path: Path) -> None:
    session = await CodingSession.load(
        _session(
            tmp_path,
            FakeProvider(
                [[assistant_done(AssistantMessage(content="hello from tau", model="fake"))]]
            ),
        )
    )
    api = WebApi(session)
    try:
        async with anyio.create_task_group() as tasks:
            api.bind(tasks)
            command = await api.command("/session")
            assert isinstance(command["message"], str)
            assert "Model: fake" in command["message"]
            await api.prompt("say hello")
            texts: list[str] = []
            streaming = True
            for _ in range(50):
                streaming = bool(api.state()["isStreaming"])
                texts = [_message_text(message) for message in api.messages()]
                if "hello from tau" in texts and not streaming:
                    break
                await anyio.sleep(0.02)
            assert "hello from tau" in texts
            assert streaming is False
            state = api.state()
            assert isinstance(state["tools"], list)
            assert all(isinstance(tool["name"], str) for tool in state["tools"])
            assert isinstance(state["extensions"], list)
            assert isinstance(state["contextTokens"], int)
            assert isinstance(state["contextWindow"], int)
            assert isinstance(state["inputTokens"], int)
            assert isinstance(state["outputTokens"], int)
            assert isinstance(state["skills"], list)
            assert isinstance(state["prompts"], list)
            assert isinstance(state["contextFiles"], list)
            assert isinstance(state["systemPromptFiles"], list)
    finally:
        await session.aclose()


@pytest.mark.anyio
async def test_each_browser_keeps_its_own_session(tmp_path: Path) -> None:
    manager = SessionManager(TauPaths(home=tmp_path / "tau"))
    session = await CodingSession.load(
        replace(
            _session(
                tmp_path,
                FakeProvider(
                    [
                        [assistant_done(AssistantMessage(content="A name", model="fake"))],
                        [
                            assistant_done(
                                AssistantMessage(content="from the new session", model="fake")
                            )
                        ],
                    ]
                ),
            ),
            session_manager=manager,
        )
    )
    legacy = manager.create_session(cwd=tmp_path, model="fake", title="legacy")
    ready = anyio.Event()
    urls: list[str] = []

    async with anyio.create_task_group() as tasks:
        tasks.start_soon(
            partial(
                serve_web,
                session,
                host="127.0.0.1",
                port=0,
                ready=ready,
                on_ready=urls.append,
            )
        )
        await ready.wait()
        url = urls[0]
        async with (
            httpx.AsyncClient(timeout=5) as owner,
            httpx.AsyncClient(timeout=5) as guest,
        ):
            opened = await owner.post(
                url + "api/sessions", json={"userId": "owner", "create": True}
            )
            assert opened.status_code == 200
            created_id = opened.json()["sessionId"]
            assert isinstance(created_id, str)
            assert created_id != session.session_id
            assert session.session_id is None
            assert opened.json()["userId"] == "owner"

            guest_list = await guest.post(url + "api/sessions", json={"userId": "guest"})
            assert guest_list.status_code == 200
            assert guest_list.json()["userId"] == "guest"
            assert all(item["id"] != created_id for item in guest_list.json()["sessions"])
            assert all(item["id"] != legacy.id for item in guest_list.json()["sessions"])
            assert all(item["id"] != legacy.id for item in opened.json()["sessions"])

            started = await owner.post(
                url + "api/session",
                json={
                    "userId": "owner",
                    "action": "prompt",
                    "sessionId": created_id,
                    "message": "hello",
                },
            )
            assert started.status_code == 204
            texts: list[str] = []
            for _ in range(50):
                body = (
                    await owner.post(
                        url + "api/session",
                        json={
                            "userId": "owner",
                            "action": "messages",
                            "sessionId": created_id,
                        },
                    )
                ).json()
                texts = [_message_text(message) for message in body["messages"]]
                if "from the new session" in texts:
                    break
                await anyio.sleep(0.02)
            assert "from the new session" in texts
            state = (
                await owner.post(
                    url + "api/session",
                    json={"userId": "owner", "action": "state", "sessionId": created_id},
                )
            ).json()
            listed = next(item for item in state["sessions"] if item["id"] == created_id)
            assert listed["preview"] == "hello"
            guest_open = await guest.post(
                url + "api/sessions", json={"userId": "guest", "create": True}
            )
            guest_id = guest_open.json()["sessionId"]
            assert guest_id != created_id
            guest_texts = [
                _message_text(message)
                for message in (
                    await guest.post(
                        url + "api/session",
                        json={"userId": "guest", "action": "messages", "sessionId": guest_id},
                    )
                ).json()["messages"]
            ]
            assert "from the new session" not in guest_texts

            switched = await guest.post(
                url + "api/sessions", json={"userId": "guest", "sessionId": created_id}
            )
            assert switched.status_code == 400
        tasks.cancel_scope.cancel()


def _message_text(message: object) -> str:
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and isinstance(block.get("text"), str)
        )
    summary = message.get("summary")
    return summary if isinstance(summary, str) else ""


def test_transcript_preview_reads_the_first_user_message(tmp_path: Path) -> None:
    path = tmp_path / "session.jsonl"
    path.write_text(
        "\n".join(
            [
                dumps({"type": "session_info", "cwd": str(tmp_path)}),
                dumps(
                    {
                        "type": "message",
                        "message": {
                            "role": "user",
                            "content": [{"type": "text", "text": "你好\n第二行"}],
                        },
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    assert _transcript_preview(path) == "你好 第二行"


def test_frontend_root_points_at_the_standalone_client() -> None:
    root = frontend_root()
    assert root is not None
    assert (root / "index.html").is_file()
    assert (root / "app.js").is_file()


def test_web_command_starts_the_api(monkeypatch: pytest.MonkeyPatch) -> None:
    called: dict[str, object] = {}

    async def fake_web(*args: object, **kwargs: object) -> None:
        called["args"] = args
        called["kwargs"] = kwargs

    monkeypatch.setattr(cli, "run_openai_web_mode", fake_web)
    result = CliRunner().invoke(app, ["web", "--port", "9000", "--no-browser"])

    assert result.exit_code == 0, result.output
    assert called["kwargs"] == {
        "host": "0.0.0.0",
        "port": 9000,
        "open_browser": False,
        "serve_frontend": True,
        "thinking_level_override": None,
    }


def test_web_words_stay_a_tui_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    called: list[object] = []

    async def fake_tui(*args: object, **kwargs: object) -> None:
        called.append(args)

    monkeypatch.setattr(cli, "_startup_update_notice", lambda: None)
    monkeypatch.setattr(cli, "run_openai_tui", fake_tui)
    result = CliRunner().invoke(app, ["web", "explain", "this"])

    assert result.exit_code == 0, result.output
    assert called
    assert "web explain this" in called[0]


def test_web_rejects_a_bad_port() -> None:
    result = CliRunner().invoke(app, ["web", "--port", "nope"])
    assert result.exit_code != 0
    assert "integer" in result.output
