"""Behavioral tests for the shipped example extensions.

Mirrors Pi's practice of testing example extensions from the main suite
(plan-mode-extension.test.ts and friends), with one difference: instead of
mocking the extension API, these load the real files through the real
`ExtensionRuntime` and drive the composed tools — which doubles as a template
for how extension authors can test their own extensions.
"""

from collections.abc import Sequence
from pathlib import Path

import pytest

from tau_agent.messages import TextContent
from tau_agent.tools import AgentTool, AgentToolResult
from tau_coding import TauResourcePaths
from tau_coding.extensions import ExtensionRuntime, NullUiBridge

pytestmark = pytest.mark.anyio

EXAMPLES_DIR = Path(__file__).resolve().parent.parent / "examples" / "extensions"


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _runtime_with_examples(tmp_path: Path, *names: str) -> ExtensionRuntime:
    runtime = ExtensionRuntime()
    runtime.load(
        TauResourcePaths(
            root=tmp_path / "home-tau",
            cwd=tmp_path / "project",
            agents_root=tmp_path / "home-agents",
        ),
        extra_paths=tuple(EXAMPLES_DIR / name for name in names),
        include_resource_dirs=False,
    )
    assert not [diag for diag in runtime.diagnostics if diag.severity == "error"]
    return runtime


def _fake_tool(name: str) -> tuple[AgentTool, list[dict[str, object]]]:
    executed: list[dict[str, object]] = []

    async def executor(tool_call_id, arguments, signal=None, on_update=None):  # noqa: ANN001, ANN202
        del tool_call_id, signal, on_update
        executed.append(dict(arguments))
        return AgentToolResult(content=[TextContent(text="ran")])

    tool = AgentTool(
        name=name,
        label=name,
        description="fake",
        parameters={},
        execute_fn=executor,
    )
    return tool, executed


def _extension_tool(runtime: ExtensionRuntime, name: str) -> AgentTool:
    matches = [tool for tool in runtime.compose_tools([]) if tool.name == name]
    assert len(matches) == 1
    return matches[0]


class SelectingUiBridge(NullUiBridge):
    def __init__(self, selected: str | None) -> None:
        self.selected = selected
        self.calls: list[tuple[str, tuple[str, ...]]] = []

    @property
    def has_ui(self) -> bool:
        return True

    async def select(
        self,
        title: str,
        options: Sequence[str],
        *,
        timeout: float | None = None,
    ) -> str | None:
        del timeout
        choices = tuple(options)
        self.calls.append((title, choices))
        return self.selected


# -- shipped examples ----------------------------------------------------------


def test_shipped_examples_load(tmp_path: Path) -> None:
    runtime = _runtime_with_examples(
        tmp_path,
        "ask_user_question.py",
        "hello_tool.py",
        "permission_gate.py",
        "prompt_section.py",
        "sidebar_status.py",
    )

    assert runtime.extension_names == (
        "ask_user_question",
        "hello_tool",
        "permission_gate",
        "prompt_section",
        "sidebar_status",
    )
    assert [tool.name for tool in runtime.extension_tools] == [
        "ask_user_question",
        "hello",
    ]
    assert runtime.prompt_sections[0].title == "Review procedure"
    assert "```bash" in runtime.prompt_sections[0].body


async def test_ask_user_question_returns_selected_option(tmp_path: Path) -> None:
    runtime = _runtime_with_examples(tmp_path, "ask_user_question.py")
    ui = SelectingUiBridge("Run focused tests")
    runtime.set_ui_bridge(ui)
    tool = runtime.compose_tools([])[0]

    result = await tool.execute(
        "test-call",
        {
            "question": "Which checks should I run?",
            "options": ["Run focused tests", "Run all tests"],
        },
    )

    assert result.text == "The user selected: Run focused tests"
    assert result.details == {"selected": "Run focused tests"}
    assert ui.calls == [
        (
            "Which checks should I run?",
            ("Run focused tests", "Run all tests"),
        )
    ]


async def test_ask_user_question_handles_cancel(tmp_path: Path) -> None:
    runtime = _runtime_with_examples(tmp_path, "ask_user_question.py")
    runtime.set_ui_bridge(SelectingUiBridge(None))
    tool = runtime.compose_tools([])[0]

    result = await tool.execute(
        "test-call",
        {"question": "Continue?", "options": ["Yes", "No"]},
    )

    assert result.text == "The user did not select an option."
    assert result.details == {"selected": None}


# -- hello_tool.py -------------------------------------------------------------


async def test_hello_tool_greets(tmp_path: Path) -> None:
    runtime = _runtime_with_examples(tmp_path, "hello_tool.py")
    hello = runtime.compose_tools([])[0]

    result = await hello.execute("test-call", {"who": "Tau"})

    assert result.text == "Hello, Tau!"


