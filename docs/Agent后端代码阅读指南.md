# Agent 后端代码阅读指南

这份指南以“查询乙醇库存”为例，帮助你从一个具体问题出发，看懂请求怎样进入后端、如何调用 Agent 工具、结果怎样返回，以及写入操作如何经过人工确认。

建议先阅读 [Agent 能力与 RSI 成熟度分析](Agent能力与RSI成熟度分析.md) 的第 1～3 节，了解有哪些能力，再按下面的顺序对照代码。该分析文档记录的是特定代码版本及评测结果；了解当前行为时，以代码和相应测试为准。

## 一、先建立整体认识

1. 阅读 [后端入口 main.py](../backend/app/main.py)，搜索 `include_router`，了解 FastAPI 如何注册业务接口。
2. 阅读 [ai_agent 模块说明](../backend/app/modules/ai_agent/__init__.py)，了解执行、查询、会话、写入和模型接入分别放在哪里。

先记住一条主线：

```text
用户问“乙醇还有多少库存？”
  → 接口接收请求
  → 路由理解问题及当前可用能力
  → Agent 决定下一步
  → 工具查找产品、查询用户可见库存
  → 任务保存状态和结果，返回用户
```

阅读每个函数时，先回答三个问题：**输入是什么、调用了谁、输出是什么**。

## 二、从接口看请求如何进入后端

打开 [AI 接口 controller.py](../backend/app/modules/ai_agent/controller.py)，搜索以下接口：

| 接口 | 阅读重点 |
| --- | --- |
| `/route` | 如何结合用户、会话和能力清单理解请求。 |
| `/agent/tasks/start` | 如何创建只读任务并立即返回。 |
| `/agent/tasks/{task_id}` | 如何查询任务状态和结果。 |
| `/action-proposals` | 如何生成、查看和确认动作提案。 |

遇到不熟悉的输入、输出字段时，在 [schema.py](../backend/app/modules/ai_agent/schema.py) 中搜索相应的数据类，例如 `TaskCreate`。不需要一次读完整个文件。

## 三、看 Agent 如何决策和查询

1. 在 [routing.py](../backend/app/modules/ai_agent/agent_execution/routing.py) 搜索 `understand`，看问题如何被理解为路由结果。
2. 在 [agent_runtime.py](../backend/app/modules/ai_agent/agent_execution/agent_runtime.py) 搜索 `_drive_impl`，看任务如何规划、调用工具、等待用户补充信息和结束。这个文件较大，第一遍只跟随当前例子阅读。
3. 在 [agent_tools.py](../backend/app/modules/ai_agent/agent_execution/agent_tools.py) 中依次查看 `TOOLS`、`execute_tool` 和 `query_inventory`。
4. 重点追踪：产品如何定位、用户权限和仓库范围在哪里检查、查询结果如何交回 Agent。

## 四、看任务如何异步执行

从 [agent_runtime.py](../backend/app/modules/ai_agent/agent_execution/agent_runtime.py) 的 `schedule_async` 入手：它根据配置选择数据库任务队列或进程内后台任务。

然后阅读 [任务队列 service.py](../backend/app/modules/task_queue/service.py)，关注 `enqueue`、`claim_execution`、`heartbeat` 和 `finish`，理解任务入队、领取、租约续期和结束。再回看分析文档中的取消、重试和续跑说明。

## 五、单独看写入操作

以“创建采购申请草稿”为例：

1. 在 [action_proposals.py](../backend/app/modules/ai_agent/action_management/action_proposals.py) 中查看 `propose_action` 和 `confirm_action`。
2. 在 [action_handlers.py](../backend/app/modules/ai_agent/action_management/action_handlers.py) 中查找对应动作处理器，追踪它调用的业务服务。
3. 重点理解：**提案预览和正式执行是两步**。用户确认时，服务端再次检查权限、版本、来源证据和业务状态。

## 六、最后看模型调用和评测

- [llm.py](../backend/app/modules/ai_agent/model_access/llm.py)：模型消息、调用和响应处理。
- [agent_prompt.py](../backend/app/modules/ai_agent/agent_execution/agent_prompt.py)：系统提示词和阶段提示词。
- [model_catalog.py](../backend/app/modules/ai_agent/model_access/model_catalog.py)：模型配置目录。
- [Agent 能力与 RSI 成熟度分析](Agent能力与RSI成熟度分析.md) 第 4 节及以后：评测、回归和自改进工作。

先理解 Agent 的请求和工具调用，再读评测内容，更容易把评测结果与实际代码对应起来。

## VS Code 代码跳转快捷键

- 跳转到函数或定义后，按 **`Alt + ←`** 返回上一个位置。
- 按 **`Alt + →`** 前进到刚才的位置。
- 按 **`Ctrl + Tab`** 切换最近打开的文件。
