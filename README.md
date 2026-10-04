<div align="center">
  <img src="frontend-design/apps/web-chemicalops/public/logo.svg" alt="ChemicalOps" width="96" />
  <h1>ChemicalOps · 化工企业运营管理平台</h1>
  <p>让采购、到货、质量、库存与财务流程连得起来</p>
</div>

<table>
  <tr>
    <th align="left">项目周期</th>
    <td>2026.09 — 至今</td>
    <th align="left">项目定位</th>
    <td>面向化工企业的采购与运营协同平台</td>
  </tr>
  <tr>
    <th align="left">核心技术</th>
    <td colspan="3">Python · FastAPI · SQLAlchemy · Vue 3 · TypeScript · Vben Admin · MySQL · ECharts</td>
  </tr>
  <tr>
    <th align="left">可选集成</th>
    <td colspan="3">Redis / Celery · MinIO · Qdrant · OpenAI 兼容模型（默认配置 DeepSeek）· MinerU</td>
  </tr>
</table>

## 项目简介

ChemicalOps 覆盖化学品采购运营中的主数据、采购申请、询价报价、采购订单、到货收货、质量验收、批次库存、仓储作业和财务对账等环节。系统提供权限管理、附件、通知、任务和运营看板；AI 工作台支持受权限约束的业务查询、图表、化学品资料问答、运营晨报、自然语言筛选与人工确认的采购申请草稿。质量验收和其他业务页面提供按需触发的辅助核对与只读分析。

项目采用前后端分离结构：Vue 管理端通过 FastAPI 接口访问 MySQL；文件、模型、检索和异步任务服务按部署需要配置。AI 查询由后端白名单、权限和只读规则约束，不直接执行模型生成的 SQL，也不代替用户审批或执行高风险写操作。

## 主要功能

- **采购协同：** 采购申请、审批、询价、供应商报价和采购订单管理。
- **供应商门户：** 处理受邀询价、订单、交期、发货、质量资料及对账协同。
- **到货、质量与库存：** 收货、质量验收、批次库存、领用、调拨、盘点和退货。
- **财务管理：** 订单行对账、发票登记、付款申请及结算记录。
- **AI 工作台：** 受权限约束的业务查询、化学品资料检索、运营摘要及人工确认的采购申请草稿。
- **技术资料：** 技术研发人员和管理员可拉取 MSDS/TDS 至 MinIO，预览原文，再单独写入结构化与向量知识库。

## 技术架构

| 部分 | 技术 |
| --- | --- |
| 前端 | Vue 3、TypeScript、Vben Admin、Antdv Next、ECharts |
| 后端 | Python、FastAPI、SQLAlchemy |
| 业务数据 | MySQL |
| 可选集成 | Redis/Celery、MinIO、Qdrant、OpenAI 兼容模型、MinerU |

AI 查询通过后端权限与数据范围校验；模型不直接执行生成的 SQL，也不代替用户审批或执行高风险操作。可选服务需自行配置后才可使用。

## 本地启动

### 环境要求

- Python 3.11+
- MySQL 8+
- Node.js 22.18+、pnpm 11+

### 配置与初始化

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r backend/requirements.txt
Copy-Item .env.example .env
```

编辑 `.env` 配置 MySQL、JWT 和管理员账号。按需配置模型、MinIO、Qdrant 等服务。不要提交 `.env` 或真实凭据。

```powershell
python scripts/init_database.py
```

已有数据库可先检查迁移状态，再升级：

```powershell
python scripts/migrate_database.py status
python scripts/migrate_database.py upgrade
```

### 启动服务

后端终端：

```powershell
.\.venv\Scripts\Activate.ps1
python main.py run --env=dev
```

前端终端：

```powershell
corepack pnpm --dir frontend-design install
corepack pnpm --dir frontend-design dev:chemicalops
```

打开 `http://localhost:3000`。后端 API 默认地址为 `http://127.0.0.1:8888`，接口文档为 `http://127.0.0.1:8888/docs`。

## 测试

```powershell
.\.venv\Scripts\python.exe -m pytest
corepack pnpm --dir frontend-design/apps/web-chemicalops run typecheck
corepack pnpm --dir frontend-design/apps/web-chemicalops run build
```

## 项目结构

```text
backend/          FastAPI 应用与业务模块
frontend-design/  Vben Admin 前端
database/        MySQL 表结构与迁移
docs/             项目、接口和运行文档
scripts/          初始化、迁移及数据处理脚本
tests/            后端测试
main.py           后端开发启动入口
```

## 文档

- [项目介绍与成果（STAR）](docs/项目介绍与成果（STAR）.md)
- [项目简介与业务流程](docs/项目简介与业务流程.md)
- [运行体验与测试指南](docs/运行体验与测试指南.md)
- [数据库设计说明](docs/数据库设计说明.md)
- [接口文档](docs/接口文档.md)
- [Agent 只读任务运行与验收](docs/Agent只读任务运行与验收.md)

## 使用边界

- 业务接口仍独立执行登录、角色权限和数据范围校验；菜单隐藏不构成安全边界。
- AI 查询为受限只读能力；采购草稿需用户确认，正式审批、质量放行、库存操作和付款由相应业务流程处理。
- 截图和开发数据库内容仅用于演示，不代表生产数据或生产运行指标。

---

<p align="center">ChemicalOps · 让化学品运营更清晰、更可追溯</p>
