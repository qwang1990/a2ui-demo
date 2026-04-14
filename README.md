# a2ui-demo

大模型驱动本体流程（AIP Logic JSON → LangGraph）与 **A2UI v0.8**（`@a2ui/lit`）前端交互的演示项目。

**设计说明（单一文档）：[docs/DESIGN.md](docs/DESIGN.md)**（根目录 [DESIGN.md](DESIGN.md) 仅为跳转入口。）

## 结构

- [`ontology/`](ontology/)：Palantir Foundry 风格的 **objectTypes / properties** + AIP 流程节点（`sam_credit_card`、`simple_kyc`），支持热加载。
- [`backend/`](backend/)：FastAPI + WebSocket + LangGraph + OpenRouter（可选 A2UI / 表单 schema）+ 全链路日志（`LOG_LEVEL`）。
- [`frontend/`](frontend/)：Vite + Lit Web Components，采用“固定首表单 + 对话时间线 + 动态 A2UI 卡片”交互，渲染服务端下发的 A2UI 消息。

## 配置

复制 [`.env.example`](.env.example) 为 `.env`（或直接在 shell 中 `export`）。常用项：

| 变量 | 作用 |
|------|------|
| `LOG_LEVEL` | `DEBUG` / `INFO`（默认）等，控制服务端日志详细程度 |
| `OPENROUTER_API_KEY` / `OPENROUTER_MODEL` | OpenRouter 密钥与模型 |
| `OPENROUTER_BASE_URL` | 默认 `https://openrouter.ai/api/v1` |
| `OPENROUTER_HTTP_REFERER` / `OPENROUTER_APP_TITLE` | 可选，随请求发给 OpenRouter |
| `ENABLE_LLM_FORM_SCHEMA` | 默认 `1`；有 `OPENROUTER_API_KEY` 时，`user_input` interrupt 会尝试让 LLM 生成结构化表单 schema（失败自动回落模板） |
| `ENABLE_LLM_FULL_A2UI` | 默认 `1`；允许 LLM 返回完整 v0.8 A2UI messages（校验失败回落 schema/模板） |
| `PUBLIC_BASE_URL` | Mock 本体 HTTP 客户端使用的本服务地址（默认 `http://127.0.0.1:8000`） |

## 运行

**1. 后端**（仓库根目录下的 `ontology/` 会被自动加载，也可通过环境变量 `ONTOLOGY_DIR` 指定）：

```bash
cd backend
# 可选：cp ../.env.example ../.env 并填写 OPENROUTER_* 
uv sync --extra dev
uv run a2ui-demo-serve
# 默认 http://127.0.0.1:8000
```

**2. 前端**：

```bash
cd frontend
npm install
npm run dev
```

浏览器打开 Vite 提示的地址（一般为 `http://localhost:5173`），通过 Vite 代理访问 `/api` 与 `/ws`。

## 前端交互模式（对话式）

1. 顶部固定表单：输入 `flow_id`、姓名、身份证，点击开始。
2. 对话时间线：展示用户输入、节点推进、助手提示与完成结果。
3. 动态交互卡片：当后端返回 `a2ui_batch` 时，在“当前交互卡片”区域渲染 A2UI 表单/动作按钮。
4. 继续交互：用户在 A2UI 卡片中提交后，前端发送 `a2ui_event`，流程继续推进直到 `flow_done`。

`a2ui_batch` 中的 `messages_source` 语义：

- `llm_schema`：由 LLM 结构化 schema 生成后转 A2UI。
- `template_fallback`：LLM 失败或未启用，走模板回退。
- `template_non_user_input`：非 `user_input` interrupt（如 `action`）走模板。

## 演示规则（Mock 本体）

前端提交的 `attrs` 使用 **camelCase** 属性名（与 ontology 中 `properties[].apiName` 一致），例如 `fullName`、`idNumber`。

身份证号（字符串）中：

- 包含 **`SAMS_MEMBER`** → 视为山姆会员 → **不予开卡**
- 包含 **`HAS_MS`** → 视为已有民生信用卡 → **不予开卡**

## 单元测试

```bash
cd backend
uv run pytest
```

## 手工验收清单

1. 启动后端，确认日志包含：
   - `compiled flow ... langgraph_edges_preview=...`
   - `compiled langgraph ... nodes=...`
   - `compiled langgraph ... mermaid_single_line=...`
2. 启动前端并在 `http://localhost:5173` 打开页面，输入姓名和身份证后点击办理。
3. 当流程缺失字段时，页面应在 A2UI 区出现动态表单（非空白），并显示渲染状态 `rendering`。
4. 提交 A2UI 表单后，后端应继续推进流程，最终出现 `flow_done`。
5. 若配置了 OpenRouter，后端 `ws send a2ui_batch` 日志应出现 `source=llm_schema`；未配置或失败时应回落 `source=template_*`。

## 参考

- [A2UI](https://github.com/google/A2UI)
- [OpenRouter](https://openrouter.ai/)
