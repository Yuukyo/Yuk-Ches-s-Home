# Render + Supabase 部署教程

## 一、上传 GitHub

把整个 `Yuk-Ches-Home` 目录作为仓库根目录：

```bash
git init
git add .
git commit -m "Initial home"
git branch -M main
git remote add origin https://github.com/你的用户名/你的仓库.git
git push -u origin main
```

`.env`、`instance/` 和本地上传目录已在 `.gitignore` 中，提交前仍请用 GitHub 搜索确认没有 API Key。

## 二、Supabase

1. 新建 Supabase Project。
2. 打开 SQL Editor，完整执行 `sql/supabase.sql`。
3. 在 Project Settings / API 中取得 Project URL 与服务端 Secret key。兼容旧项目的 `service_role` JWT，也可使用新的 `sb_secret_...`。
4. 不要使用 `anon` / publishable key；也不要把 Secret 放到前端。
5. 确认 Storage 中有私有 bucket `home-attachments`。

主应用需要：

```dotenv
SUPABASE_URL=https://xxxx.supabase.co
SUPABASE_SERVICE_ROLE_KEY=你的服务端Secret
SUPABASE_STORAGE_BUCKET=home-attachments
```

SQL 已启用 RLS，且没有给浏览器身份创建公开 policy；数据库只由 Render 后端访问。

## 三、Render 主应用

1. Render Dashboard → New → Blueprint。
2. 连接 GitHub 仓库；Render 会读取根目录的 `render.yaml`。
3. 填写所有标记为 `sync: false` 的变量。
4. 部署完成后先访问 `/api/health`，应返回 `{"ok": true, ...}`。
5. 再打开首页，用 `APP_PASSWORD` 登录。

建议先配置：

```dotenv
APP_PASSWORD=家庭访问密码
USER_NAME=你的名字
AI_NAME=AI的名字
API_URL=https://你的接口
API_KEY=...
API_MODEL=...
SUPABASE_URL=...
SUPABASE_SERVICE_ROLE_KEY=...
CRON_SECRET=另一串随机长密钥
```

再按 `MCP_SETUP.md` 接 Ombre Brain 与共读。主动消息默认关闭，全部验证后再把 `PROACTIVE_ENABLED` 改为 `true`，或在设置页开启。

## 四、定时任务

仓库带有 `.github/workflows/home-cron.yml`，用于：

- 每天北京时间 00:00–06:00 每小时检查一次，并在随机目标小时生成 AI 每日一句；
- 08:00、12:00、18:00、22:00 评估奖励；
- 22:00 结转购物基金；
- 检查是否应该发送主动消息。

在 GitHub 仓库 Settings → Secrets and variables → Actions 添加：

| 类型 | 名称 | 值 |
| --- | --- | --- |
| Variable | `HOME_URL` | `https://你的主应用.onrender.com` |
| Secret | `CRON_SECRET` | 与 Render 中相同 |

先在 Actions 页手动运行一次 `Home scheduled tick`。成功返回 200 后，再等待计划任务。

也可以改用其他定时器，向以下地址发送 POST：

```http
POST https://你的主应用.onrender.com/api/cron/tick
Authorization: Bearer <CRON_SECRET>
```

GitHub Actions 的计划时间可能有几分钟延迟；奖励逻辑按应用时区和已结算标记幂等处理，不会因重复调用无限加分。

## 五、Render 免费层要注意

- 免费 Web Service 长时间无访问会休眠，计划任务第一次唤醒可能较慢。
- 主应用使用 Supabase 后，本地文件系统是否重建不会影响消息和附件；没有 Supabase 时，SQLite 和本地附件会丢失，所以线上不要依赖本地 fallback。
- Ombre Brain 必须使用持久磁盘；免费无盘实例不适合长期记忆。
- co-reading-mcp 也建议挂盘，否则书籍、阅读进度与批注无法保证持久。

## 六、上线验收清单

- [ ] 家庭密码错误时无法进入 API
- [ ] 聊天 API 正常，手机端发送/换行正常
- [ ] OVO JSON 先用“追加”导入一份备份
- [ ] 消息编辑、引用、删除、重生成与墓地正常
- [ ] Supabase 刷新后消息、记录、附件仍存在
- [ ] Ombre 手动写入后能搜索到
- [ ] 共读能导入、阅读、批注、标记已读
- [ ] 生图（如启用）结果能在画廊打开
- [ ] 手动运行 GitHub Actions 返回 200
- [ ] 浏览器开发者工具中看不到任何 API/MCP/数据库密钥

## 七、备份

- 定期从本应用导出聊天 JSON。
- 在 Supabase 启用合适的数据库备份策略。
- 从 Ombre Dashboard 导出记忆备份，或配置其 GitHub 同步。
- 备份 co-reading 的整个 `READING_MCP_DATA_DIR`。

