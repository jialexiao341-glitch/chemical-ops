# 剩余整改实施计划

> 用户已批准方向、授权自主详细设计和分批提交，并跳过后续逐次审批。采用当前会话原生执行，末尾一次独立整体验证审查。

**Goal:** 完成问题清单剩余代码与可执行验收；不可取得的生产/历史事实保留边界。
**Spec:** docs/superpowers/specs/2026-10-21-complete-remediation-design.md
**Architecture:** 现有领域服务、同步 SQLAlchemy、受控 Agent 和 Vue 模板增量扩展，不重写业务状态机。
**Global Constraints:** 中文 Conventional Commits；README/STAR 不自动修改；历史业务记录不清空来源；凭据不入 Git；禁止推送与公开发布；所有行为修改 RED→GREEN；模型不承担权限/状态/金额决策。
**Verification:** 后端全量 `python -m pytest -q -rs -p no:cacheprovider`；前端 `vue-tsc --noEmit --skipLibCheck` 与 `vitest run --dom apps/web-chemicalops/src`；性能、浏览器和依赖按任务实测。
**Pre-flight:** Task1 的来源标记只由迁移产生；Task2 的缓存失效供 Tasks5/7 的授权重验使用；Task3 的分页契约供 Task10 远程选择器使用；Task4 的时间工具供 Tasks5-8/11-12 使用；Task5 的 PendingChoice/版本供 Tasks6-7/UI 使用；Task6 的清理不能删除 Task7 已创建申请；Task12 的隔离验收资源供 Task13 使用。任何偏离写入 ledger。

### Task 1: 历史来源例外与数据库唯一约束

**Files:** database/migrations/053_purchase_order_source_guard.sql; backend/app/modules/purchase_orders/model.py; tests/test_procurement_concurrency.py
**Interfaces:** source_comparison_guard 仅豁免迁移标记的历史重复订单；新 PO 不接受例外字段；保留两张原订单来源。
**Tests / independent expectations:** test_source_guard_rejects_duplicate_new_order；test_legacy_duplicate_preserves_sources：对历史例外保留两单，新第三单 IntegrityError；重复执行迁移不重加标记。
- [ ] 写出以上行为的最小失败测试（先命名能捕捉的真实错误，必要时使用真实 MySQL 回滚事务）。
- [ ] 运行对应测试，Expected: 因功能缺失出现预期断言失败，而非导入/环境错误。
- [ ] 在指定文件实现最小改动，保留权限、资源范围、幂等和事务约束。
- [ ] 运行对应测试及直接相关回归，Expected: 全部通过；任务 13/14 执行全量及实际验收。
- [ ] 提交 `fix(procurement): 为历史重复来源建立审计例外并约束新订单`，同次记录台账的提交、测试输出和设计裁决。

### Task 2: 请求体、可信代理与授权审计

**Files:** backend/app/core/request_limits.py; backend/app/core/auth.py; backend/app/modules/system/crud.py; backend/app/modules/system/audit.py; tests/test_runtime_boundaries.py
**Interfaces:** RequestBodyLimitMiddleware(app, json_limit_bytes, multipart_limit_bytes)；RBAC 缓存 Session.info，角色写入和事务事件失效；请求上下文 IP/UA。
**Tests / independent expectations:** test_chunked_body_limit_without_content_length；test_shared_nat_account_lock_isolated；test_untrusted_xff_ignored；test_rbac_cache_invalidates_on_role_change；test_audit_records_request_context。
- [ ] 写出以上行为的最小失败测试（先命名能捕捉的真实错误，必要时使用真实 MySQL 回滚事务）。
- [ ] 运行对应测试，Expected: 因功能缺失出现预期断言失败，而非导入/环境错误。
- [ ] 在指定文件实现最小改动，保留权限、资源范围、幂等和事务约束。
- [ ] 运行对应测试及直接相关回归，Expected: 全部通过；任务 13/14 执行全量及实际验收。
- [ ] 提交 `fix(core): 补齐全局请求限额与请求级授权审计`，同次记录台账的提交、测试输出和设计裁决。

