# 后台管理基础 CRUD 接口说明

当前已完成化学品、产品、供应商三个基础主数据模块。每个模块按以下结构组织：

```text
模块/
├── controller.py  # HTTP 路由和参数说明
├── schema.py      # 请求/响应数据校验
├── crud.py        # 数据库增删改查
├── service.py     # 业务校验和事务编排
└── model.py       # SQLAlchemy 表模型
```

## 1. 接口统一规则

- 基础路径：`/api/v1`
- 列表接口统一分页：`page` 从 1 开始，`page_size` 默认 20，最大 100。
- `POST` 用于新增，返回 `201`。
- `GET /{id}` 用于查询详情，不存在返回 `404`。
- `PATCH /{id}` 用于部分更新，只修改请求体中出现的字段。
- `DELETE /{id}` 为软删除，将主数据的 `status` 改为 `INACTIVE`，不物理删除历史数据。
- 唯一编码或 CAS 重复返回 `409`。
- 当前接口已接入 JWT 登录和 RBAC 权限；没有 Bearer Token 返回 `401`，没有对应权限返回 `403`。

## 2. 化学品模块

代码目录：`backend/app/modules/chemicals/`

| 方法 | 路径 | 说明 |
|---|---|---|
| `create_chemical` | `POST /api/v1/chemicals` | 新增化学品；如果 CAS 号已存在则拒绝 |
| `list_chemicals` | `GET /api/v1/chemicals` | 按名称、状态分页查询 |
| `get_chemical` | `GET /api/v1/chemicals/{chemical_id}` | 按主键查询详情 |
| `update_chemical` | `PATCH /api/v1/chemicals/{chemical_id}` | 部分更新化学品字段，并校验 CAS 唯一 |
| `delete_chemical` | `DELETE /api/v1/chemicals/{chemical_id}` | 软删除，状态改为 `INACTIVE` |

### 请求示例

```json
{
  "chemical_name": "乙醇",
  "english_name": "Ethanol",
  "cas_no": "64-17-5",
  "chemical_formula": "C2H6O",
  "molecular_weight": 46.068,
  "hazard_class": "易燃液体"
}
```

## 3. 产品模块

代码目录：`backend/app/modules/products/`

| 方法 | 路径 | 说明 |
|---|---|---|
| `create_product` | `POST /api/v1/products` | 新增产品规格；产品编码不可重复 |
| `list_products` | `GET /api/v1/products` | 按名称、化学品 ID、状态分页查询 |
| `get_product` | `GET /api/v1/products/{product_id}` | 按主键查询产品详情 |
| `update_product` | `PATCH /api/v1/products/{product_id}` | 部分更新产品，并递增 `version_no` |
| `delete_product` | `DELETE /api/v1/products/{product_id}` | 软删除，状态改为 `INACTIVE`，版本号递增 |

产品创建时必须提供 `chemical_id` 和 `unit_id`，这两个关联由 MySQL 外键校验。复杂可检索参数应使用后续的 `md_product_parameters` 表，不应只写入 `parameter_json`。

## 4. 供应商模块

代码目录：`backend/app/modules/suppliers/`

| 方法 | 路径 | 说明 |
|---|---|---|
| `create_supplier` | `POST /api/v1/suppliers` | 新增供应商档案；供应商编码不可重复 |
| `list_suppliers` | `GET /api/v1/suppliers` | 按名称、地区、状态分页查询 |
| `get_supplier` | `GET /api/v1/suppliers/{supplier_id}` | 按主键查询供应商详情 |
| `update_supplier` | `PATCH /api/v1/suppliers/{supplier_id}` | 部分更新供应商字段，供应商编码不允许修改 |
| `delete_supplier` | `DELETE /api/v1/suppliers/{supplier_id}` | 软删除，状态改为 `INACTIVE` |

## 5. 分层职责

### `model.py`

定义数据库表映射、字段类型、可空性和外键。模型不处理 HTTP 参数，也不直接编排业务流程。

### `schema.py`

定义接口输入输出格式。`Create` 用于新增，`Update` 的字段全部可选以支持 PATCH，`Read` 用于响应，分页响应额外返回 `total/page/page_size`。

### `crud.py`

只负责 SQLAlchemy 数据访问：按 ID 查询、按业务唯一字段查询、分页查询、新增、更新和软删除。CRUD 方法不决定 HTTP 状态码。

### `service.py`

负责业务规则：资源不存在判断、业务唯一性判断、版本号递增和软删除策略。复杂的跨表校验应继续放在 service 层，并通过一个事务完成。

### `controller.py`

负责路由、Query 参数、请求体和响应模型声明。业务异常统一由 `main.py` 转换为 HTTP `404/409` 响应。

## 6. 系统管理与登录接口

系统管理代码目录：`backend/app/modules/system/`

| 方法 | 路径 | 说明 |
|---|---|---|
| `login` | `POST /api/v1/auth/login` | 校验账号密码并返回 JWT，不需要登录 |
| `current_user` | `GET /api/v1/auth/me` | 返回当前用户、角色和权限，需要 Bearer Token |
| `create_user/list_users/get_user/update_user/delete_user` | `/api/v1/system/users` | 用户增删改查，删除为停用 |
| `create_department/list_departments/get_department/update_department/delete_department` | `/api/v1/system/departments` | 部门增删改查，删除为停用 |
| `create_role/list_roles/get_role/update_role/delete_role` | `/api/v1/system/roles` | 角色增删改查，并维护角色权限关联 |
| `create_permission/list_permissions/get_permission/update_permission/delete_permission` | `/api/v1/system/permissions` | 权限增删改查，已绑定角色的权限不能删除 |

