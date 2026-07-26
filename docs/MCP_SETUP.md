# MCP 配置教程

本应用是 MCP 客户端：Render 上的 Flask 后端主动调用 Ombre Brain 与 co-reading-mcp。浏览器不直接连接 MCP，也看不到 Token。

## 1. Ombre Brain

### 推荐：单独部署到 Render

1. Fork [P0luz/Ombre-Brain](https://github.com/P0luz/Ombre-Brain)。
2. 使用上游 README 的 “Deploy to Render” 按钮或其 `render.yaml`。
3. 必须选带持久磁盘的付费实例；上游 Blueprint 会把磁盘挂到 `/opt/render/project/src/buckets`。
4. 至少设置 `OMBRE_COMPRESS_API_KEY`，按你的模型服务补充 `OMBRE_COMPRESS_BASE_URL`、`OMBRE_COMPRESS_MODEL` 和可选的 embedding 配置。
5. 进入 Ombre Dashboard 完成 onboarding，并给 Dashboard 设置密码。

### 给这个家使用静态 Token

自定义服务端客户端最适合静态 Token：

```dotenv
OMBRE_MCP_AUTH_MODE=token
OMBRE_MCP_TOKEN=请生成一串足够长的随机密钥
OMBRE_TRANSPORT=streamable-http
```

重启 Ombre Brain。然后在本项目的 Render 环境变量填写：

```dotenv
OMBRE_BRAIN_ENABLED=true
OMBRE_BRAIN_MCP_URL=https://你的-ombre-服务.onrender.com/mcp
OMBRE_BRAIN_ACCESS_TOKEN=与OMBRE_MCP_TOKEN相同
```

不要把 Token 拼在 URL 查询参数里。应用会用：

```http
Authorization: Bearer <token>
```

本地同机测试可把 Ombre 只监听 `127.0.0.1` 并关闭鉴权，但绝不能把免鉴权 `/mcp` 暴露到公网。

### 检查

打开本应用“设置 → API 与连接”。应显示 Ombre Brain 已连接。再在“记忆系统”里：

1. 写入一条测试记忆；
2. 用其中一个关键词搜索；
3. 正常聊天一轮，确认聊天不报记忆连接警告。

应用会使用 `breath`、`breath_search`、`hold`、`grow` 和 `pulse`；其余 Ombre 工具仍留给未来的 AI 工具调用。

## 2. co-reading-mcp

### 本机或 VPS

```bash
git clone https://github.com/idleprocesscc/co-reading-mcp.git
cd co-reading-mcp
npm install
READING_MCP_DATA_DIR=./data MCP_AUTH_TOKEN="换成随机密钥" npm run start:sse
```

Windows PowerShell：

```powershell
$env:READING_MCP_DATA_DIR="$PWD\data"
$env:MCP_AUTH_TOKEN="换成随机密钥"
npm run start:sse
```

同一个进程提供：

- 阅读器：`http://localhost:3100/`
- REST：`http://localhost:3100/api/*`
- MCP：`http://localhost:3100/mcp`
- 健康检查：`http://localhost:3100/health`

公网部署必须使用 HTTPS 和 `MCP_AUTH_TOKEN`。

### 部署到 Render

从上游 GitHub 仓库新建一个 Web Service：

| 项目 | 值 |
| --- | --- |
| Runtime | Node |
| Build Command | `npm install` |
| Start Command | `npm run start:sse` |
| Health Check | `/health` |
| `READING_MCP_DATA_DIR` | `/var/data` |
| `MCP_AUTH_TOKEN` | 随机长密钥 |
| `MCP_MAX_BODY_BYTES` | `25000000` |
| `READING_IMPORT_MAX_BYTES` | `25000000` |

给服务添加持久磁盘，挂载到 `/var/data`。没有磁盘时，导入的书、进度和批注会在实例重建后丢失。

然后在主应用 Render 环境变量填写：

```dotenv
CO_READING_URL=https://你的共读服务.onrender.com
CO_READING_MCP_URL=https://你的共读服务.onrender.com/mcp
CO_READING_ACCESS_TOKEN=与MCP_AUTH_TOKEN相同
```

`CO_READING_URL` 用于书架、章节、搜索等 REST 操作；`CO_READING_MCP_URL` 用于导入书籍和 MCP 工具。只配 MCP 地址也能工作，但返回内容会以文本结果为主，界面体验不如同时配置 REST。

### 检查

1. 本应用设置页应显示共读已连接及工具数。
2. 进入共读室，导入一个小的 TXT 或 EPUB。
3. 打开章节、搜索一句原文、写一条批注并标记已读。
4. 点“带去聊天”，确认 AI 能看到当前段落。

## 3. 如果还要给其他 AI 客户端添加 MCP

支持自定义 Header 的 Streamable HTTP 客户端可使用类似配置：

```json
{
  "mcpServers": {
    "ombre-brain": {
      "type": "streamableHttp",
      "url": "https://ombre.example.com/mcp",
      "headers": {
        "Authorization": "Bearer <OMBRE_MCP_TOKEN>"
      }
    },
    "co-reading": {
      "type": "streamableHttp",
      "url": "https://reading.example.com/mcp",
      "headers": {
        "Authorization": "Bearer <MCP_AUTH_TOKEN>"
      }
    }
  }
}
```

不同客户端可能把 `url` 叫作 `baseUrl`，或把类型写成 `http`。以该客户端自己的配置格式为准。不要把生产 Token 提交到 GitHub。

## 4. 常见故障

| 现象 | 检查 |
| --- | --- |
| 401 / 403 | Token 是否一致；Ombre 是否选了 `token` 模式；是否误把 OAuth 与 Token 混用 |
| Ombre 工具为 0 | URL 是否以 `/mcp` 结尾；Transport 是否为 `streamable-http` |
| 共读书架可开、批注失败 | `CO_READING_MCP_URL` 和 Token 是否配置 |
| Render 重启后记忆/书籍消失 | 持久磁盘与挂载路径是否正确 |
| 导入大书失败 | 文件是否超过本应用 12 MB；MCP body/import 上限是否足够 |
| 主应用仍显示旧配置 | 修改 Render Environment 后是否重新部署/重启 |