### Task 3: 分页与批量查询

**Files:** backend/app/modules/inventory/controller.py; backend/app/modules/inventory_cost/service.py; backend/app/modules/supplier_portal/service.py; tests/test_query_scaling.py
**Interfaces:** 领用/效期分页 page>=1、1<=page_size<=100，keyword；兼容旧 list 调用但受上限控制；发货/质量列表两次基础查询返回 total/items。
**Tests / independent expectations:** test_issue_options_scope_and_second_page；test_expiry_has_bounded_pages；test_supplier_list_query_count_constant：页大小 1/20 查询次数一致。
- [ ] 写出以上行为的最小失败测试（先命名能捕捉的真实错误，必要时使用真实 MySQL 回滚事务）。
- [ ] 运行对应测试，Expected: 因功能缺失出现预期断言失败，而非导入/环境错误。
- [ ] 在指定文件实现最小改动，保留权限、资源范围、幂等和事务约束。
- [ ] 运行对应测试及直接相关回归，Expected: 全部通过；任务 13/14 执行全量及实际验收。
- [ ] 提交 `perf(query): 分页库存选项并消除门户列表逐行查询`，同次记录台账的提交、测试输出和设计裁决。

### Task 4: 时间协议

**Files:** backend/app/core/time.py; backend/app/core/db.py; backend/app/modules/finance/service.py; backend/app/modules/purchase_orders/service.py; frontend-design/apps/web-chemicalops/src/utils/format.ts; scripts/audit_legacy_timestamps.py
**Interfaces:** utc_now() 返回 UTC naive；业务日期到 UTC 半开区间；响应时间带明确 UTC；历史工具默认只读，混合来源不猜测迁移。
**Tests / independent expectations:** test_utc_now_naive；test_shanghai_date_window_crosses_utc_day；test_format_utc_timestamp_in_business_zone；历史预演无写入。
- [ ] 写出以上行为的最小失败测试（先命名能捕捉的真实错误，必要时使用真实 MySQL 回滚事务）。
- [ ] 运行对应测试，Expected: 因功能缺失出现预期断言失败，而非导入/环境错误。
- [ ] 在指定文件实现最小改动，保留权限、资源范围、幂等和事务约束。
- [ ] 运行对应测试及直接相关回归，Expected: 全部通过；任务 13/14 执行全量及实际验收。
- [ ] 提交 `fix(time): 统一新数据时间协议并提供历史时间核查`，同次记录台账的提交、测试输出和设计裁决。

### Task 5: 统一候选与结构化续跑

**Files:** backend/app/modules/ai/schema.py; backend/app/modules/ai/candidate_resolution.py; backend/app/modules/ai/multi_intent.py; backend/app/modules/ai/agent_runtime.py; backend/app/modules/ai/routing.py; tests/test_batch_continuation.py
**Interfaces:** PendingChoice 为产品/询价候选统一契约；批次持久化候选和版本；服务端验证当前候选 ID，成功子任务不重新规划；移除 RFQ/limit/warehouse 语义正则。
**Tests / independent expectations:** test_batch_choice_survives_reload；test_choice_rejects_stale_or_foreign_candidate；test_batch_resume_preserves_successes；Agent/批次相同候选行为；代表性语义样本。
- [ ] 写出以上行为的最小失败测试（先命名能捕捉的真实错误，必要时使用真实 MySQL 回滚事务）。
- [ ] 运行对应测试，Expected: 因功能缺失出现预期断言失败，而非导入/环境错误。
- [ ] 在指定文件实现最小改动，保留权限、资源范围、幂等和事务约束。
- [ ] 运行对应测试及直接相关回归，Expected: 全部通过；任务 13/14 执行全量及实际验收。
- [ ] 提交 `refactor(ai): 统一候选消歧与批次续跑契约`，同次记录台账的提交、测试输出和设计裁决。

### Task 6: 历史预算与删除生命周期

