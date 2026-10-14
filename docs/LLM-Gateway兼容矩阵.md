# LLM Gateway 兼容矩阵

本文描述当前客户端代码和 Mock 契约，不代表每个模型服务商的线上能力声明。配置了 OpenAI-compatible URL 只说明请求协议入口，不证明该模型支持所有可选字段。真实服务兼容性需按模型 profile 单独验收。

## 当前运行边界

Gateway 支持一个 legacy 环境配置和可选的命名模型 profile。当前 development 配置未定义命名 profile，使用 legacy 单模型设置。profile 配置可覆盖模型、endpoint、密钥、超时、有限重试、并发、温度、Token 上限及 `stream_usage`；没有结构化输出、原生 Tool Calling 等能力声明字段。

| 能力 | 当前请求与解析方式 | 已验证范围 | 限制与使用规则 |
| --- | --- | --- | --- |
| `json_object` | OpenAI Chat Completions `response_format`；服务端解析 assistant `message.content` | Mock 请求与解析 | 仅要求 JSON 对象，不代表字段符合业务 Schema；之后仍由 Pydantic 校验 |
| `json_schema` | 通用 OpenAI-compatible endpoint 走 Chat Completions strict schema；主机为 `api.deepseek.com` 时转换为 `/responses` 与 `text.format`，要求 `status=completed` 并读取 `output_text` | 两类协议、严格 Schema、截断拒绝均有 Mock | DeepSeek 分支按 hostname 判断；其他厂商的 Responses API 差异不自动适配 |
| 流式文本 | Chat Completions `stream=true`，只解析 `choices[0].delta.content`；结束后取可选 usage | 重试边界、首 token 后断流不重放、取消后关闭 HTTP 上游及客户端上下文均有 Mock | 当前无流式 JSON Schema 或流式结构化结果解析；断流已有部分输出时返回错误，不拼接后重试 |
| 原生 Tool Calling | 不发送 `tools`/`tool_choice`，也不解析 `tool_calls` | Agent 工具调度由服务端流程测试覆盖 | Agent 使用 JSON action/QueryPlan 加 Pydantic 校验，再由权限护栏执行只读工具；不能把 provider function calling 当成已支持能力 |
| 同步 Token usage | 接受响应中的 `usage`，只统计已知的整数 Token 字段 | 有 usage 与缺失 usage 的 Mock | 缺失或非法 usage 表示未知 (`None`)，不补 0、不估价；当前没有持久化用户/请求费用账本 |
| 流式 Token usage | profile 的 `stream_usage=true` 时发送 `stream_options.include_usage`，解析带 usage 的 SSE 帧 | opt-in payload 与 usage 帧 Mock | 默认关闭；服务商若不返回 usage，回答仍成功且 usage 未知 |
| 自动重试 | 有限次数；连接建立前错误可重试，HTTP 429 明确拒绝可按配置重试；指数退避 250ms 起、最多 2s | 连接失败、429 和读超时 Mock | 读/写超时、连接重置等请求状态不明时不重放，避免重复计费；仅读模型规划请求进入 Gateway，业务工具执行不由 Gateway 自动重试 |
| 熔断与备用模型 | 按 model key 的进程内状态计数；连接失败/可安全切换错误可选 fallback | 熔断、单探测恢复、连接前失败后 fallback 均有 Mock | 状态不跨进程共享；部署多个 API 实例时每实例独立配额和熔断器 |
| 用户/模型并发 | asyncio semaphore 按用户与模型限制 | 多用户并发边界及取消归还许可有 Mock | 仅进程内；不承诺跨 API 实例全局配额 |

## 当前测试证据

使用本地 Mock 和单元/集成测试，不调用真实模型。当前覆盖结构化输出协议分支、计划格式校验、连接前重试、429 有限重试、响应读超时不重放、熔断/恢复、fallback、用户/模型并发、流式首 token 后断流、取消关闭资源、usage 缺失和业务写意图在网络请求前拒绝。

运行入口：

```powershell
.venv/Scripts/python.exe -m pytest tests/test_llm_gateway.py tests/test_ai_llm_stream.py tests/test_ai_structured_output.py tests/test_ai_service.py -q
```

Mock 测试说明客户端兼容处理，不提供真实模型的 Tool Calling、Schema 遵循率、usage 可用性、费用或 TTFT 结论。真实模型集成结果须另行记录模型/版本、endpoint、提示词、网络、样本与 usage 返回情况。
