"""HTTP API for coding sessions, plus the optional static client."""

from __future__ import annotations

import contextlib
import json
import threading
from collections.abc import AsyncIterator, Callable, Iterator
from dataclasses import asdict, is_dataclass
from os import environ
from pathlib import Path
from uuid import uuid4

import anyio
import uvicorn
from anyio.streams.memory import MemoryObjectSendStream
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from agent.events import MessageEndEvent, MessageStartEvent, MessageUpdateEvent
from agent.messages import AssistantMessage
from application.commands import CommandResult, format_reload_summary
from application.events import AgentSettledEvent, CodingSessionEvent
from application.extensions import StderrUiBridge
from application.session import CodingSession, ModelChoice, session_for_client
from application.version import current_version
from entity.web import (
    EventsRequest,
    SessionRequest,
    SessionsRequest,
    StreamingBehavior,
)
from model.client import ModelProvider

_JSON = dict[str, object]
ReadyCallback = Callable[[str], None]


class WebApi:
    """Publish one coding session. The client keeps display state."""

    def __init__(self, session: CodingSession) -> None:
        self._session = session
        self._tasks: anyio.abc.TaskGroup | None = None
        self._lock = anyio.Lock()
        self._prompt_active = False
        self._latest: _JSON | None = None
        self._subscribers: list[MemoryObjectSendStream[_JSON]] = []

    def bind(self, tasks: anyio.abc.TaskGroup) -> None:
        """Attach the server task group that owns prompt turns."""
        self._tasks = tasks

    def state(self) -> _JSON:
        """Return the session facts a frontend reads beside the event stream."""
        session = self._session
        stats = session.session_stats
        usage = session.context_usage
        tool_sources = session.extension_tool_sources
        return {
            "sessionId": session.session_id,
            "sessionName": session.session_title,
            "model": session.model,
            "provider": session.provider_name,
            "cwd": str(session.cwd),
            "thinkingLevel": session.thinking_level,
            "isStreaming": session.is_running or self._prompt_active,
            "pendingMessageCount": session.queued_message_count,
            "contextTokens": usage.total_tokens,
            "contextWindow": session.context_window_tokens,
            "usesProviderUsage": usage.uses_provider_usage,
            "inputTokens": stats.input_tokens,
            "outputTokens": stats.output_tokens,
            "cacheHitRate": stats.cache_hit_rate,
            "estimatedCost": stats.estimated_cost,
            "turnCount": stats.turn_count,
            "toolCallCount": stats.tool_call_count,
            "autoCompactTokens": session.auto_compact_token_threshold,
            "outputTokensPerSecond": stats.output_tokens_per_second,
            "averageTimeToFirstOutputMs": stats.average_time_to_first_output_ms,
            "extensions": list(session.extension_names),
            "tools": [
                {
                    "name": tool.name,
                    "label": tool.label or tool.name,
                    "description": tool.description,
                    "extension": tool_sources.get(tool.name),
                }
                for tool in session.tools
            ],
            "skills": [
                {"name": skill.name, "description": skill.description or ""}
                for skill in session.skills
            ],
            "prompts": [
                {"name": template.name, "description": template.description or ""}
                for template in session.prompt_templates
            ],
            "contextFiles": [Path(item.path).name for item in session.context_files],
            "systemPromptFiles": [Path(path).name for path in session.system_prompt_files],
        }

    def messages(self) -> list[_JSON]:
        """Return the durable transcript as wire messages."""
        return [_object(message) for message in self._session.messages]

    async def event_stream(self) -> AsyncIterator[bytes]:
        """Yield session events. A late subscriber first gets the open assistant update."""
        send, receive = anyio.create_memory_object_stream[_JSON](256)
        latest = self._latest
        self._subscribers.append(send)
        try:
            if latest is not None:
                yield _sse(latest)
            while True:
                data = await receive.receive()
                yield _sse(data)
                if data.get("type") in {"agent_settled", "error"}:
                    return
        except anyio.EndOfStream:
            return
        finally:
            if send in self._subscribers:
                self._subscribers.remove(send)
            with anyio.CancelScope(shield=True):
                await send.aclose()

    async def prompt(
        self,
        message: str,
        *,
        streaming_behavior: StreamingBehavior | None = None,
    ) -> None:
        """Start ``session.prompt``. Queue only when ``streaming_behavior`` is set."""
        text = message.strip()
        if not text:
            raise ValueError("message must be a non-empty string")
        async with self._lock:
            await self._wait_until_running()
            if self._session.is_running or self._prompt_active:
                if streaming_behavior is None:
                    raise RuntimeError(
                        "Agent is already streaming; set streamingBehavior to steer or followUp"
                    )
                stream = self._session.prompt(text, streaming_behavior=streaming_behavior)
                async for event in stream:
                    self._publish(event)
                return
            tasks = self._tasks
            if tasks is None:
                raise RuntimeError("Web server is not running")
            self._prompt_active = True
            tasks.start_soon(self._consume_prompt, text)

    async def command(
        self,
        text: str,
        *,
        can_resume: Callable[[str], bool] | None = None,
    ) -> _JSON:
        """Run a slash command and return its result, including session effects."""
        result = self._session.handle_command(text)
        if not result.handled:
            raise ValueError("Not a slash command")
        if (
            result.resume_session_id is not None
            and can_resume is not None
            and not can_resume(result.resume_session_id)
        ):
            raise ValueError(f"Unknown session: {result.resume_session_id}")
        try:
            notes = await self._apply_command(result)
        except (OSError, RuntimeError, ValueError) as exc:
            notes = [str(exc)]
        payload = _object(result)
        message = "\n".join(part for part in [result.message, *notes] if part)
        if message:
            payload["message"] = message
        return payload

    async def terminal(self, command: str, *, add_to_context: bool) -> _JSON:
        """Run a shell command in the session directory."""
        result = await self._session.run_terminal_command(command, add_to_context=add_to_context)
        return _object(result)

    def abort(self) -> None:
        """Cancel the current turn. Later events show how it stopped."""
        self._session.cancel()

    async def _wait_until_running(self) -> None:
        for _ in range(100):
            if not self._prompt_active or self._session.is_running:
                return
            await anyio.sleep(0.01)
        if self._prompt_active and not self._session.is_running:
            raise RuntimeError("Agent is still starting")

    async def _consume_prompt(self, text: str) -> None:
        try:
            async for event in self._session.prompt(text):
                self._publish(event)
        except (RuntimeError, ValueError) as exc:
            self._send({"type": "error", "error": str(exc)})
        finally:
            self._prompt_active = False

    async def _apply_command(self, command: CommandResult) -> list[str]:
        session = self._session
        notes: list[str] = []
        if command.reload_requested:
            notes.append(format_reload_summary(await session.reload()))
        if command.new_session_requested:
            self._latest = None
            notes.append(f"Started session {await session.new_session()}")
        if command.compact_summary is not None:
            if session.is_running or self._prompt_active:
                raise RuntimeError("Wait for the current turn to finish before compacting")
            notes.append(await session.compact(command.compact_summary or None))
        if command.export_requested:
            exported = await session.export(
                command.export_destination,
                format=command.export_format,
            )
            notes.append(f"Exported session to {exported}")
        if command.resume_session_id is not None:
            self._latest = None
            notes.append(f"Resumed session {await session.resume(command.resume_session_id)}")
        if command.session_name is not None:
            await session.set_session_name(command.session_name)
        if command.thinking_level is not None:
            await session.set_thinking_level(command.thinking_level)
        if command.model_selection_model is not None:
            selected = await session.select_provider_model(
                ModelChoice(
                    provider_name=command.model_selection_provider or session.provider_name,
                    model=command.model_selection_model,
                )
            )
            notes.append(f"Current model: {selected.choice.provider_name}/{selected.choice.model}")
        return notes

    def _publish(self, event: CodingSessionEvent) -> None:
        data = _event(event)
        if isinstance(event, MessageStartEvent | MessageUpdateEvent) and isinstance(
            event.message, AssistantMessage
        ):
            self._latest = data
        elif isinstance(event, MessageEndEvent | AgentSettledEvent):
            self._latest = None
        self._send(data)

    def _send(self, data: _JSON) -> None:
        closed: list[MemoryObjectSendStream[_JSON]] = []
        for subscriber in self._subscribers:
            try:
                subscriber.send_nowait(data)
            except (anyio.WouldBlock, anyio.BrokenResourceError, anyio.ClosedResourceError):
                closed.append(subscriber)
        for subscriber in closed:
            self._subscribers.remove(subscriber)
            subscriber.close()