**Files:** backend/app/modules/ai/history_access.py; backend/app/modules/ai/conversation_store.py; backend/app/modules/ai/agent_runtime.py; backend/app/modules/jobs/service.py; tests/test_ai_history_lifecycle.py
**Interfaces:** 历史预算保留最近目标/待选候选，不以摘要授权；delete_conversation 同事务取消/清理关联任务及未确认草稿，不删除采购申请；任务保留 TTL。
**Tests / independent expectations:** test_long_history_still_runs；test_history_permission_revocation_invalidates_cache；test_delete_conversation_cancels_tasks_and_retains_created_request；test_cleanup_expired_tasks。
- [ ] 写出以上行为的最小失败测试（先命名能捕捉的真实错误，必要时使用真实 MySQL 回滚事务）。
- [ ] 运行对应测试，Expected: 因功能缺失出现预期断言失败，而非导入/环境错误。
- [ ] 在指定文件实现最小改动，保留权限、资源范围、幂等和事务约束。
- [ ] 运行对应测试及直接相关回归，Expected: 全部通过；任务 13/14 执行全量及实际验收。
- [ ] 提交 `fix(ai): 控制历史预算并补全会话与任务清理`，同次记录台账的提交、测试输出和设计裁决。

### Task 7: 本人任务、结果导出与草稿 patch

**Files:** backend/app/modules/ai/controller.py; backend/app/modules/ai/purchase_draft_confirmations.py; backend/app/modules/ai/schema.py; frontend-design/apps/web-chemicalops/src/views/ai/tasks/index.vue; tests/test_ai_task_management.py
**Interfaces:** GET 本人任务分页；受权限重验的 CSV 导出；patch_purchase_draft(db,user,confirmation_id,patch) 锁版本、重算 hash 和对象快照；前端复用列表/抽屉。
**Tests / independent expectations:** test_task_list_is_owner_scoped；test_export_rechecks_scope_and_escapes_formulas；test_patch_draft_version_conflict_and_confirmation；输入不合法不落业务单。
- [ ] 写出以上行为的最小失败测试（先命名能捕捉的真实错误，必要时使用真实 MySQL 回滚事务）。
- [ ] 运行对应测试，Expected: 因功能缺失出现预期断言失败，而非导入/环境错误。
- [ ] 在指定文件实现最小改动，保留权限、资源范围、幂等和事务约束。
- [ ] 运行对应测试及直接相关回归，Expected: 全部通过；任务 13/14 执行全量及实际验收。
- [ ] 提交 `feat(ai): 提供本人任务管理与可重新确认的草稿修改`，同次记录台账的提交、测试输出和设计裁决。

### Task 8: 数值关联与离线评测门禁

**Files:** backend/app/modules/ai/numeric_fidelity.py; backend/app/modules/ai/agent_prompt.py; backend/app/core/config.py; scripts/check_evaluation_fixtures.py; tests/test_ai_numeric_associations.py; .github/workflows/ci.yml
**Interfaces:** 删除死配置并修正文案；冻结样本、oracle、SHA 与权限/批次/草稿离线护栏；数字与指标对应关系的确定性验证/模板回退。
**Tests / independent expectations:** test_swapped_metric_values_fall_back；test_unauthorized_units_fall_back；冻结清单修改导致命令非零；真实模型报告不复用旧指标。
- [ ] 写出以上行为的最小失败测试（先命名能捕捉的真实错误，必要时使用真实 MySQL 回滚事务）。
- [ ] 运行对应测试，Expected: 因功能缺失出现预期断言失败，而非导入/环境错误。
- [ ] 在指定文件实现最小改动，保留权限、资源范围、幂等和事务约束。
- [ ] 运行对应测试及直接相关回归，Expected: 全部通过；任务 13/14 执行全量及实际验收。
- [ ] 提交 `test(ai): 增加数值关联护栏与冻结题集校验`，同次记录台账的提交、测试输出和设计裁决。

### Task 9: 共享列表与原因确认模板