系统管理写接口需要对应的 `system.*.write` 权限，读接口需要对应的 `system.*.read` 权限。拥有 `SYS_ADMIN` 角色的用户可以绕过单项权限检查。

### 初始化管理员

先在 `.env` 中设置独立的应用管理员密码：

```env
ADMIN_USERNAME=system_admin
ADMIN_PASSWORD=CHANGE_ME_ADMIN_PASSWORD
ADMIN_DISPLAY_NAME=系统管理员
JWT_SECRET_KEY=CHANGE_ME_TO_A_LONG_RANDOM_SECRET
```

然后执行：

```powershell
$env:PYTHONPATH = "backend"
python scripts\seed_admin.py
```

初始化脚本会创建 `SYS_ADMIN` 角色和基础权限；如果管理员已经存在，不会覆盖其原密码。

### 当前开发环境演示账号

以下账号已写入当前 `chemicalops` 数据库，统一使用 `.env` 中的 `DEMO_DEFAULT_PASSWORD`：

| 登录名 | 角色 | 主要权限范围 |
|---|---|---|
| `system_admin` | 系统管理员 | 全部系统管理和主数据权限 |
| `procurement_manager` | 采购经理 | 化学品、产品、供应商读写 |
| `buyer` | 采购员 | 化学品查看、产品和供应商读写 |
| `technical_engineer` | 技术研发人员 | 化学品和产品读写 |
| `warehouse_receiver` | 仓库收货人员 | 产品、供应商查看 |
| `quality_inspector` | 质量检验人员 | 化学品、产品、供应商查看 |
| `finance_viewer` | 财务查看者 | 化学品、产品、供应商查看 |
| `management_viewer` | 管理层查看者 | 化学品、产品、供应商查看 |

当前开发环境默认密码：`ChemicalOps@2026`。该密码仅用于本地演示，上线前必须替换并重新执行账号密码初始化策略。

## 7. 采购申请与询价报价接口

采购申请代码目录：`backend/app/modules/purchase_requests/`；询价报价代码目录：`backend/app/modules/rfqs/`。

| 方法 | 路径 | 说明 |
|---|---|---|
| `create_request/list_requests/get_request/update_request` | `/api/v1/purchase-requests` | 采购申请草稿的增删改查；删除通过取消接口完成，不物理删除 |
| `submit_request` | `POST /api/v1/purchase-requests/{id}/submit` | 提交申请并创建待审批节点 |
| `approve_request/reject_request` | `POST /api/v1/purchase-requests/{id}/approve` 或 `/reject` | 采购经理审批或驳回，并记录意见 |
| `create_rfq/list_rfqs/get_rfq/update_rfq` | `/api/v1/rfqs` | 询价单草稿的增删改查；可关联已审批采购申请明细 |
| `send_rfq` | `POST /api/v1/rfqs/{id}/send` | 校验明细和邀请供应商后，将询价单置为 `SENT` |
| `create_quote` | `POST /api/v1/rfqs/{id}/quotes` | 录入被邀请供应商报价，询价单进入 `RESPONDING` |
| `build_comparison` | `POST /api/v1/rfqs/{id}/comparison` | 生成报价快照，按每个询价明细的单价升序排名 |
| `get_comparison` | `GET /api/v1/rfqs/{id}/comparison` | 查询最近一次生成的比价快照 |
| `select_quote` | `POST /api/v1/rfqs/{id}/select-quote` | 确认中选报价，其他已提交报价置为 `REJECTED`，询价单置为 `CLOSED` |

### 询价报价字段规则

- `rfqs.source_request_id` 可以为空；不为空时必须指向状态为 `APPROVED` 的采购申请。
- `rfq_items.product_id` 和 `source_request_item_id` 可以为空，便于处理尚未完成产品主数据确认的临时采购；`requested_name`、`quantity`、`unit_id` 非空。
- `rfq_suppliers` 使用 `(rfq_id, supplier_id)` 联合主键，防止同一供应商被重复邀请。
- `supplier_quotes` 使用 `(rfq_id, supplier_id, quote_version)` 联合唯一约束，允许同一供应商提交多个版本报价。
- `supplier_quote_items` 使用 `(quote_id, rfq_item_id)` 联合唯一约束，确保一份报价对同一询价明细只有一行。
- `quote_comparison_items` 保存比价时的价格、总额、交期和排名快照，避免供应商后续修改报价影响历史比价记录。

### 演示主数据

首次开发环境初始化可执行：

```powershell
$env:PYTHONPATH = "backend"
uv run python scripts\seed_demo_master_data.py
uv run python scripts\seed_demo_accounts.py
```

脚本会幂等创建两个计量单位、两家演示供应商和一个演示产品；已有数据不会覆盖。

## 8. 采购订单接口

采购订单代码目录：`backend/app/modules/purchase_orders/`。

