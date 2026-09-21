# ChemicalOps 化学品运营管理平台

ChemicalOps 是一个面向化学品采购、到货、质量、库存和供应商管理的运营平台。项目当前包含后台管理 API、运营看板、业务链路页面、AI 工作台、附件解析和 MinIO 文件存储能力。

## 项目一览

```mermaid
flowchart LR
    U[运营人员] --> FE[React + Vite 前端]
    FE --> API[FastAPI 业务 API]
    API --> DB[(MySQL)]
    API --> OBJ[(MinIO 对象存储)]
    API --> AI[DeepSeek 兼容接口]
    API --> MU[MinerU 文档解析]
```

## 核心业务链路

```mermaid
flowchart LR
    A[采购订单] --> B[到货计划]
    B --> C[收货确认]
    C --> D[质量验收]
    D -->|合格| E[库存入库]
    D -->|异常/复检| F[异常处理]
    E --> G[库存预警与运营看板]
```

## 已实现功能

| 模块 | 当前能力 |
|---|---|
| 运营看板 | 实时聚合指标、采购趋势折线图、订单状态饼图、统计图表和待办事项 |
| 采购管理 | 采购订单列表、详情和基础业务状态 |
| 到货与收货 | 登记到货计划、收货确认、物流信息和数量校验 |
| 质量验收 | 创建验收、提交验收结果、合格/部分合格/不合格/复检状态 |
| 库存入库 | 按验收结果进入入库流程，展示库存与批次信息 |
| AI 工作台 | 悬浮球、可拖动聊天窗、历史会话、附件上传、Markdown 渲染、SSE 流式输出 |
| 文档解析 | TXT/CSV/Markdown/JSON 本地解析，PDF/Office 通过 MinerU v4 解析，OCR 暂不启用 |
| 文件存储 | MinIO 原始文档桶与解析结果桶，私有权限和业务资源权限校验 |
| 安全能力 | JWT、角色权限、附件大小/MIME/魔数校验、可选 ClamAV、审计日志 |

## AI 工作台

AI 对话采用 SSE 流式协议：

```mermaid
sequenceDiagram
    participant B as 浏览器
    participant API as ChemicalOps API
    participant LLM as DeepSeek
    B->>API: POST /api/v1/ai/chat/stream
    API->>API: 校验权限、读取附件和实时业务数据
    API->>LLM: stream=true
    loop 增量输出
        LLM-->>API: delta
        API-->>B: SSE event: delta
    end
    API-->>B: SSE event: done
    API->>API: 保存完整会话消息
```

AI 回复支持标题、列表、加粗、行内代码、代码块和换行等 Markdown 展示。

## MinIO 文件分层

```mermaid
flowchart TB
    F[用户上传文件] --> D[(chemicalops-documents)]
    D --> P[MinerU / 本地解析]
    P --> R[(chemicalops-results)]
    R --> C[AI 引用与 Markdown 展示]
```

默认桶规划：

- `chemicalops-documents`：原始上传文件
- `chemicalops-results`：解析后的 Markdown 结果

数据库只保存文件元数据和对象键，文件内容不写入业务表。

## 本地启动

### 1. 安装后端依赖

```powershell
uv sync
```

如果项目环境没有使用 `uv`，也可以根据 `backend/requirements.txt` 安装依赖。

### 2. 配置环境变量

复制示例配置并填写本地值：

```powershell
Copy-Item .env.example .env
```

至少需要配置数据库、JWT 密钥、AI API key，以及 MinIO：

```env
FILE_STORAGE_BACKEND=minio
MINIO_ENDPOINT=127.0.0.1:19000
MINIO_ACCESS_KEY=你的MinIO账号
MINIO_SECRET_KEY=你的MinIO密码
MINIO_DOCUMENT_BUCKET=chemicalops-documents
MINIO_RESULT_BUCKET=chemicalops-results
```

### 3. 启动 MinIO

项目提供 Docker 配置：

```powershell
docker compose -f deploy/docker-compose.minio.yml up -d
```

如果已有 MinIO 容器，直接使用已有端口，并在控制台创建两个私有桶即可。MinIO 控制台通常通过 `http://127.0.0.1:19001` 访问，具体以 Docker Desktop 的端口映射为准。

### 4. 启动后端

```powershell
uv run main.py run --env=dev
```

后端默认地址：`http://127.0.0.1:8888`。

### 5. 启动前端

前端基于 Vben Admin（Vue 3 + antdv-next），位于 `frontend-design/apps/web-chemicalops`。

```powershell
# monorepo 要求 pnpm >= 11，首次先激活
corepack prepare pnpm@11.16.0 --activate

corepack pnpm --dir frontend-design install
corepack pnpm --dir frontend-design dev:chemicalops
```

前端默认地址：`http://localhost:3000`，已配置代理把 `/api` 与 `/health` 转发到后端 8888。

依赖安装与构建的注意事项见 [`docs/build-notes/前端构建环境说明.md`](docs/build-notes/前端构建环境说明.md)。

## 目录结构

```text
ChemicalOps/
├─ backend/       FastAPI 后端、业务模块、权限和文件服务
├─ frontend-design/  Vben Admin monorepo，业务前端在 apps/web-chemicalops
├─ database/      数据库初始化和迁移脚本
├─ deploy/        Docker 与部署配置
├─ docs/          需求、接口、流程和实现进度文档
├─ scripts/       调度、初始化和运维脚本
├─ tests/         后端接口与业务测试
├─ .env.example   中文配置说明模板
└─ main.py        开发启动入口
```

## 重要接口

| 接口 | 说明 |
|---|---|
| `POST /api/v1/auth/login` | 用户登录 |
| `GET /api/v1/dashboard/overview` | 运营看板实时概览 |
| `POST /api/v1/files` | 上传文件 |
| `POST /api/v1/ai/chat/stream` | AI SSE 流式对话 |
| `GET /api/v1/ai/conversations` | 查询 AI 历史会话 |

完整接口说明见 [`docs/后台管理CRUD接口说明.md`](docs/后台管理CRUD接口说明.md)。

## 验证命令

```powershell
corepack pnpm --dir frontend-design build:chemicalops
uv run pytest -q
```

`.env`、上传文件、解析结果和前端构建产物均已加入 Git 忽略规则，不应提交到仓库。

## 当前边界

- AI 当前以查询分析和业务草稿建议为主，不直接执行订单、入库等高风险写操作。
- OCR 暂不纳入本轮实现。
- 生产环境还需要补充对象存储密钥管理、ClamAV 服务、监控告警和更细的部门/仓库数据范围。