class WebUsers:
    """Remember which user owns each session. The map survives a server restart."""

    def __init__(self, path: Path | None) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._owners: dict[str, str] = {}
        if path is None or not path.is_file():
            return
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        sessions = loaded.get("sessions") if isinstance(loaded, dict) else None
        if not isinstance(sessions, dict):
            return
        self._owners = {
            str(session_id): str(owner)
            for session_id, owner in sessions.items()
            if isinstance(session_id, str) and isinstance(owner, str)
        }

    def owner(self, session_id: str) -> str | None:
        """Return the user who owns this session, if one has been recorded."""
        with self._lock:
            return self._owners.get(session_id)

    def ids_for(self, user_id: str) -> set[str]:
        """Return the session ids owned by this user."""
        with self._lock:
            return {session_id for session_id, owner in self._owners.items() if owner == user_id}

    def claim(self, user_id: str, session_id: str) -> None:
        """Give this session to the user. A session already owned by someone else stays theirs."""
        with self._lock:
            current = self._owners.get(session_id)
            if current is not None and current != user_id:
                raise ValueError(f"Unknown session: {session_id}")
            if current == user_id:
                return
            self._owners[session_id] = user_id
            self._save(dict(self._owners))

    def _save(self, owners: dict[str, str]) -> None:
        if self._path is None:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps({"sessions": owners}) + "\n", encoding="utf-8")
        temporary.replace(self._path)