| 方法 | 路径 | 说明 |
|---|---|---|
| `create_order` | `POST /api/v1/purchase-orders` | 根据已确认的中选报价生成订单草稿；报价必须覆盖全部询价明细，且产品主数据不能为空 |
| `list_orders/get_order` | `/api/v1/purchase-orders` | 按订单编号、状态分页查询或查看订单详情 |
| `update_order` | `PATCH /api/v1/purchase-orders/{id}` | 修改订单地址、期望到货日期和备注，仅限草稿 |
| `submit_order` | `POST /api/v1/purchase-orders/{id}/submit` | 创建采购经理审批节点，订单进入 `APPROVING` |
| `approve_order/reject_order` | `POST /api/v1/purchase-orders/{id}/approve` 或 `/reject` | 处理订单审批，审批通过进入 `APPROVED`，驳回回到 `DRAFT` |
| `place_order` | `POST /api/v1/purchase-orders/{id}/place` | 正式下单，进入 `ORDERED`，并回写采购申请明细已采购数量 |
| `cancel_order` | `POST /api/v1/purchase-orders/{id}/cancel` | 取消草稿、审批中或已审批但尚未正式下单的订单 |

订单金额由服务层按 `报价单价 × 订购数量 × (1 + 税率)` 计算；每个订单明细保存产品名称、供应商型号、单价和报价明细快照。采购员可以创建和下单，采购经理负责审批。

## 9. 到货与收货接口

到货代码目录：`backend/app/modules/deliveries/`。

| 方法 | 路径 | 说明 |
|---|---|---|
| `create_delivery` | `POST /api/v1/deliveries` | 为 `ORDERED` 或 `PARTIAL` 状态的采购订单登记到货计划 |
| `list_deliveries/get_delivery` | `/api/v1/deliveries` | 按到货编号、状态分页查询或查看到货明细 |
| `receive_delivery` | `POST /api/v1/deliveries/{id}/receive` | 登记实际收货和短交数量，自动累计订单收货数量 |

到货单创建时状态为 `IN_TRANSIT`，确认收货后变为 `RECEIVED`。订单明细会更新为 `PARTIAL` 或 `FULFILLED`，订单主单会更新为 `PARTIAL` 或 `COMPLETED`。仓库角色只拥有到货和收货权限，不默认开放采购订单审批权限。

如果收货明细存在短交，系统会自动创建 `SHORT_DELIVERY` 异常，并向采购经理、仓库人员和订单采购员发送站内通知。

## 10. 质量验收接口

质量验收代码目录：`backend/app/modules/quality_acceptances/`。

| 方法 | 路径 | 说明 |
|---|---|---|
| `create_acceptance` | `POST /api/v1/quality-acceptances` | 为已收货的到货单创建待检验记录，并将到货单置为 `INSPECTING` |
| `list_acceptances/get_acceptance` | `/api/v1/quality-acceptances` | 按验收结果分页查询或查看验收详情 |
| `submit_result` | `POST /api/v1/quality-acceptances/{id}/result` | 录入检测结果、证书状态、检测数据和结论 |

验收结果为 `PASSED` 时到货单进入 `ACCEPTED`；`PARTIAL` 和 `FAILED` 进入 `EXCEPTION`；已完成验收只能先提交 `REINSPECTION`，再录入新的最终结果。质量人员拥有验收写权限，仓库人员只负责前置收货。

验收结果为 `PARTIAL` 或 `FAILED` 时，系统会自动创建 `QUALITY` 异常，并向采购经理、质量人员和订单采购员发送站内通知；同一来源存在未关闭同类异常时不会重复创建。

## 11. 库存与入库接口

库存代码目录：`backend/app/modules/inventory/`。库存模块的数据结构由 `database/migrations/` 中的编号迁移维护，并通过统一迁移 runner 按序升级。

| 方法 | 路径 | 说明 |
|---|---|---|
| `create_warehouse/list_warehouses` | `/api/v1/inventory/warehouses` | 仓库主数据的创建和查询 |
| `create_location/list_locations` | `/api/v1/inventory/warehouses/{id}/locations` | 仓库库位的创建和查询 |
| `create_inbound` | `POST /api/v1/inventory/inbounds` | 仅允许将质量验收通过的到货单入库；同一到货明细只能生成一次入库流水 |
| `list_balances` | `GET /api/v1/inventory/balances` | 按产品和仓库查询库存余额 |
| `list_transactions` | `GET /api/v1/inventory/transactions` | 查询入库、出库和调整流水 |
| `freeze_balance/unfreeze_balance` | `POST /api/v1/inventory/balances/{id}/freeze` 或 `/unfreeze` | 冻结或解冻库存余额，不改变数量；必须填写原因 |
| `list_balance_status_logs` | `GET /api/v1/inventory/balances/{id}/status-logs` | 查询库存冻结和解冻历史 |

入库时按产品、批次、仓库、库位和单位维护库存余额，并保存来源到货明细。库存写权限仅授予仓库角色，入库前必须经过质量验收。

已有数据库升级时，按项目 README 的数据库升级流程运行统一迁移 runner；它会按序执行所有待处理迁移并在升级前备份。演示主数据仅在开发环境需要时单独运行 `scripts/seed_demo_master_data.py`。

库存数据表字段中的 `warehouse_id + location_id + product_id + batch_id + unit_id` 使用联合唯一约束；`inventory_transactions.delivery_item_id` 使用唯一约束，保证同一到货明细不会被重复入库。库存余额状态为 `AVAILABLE` 或 `FROZEN`；冻结状态会阻止领用、调拨和盘点差异调整。

## 12. 库存领用与出库接口

库存领用代码与入库共用目录：`backend/app/modules/inventory/`。领用申请使用“草稿 → 提交 → 审批 → 出库完成”的状态流转，驳回后可以修改并重新提交。

