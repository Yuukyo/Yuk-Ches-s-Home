# Yuk & Ches's Home

一个给“你和 API 端 AI”共同生活的私密小家。界面以绿色木质书房为主，不照搬需求文档里的参考图；聊天、记录、账本、奖励、共读、生图与记忆都在同一个应用中。

项目参考了：

- [wq70/OVO](https://github.com/wq70/OVO) 的聊天记录结构，并提供兼容导入/导出；
- [P0luz/Ombre-Brain](https://github.com/P0luz/Ombre-Brain) 的长期记忆 MCP；
- [idleprocesscc/co-reading-mcp](https://github.com/idleprocesscc/co-reading-mcp) 的共读 REST/MCP。

上游项目没有被复制进本仓库。它们作为独立服务运行，本应用通过服务端安全连接。Ombre Brain 在界面中归入“记忆系统”，没有单独做一个割裂的主功能入口。

## 快速开始

需要 Python 3.11+。

```bash
python -m venv .venv
```

Windows PowerShell：

```powershell
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
python app.py
```

macOS / Linux：

```bash
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python app.py
```

打开 `http://127.0.0.1:5000`。首次运行未配置 Supabase 时，会自动使用 `instance/home.db`；这只适合本地试用。

至少先在 `.env` 填好：

```dotenv
APP_SECRET=一串至少32位的随机字符
APP_PASSWORD=进入小家的访问密码
API_URL=https://你的OpenAI兼容接口
API_KEY=你的密钥
API_MODEL=模型名
```

`API_URL` 可以写到服务根地址、`/v1`，或完整的 `/v1/chat/completions`。

## 功能怎么用

### 首页与聊天

- 开屏显示天气、时间、从 `2024-09-01` 起相伴的天数和每日一句；上滑或点“回家”进入。
- 输入框回车发送，`Shift+Enter` 换行。
- 点“稍后一起发”可把多条话排进发送队列，再一次连续发送。
- 长按发送键可以填写“我的内心想法”。这只是用户主动给 AI 的情绪语境，不要求、也不展示模型隐藏思维链。
- 加号菜单可上传图片/文本/Word 附件、添加音乐链接、贴纸或共读片段。图片会作为视觉输入发送给兼容多模态的聊天模型；TXT、Markdown、JSON、CSV、日志和 DOCX 会提取正文。
- 长按消息可编辑、引用、收藏、删除并填写原因；AI 消息还可重新生成。被删除或被重生成替换的消息进入 AI 小黑屋的墓地，不会直接物理删除。
- “生成分享图”在浏览器本地绘制，不会把聊天内容发送到第三方制图网站。
- 设置中打开“允许主动消息”后，定时任务会根据空闲时间随机生成主动消息。

### OVO 聊天记录迁移

1. 在 OVO 中导出角色聊天 JSON。
2. 打开“设置 → OVO 聊天记录迁移”。
3. 选择“追加”或“替换后导入”并上传文件。

兼容官方 `uwu-chat-history` 的 `history`，也兼容含 `characters[].history` 的完整备份。导入会保留角色、时间和源消息 ID；重复导入会跳过已有 ID。“替换”会把旧消息移进墓地，便于恢复线索。

“导出当前聊天”会生成可迁移的 `uwu-chat-history` JSON。建议导入前先备份两边数据。

### 生活记录

- 时间线分类：便签、任务、习惯、心情、附件和链接。
- 任务/习惯可勾选完成，完成记录会用于奖励评估。
- 每条记录都可编辑或移入废纸篓。

### 账本与计划

- “资产”登记账户余额；
- “统计”根据收入/支出流水汇总；
- “计划”管理存钱计划与购物清单；
- 可记录消费、收入、每日小票说明和发生时间。

金额仅是共同生活账本数据，不连接真实银行或支付账户。

### 奖励商店

- 新建奖励时可让 AI 建议积分，也可手动填写。
- 定时任务会在每天 08:00、12:00、18:00、22:00（应用时区）检查已完成任务/习惯并发放积分。
- 奖励项目兑换后进入当日记录；22:00 后的剩余积分会结转到购物基金。
- 所有加分、扣分和结转都有流水，便于核对。

### 共读

- 配置 co-reading-mcp 后，可查看书架、章节、全文搜索、读章节、标记已读和写页边批注。
- 支持从首页导入 EPUB、TXT 和 Markdown（单文件不超过 12 MB）。
- 用户批注默认以 `author=user`、`status=open` 保存，先保持私密；上游阅读器的“Send to Claude/AI”流程可再提交它们。
- 在章节页点“带去聊天”，当前段落会作为本轮阅读语境发给 AI。

### 记忆系统

- 配置 Ombre Brain 后，每轮聊天前会用 `breath` / `breath_search` 召回相关长期记忆，回复后用 `hold` 或 `grow` 写入本轮经历。
- “设置 → 记忆系统”可以手动搜索或写入一段记忆。
- Ombre Brain 不可用时，聊天仍可继续，并在响应里返回记忆警告；不会因为记忆服务短暂离线而丢掉本轮聊天。

完整配置见 [MCP_SETUP.md](docs/MCP_SETUP.md)。

### 生图、收藏与小剧场

- 支持 NovelAI 接口和 OpenAI-compatible Images 接口。
- 生成结果保存为私有附件，并出现在画廊。
- 画廊还汇总消息收藏、AI 收藏和小剧场。
- 小剧场评论支持记录延迟阅读时间；前端只在到期后显示为已读。

### AI 小黑屋

长按聊天页顶部 AI 名称进入。这里展示 AI 收藏、备忘、钱包和消息墓地。当前实现按需求设计为用户只读；修改这些内容应由后续 AI 工具或后台逻辑完成，避免用户无意改写 AI 私人区。

## 环境变量

复制 `.env.example` 后按注释填写。密钥只能放在 `.env`、Render Environment 或 GitHub Secrets，不能写进 `static/`、截图或提交到 Git。

核心变量：

| 变量 | 用途 |
| --- | --- |
| `APP_SECRET` / `APP_PASSWORD` | 会话签名与家庭访问密码 |
| `API_URL` / `API_KEY` / `API_MODEL` | OpenAI 兼容聊天 API |
| `SUPABASE_URL` / `SUPABASE_SERVICE_ROLE_KEY` | 数据与私有附件 |
| `OMBRE_BRAIN_MCP_URL` / `OMBRE_BRAIN_ACCESS_TOKEN` | Ombre Brain Streamable HTTP |
| `CO_READING_URL` / `CO_READING_MCP_URL` | 共读 REST 根地址与 `/mcp` |
| `IMAGE_PROVIDER` / `IMAGE_*` | NovelAI 或 OpenAI-compatible 生图 |
| `CRON_SECRET` | 保护 `/api/cron/tick` |

生图示例：

```dotenv
# NovelAI
IMAGE_PROVIDER=novelai
IMAGE_API_URL=https://image.novelai.net
IMAGE_API_KEY=...
IMAGE_MODEL=nai-diffusion-4-full

# 或 OpenAI-compatible
IMAGE_PROVIDER=openai-compatible
IMAGE_API_URL=https://example.com/v1
IMAGE_API_KEY=...
IMAGE_MODEL=你的图片模型
```

## 部署

推荐结构：

```text
浏览器
  └─ Yuk & Ches's Home（Render）
       ├─ 聊天/视觉/生图 API
       ├─ Supabase（消息、记录、附件）
       ├─ Ombre Brain /mcp（必须持久盘）
       └─ co-reading-mcp REST + /mcp（建议持久盘）
```

逐步操作见 [DEPLOYMENT.md](docs/DEPLOYMENT.md)。仓库中的：

- `sql/supabase.sql`：首次建表和私有 Storage bucket；
- `render.yaml`：主应用 Blueprint；
- `.github/workflows/home-cron.yml`：每日一句、奖励结算和主动消息唤醒；
- `sql/reset_demo_data.sql`：仅在确定要清空演示数据时手动执行。

## 安全设计

- 整个 API 可用家庭密码保护，并带登录限速。
- 变更请求检查同源，Cookie 为 HttpOnly / SameSite。
- Supabase `service_role` 或 `sb_secret_...` 只在服务端使用；浏览器不拿数据库密钥。
- 表启用 RLS 且不为 `anon` / `authenticated` 建公开策略。
- Storage bucket 私有，下载通过服务端生成短效签名 URL。
- MCP Token、聊天密钥和生图密钥都不会通过 `/api/config` 返回前端。

## 项目结构

```text
app.py                 Flask 路由与业务流程
config.py              环境变量
store.py               Supabase / SQLite 存储适配
integrations.py        聊天、MCP、天气和生图适配
templates/index.html   单页应用结构
static/css/style.css   绿色木质书房视觉
static/js/app.js       前端交互
sql/                   Supabase 初始化
docs/                  MCP 与部署教程
tests/                 后端自动测试
```

## 测试

```bash
python -m unittest discover -s tests -v
node --check static/js/app.js
```

正式部署前建议再做一次：OVO 备份导入、附件上传/下载、Ombre 搜索/写入、共读导书和定时任务手动触发。