class WebOffice:
    """Keep each user's sessions apart, including the turn that session is running."""

    def __init__(self, session: CodingSession) -> None:
        self._origin = session
        self._lock = anyio.Lock()
        self._tasks: anyio.abc.TaskGroup | None = None
        self._origin_user: str | None = None
        self._users = WebUsers(_web_users_path(session))
        self._memory_ids: dict[str, str] = {}
        self._sessions: dict[tuple[str, str | None], CodingSession] = {}
        self._apis: dict[tuple[str, str | None], WebApi] = {}

    def bind(self, tasks: anyio.abc.TaskGroup) -> None:
        """Attach the server task group that owns every open session's turns."""
        self._tasks = tasks
        for api in self._apis.values():
            api.bind(tasks)

    async def open_session(self, user_id: str, session_id: str | None) -> WebApi:
        """Start a session for this user, or attach them to one they own."""
        async with self._lock:
            if session_id is not None and not self._allows(user_id, session_id):
                raise ValueError(f"Unknown session: {session_id}")
            if session_id is None and self._origin.session_manager is None:
                if not self._origin_available(user_id):
                    raise ValueError("Session manager is not available")
                return self._attach_origin(user_id)
            if session_id is None and self._should_adopt_origin(user_id):
                return self._attach_origin(user_id)
            return await self._open_locked(user_id, session_id)

    def _should_adopt_origin(self, user_id: str) -> bool:
        """Give this user the session the server already started, once.

        A later create from the same user starts a separate session. Another
        user does not receive this one.
        """
        origin_id = self._origin.session_id
        if not isinstance(origin_id, str) or not origin_id:
            return False
        if not self._origin_available(user_id):
            return False
        return not self._users.ids_for(user_id)

    async def session(self, user_id: str, session_id: str) -> WebApi:
        """Attach this user to one session they already own."""
        if not session_id.strip():
            raise ValueError("sessionId is required")
        return await self.open_session(user_id, session_id)

    def allows(self, user_id: str, session_id: str) -> bool:
        """Return whether this user may resume that session."""
        return self._allows(user_id, session_id)

    def bound_id(self, user_id: str, api: WebApi, fallback: str) -> str:
        """Return the id the client should send for this live session."""
        real = api._session.session_id
        if isinstance(real, str) and real:
            return real
        for (owner, session_id), found in self._apis.items():
            if owner == user_id and found is api and isinstance(session_id, str) and session_id:
                return session_id
        return fallback

    async def rebind(self, user_id: str, previous_id: str, api: WebApi) -> str:
        """Point this user's requests at the session a command just adopted."""
        async with self._lock:
            current = api._session.session_id
            if not isinstance(current, str) or not current or current == previous_id:
                return self.bound_id(user_id, api, previous_id)
            self._users.claim(user_id, current)
            old = (user_id, previous_id)
            if self._apis.get(old) is api:
                self._apis.pop(old, None)
                self._sessions.pop(old, None)
            self._apis[(user_id, current)] = api
            self._sessions[(user_id, current)] = api._session
            return current

    def list_sessions(self, user_id: str) -> list[_JSON]:
        """Return this user's sessions, this project first, then sessions from elsewhere."""
        manager = self._origin.session_manager
        records = manager.list_sessions() if manager is not None else []
        owned = self._users.ids_for(user_id)
        records = [record for record in records if record.id in owned]
        origin_cwd = self._origin.cwd.resolve()
        local = [record for record in records if record.cwd.resolve() == origin_cwd]
        other = [record for record in records if record.cwd.resolve() != origin_cwd]
        remembered = {
            key[1]: _session_preview(session)
            for key, session in self._sessions.items()
            if key[0] == user_id and key[1] is not None
        }
        known = {record.id for record in records}
        items = [
            self._session_item(session_id, session, remembered.get(session_id, ""))
            for (owner, session_id), session in reversed(self._sessions.items())
            if owner == user_id and session_id is not None and session_id not in known
        ]
        for record in (*local, *other):
            items.append(
                {
                    "id": record.id,
                    "title": record.title,
                    "preview": _transcript_preview(record.path) or remembered.get(record.id, ""),
                    "model": record.model,
                    "provider": record.provider_name,
                    "cwd": str(record.cwd),
                    "updatedAt": record.updated_at,
                }
            )
        return items

    def _session_item(self, session_id: str, session: CodingSession, preview: str) -> _JSON:
        return {
            "id": session_id,
            "title": session.session_title,
            "preview": preview,
            "model": session.model,
            "provider": session.provider_name,
            "cwd": str(session.cwd),
            "updatedAt": None,
        }

    def _allows(self, user_id: str, session_id: str) -> bool:
        return self._users.owner(session_id) == user_id or (user_id, session_id) in self._apis

    def _origin_available(self, user_id: str) -> bool:
        origin_id = self._origin.session_id
        if origin_id is None:
            return self._origin_user in (None, user_id)
        return self._users.owner(origin_id) in (None, user_id)

    def _attach_origin(self, user_id: str) -> WebApi:
        origin_id = self._origin.session_id
        if isinstance(origin_id, str) and origin_id:
            self._users.claim(user_id, origin_id)
            public_id = origin_id
        else:
            public_id = self._memory_ids.get(user_id)
            if public_id is None:
                public_id = uuid4().hex
                self._memory_ids[user_id] = public_id
        self._origin_user = user_id
        key = (user_id, public_id)
        api = self._apis.get(key)
        if api is None:
            api = WebApi(self._origin)
            if self._tasks is not None:
                api.bind(self._tasks)
            self._sessions[key] = self._origin
            self._apis[key] = api
        return api

    async def _open_locked(self, user_id: str, session_id: str | None) -> WebApi:
        if session_id is not None and session_id == self._origin.session_id:
            return self._attach_origin(user_id)
        key = (user_id, session_id)
        if session_id is not None and key in self._apis:
            return self._apis[key]
        opened = await self._origin.open_alongside(session_id)
        try:
            opened.extension_runtime.set_ui_bridge(StderrUiBridge())
            await opened.emit_pending_session_start()
        except BaseException:
            await opened.aclose()
            raise
        opened_id = opened.session_id
        if opened_id is None:
            await opened.aclose()
            raise ValueError("Session manager is not available")
        try:
            self._users.claim(user_id, opened_id)
        except ValueError:
            await opened.aclose()
            raise
        api = WebApi(opened)
        if self._tasks is not None:
            api.bind(self._tasks)
        opened_key = (user_id, opened_id)
        self._sessions[opened_key] = opened
        self._apis[opened_key] = api
        return api

    def abort_all(self) -> None:
        """Cancel the turn in every open session."""
        for api in self._apis.values():
            api.abort()

    async def aclose(self) -> None:
        """Close every session this process opened, spawned ones before the first."""
        origin = self._origin
        for session in list(self._sessions.values()):
            if session is not origin:
                await session.aclose()
        await origin.aclose()