**Files:** frontend-design/apps/web-chemicalops/src/components/reason-modal/index.vue; frontend-design/apps/web-chemicalops/src/views/supplier-portal/components/SupplierRecordList.vue; frontend-design/apps/web-chemicalops/src/views/master/products/index.vue; frontend-design/apps/web-chemicalops/src/views/warehouse/stocktakes/index.vue; frontend-design/apps/web-chemicalops/src/views/finance/reconciliations/index.vue
**Interfaces:** 保留现有样式，复用 Modal 表单校验、loading、焦点和确认；列表共享脚手架实现真实所需配置；停用文案一致。
**Tests / independent expectations:** ReasonModal 必填/双击/异常恢复交互；产品停用先确认且取消不发请求；共享列表 props 行为。
- [ ] 写出以上行为的最小失败测试（先命名能捕捉的真实错误，必要时使用真实 MySQL 回滚事务）。
- [ ] 运行对应测试，Expected: 因功能缺失出现预期断言失败，而非导入/环境错误。
- [ ] 在指定文件实现最小改动，保留权限、资源范围、幂等和事务约束。
- [ ] 运行对应测试及直接相关回归，Expected: 全部通过；任务 13/14 执行全量及实际验收。
- [ ] 提交 `refactor(web): 统一原因弹窗与列表操作确认`，同次记录台账的提交、测试输出和设计裁决。

### Task 10: 远程选项、工作台与可访问性

**Files:** frontend-design/apps/web-chemicalops/src/components/items-editor/index.vue; frontend-design/apps/web-chemicalops/src/views/ai/workspace/index.vue; frontend-design/apps/web-chemicalops/src/utils/lookup.ts; frontend-design/apps/web-chemicalops/src/views/dashboard/overview/components/trend-chart.vue
**Interfaces:** 远程搜索+按 ID 回填；拆 useChatStream/useConversation；Markdown 缓存/滚动节流；菜单键盘焦点、图表摘要、窄屏抽屉；中文字典、登录资源压缩；保留 hash。
**Tests / independent expectations:** 101+选项远程命中与已选名称；IME/SSE错误恢复；菜单键盘与窄屏浏览器验收；构建资源体积对比。
- [ ] 写出以上行为的最小失败测试（先命名能捕捉的真实错误，必要时使用真实 MySQL 回滚事务）。
- [ ] 运行对应测试，Expected: 因功能缺失出现预期断言失败，而非导入/环境错误。
- [ ] 在指定文件实现最小改动，保留权限、资源范围、幂等和事务约束。
- [ ] 运行对应测试及直接相关回归，Expected: 全部通过；任务 13/14 执行全量及实际验收。
- [ ] 提交 `fix(web): 补齐远程选项与工作台可访问性`，同次记录台账的提交、测试输出和设计裁决。

### Task 11: 异步入口数据库边界

**Files:** backend/app/modules/ai/service.py; backend/app/modules/ai/agent_runtime.py; backend/app/modules/ai/text2sql.py; backend/app/modules/ai/briefing.py; tests/test_ai_async_responsiveness.py
**Interfaces:** 高开销同步数据库阶段在线程池运行，同一 Session 串行使用，模型等待前释放事务；不采用每请求新 event loop 绕开异步网关。
**Tests / independent expectations:** test_database_stage_does_not_block_event_loop；并发 AI 的健康请求延迟基线对比；现有权限/事务集成不回归。
- [ ] 写出以上行为的最小失败测试（先命名能捕捉的真实错误，必要时使用真实 MySQL 回滚事务）。
- [ ] 运行对应测试，Expected: 因功能缺失出现预期断言失败，而非导入/环境错误。
- [ ] 在指定文件实现最小改动，保留权限、资源范围、幂等和事务约束。
- [ ] 运行对应测试及直接相关回归，Expected: 全部通过；任务 13/14 执行全量及实际验收。
- [ ] 提交 `perf(ai): 将高开销数据库阶段移出事件循环`，同次记录台账的提交、测试输出和设计裁决。

### Task 12: 可复现依赖与完整部署

