# ChemicalOps 统一 LLM Gateway 设计

## 调用边界

业务服务与 Agent 继续调用 `ai.llm.chat()` / `ai.llm.stream_chat()`。Gateway 负责解析模型目录、统一 OpenAI-compatible HTTP 调用、并发配额、熔断、有限重试和用量指标；业务代码不直接依赖供应商 SDK。旧的 `LLM_PROVIDER`、`OPENAI_BASE_URL`、`OPENAI_API_KEY` 和 `LLM_MODEL` 配置继续作为默认模型。

可选模型目录通过 `LLM_MODEL_PROFILES_JSON` 配置，模型由内部用例用 `model_name` 选择，不从用户请求体直接接受模型名：

```json
{
  "default": {
    "provider": "openai_compatible",
    "model": "deepseek-chat",
    "fallback_profile": "local-eval",
    "base_url": "https://api.deepseek.com",
    "api_key": "${MODEL_KEY_FROM_DEPLOYMENT_SECRET}",
    "timeout_seconds": 60,
    "max_retries": 2,
    "max_concurrency": 8,
    "temperature": 0.2,
    "max_tokens": 8192,
    "stream_usage": false
  },
  "local-eval": {
    "provider": "openai_compatible",
    "model": "qwen2.5-14b-instruct",
    "base_url": "http://127.0.0.1:1234/v1",
    "api_key": "lm-studio",
    "timeout_seconds": 90,
    "max_retries": 1,
    "max_concurrency": 2,
    "temperature": 0,
    "max_tokens": 4096,
    "stream_usage": true
  }
}
```

部署环境需要在 JSON 中展开实际密钥；示例中的 `${...}` 只是说明密钥来源，不会被应用自动插值。不要把真实密钥提交到仓库。

## 故障与并发策略

- 每模型并发上限默认为 8；每用户并发上限默认为 2。调用用户上下文从 AI 请求服务传到嵌套 Gateway 调用。并发信号量为**单进程**状态，多 Worker 部署时实际模型上限是各进程上限之和；已有 Redis AI 限流仍负责跨进程用户请求频率限制。
- 熔断器按 provider、base URL、model 隔离，默认连续 5 次上游不可用后打开 30 秒；恢复期仅允许一个半开探测。熔断状态也是单进程状态，各 Worker 独立恢复。
- 自动重试及备用模型切换仅限连接建立失败（ConnectError、ConnectTimeout、PoolTimeout）及 HTTP 429。读取超时、写入中断、HTTP 5xx 和流式首 token 后断开均不重放或切换，避免请求已被模型接收后重复计费或重复生成。重试次数有上限，退避为指数增长并封顶 2 秒；备用模型由 `fallback_profile` 显式配置，最多切换一次。
- 上游未返回 usage 时不估算 Token；流式 usage 仅在模型配置 `stream_usage: true` 且供应商返回 usage chunk 时统计。
- Prometheus 指标沿用现有进程内注册表：`ai_external_requests` / `ai_external_retries` 记录请求与重试，`ai_external_duration_seconds` / `ai_first_token_seconds` 记录上游耗时与 TTFT，`llm_gateway_duration_seconds` / `llm_concurrency_wait_seconds` 记录 Gateway 总耗时与配额等待，`llm_tokens` 按有限 Token 字段累计实际用量；熔断开路、拒绝和客户端取消有独立计数。
- profile 可独立配置 temperature、最大输出 Token、timeout、retry、并发上限及流式 usage；未设置的字段回退到原有默认配置。目前 provider 适配器只实现 OpenAI-compatible 协议。

## 兼容性边界

- 当前 Gateway 不在 HTTP 请求中发送模型原生 `tools` 参数；业务工具调用仍由 LangGraph 节点完成，因此各模型原生 Tool Calling 能力不构成 Gateway 的兼容承诺。
- JSON Schema 输出沿用现有适配：DeepSeek 严格 schema 走 Responses API，其他 OpenAI-compatible 服务走 Chat Completions 的 `response_format`。供应商是否实际支持严格 schema 由部署配置和集成测试确认。
- SSE 只向调用方转发文本 delta。客户端取消会关闭模型响应流并释放并发许可；SSE usage 不发送给前端，只进入指标。
- 熔断器、并发计数和当前 Prometheus 指标是进程内状态；跨实例汇总或全局并发配额需要后续结合共享状态后端设计。

## 验证

`tests/test_llm_gateway.py` 覆盖模型目录回退/选择、无效配置、熔断开闭及半开探测、每用户与每模型并发许可和取消释放。`tests/test_ai_service.py`、`tests/test_ai_llm_stream.py` 与 `tests/test_ai_structured_output.py` 使用 Mock 验证兼容请求、重试边界、SSE 和结构化输出。真实模型联调单独执行，不作为默认测试门禁。