def create_app(office: WebOffice, *, frontend: Path | None = None) -> FastAPI:
    """Build the HTTP API. ``userId`` selects the person. ``sessionId`` selects their session."""

    def as_json(owner: str, payload: _JSON) -> JSONResponse:
        payload["userId"] = owner
        return JSONResponse(payload)

    def view(owner: str, api: WebApi) -> _JSON:
        payload = api.state()
        if not isinstance(payload.get("sessionId"), str) or not payload.get("sessionId"):
            public = office.bound_id(owner, api, "")
            if public:
                payload["sessionId"] = public
        payload["sessions"] = office.list_sessions(owner)
        return payload

    @contextlib.asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        async with anyio.create_task_group() as tasks:
            office.bind(tasks)
            try:
                yield
            finally:
                office.abort_all()

    app = FastAPI(
        title="Tau",
        version=current_version(),
        description="HTTP API for coding sessions. frontend/ is a separate client.",
        lifespan=lifespan,
    )

    @app.exception_handler(ValueError)
    async def value_error(_request: Request, exc: ValueError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"error": str(exc)})

    @app.exception_handler(RuntimeError)
    async def runtime_error(_request: Request, exc: RuntimeError) -> JSONResponse:
        return JSONResponse(status_code=409, content={"error": str(exc)})

    @app.post("/api/sessions")
    async def sessions_api(body: SessionsRequest) -> JSONResponse:
        """List sessions, open one this user owns, or create one.

        ``userId`` alone lists sessions and does not create one. ``sessionId``
        opens that session. ``create`` starts one. The first create for a user
        adopts the session this server already started, when it has no owner.
        """
        owner = _user_id(body.user_id)
        session_id = _blank_to_none(body.session_id)
        if body.create and session_id is not None:
            raise ValueError("create and sessionId cannot both be set")
        if not body.create and session_id is None:
            return as_json(owner, {"sessions": office.list_sessions(owner)})
        api = await office.open_session(owner, None if body.create else session_id)
        if body.model is not None and body.model.strip():
            api._session.set_model(body.model.strip())
        return as_json(owner, view(owner, api))

    @app.post("/api/session")
    async def session_api(body: SessionRequest) -> Response:
        """Run one JSON action on the session named by ``sessionId``."""
        owner = _user_id(body.user_id)
        session_id = _required_session(body.session_id)
        api = await office.session(owner, session_id)
        if body.action == "state":
            return as_json(owner, view(owner, api))
        if body.action == "messages":
            return as_json(
                owner,
                {
                    "sessionId": office.bound_id(owner, api, session_id),
                    "messages": api.messages(),
                },
            )
        if body.action == "prompt":
            if body.message is None:
                raise ValueError("message is required")
            _apply_model(api, body.model)
            await api.prompt(body.message, streaming_behavior=body.streaming_behavior)
            return Response(status_code=204)
        if body.action == "command":
            if body.text is None or not body.text.strip():
                raise ValueError("text is required")
            payload = await api.command(
                body.text,
                can_resume=lambda target: office.allows(owner, target),
            )
            payload["sessionId"] = await office.rebind(owner, session_id, api)
            payload["userId"] = owner
            return JSONResponse(payload)
        if body.action == "terminal":
            if body.command is None or not body.command.strip():
                raise ValueError("command is required")
            payload = await api.terminal(body.command, add_to_context=body.add_to_context)
            payload["sessionId"] = office.bound_id(owner, api, session_id)
            payload["userId"] = owner
            return JSONResponse(payload)
        api.abort()
        return Response(status_code=204)

    @app.post("/api/events")
    async def events_api(body: EventsRequest) -> StreamingResponse:
        """Stream one turn. The response ends when that turn settles."""
        owner = _user_id(body.user_id)
        api = await office.session(owner, _required_session(body.session_id))
        return StreamingResponse(api.event_stream(), media_type="text/event-stream")

    if frontend is not None:
        app.mount("/", StaticFiles(directory=frontend, html=True), name="frontend")
    app.add_middleware(_BrowserAccess)
    return app


