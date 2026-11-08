---
id: orphan_order
title: 找不到客户的订单
tags: 订单, 客户, 孤儿数据, fact_order
summary: 源订单的客户在维度中不存在时，事实表不生成客户代理键。
---

# 找不到客户的订单

本文件是历史样例，只示范测试用例的写法。预期结果以用户本次描述的 ETL 规则为准。

## 样例所依据的规则

订单事实通过 `legacy.orders.customer_id` 关联 `dwh.dim_customer.customer_id`：

- 关联成功时写入对应 `customer_sk`
- 关联失败时订单仍然进入事实表，`customer_sk` 为空
- 错误明细记录 `missing_customer`，同时保留订单号和源客户编号
- 关联失败不改变订单状态和金额

## 测试用例

### TC-ORD-010 客户不存在时订单仍然装载

- 优先级：P0
- 关联：`legacy.orders.customer_id` -> `dwh.fact_order.customer_sk`
- 前置条件：订单 50004 的 `customer_id=9999`，客户表和客户维度都没有 9999
- 测试数据：demo 快照中的 50004
- 步骤：
  1. 确认源客户表不存在 9999
  2. 按本次规则装载订单事实
  3. 检查事实表和错误明细
- 预期结果：事实表有 50004；`customer_sk` 为空；`amount=88.00`；`order_status` 按状态码 2 映射；错误明细包含 `missing_customer`、订单号 50004、客户编号 9999
- 备注：不能因为客户缺失把整张订单丢弃，也不能发明一个客户代理键

### TC-ORD-011 客户存在时写入代理键

- 优先级：P0
- 关联：`dwh.dim_customer.customer_sk` -> `dwh.fact_order.customer_sk`
- 前置条件：订单 50001 的客户 1001 已经在维度中，`customer_sk=1`
- 测试数据：demo 快照中的 50001 和维度客户 1001
- 步骤：
  1. 用客户编号 1001 取得 `customer_sk`
  2. 装载订单 50001 并回查事实表
- 预期结果：50001 的 `customer_sk=1`，错误明细没有这条订单
- 备注：这是关联成功的对照用例，和 TC-ORD-010 一起执行