| 方法 | 路径 | 说明 |
|---|---|---|
| `create_issue_request` | `POST /api/v1/inventory/issue-requests` | 创建库存领用申请草稿，明细必须指定产品、仓库、库位、批次、单位和数量 |
| `list_issue_requests` | `GET /api/v1/inventory/issue-requests` | 按状态分页查询；普通申请人只查看自己的申请，管理角色可查看全部 |
| `get_issue_request` | `GET /api/v1/inventory/issue-requests/{id}` | 查询领用申请及明细 |
| `update_issue_request` | `PATCH /api/v1/inventory/issue-requests/{id}` | 修改草稿或已驳回申请；已提交、已审批和已完成申请不可修改 |
| `submit_issue_request` | `POST /api/v1/inventory/issue-requests/{id}/submit` | 提交申请，进入待审批状态 |
| `approve_issue_request` | `POST /api/v1/inventory/issue-requests/{id}/approve` | 采购经理或系统管理员审批通过 |
| `reject_issue_request` | `POST /api/v1/inventory/issue-requests/{id}/reject` | 驳回申请并记录必填原因 |
| `cancel_issue_request` | `POST /api/v1/inventory/issue-requests/{id}/cancel` | 取消草稿或已驳回申请 |
| `execute_issue_request` | `POST /api/v1/inventory/issue-requests/{id}/execute` | 仓库人员执行出库，扣减库存并生成出库流水 |

执行出库时会锁定领用申请和库存余额记录，校验可用库存 `quantity - locked_quantity`，避免库存扣减为负数。多个明细按固定键顺序加锁，降低并发出库死锁风险；同一申请只有 `APPROVED` 状态可以执行，重复执行不会再次扣减。出库流水使用 `source_type=ISSUE_REQUEST` 和 `source_id=领用申请 ID` 追溯来源。

已有数据库升级时使用统一迁移 runner；无需单独运行领用模块的迁移脚本。演示账号仅在开发环境需要时单独运行 `scripts/seed_demo_accounts.py`。

## 13. 库存调拨接口

库存调拨与库存入库、领用共用目录：`backend/app/modules/inventory/`。调拨申请同样使用“草稿 → 提交 → 审批 → 调拨完成”的状态流转，驳回后可以修改并重新提交。

| 方法 | 路径 | 说明 |
|---|---|---|
| `create_transfer_request` | `POST /api/v1/inventory/transfer-requests` | 创建调拨申请草稿，明细必须指定产品、源仓库/库位、目标仓库/库位、批次、单位和数量 |
| `list_transfer_requests` | `GET /api/v1/inventory/transfer-requests` | 按状态分页查询调拨申请；仓库、采购经理和系统管理员可查看全部 |
| `get_transfer_request` | `GET /api/v1/inventory/transfer-requests/{id}` | 查询调拨申请及明细 |
| `update_transfer_request` | `PATCH /api/v1/inventory/transfer-requests/{id}` | 修改草稿或已驳回申请 |
| `submit_transfer_request` | `POST /api/v1/inventory/transfer-requests/{id}/submit` | 提交调拨申请审批 |
| `approve_transfer_request` | `POST /api/v1/inventory/transfer-requests/{id}/approve` | 采购经理或系统管理员审批通过 |
| `reject_transfer_request` | `POST /api/v1/inventory/transfer-requests/{id}/reject` | 驳回并记录必填原因 |
| `cancel_transfer_request` | `POST /api/v1/inventory/transfer-requests/{id}/cancel` | 取消草稿或已驳回申请 |
| `execute_transfer_request` | `POST /api/v1/inventory/transfer-requests/{id}/execute` | 一个事务内扣减源库位、增加目标库位，并生成一出一入两条库存流水 |

执行调拨前会校验源库位可用库存和目标库位状态，并按固定顺序锁定涉及的库存余额。目标库位没有余额记录时会幂等创建零余额行；同一调拨申请只有 `APPROVED` 状态可以执行，重复执行不会再次变更库存。调拨流水使用 `source_type=INVENTORY_TRANSFER` 和 `source_id=调拨申请 ID` 追溯来源。

已有数据库升级时使用统一迁移 runner；无需单独运行调拨模块的迁移脚本。

## 14. 库存盘点接口

库存盘点与其他库存业务共用目录：`backend/app/modules/inventory/`。盘点单创建时保存账面数量快照，确认执行时只允许在账面数量未发生变化的情况下调整库存。

| 方法 | 路径 | 说明 |
|---|---|---|
| `create_stocktake_request` | `POST /api/v1/inventory/stocktakes` | 创建盘点申请草稿，并由服务端保存当前账面数量 |
| `list_stocktake_requests` | `GET /api/v1/inventory/stocktakes` | 按状态分页查询盘点申请 |
| `get_stocktake_request` | `GET /api/v1/inventory/stocktakes/{id}` | 查询盘点申请及明细 |
| `update_stocktake_request` | `PATCH /api/v1/inventory/stocktakes/{id}` | 修改草稿或已驳回申请，并重新生成明细账面快照 |
| `submit_stocktake_request` | `POST /api/v1/inventory/stocktakes/{id}/submit` | 提交盘点申请审批 |
| `approve_stocktake_request` | `POST /api/v1/inventory/stocktakes/{id}/approve` | 采购经理或系统管理员审批通过 |
| `reject_stocktake_request` | `POST /api/v1/inventory/stocktakes/{id}/reject` | 驳回并记录必填原因 |
| `cancel_stocktake_request` | `POST /api/v1/inventory/stocktakes/{id}/cancel` | 取消草稿或已驳回申请 |
| `execute_stocktake_request` | `POST /api/v1/inventory/stocktakes/{id}/execute` | 锁定库存余额，按实盘数量执行差异调整 |