_BROWSER_HEADERS = (
    (b"access-control-allow-origin", b"*"),
    (b"access-control-allow-methods", b"GET, POST, OPTIONS"),
    (b"access-control-allow-headers", b"Content-Type"),
    (b"cache-control", b"no-store"),
)


class _BrowserAccess:
    """Add browser headers without buffering a streaming response."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        if scope["method"] == "OPTIONS":
            await send(
                {
                    "type": "http.response.start",
                    "status": 204,
                    "headers": [*_BROWSER_HEADERS, (b"content-length", b"0")],
                }
            )
            await send({"type": "http.response.body", "body": b""})
            return

        async def send_with_browser_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = [
                    item
                    for item in message.get("headers", [])
                    if item[0].lower() not in {b"cache-control", b"access-control-allow-origin"}
                ]
                headers.extend(_BROWSER_HEADERS)
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_browser_headers)


def frontend_root() -> Path | None:
    """Find the standalone frontend, if this checkout or install has one."""
    override = environ.get("TAU_WEB_FRONTEND")
    candidates = [Path(override).expanduser()] if override else []
    module_dir = Path(__file__).resolve().parent
    candidates.extend(parent / "frontend" for parent in module_dir.parents)
    candidates.append(module_dir / "static")
    for candidate in candidates:
        if (candidate / "index.html").is_file():
            return candidate
    return None


class _Server(uvicorn.Server):
    """Serve without replacing the process signal handlers."""

    @contextlib.contextmanager
    def capture_signals(self) -> Iterator[None]:
        yield


async def serve(
    client: ModelProvider,
    *,
    model: str,
    host: str = "127.0.0.1",
    port: int = 8765,
) -> None:
    """Serve the HTTP API with a model client the caller already opened.

    The first session is the one later requests copy. The caller still owns the client.
    """
    session = await session_for_client(client, model=model)
    try:
        session.extension_runtime.set_ui_bridge(StderrUiBridge())
        await session.emit_pending_session_start()
    except BaseException:
        await session.aclose()
        raise
    await serve_web(session, host=host, port=port, access_log=True)


async def serve_web(
    session: CodingSession,
    *,
    host: str = "0.0.0.0",
    port: int = 8765,
    ready: anyio.Event | None = None,
    on_ready: ReadyCallback | None = None,
    serve_frontend: bool = True,
    access_log: bool = False,
) -> None:
    """Serve the FastAPI app until this task is cancelled."""
    office = WebOffice(session)
    app = create_app(office, frontend=frontend_root() if serve_frontend else None)
    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        log_level="info" if access_log else "warning",
        access_log=access_log,
    )
    server = _Server(config)
    try:
        async with anyio.create_task_group() as tasks:
            tasks.start_soon(_run_server, server, host, port)
            with anyio.fail_after(10):
                while not server.started:
                    if server.should_exit:
                        raise RuntimeError(f"Could not listen on {host}:{port}")
                    await anyio.sleep(0.01)
            url = public_url(host, _listening_port(server, port))
            if on_ready is not None:
                on_ready(url)
            if ready is not None:
                ready.set()
            try:
                await anyio.sleep_forever()
            finally:
                server.should_exit = True
    finally:
        with anyio.CancelScope(shield=True):
            server.should_exit = True
            await office.aclose()


async def _run_server(server: _Server, host: str, port: int) -> None:
    try:
        await server.serve()
    except SystemExit as exc:
        raise RuntimeError(f"Could not listen on {host}:{port}") from exc


def _listening_port(server: uvicorn.Server, fallback: int) -> int:
    for listener in getattr(server, "servers", ()):
        for sock in getattr(listener, "sockets", None) or ():
            address = sock.getsockname()
            if isinstance(address, tuple) and len(address) >= 2 and isinstance(address[1], int):
                return address[1]
    return fallback


def _apply_model(api: WebApi, model: str | None) -> None:
    """Switch the session model when the request names one."""
    chosen = model.strip() if isinstance(model, str) else ""
    if chosen:
        api._session.set_model(chosen)
        return
    if not api._session.model.strip():
        raise ValueError("model is required")


def _event(event: CodingSessionEvent) -> _JSON:
    try:
        return _object(event)
    except (TypeError, ValueError):
        return {"type": event.type}


def _object(value: object) -> _JSON:
    dumped = _jsonable(value)
    if isinstance(dumped, dict):
        return {str(key): item for key, item in dumped.items()}
    return {}


def _jsonable(value: object) -> object:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if is_dataclass(value) and not isinstance(value, type):
        return {_camel(key): _jsonable(item) for key, item in asdict(value).items()}
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {_camel(str(key)): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _web_users_path(session: CodingSession) -> Path | None:
    manager = session.session_manager
    if manager is None:
        return None
    return manager.paths.home / "web-users.json"


def _required_session(value: str | None) -> str:
    session_id = _blank_to_none(value)
    if session_id is None:
        raise ValueError("sessionId is required")
    return session_id


def _blank_to_none(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    return value


def _user_id(raw: str | None) -> str:
    """Return the user id carried in the request body."""
    if not isinstance(raw, str):
        raise ValueError("userId is required")
    user_id = raw.strip()
    if not user_id or len(user_id) > 128 or any(char in user_id for char in " \t\r\n/\\"):
        raise ValueError("userId is required")
    return user_id


def _session_preview(session: CodingSession) -> str:
    """Return the first user message already loaded in a live session."""
    for message in session.messages:
        if getattr(message, "role", None) != "user":
            continue
        preview = _clip_preview(_content_text(getattr(message, "content", None)))
        if preview:
            return preview
    return ""


def _transcript_preview(path: Path) -> str:
    """Return the first user message stored in a session transcript."""
    try:
        handle = path.open(encoding="utf-8")
    except OSError:
        return ""
    with handle:
        for index, line in enumerate(handle):
            if index >= 80:
                break
            if '"user"' not in line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            message = entry.get("message") if isinstance(entry, dict) else None
            if not isinstance(message, dict) or message.get("role") != "user":
                continue
            preview = _clip_preview(_content_text(message.get("content")))
            if preview:
                return preview
    return ""


def _content_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list | tuple):
        return ""
    parts: list[str] = []
    for block in content:
        if isinstance(block, str):
            parts.append(block)
            continue
        text = block.get("text") if isinstance(block, dict) else getattr(block, "text", None)
        if isinstance(text, str):
            parts.append(text)
    return "".join(parts)


def _clip_preview(text: str) -> str:
    collapsed = " ".join(text.split())
    if len(collapsed) <= 72:
        return collapsed
    return collapsed[:71].rstrip() + "…"


def _camel(name: str) -> str:
    head, *rest = name.split("_")
    return head + "".join(part[:1].upper() + part[1:] for part in rest if part)


def _sse(data: _JSON) -> bytes:
    name = data.get("type", "message")
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return f"event: {name}\ndata: {payload}\n\n".encode()


def public_url(host: str, port: int) -> str:
    """Return the URL printed for the address this server is bound to."""
    return f"http://{host}:{port}/"