**Files:** backend/requirements.lock; backend/Dockerfile; deploy/compose.full.yaml; deploy/nginx; scripts/restore_mysql.py; docs/完整部署与恢复运行说明.md
**Interfaces:** 锁定解析依赖；API/前端/Worker/反代/TLS/数据库和存储；复用现有备份恢复工具，演练在独立数据库/卷；不公开部署。
**Tests / independent expectations:** 干净依赖安装；docker compose config；空环境健康检查；独立数据库恢复后迁移/行数/样本对账。
- [ ] 写出以上行为的最小失败测试（先命名能捕捉的真实错误，必要时使用真实 MySQL 回滚事务）。
- [ ] 运行对应测试，Expected: 因功能缺失出现预期断言失败，而非导入/环境错误。
- [ ] 在指定文件实现最小改动，保留权限、资源范围、幂等和事务约束。
- [ ] 运行对应测试及直接相关回归，Expected: 全部通过；任务 13/14 执行全量及实际验收。
- [ ] 提交 `build(deploy): 提供完整运行栈与可复现依赖`，同次记录台账的提交、测试输出和设计裁决。

### Task 13: 真实依赖与浏览器验收

**Files:** docs/evidence/remediation; docs/项目问题与后续工作.md; tests/test_redis_features.py; tests/test_supplier_portal_api.py; tests/test_task_queue_live_cli.py
**Interfaces:** 运行可用 Redis/MinIO/Worker 验收；浏览器关键路径；真实模型仅使用已配置且明确样本，报告原始结果与边界。
**Tests / independent expectations:** pytest -q -rs 全量；vue-tsc；vitest；生产配置/安全扫描；浏览器实测记录；不能运行的外部条件明确留证。
- [ ] 写出以上行为的最小失败测试（先命名能捕捉的真实错误，必要时使用真实 MySQL 回滚事务）。
- [ ] 运行对应测试，Expected: 因功能缺失出现预期断言失败，而非导入/环境错误。
- [ ] 在指定文件实现最小改动，保留权限、资源范围、幂等和事务约束。
- [ ] 运行对应测试及直接相关回归，Expected: 全部通过；任务 13/14 执行全量及实际验收。
- [ ] 提交 `test: 补齐集成验收与整改闭环证据`，同次记录台账的提交、测试输出和设计裁决。

### Task 14: 整体验证与独立审查

**Files:** docs/项目问题与后续工作.md; docs/evidence/remediation
**Interfaces:** 以分支起点至 HEAD 的完整范围做一次独立审查，Critical/Important 补回归再修；记录所有决策与真实剩余外部条件。
**Tests / independent expectations:** 全量后端、类型、前端测试通过；独立 reviewer 返回可审查结论；git diff --check；每项状态有证据。
- [ ] 写出以上行为的最小失败测试（先命名能捕捉的真实错误，必要时使用真实 MySQL 回滚事务）。
- [ ] 运行对应测试，Expected: 因功能缺失出现预期断言失败，而非导入/环境错误。
- [ ] 在指定文件实现最小改动，保留权限、资源范围、幂等和事务约束。
- [ ] 运行对应测试及直接相关回归，Expected: 全部通过；任务 13/14 执行全量及实际验收。
- [ ] 提交 `docs: 汇总剩余整改的实施与验收结果`，同次记录台账的提交、测试输出和设计裁决。

## Review Focus

1. 历史例外字段是否能由普通 API 注入，或让新重复单绕过唯一约束。
2. 请求体超限、客户端断开时是否仍完整缓冲、返回已开始的响应或泄露堆栈。
3. 批次续跑在版本冲突、权限变化、会话删除时是否重用过期候选或重复执行成功项。
4. 草稿 patch 是否让旧确认快照继续可用，或让非法字段/产品状态绕过领域校验。
5. 时间转换、线程池与缓存是否改变业务日期、复用跨用户数据或并发使用 Session。

每项风险在所属任务增加回归；最终独立审查逐项检查。维护工具执行前备份且先预演。
