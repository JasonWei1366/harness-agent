---
id: order_status_mapping
title: 订单状态码映射
tags: 订单, 状态映射, fact_order
summary: 把源订单状态码映射成目标枚举，并覆盖待支付、取消和未知码。
---

# 订单状态码映射

本文件是历史样例，只示范测试用例的写法。预期结果以用户本次描述的 ETL 规则为准。

## 样例所依据的规则

`legacy.orders.status` 映射到 `dwh.fact_order.order_status`：

- 0 -> PENDING
- 1 -> PAID
- 2 -> SHIPPED
- 3 -> CANCELLED
- 其他值不进入事实表，写入错误明细，保留源订单号和原状态码

金额原样保留两位小数。`status=0` 时 `pay_channel` 允许为空。

## 测试用例

### TC-ORD-001 已支付订单映射为 PAID

- 优先级：P0
- 关联：`legacy.orders.status` -> `dwh.fact_order.order_status`，以及 `amount`、`pay_channel`
- 前置条件：源表存在 `order_id=50001`，`status=1`，`amount=128.50`，`pay_channel=alipay`
- 测试数据：直接使用 demo 快照中的 50001，不改金额
- 步骤：
  1. 按本次 ETL 规则处理源订单 50001
  2. 用 `order_id` 在目标事实表查找对应记录
- 预期结果：目标只有一条 50001；`order_status=PAID`；`amount=128.50`；`pay_channel=alipay`
- 备注：这是主路径，金额不能因为状态转换被改写

### TC-ORD-002 待支付订单保留空支付渠道

- 优先级：P0
- 关联：`legacy.orders.status=0`、`pay_channel`
- 前置条件：源表存在 `order_id=50002`，金额为 0.00，支付渠道为空
- 测试数据：demo 快照中的 50002
- 步骤：
  1. 处理源订单 50002
  2. 检查目标状态和支付渠道
- 预期结果：`order_status=PENDING`；`amount=0.00`；`pay_channel` 为空，不能被填成默认渠道
- 备注：空渠道是合法数据，不是脏数据

### TC-ORD-003 取消订单仍保留原金额

- 优先级：P1
- 关联：`legacy.orders.status=3`、`amount`
- 前置条件：源表存在 `order_id=50003`，`status=3`，`amount=56.00`
- 测试数据：demo 快照中的 50003
- 步骤：
  1. 处理源订单 50003
  2. 核对目标金额没有被置零
- 预期结果：`order_status=CANCELLED`；`amount` 仍为 56.00
- 备注：取消只改变状态，不改变历史金额

### TC-ORD-004 未知状态码进入错误明细

- 优先级：P0
- 关联：`legacy.orders.status` 未定义取值
- 前置条件：源表存在 `order_id=50005`，`status=9`
- 测试数据：demo 快照中的 50005
- 步骤：
  1. 处理源订单 50005
  2. 分别检查事实表和错误明细
- 预期结果：事实表没有 50005；错误明细保留订单号 50005 和原状态码 9
- 备注：未知码不能悄悄映射成 PAID 或其他已知状态
