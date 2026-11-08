"""Generate tester-facing cases from a described ETL migration.

The model writes the cases. This extension only supplies two demo tools:
a fake migration catalog, and previously written test-case samples.

Run:

    tau -e examples/extensions/etl_testcases
"""

from collections.abc import Mapping

from agent.messages import TextContent
from agent.tools import (
    AgentTool,
    AgentToolResult,
    ToolCancellationToken,
    ToolUpdateCallback,
)
from agent.types import JSONValue
from application.extensions import ExtensionAPI

from .catalog import query_catalog
from .samples import read_samples

_PROMPT = """\
用户描述一套数据迁移 ETL 规则后，为测试人员编写可执行的测试用例。

按这个顺序使用工具：

1. 调用 `query_database`。先 `list_tables`，再对用户提到的表
   `describe_table`，需要对照数据时再 `preview_rows`。
2. 调用 `read_test_samples`。先按规则里的关键词检索，再读取最接近的一份全文，
   沿用它的章节和字段。
3. 用例依据只能是用户本次描述的规则、demo 库里真实存在的表和字段，
   以及历史样例的写法。
4. 历史样例里的映射不能覆盖用户规则。demo 库没有的表或字段要明确说没有，
   不要编造。
5. 每条用例都写出：编号、标题、优先级（P0/P1/P2）、关联表和字段、前置条件、
   测试数据、步骤、预期结果、备注。
6. 规则涉及到转换、空值和关联时，分别覆盖正常路径、空值、非法值或脏数据、
   关联失败。
7. 在结果开头说明：表结构和样例行来自插件内置 demo，没有查询真实数据库。
"""


def _result(text: str, details: dict[str, JSONValue]) -> AgentToolResult:
    return AgentToolResult(content=[TextContent(text=text)], details=details)


def _invalid(message: str) -> AgentToolResult:
    return _result(message, {"demo": True, "error": message})


def setup(tau: ExtensionAPI) -> None:
    """Register the demo catalog tools and the test-case procedure."""

    async def query_database(
        tool_call_id: str,
        arguments: Mapping[str, JSONValue],
        signal: ToolCancellationToken | None = None,
        on_update: ToolUpdateCallback | None = None,
    ) -> AgentToolResult:
        del tool_call_id, signal, on_update
        action = arguments.get("action")
        if not isinstance(action, str) or not action.strip():
            return _invalid("action 必须是 list_tables、describe_table 或 preview_rows。")
        table_name = arguments.get("table")
        if table_name is not None and not isinstance(table_name, str):
            return _invalid("table 必须是字符串，例如 legacy.orders。")
        limit = arguments.get("limit", 5)
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 20:
            return _invalid("limit 必须是 1 到 20 的整数。")
        text, details = query_catalog(action.strip(), table_name, limit)
        return _result(text, details)

    async def read_test_samples(
        tool_call_id: str,
        arguments: Mapping[str, JSONValue],
        signal: ToolCancellationToken | None = None,
        on_update: ToolUpdateCallback | None = None,
    ) -> AgentToolResult:
        del tool_call_id, signal, on_update
        sample_id = arguments.get("sample_id")
        keyword = arguments.get("keyword")
        if sample_id is not None and not isinstance(sample_id, str):
            return _invalid("sample_id 必须是字符串。")
        if keyword is not None and not isinstance(keyword, str):
            return _invalid("keyword 必须是字符串。")
        text, details = read_samples(sample_id, keyword)
        return _result(text, details)

    tau.register_tool(
        AgentTool(
            name="query_database",
            label="query database",
            description=(
                "查询数据迁移 demo 库的表、字段和样例行。"
                "数据内置在插件中，不会连接真实数据库。"
                "action 取 list_tables、describe_table 或 preview_rows。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["list_tables", "describe_table", "preview_rows"],
                        "description": (
                            "list_tables 列出表；describe_table 看字段；preview_rows 看样例行。"
                        ),
                    },
                    "table": {
                        "type": "string",
                        "description": "schema.table，例如 legacy.orders。list_tables 时省略。",
                    },
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 20,
                        "description": "preview_rows 返回的最大行数，默认 5。",
                    },
                },
                "required": ["action"],
                "additionalProperties": False,
            },
            execute_fn=query_database,
            prompt_snippet="查询内置 demo 迁移库的表结构、字段和样例行。",
            prompt_guidelines=(
                "query_database 的结果来自插件内置快照，不能把它说成真实数据库查询。",
            ),
        )
    )
    tau.register_tool(
        AgentTool(
            name="read_test_samples",
            label="read test samples",
            description=(
                "读取历史上已经写好的 ETL 测试用例样例。"
                "不传 sample_id 时返回摘要，可使用 keyword 过滤；"
                "传入 sample_id 时返回这份样例的全文。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "sample_id": {
                        "type": "string",
                        "description": "样例编号，例如 order_status_mapping。省略则只返回摘要。",
                    },
                    "keyword": {
                        "type": "string",
                        "description": "按标题、标签、摘要或正文过滤，例如 订单状态。",
                    },
                },
                "additionalProperties": False,
            },
            execute_fn=read_test_samples,
            prompt_snippet="读取历史 ETL 测试用例样例，用来对齐用例写法。",
            prompt_guidelines=(
                "历史样例只决定用例的结构和覆盖方式，预期结果必须遵守用户本次描述的 ETL 规则。",
            ),
        )
    )
    tau.add_prompt_section("ETL 测试用例", _PROMPT)