async def test_hello_tool_defaults_to_world(tmp_path: Path) -> None:
    runtime = _runtime_with_examples(tmp_path, "hello_tool.py")
    hello = runtime.compose_tools([])[0]

    result = await hello.execute("test-call", {})

    assert result.text == "Hello, world!"


# -- permission_gate.py ---------------------------------------------------------


@pytest.mark.parametrize(
    "command",
    [
        "rm -rf build/",
        "rm -fr /tmp/x",
        "git push --force origin main",
        "git reset --hard HEAD~3",
        "chmod -R 777 .",
        "dd if=/dev/zero of=/dev/sda",
    ],
)
async def test_permission_gate_blocks_dangerous_bash(tmp_path: Path, command: str) -> None:
    runtime = _runtime_with_examples(tmp_path, "permission_gate.py")
    bash, executed = _fake_tool("bash")
    wrapped = runtime.compose_tools([bash])[0]

    result = await wrapped.execute("test-call", {"command": command})

    assert "blocked" in result.text.lower()
    assert "guarded pattern" in result.text
    assert executed == []


@pytest.mark.parametrize(
    "command",
    [
        "ls -la",
        "rm build/output.txt",
        "git push origin feature-branch",
        "git log --oneline",
    ],
)
async def test_permission_gate_allows_safe_bash(tmp_path: Path, command: str) -> None:
    runtime = _runtime_with_examples(tmp_path, "permission_gate.py")
    bash, executed = _fake_tool("bash")
    wrapped = runtime.compose_tools([bash])[0]

    result = await wrapped.execute("test-call", {"command": command})

    assert result.text == "ran"
    assert executed == [{"command": command}]


# -- etl_testcases/ ------------------------------------------------------------


def test_etl_testcases_extension_loads(tmp_path: Path) -> None:
    runtime = _runtime_with_examples(tmp_path, "etl_testcases")

    assert runtime.extension_names == ("etl_testcases",)
    assert [tool.name for tool in runtime.extension_tools] == [
        "query_database",
        "read_test_samples",
    ]
    assert runtime.prompt_sections[0].title == "ETL 测试用例"
    assert "query_database" in runtime.prompt_sections[0].body


async def test_query_database_lists_and_describes_demo_tables(tmp_path: Path) -> None:
    runtime = _runtime_with_examples(tmp_path, "etl_testcases")
    tool = _extension_tool(runtime, "query_database")

    listed = await tool.execute("test-call", {"action": "list_tables"})
    described = await tool.execute(
        "test-call",
        {"action": "describe_table", "table": "orders"},
    )
    preview = await tool.execute(
        "test-call",
        {"action": "preview_rows", "table": "legacy.orders", "limit": 1},
    )

    assert "legacy.orders" in listed.text
    assert "没有连接真实数据库" in listed.text
    assert "status" in described.text
    assert "50001" in preview.text
    assert "50002" not in preview.text
    assert preview.details["row_count"] == 1


async def test_query_database_rejects_unknown_table(tmp_path: Path) -> None:
    runtime = _runtime_with_examples(tmp_path, "etl_testcases")
    tool = _extension_tool(runtime, "query_database")

    missing = await tool.execute(
        "test-call",
        {"action": "describe_table", "table": "legacy.payments"},
    )
    needs_table = await tool.execute("test-call", {"action": "preview_rows"})

    assert "没有表" in missing.text
    assert "需要 table" in needs_table.text


async def test_read_test_samples_lists_and_reads_history(tmp_path: Path) -> None:
    runtime = _runtime_with_examples(tmp_path, "etl_testcases")
    tool = _extension_tool(runtime, "read_test_samples")

    listed = await tool.execute("test-call", {})
    matched = await tool.execute("test-call", {"keyword": "孤儿"})
    sample = await tool.execute("test-call", {"sample_id": "order_status_mapping"})
    missing = await tool.execute("test-call", {"sample_id": "not_a_sample"})

    assert "order_status_mapping" in listed.text
    assert "customer_mobile_dedup" in listed.text
    assert "orphan_order" in matched.text
    assert "order_status_mapping" not in matched.text
    assert "TC-ORD-004" in sample.text
    assert "未知状态码" in sample.text
    assert "没有历史样例" in missing.text


async def test_permission_gate_ignores_other_tools(tmp_path: Path) -> None:
    runtime = _runtime_with_examples(tmp_path, "permission_gate.py")
    write, executed = _fake_tool("write")
    wrapped = runtime.compose_tools([write])[0]

    result = await wrapped.execute("test-call", {"content": "rm -rf / would be bad"})

    assert result.text == "ran"
    assert len(executed) == 1