差异数量为“实盘数量 - 账面数量”，盘盈和盘亏都生成 `ADJUSTMENT` 流水，数量记录绝对值，盘盈/盘亏方向写入流水备注。执行时发现账面数量已变化会返回中文业务错误并回滚，不会覆盖期间发生的库存业务。

已有数据库升级时使用统一迁移 runner；无需单独运行盘点模块的迁移脚本。

## 15. 库存冻结与解冻接口

库存冻结记录代码与库存模块共用目录：`backend/app/modules/inventory/`。冻结操作使用库存余额主键，先锁定余额行，再校验状态和锁定数量；冻结、解冻和重复操作都会返回清晰的中文业务提示，并写入状态变更历史和审计日志。

| 方法 | 路径 | 说明 |
|---|---|---|
| `freeze_balance` | `POST /api/v1/inventory/balances/{id}/freeze` | 将 `AVAILABLE` 库存冻结为 `FROZEN`；存在锁定库存时不允许冻结 |
| `unfreeze_balance` | `POST /api/v1/inventory/balances/{id}/unfreeze` | 将 `FROZEN` 库存恢复为 `AVAILABLE` |
| `list_balance_status_logs` | `GET /api/v1/inventory/balances/{id}/status-logs` | 分页查看冻结/解冻的前后状态、原因、操作人和时间 |

已有数据库升级时使用统一迁移 runner；无需单独运行冻结模块的迁移脚本。

## 16. 运营异常接口

运营异常代码目录：`backend/app/modules/operation_exceptions/`。第一版覆盖短交、质量不合格、文件缺失、逾期到货和其他异常的登记、查询、指派、处理和关闭。

| 方法 | 路径 | 说明 |
|---|---|---|
| `create_exception` | `POST /api/v1/operation-exceptions` | 登记异常，必须填写异常类型、来源类型、来源 ID、严重级别和描述；订单、到货单、到货明细和质量验收来源会校验关联记录 |
| `list_exceptions` | `GET /api/v1/operation-exceptions` | 按异常类型、状态分页查询；采购经理、仓库、质量和系统管理员可查看全部，其他角色只查看自己负责的异常 |
| `get_exception` | `GET /api/v1/operation-exceptions/{id}` | 查询异常详情，并按负责人数据范围校验访问权限 |
| `update_exception` | `PATCH /api/v1/operation-exceptions/{id}` | 指派负责人、调整截止时间或推进处理状态；关闭时必须填写关闭说明 |

异常状态流转为 `OPEN → PROCESSING → RESOLVED → CLOSED`；处理中的异常也可以取消，已关闭或已取消的异常不能再次修改。

### 异常处理任务与评论

| 方法 | 路径 | 说明 |
|---|---|---|
| `create_task/list_tasks` | `/api/v1/operation-exceptions/{exception_id}/tasks` | 为异常创建任务，或按状态分页查询任务；首次创建任务会将异常推进为 `PROCESSING` |
| `get_task/update_task` | `/api/v1/operation-exceptions/{exception_id}/tasks/{task_id}` | 查询或更新任务；任务状态支持 `OPEN → PROCESSING → COMPLETED`，也可以取消或重新打开已完成任务 |
| `create_comment/list_comments` | `/api/v1/operation-exceptions/{exception_id}/tasks/{task_id}/comments` | 追加和查询任务处理记录，可关联已有文件元数据 |

任务完成时必须填写完成说明；已取消任务不能继续修改或追加处理记录。异常负责人、任务负责人和异常管理角色可以访问对应处理数据。

## 17. 站内通知接口

通知代码目录：`backend/app/modules/notifications/`。通知由业务事件自动创建，用户只能读取和处理发给自己的通知。

已有数据库升级时使用统一迁移 runner；无需单独运行通知模块的迁移脚本。

| 方法 | 路径 | 说明 |
|---|---|---|
| `list_notifications` | `GET /api/v1/notifications` | 查询当前用户通知，支持 `unread_only`、分页参数 |
| `unread_count` | `GET /api/v1/notifications/unread-count` | 查询未读数量 |
| `mark_read` | `PATCH /api/v1/notifications/{id}/read` | 标记单条通知已读 |
| `mark_all_read` | `POST /api/v1/notifications/read-all` | 将当前用户全部未读通知标记为已读 |

## 18. 启动与接口检查

### 自动化测试

测试代码位于 `tests/`，当前使用本地 MySQL 演示数据库，测试夹具会在每个测试结束后回滚事务；并发专项测试会创建临时业务数据，完成后自动恢复库存并清理记录。

```powershell
$env:PYTHONPATH = "backend"
.venv\Scripts\python.exe -m pytest -q
```

测试覆盖统一错误响应、角色权限、库存领用重复执行、调拨参数校验、盘点账面快照、冻结状态，以及两个独立数据库会话同时扣减同一库存余额的场景。

### 错误状态码和中文提示

所有接口的失败响应统一包含 `code`、`message` 和 `detail` 字段；成功响应的数据结构保持不变，不影响现有前端页面。

