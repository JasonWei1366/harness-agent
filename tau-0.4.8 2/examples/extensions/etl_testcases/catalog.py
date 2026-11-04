"""In-memory demo catalog for the ETL test-case extension.

Nothing here opens a database connection. `query_database` only reads this
fixture, which is a partial snapshot of a legacy-to-warehouse migration.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from tau_agent.types import JSONValue


@dataclass(frozen=True, slots=True)
class Column:
    name: str
    data_type: str
    comment: str
    nullable: bool = False


@dataclass(frozen=True, slots=True)
class Table:
    name: str
    role: str
    comment: str
    columns: tuple[Column, ...]
    rows: tuple[dict[str, JSONValue], ...]


def _table(
    name: str,
    role: str,
    comment: str,
    columns: tuple[Column, ...],
    rows: tuple[dict[str, JSONValue], ...],
) -> Table:
    return Table(name=name, role=role, comment=comment, columns=columns, rows=rows)


TABLES: dict[str, Table] = {
    table.name: table
    for table in (
        _table(
            "legacy.customers",
            "source",
            "迁移源：客户主数据。status=1 有效，0 无效。",
            (
                Column("customer_id", "bigint", "客户编号"),
                Column("name", "varchar(64)", "客户姓名"),
                Column("mobile", "varchar(20)", "手机号，允许为空", nullable=True),
                Column("email", "varchar(128)", "邮箱，允许为空", nullable=True),
                Column("city", "varchar(32)", "城市"),
                Column("created_at", "timestamp", "建档时间"),
                Column("status", "int", "1 有效，0 无效"),
            ),
            (
                {
                    "customer_id": 1001,
                    "name": "张伟",
                    "mobile": "13800001111",
                    "email": "zhangwei@example.com",
                    "city": "上海",
                    "created_at": "2024-01-03 09:12:00",
                    "status": 1,
                },
                {
                    "customer_id": 1002,
                    "name": "李娜",
                    "mobile": "13800001111",
                    "email": "lina@example.com",
                    "city": "北京",
                    "created_at": "2024-02-11 14:20:00",
                    "status": 1,
                },
                {
                    "customer_id": 1003,
                    "name": "王强",
                    "mobile": None,
                    "email": None,
                    "city": "杭州",
                    "created_at": "2024-03-01 08:00:00",
                    "status": 1,
                },
                {
                    "customer_id": 1004,
                    "name": "陈静",
                    "mobile": "13900002222",
                    "email": "chenjing@example.com",
                    "city": "深圳",
                    "created_at": "2023-11-20 18:45:00",
                    "status": 0,
                },
            ),
        ),
        _table(
            "legacy.orders",
            "source",
            "迁移源：订单。status 是源系统状态码，不是目标枚举。",
            (
                Column("order_id", "bigint", "订单号"),
                Column("customer_id", "bigint", "客户编号，可能在客户表中不存在"),
                Column("order_time", "timestamp", "下单时间"),
                Column("amount", "decimal(12,2)", "订单金额"),
                Column("status", "int", "0 待支付，1 已支付，2 已发货，3 已取消，其他为未知"),
                Column("pay_channel", "varchar(16)", "支付渠道，待支付订单可能为空", nullable=True),
            ),
            (
                {
                    "order_id": 50001,
                    "customer_id": 1001,
                    "order_time": "2024-06-01 10:00:00",
                    "amount": "128.50",
                    "status": 1,
                    "pay_channel": "alipay",
                },
                {
                    "order_id": 50002,
                    "customer_id": 1001,
                    "order_time": "2024-06-02 11:30:00",
                    "amount": "0.00",
                    "status": 0,
                    "pay_channel": None,
                },
                {
                    "order_id": 50003,
                    "customer_id": 1003,
                    "order_time": "2024-06-03 09:15:00",
                    "amount": "56.00",
                    "status": 3,
                    "pay_channel": "wechat",
                },
                {
                    "order_id": 50004,
                    "customer_id": 9999,
                    "order_time": "2024-06-04 16:40:00",
                    "amount": "88.00",
                    "status": 2,
                    "pay_channel": "card",
                },
                {
                    "order_id": 50005,
                    "customer_id": 1002,
                    "order_time": "2024-06-05 20:05:00",
                    "amount": "15.80",
                    "status": 9,
                    "pay_channel": "alipay",
                },
            ),
        ),
        _table(
            "dwh.dim_customer",
            "target",
            "迁移目标：客户维度。当前快照只包含部分源客户，不能当成 ETL 已经正确。",
            (
                Column("customer_sk", "bigint", "代理键"),
                Column("customer_id", "bigint", "源客户编号"),
                Column("customer_name", "varchar(64)", "客户姓名"),
                Column("mobile", "varchar(20)", "手机号", nullable=True),
                Column("email", "varchar(128)", "邮箱", nullable=True),
                Column("city", "varchar(32)", "城市"),
                Column("is_active", "boolean", "是否有效"),
                Column("effective_from", "date", "生效日期，取源 created_at 的日期"),
            ),
            (
                {
                    "customer_sk": 1,
                    "customer_id": 1001,
                    "customer_name": "张伟",
                    "mobile": "13800001111",
                    "email": "zhangwei@example.com",
                    "city": "上海",
                    "is_active": True,
                    "effective_from": "2024-01-03",
                },
                {
                    "customer_sk": 2,
                    "customer_id": 1004,
                    "customer_name": "陈静",
                    "mobile": "13900002222",
                    "email": "chenjing@example.com",
                    "city": "深圳",
                    "is_active": False,
                    "effective_from": "2023-11-20",
                },
            ),
        ),
        _table(
            "dwh.fact_order",
            "target",
            "迁移目标：订单事实。当前快照只落入了部分订单。",
            (
                Column("order_sk", "bigint", "代理键"),
                Column("order_id", "bigint", "源订单号"),
                Column("customer_sk", "bigint", "客户代理键，关联失败时为空", nullable=True),
                Column("order_date", "date", "下单日期"),
                Column("amount", "decimal(12,2)", "订单金额"),
                Column("order_status", "varchar(16)", "目标状态枚举"),
                Column("pay_channel", "varchar(16)", "支付渠道", nullable=True),
            ),
            (
                {
                    "order_sk": 1,
                    "order_id": 50001,
                    "customer_sk": 1,
                    "order_date": "2024-06-01",
                    "amount": "128.50",
                    "order_status": "PAID",
                    "pay_channel": "alipay",
                },
                {
                    "order_sk": 2,
                    "order_id": 50003,
                    "customer_sk": None,
                    "order_date": "2024-06-03",
                    "amount": "56.00",
                    "order_status": "CANCELLED",
                    "pay_channel": "wechat",
                },
            ),
        ),
    )
}

_MAX_LIMIT = 20


def query_catalog(
    action: str, table_name: str | None, limit: int
) -> tuple[str, dict[str, JSONValue]]:
    """Return demo catalog text and structured details for one tool call."""
    if action == "list_tables":
        return _list_tables()
    if action == "describe_table":
        return _with_table(table_name, _describe_table)
    if action == "preview_rows":
        bounded = min(max(limit, 1), _MAX_LIMIT)
        return _with_table(table_name, lambda table: _preview_rows(table, bounded))
    known = "list_tables, describe_table, preview_rows"
    return _error(f"不支持的 action `{action}`。可用值：{known}。")


def _list_tables() -> tuple[str, dict[str, JSONValue]]:
    lines = [
        f"demo 库没有连接真实数据库。下面是内置的迁移快照，共 {len(TABLES)} 张表：",
    ]
    tables: list[dict[str, JSONValue]] = []
    for table in TABLES.values():
        lines.append(f"- {table.name} | {table.role} | {table.comment}")
        tables.append({"name": table.name, "role": table.role, "comment": table.comment})
    return "\n".join(lines), {"demo": True, "tables": tables}


def _describe_table(table: Table) -> tuple[str, dict[str, JSONValue]]:
    lines = [
        f"表 {table.name}（{table.role}）",
        table.comment,
        "",
        "字段：",
    ]
    columns: list[dict[str, JSONValue]] = []
    for column in table.columns:
        nullability = "可空" if column.nullable else "不可空"
        lines.append(f"- {column.name} | {column.data_type} | {nullability} | {column.comment}")
        columns.append(
            {
                "name": column.name,
                "data_type": column.data_type,
                "nullable": column.nullable,
                "comment": column.comment,
            }
        )
    details: dict[str, JSONValue] = {
        "demo": True,
        "table": table.name,
        "role": table.role,
        "comment": table.comment,
        "columns": columns,
    }
    return "\n".join(lines), details


def _preview_rows(table: Table, limit: int) -> tuple[str, dict[str, JSONValue]]:
    rows = list(table.rows[:limit])
    header = " | ".join(column.name for column in table.columns)
    rendered = [header]
    for row in rows:
        rendered.append(" | ".join(_cell(row.get(column.name)) for column in table.columns))
    text = f"{table.name} 的 demo 快照，返回 {len(rows)} 行，不是线上查询：\n" + "\n".join(rendered)
    details: dict[str, JSONValue] = {
        "demo": True,
        "table": table.name,
        "row_count": len(rows),
        "rows": rows,
    }
    return text, details


def _with_table(
    table_name: str | None,
    reader: Callable[[Table], tuple[str, dict[str, JSONValue]]],
) -> tuple[str, dict[str, JSONValue]]:
    resolved = _resolve_table(table_name)
    if isinstance(resolved, str):
        return _error(resolved)
    return reader(resolved)


def _resolve_table(table_name: str | None) -> Table | str:
    if table_name is None or not table_name.strip():
        return "describe_table 和 preview_rows 需要 table，例如 legacy.orders。"
    key = table_name.strip().lower()
    table = TABLES.get(key)
    if table is not None:
        return table
    bare_matches = [item for item in TABLES.values() if item.name.split(".", 1)[1] == key]
    if len(bare_matches) == 1:
        return bare_matches[0]
    if len(bare_matches) > 1:
        names = ", ".join(item.name for item in bare_matches)
        return f"表名 `{table_name}` 不唯一，请使用 schema.table：{names}。"
    available = ", ".join(TABLES)
    return f"demo 库中没有表 `{table_name}`。可用表：{available}。"


def _cell(value: JSONValue) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _error(message: str) -> tuple[str, dict[str, JSONValue]]:
    return message, {"demo": True, "error": message}
