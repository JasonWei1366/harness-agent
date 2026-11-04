---
id: customer_mobile_dedup
title: 客户手机号去重
tags: 客户, 去重, dim_customer, 空值
summary: 相同有效手机号只保留建档更早的客户，空手机号不参与去重。
---

# 客户手机号去重

本文件是历史样例，只示范测试用例的写法。预期结果以用户本次描述的 ETL 规则为准。

## 样例所依据的规则

装载 `dwh.dim_customer` 时，按 `mobile` 去重：

- 只比较非空手机号
- 多条有效客户共用一个手机号时，保留 `created_at` 更早的一条
- 被去掉的客户不生成维度记录，并在错误明细记录 `duplicate_mobile`
- `mobile` 为空的客户单独保留，不和其他空值客户互相去重
- `status=0` 的客户仍然装载，`is_active=false`

## 测试用例

### TC-CUS-001 相同手机号保留建档更早的客户

- 优先级：P0
- 关联：`legacy.customers.mobile`、`created_at` -> `dwh.dim_customer.customer_id`
- 前置条件：1001 张伟和 1002 李娜都有效，手机号同为 13800001111；1001 的 `created_at` 更早
- 测试数据：demo 快照中的 1001、1002
- 步骤：
  1. 按本次规则装载客户维度
  2. 用手机号 13800001111 查找目标记录
  3. 检查错误明细
- 预期结果：目标只有 1001；没有 1002；错误明细包含 1002，原因是 `duplicate_mobile`
- 备注：不能按客户编号大小决定保留谁

### TC-CUS-002 空手机号客户仍然装载

- 优先级：P0
- 关联：`legacy.customers.mobile`、`email`
- 前置条件：1003 王强的手机号和邮箱都为空，状态有效
- 测试数据：demo 快照中的 1003
- 步骤：
  1. 装载客户维度
  2. 用 `customer_id=1003` 查找目标记录
- 预期结果：目标存在 1003；`mobile` 和 `email` 都为空；该客户不出现在重复手机号错误明细
- 备注：空值之间不相等，不能把所有空手机号折成一条

### TC-CUS-003 无效客户保留并标记为无效

- 优先级：P1
- 关联：`legacy.customers.status` -> `dwh.dim_customer.is_active`
- 前置条件：1004 陈静 `status=0`，手机号不与其他客户重复
- 测试数据：demo 快照中的 1004
- 步骤：
  1. 装载客户维度
  2. 检查 1004 的有效标志和生效日期
- 预期结果：目标存在 1004；`is_active=false`；`effective_from=2023-11-20`
- 备注：无效不是过滤条件，目标需要保留这条历史客户