| 状态码 | 中文提示 | 使用场景 |
|---:|---|---|
| `400` | 请求不符合业务规则 | 状态流转、业务关联或参数值不满足规则 |
| `401` | 认证失败 | 未登录、令牌无效或账号已停用 |
| `403` | 无权访问 | 当前角色没有接口权限 |
| `404` | 资源不存在 | 查询的业务数据不存在 |
| `405` | 请求方法不允许 | 使用了接口不支持的 HTTP 方法 |
| `409` | 数据已存在 | 编码、用户名等唯一字段重复 |
| `415` | 请求格式不支持 | 请求体格式不是接口要求的 JSON |
| `422` | 请求参数校验失败 | 请求体字段缺失、格式或枚举值错误 |
| `428` | 请求条件不满足 | 生产强制幂等模式下未携带 `Idempotency-Key` |
| `500` | 服务器内部错误 | 未预期的服务端异常 |

示例：

```json
{
  "code": 400,
  "message": "请求不符合业务规则",
  "detail": "只有已下单或部分到货的采购订单可以登记到货"
}
```

在项目根目录执行：

```powershell
uv run main.py run --env=dev
```

接口文档地址：

- Swagger：`http://127.0.0.1:8888/docs`
- ReDoc：`http://127.0.0.1:8888/redoc`
- 健康检查：`http://127.0.0.1:8888/health`

## 19. 财务对账、发票、付款和结算接口

财务模块以采购订单为业务主线，金额使用订单币种保存；金额快照不会随着采购订单后续资料修改而变化。

| 接口 | 说明 | 主要权限 |
|---|---|---|
| `POST /api/v1/finance/reconciliations` | 为已完成收货且全部验收通过的订单创建对账单 | `finance.reconciliations.write` |
| `GET /api/v1/finance/reconciliations` | 按状态、供应商分页查询对账单 | `finance.reconciliations.read` |
| `GET /api/v1/finance/reconciliations/{id}` | 查询对账单详情 | `finance.reconciliations.read` |
| `POST /api/v1/finance/reconciliations/{id}/confirm` | 确认对账单 | `finance.reconciliations.write` |
| `POST /api/v1/finance/reconciliations/{id}/dispute` | 发起对账争议，原因必填 | `finance.reconciliations.write` |
| `POST /api/v1/finance/invoices` | 录入发票，累计金额不能超过对账金额 | `finance.invoices.write` |
| `GET /api/v1/finance/invoices` | 分页查询发票 | `finance.invoices.read` |
| `GET /api/v1/finance/invoices/{id}` | 查询发票详情 | `finance.invoices.read` |
| `POST /api/v1/finance/invoices/{id}/submit` | 提交发票核验 | `finance.invoices.write` |
| `POST /api/v1/finance/invoices/{id}/verify` | 核验发票 | `finance.invoices.verify` |
| `POST /api/v1/finance/invoices/{id}/reject` | 驳回发票并记录原因 | `finance.invoices.verify` |
| `POST /api/v1/finance/payments` | 发起付款申请，不能超过剩余应付额且必须有足额核验发票 | `finance.payments.write` |
| `GET /api/v1/finance/payments` | 分页查询付款记录 | `finance.payments.read` |
| `GET /api/v1/finance/payments/{id}` | 查询付款详情 | `finance.payments.read` |
| `POST /api/v1/finance/payments/{id}/approve` | 审批付款申请 | `finance.payments.approve` |
| `POST /api/v1/finance/payments/{id}/reject` | 驳回付款申请并记录原因 | `finance.payments.approve` |
| `POST /api/v1/finance/payments/{id}/paid` | 登记银行流水并完成付款 | `finance.payments.write` |
| `POST /api/v1/finance/settlements` | 为已足额付款的对账单创建结算单 | `finance.settlements.write` |
| `GET /api/v1/finance/settlements` | 按状态、供应商分页查询结算单 | `finance.settlements.read` |
| `GET /api/v1/finance/settlements/{id}` | 查询结算单详情 | `finance.settlements.read` |
| `POST /api/v1/finance/settlements/{id}/confirm` | 确认结算并关闭对账单 | `finance.settlements.approve` |
| `POST /api/v1/finance/settlements/{id}/cancel` | 取消草稿结算单 | `finance.settlements.write` |

金额、订单、供应商和币种由服务层从关联订单校验或带入；系统通过对账单、付款和结算的行锁避免并发超额付款，银行流水号使用数据库唯一索引防止并发重复登记，并通过状态机阻止重复确认、重复付款和重复结算。

## 20. 退货和补货接口

退货会复用库存出库规则，补货申请负责记录异常补货需求并关联实际执行的采购订单。

| 接口 | 说明 | 主要权限 |
|---|---|---|
| `POST /api/v1/inventory/returns` | 创建供应商退货草稿，明细必须引用真实库存 | `warehouse.inventory.return.write` |
| `GET /api/v1/inventory/returns` | 分页查询退货申请 | `warehouse.inventory.return.read` |
| `GET /api/v1/inventory/returns/{id}` | 查询退货详情 | `warehouse.inventory.return.read` |
| `POST /api/v1/inventory/returns/{id}/submit` | 提交退货审批 | `warehouse.inventory.return.write` |
| `POST /api/v1/inventory/returns/{id}/approve` | 审批退货 | `warehouse.inventory.return.approve` |
| `POST /api/v1/inventory/returns/{id}/reject` | 驳回并保存原因 | `warehouse.inventory.return.approve` |
| `POST /api/v1/inventory/returns/{id}/cancel` | 取消草稿或驳回单 | `warehouse.inventory.return.write` |
| `POST /api/v1/inventory/returns/{id}/execute` | 锁定库存并执行退货出库 | `warehouse.inventory.return.write` |
| `POST /api/v1/replenishments` | 创建供应商补货申请草稿 | `procurement.replenishment.write` |
| `GET /api/v1/replenishments` | 分页查询补货申请 | `procurement.replenishment.read` |
| `GET /api/v1/replenishments/{id}` | 查询补货详情 | `procurement.replenishment.read` |
| `POST /api/v1/replenishments/{id}/submit` | 提交补货审批 | `procurement.replenishment.write` |
| `POST /api/v1/replenishments/{id}/approve` | 审批补货 | `procurement.replenishment.approve` |
| `POST /api/v1/replenishments/{id}/reject` | 驳回并保存原因 | `procurement.replenishment.approve` |
| `POST /api/v1/replenishments/{id}/cancel` | 取消草稿或驳回单 | `procurement.replenishment.write` |
| `POST /api/v1/replenishments/{id}/complete` | 关联已正式下单的采购订单并完成补货申请 | `procurement.replenishment.write` |

退货执行只允许 `AVAILABLE` 且可用数量足够的库存；所有库存扣减和流水写入在同一事务中完成，重复执行会被状态机拒绝。

## 21. 供应商门户和订单确认接口

供应商门户用户通过绑定表确定所属供应商，接口服务层会再次按当前用户绑定关系过滤订单，不能查看其他供应商的数据。

| 接口 | 说明 | 主要权限 |
|---|---|---|
| `GET /api/v1/supplier-portal/orders` | 查询当前供应商可见的采购订单，草稿订单不对外展示 | `supplier.portal.read` |
| `GET /api/v1/supplier-portal/orders/{id}` | 查询当前供应商订单详情 | `supplier.portal.read` |
| `POST /api/v1/supplier-portal/orders/{id}/confirm` | 确认订单，写入订单事件和审计日志 | `supplier.portal.confirm` |
| `POST /api/v1/supplier-portal/orders/{id}/reject` | 拒绝订单，原因必填并写入订单事件和审计日志 | `supplier.portal.confirm` |

## 22. 文件和业务附件接口

当前 Docker 部署使用 MinIO 的 `chemicalops-documents` 桶保存原始文档，使用 `chemicalops-results` 桶保存解析后的 Markdown 结果；项目提供 `deploy/docker-compose.minio.yml` 和初始化容器，会自动创建两个私有桶。数据库只保存元数据和对象键。开发环境仍可通过 `FILE_STORAGE_BACKEND=local` 使用项目 `storage` 目录。设置 `FILE_SCAN_ENABLED=true` 后，上传会先通过 `clamdscan --stream` 扫描，扫描服务不可用或报告风险时不会落盘；生产环境仍需配置实际的 ClamAV 服务并完成附件权限审计。

| 接口 | 说明 | 主要权限 |
|---|---|---|
| `POST /api/v1/files` | 校验扩展名、大小、MIME、常见文件魔数和访问级别后上传文件 | `system.files.write` |
| `GET /api/v1/files/{id}` | 查询文件元数据，不返回服务器真实路径 | `system.files.read` |
| `GET /api/v1/files/{id}/download` | 下载文件对象 | `system.files.download` |
| `POST /api/v1/files/{id}/attachments` | 将文件关联到采购订单、到货单、质量验收、异常、财务单据、退货或补货申请 | `system.files.attach` |
| `GET /api/v1/files/attachments/{resource_type}/{resource_id}` | 分页查询业务对象附件 | `system.files.read` |

附件关联使用 `(resource_type, resource_id, file_id)` 联合唯一约束防止重复绑定；`PRIVATE` 文件仅上传者和系统管理员可读取元数据、下载、关联或在附件列表中看到；已关联业务资源的 `INTERNAL`/`PUBLIC` 文件还必须通过对应资源类型读取权限，未关联的通用文件按通用文件权限访问；文件上传成功但元数据入库失败时会删除已写入的对象。

## 23. 库存成本、FIFO 和有效期预警接口

| 接口 | 说明 | 主要权限 |
|---|---|---|
| `POST /api/v1/inventory/fifo-outbounds` | 按批次成本层的先进先出顺序执行出库，生成成本分摊记录 | `warehouse.inventory.cost.write` |
| `GET /api/v1/inventory/expiry-alerts` | 查询已过期、紧急和阈值内即将过期的库存批次 | `warehouse.inventory.read` |

入库时会按采购订单含税单价生成成本层；FIFO 请求使用 `request_no` 做请求级幂等。普通领用、调拨和退货已经统一使用成本层分摊；缺少历史成本层时接口会返回中文提示，要求先执行成本回填。

## 24. 逾期扫描和 Dashboard 接口

| 接口 | 说明 | 主要权限 |
|---|---|---|
| `POST /api/v1/jobs/overdue-scan` | 扫描逾期运输中的到货单，创建未关闭的自动异常并发送站内通知 | `operations.exceptions.write` |
| `GET /api/v1/jobs/runs?limit=50` | 查询最近后台定时任务的状态、开始/结束时间、重试次数和数量摘要 | `operations.exceptions.read` |
| `GET /api/v1/dashboard/overview` | 返回采购订单、逾期到货、库存数量、开放异常、已确认对账、付款金额和有效期预警汇总 | `dashboard.read` |
| `GET /api/v1/dashboard/report` | 按日期范围聚合每日采购趋势、订单状态、供应商采购金额、产品出库成本、待办任务和库存有效期预警 | `dashboard.read` |

目前提供手工接口、单次脚本和可持续运行的 `scripts/run_scheduler.py` 定时任务执行器。调度器通过 MySQL 命名锁选出唯一执行实例；其他副本等待主实例退出后接管。每轮默认最多尝试 3 次，可通过 `--max-attempts` 和 `--retry-delay-seconds` 调整；`scheduler_job_runs` 表持久记录运行状态、尝试次数、结果数量或失败类型，可通过上述只读接口查询。API `/metrics` 按进程暴露 Prometheus 指标，部署时应让 Prometheus 分别抓取每个 API 副本，并在 Prometheus 中按服务聚合；不要只抓取经过负载均衡的单一共享地址。

前端 Dashboard 已使用上述接口绘制采购金额折线图、订单状态饼图、订单状态/供应商采购额/库存出库成本条形统计图，并支持手动刷新。页面会显示“数据库实时聚合”以及当前 `APP_ENV` 对应的数据环境；`development`/`test` 标识为演示环境，其他环境标识为生产环境。该标识说明数据库连接和运行环境，不等同于已经接入 ERP、WMS 或供应商外部系统。

## 25. AI 助手接口

AI 助手只允许已登录用户调用；后端保存当前用户的会话和消息，并且不允许模型直接绕过业务 API 修改数据库。

| 接口 | 说明 | 登录要求 |
|---|---|---|
| `POST /api/v1/ai/chat` | 调用配置的 OpenAI 兼容模型，持久化用户消息和助手回复；可提交当前用户上传的附件 ID，并返回实时数据/文件引用摘要 | Bearer JWT |
| `POST /api/v1/ai/chat/stream` | 以 `text/event-stream` 返回 AI 增量内容；事件为 `delta`、`done`、`error`，正常完成后持久化完整助手消息 | Bearer JWT |
| `GET /api/v1/ai/conversations` | 查询当前用户自己的会话列表 | Bearer JWT |
| `GET /api/v1/ai/conversations/{id}/messages` | 查询当前用户自己的会话消息 | Bearer JWT |

前端附件会先调用文件上传接口保存为 `PRIVATE` 文件，再提交 `attachment_file_ids`；后端只允许当前用户本人（或系统管理员）将文件交给 AI。TXT/CSV/Markdown/JSON 走本地解析；PDF/Office 在 `.env` 开启 `MINERU_ENABLED=true` 并配置 `MINERU_API_KEY` 后，先把文件状态持久化为 `PROCESSING`，再按 MinerU v4 的“申请签名上传地址、PUT 文件、轮询批次、下载 `full.md`”流程解析，网络瞬时失败最多按 `MINERU_MAX_RETRIES` 退避重试，完成后写回 `SUCCEEDED/EMPTY/FAILED`，引用中记录解析器、批次号和 `full.md` 定位，远程失败则回退本地解析。涉及采购、库存、到货、质量、异常、财务或供应商的问题，在用户拥有对应读取权限时会额外加载实时 Dashboard 概览和最多 8 条明细。已关联业务资源的附件还会校验对应资源类型的实时读取权限；部门/仓库级数据范围、业务写入审批和远程服务监控仍属于后续阶段，OCR 暂不纳入本轮。

## 26. 服务状态和数据环境

| 接口 | 说明 |
|---|---|
| `GET /health` | 返回 API 存活状态、服务名、`environment`、`data_source` 和 `data_mode`；`data_source=database` 表示业务指标从当前数据库聚合，`data_mode=demo/production` 由 `APP_ENV` 推导 |

前端用该接口展示看板数据环境，避免把本地演示数据库中的数据误认为生产业务数据。

```powershell
$env:PYTHONPATH = "backend"
uv run python scripts\run_scheduler.py --once
uv run python scripts\run_scheduler.py --interval-seconds 900
# 每轮失败最多重试 3 次，间隔 5 秒；可按部署环境调整
uv run python scripts\run_scheduler.py --interval-seconds 900 --max-attempts 3 --retry-delay-seconds 5
```

## 27. 统一请求幂等

所有带 `Idempotency-Key` 的 `POST`、`PUT`、`PATCH`、`DELETE` 请求由统一中间件记录。相同用户、路径、方法和请求体的重复请求会回放第一次结果；相同 key 但请求内容不同会返回 `409`；首次请求仍在执行时重复请求会返回冲突提示。默认兼容未携带请求头的旧接口，生产环境可设置 `IDEMPOTENCY_REQUIRED=true`，将写请求切换为缺少幂等键即返回 `428`。

## 28. CI、测试和运行检查

`.github/workflows/ci.yml` 已配置 MySQL 8、数据库初始化、演示账号、后端编译、pytest、API 启动后的 100 请求/10 并发 smoke load 和前端构建。当前本地验证结果为 `53 passed`，业务 Dashboard 也已完成 100 请求、10 并发验证；GitHub 远程 CI、正式业务写场景压力测试、生产环境 ClamAV 运行和更完整的故障注入矩阵尚未执行。

轻量压测工具位于 `scripts/run_load_test.py`，例如：

```powershell
$env:PYTHONPATH = "backend"
uv run python scripts\run_load_test.py --url http://127.0.0.1:8888/health --requests 200 --concurrency 20
```

该工具会输出吞吐量、P50/P95 延迟和状态码分布。本地已对带 JWT 的 Dashboard 概览接口完成 100 请求、10 并发验证，全部返回 200；正式压测还应使用隔离数据库、业务写场景、持续时间和固定的资源上限。
