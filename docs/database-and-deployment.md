# 数据库与部署说明

## 存储结构

豆格把结构化数据与图片文件分开保存：

- PostgreSQL（Docker 默认）保存账户、权限、项目元数据、审计日志、处理任务与用户消息。
- `pindou-data` 卷保存原图、蒙版、抠图、像素图、上色 JSON、预览和最终导出文件。
- 本地开发未设置 `PINDOU_DATABASE_URL` 时，结构化数据保存在 `data/pindou.sqlite3`，图片仍位于 `data/projects/`。

数据库中的图片字段是服务端受控路径。浏览器不能直接访问存储目录，所有图片都经过登录、项目所有权或管理员权限校验。

## 数据表规划

### `users`

保存邮箱、PBKDF2-SHA256 密码摘要、昵称、简介、角色、账号状态、偏好设置、邮箱验证预留字段、最后登录时间/IP、登录次数、会话版本及创建更新时间。密码修改会递增会话版本，使旧 Cookie 立即失效。角色为 `user` 或 `admin`，状态为 `active` 或 `disabled`。

### `projects`

保存项目归属、名称、处理状态、各类资产路径、原文件名和 MIME、原图尺寸/体积、项目总占用、框选参数、处理设置、格子宽高、拼豆数、使用颜色数及时间戳。删除用户时其项目记录和受控文件均应随业务流程清理。

### `activity_logs`

保存请求 ID、用户、动作、分类、成功/失败状态、方法、路径、资源标识、IP、User-Agent、脱敏后的输入输出摘要、错误和耗时。中间件仅记录查询参数与 HTTP 状态，业务事件记录必要的结构化摘要。

### `processing_jobs`

该表同时是持久化任务队列，保存抠图、抠图修正、像素化、方格画生成、上色保存、AI 配色和图纸生成的用户、项目、操作、执行方式、模型名称、`queued/running/completed/failed` 状态、结构化输入输出、错误、耗时、尝试次数、Worker 标识、抢占时间、心跳、取消标记及开始结束时间。管理员控制台的“处理输入输出”来源于此表。

### `user_messages`

保存用户提交的标题和内容、`open` / `read` / `resolved` 状态、管理员备注、提交/更新时间与解决时间。

## 隐私与日志边界

系统不会把以下内容写入审计日志：

- 明文密码或密码字段；
- 登录 Cookie、会话签名和模型 API 密钥；
- 图片 Base64 或上传文件二进制；
- 数据库连接密码。

处理任务会保存用户的方格参数、选区、色号范围和模型提示词，管理员也能查看用户图片。对外运营前应增加隐私政策、数据导出/注销流程和自动保留期限。建议操作日志保留 90 天、已完成处理任务保留 180 天；具体期限应按业务及当地法规调整。

当前已提供账户 JSON 导出、密码修改和密码确认注销。导出包含账户、项目元数据、处理设置、选区和资产是否存在，不包含图片二进制；正式运营仍应补充异步 ZIP 导出、邮箱验证、密码找回和按法规执行的删除/保留策略。

应用层还提供进程内滑动窗口限流、每用户项目数/存储量/每日任务数/并发任务数限制。多 API 副本部署时，限流应迁移到网关或 Redis；当前实现只适合单 API 实例或低流量部署。

## Docker 部署

1. 从示例生成配置并替换所有占位值：

   ```bash
   cp .env.example .env
   ```

2. `POSTGRES_PASSWORD` 建议使用只含 URL 安全字符的随机值；如包含 `@`、`:`、`/` 等字符，需要先做 URL 百分号编码。

3. 启动并检查状态：

   ```bash
   docker compose up --build -d
   docker compose ps
   docker compose logs --tail=100 api worker frontend
   ```

4. 在 HTTPS 反向代理后部署时设置：

   ```dotenv
   PINDOU_COOKIE_SECURE=1
   PINDOU_TRUST_PROXY=1
   ```

   Compose 中 API 只接受内部 Nginx 代理访问并信任其 `X-Forwarded-For`；不要把 API 容器端口单独暴露到公网。

## 服务职责

- `frontend`：只提供 HTML/CSS/JavaScript，并把 `/api` 代理到 API。
- `api`：鉴权、参数验证、数据库查询及后台任务入队，不执行耗时图像处理。
- `worker`：原子抢占 `processing_jobs` 中的任务，读写共享图片卷并调用可选模型 API。
- `database`：PostgreSQL 结构化数据与持久化任务队列。

Worker 每隔轮询周期检查心跳，超过 `PINDOU_WORKER_STALE_SECONDS` 的 `running` 任务会在达到最大尝试次数前恢复为 `queued`。可以增加 Worker 副本提升吞吐；同一任务只能被一个 Worker 抢占。用户取消或删除项目产生的任务不会重试。

## 管理员初始化

`PINDOU_ADMIN_EMAIL`、`PINDOU_ADMIN_PASSWORD` 和 `PINDOU_ADMIN_NAME` 用于首次启动初始化。邮箱不存在时创建账号；已存在的普通账号会提升为启用的管理员，但已有管理员不会被重新激活或覆盖密码。初始化成功后仍需保留管理员邮箱配置；如移除密码配置，应用不会在后续启动时执行管理员引导。系统阻止停用或降级最后一个启用管理员。

## 备份与恢复

数据库与文件卷必须在同一备份窗口内成对保存，否则项目记录可能指向不存在的文件。

导出 PostgreSQL：

```bash
docker compose exec -T database pg_dump -U pindou -d pindou -Fc > pindou-db.dump
```

导出图片卷：

```bash
docker run --rm -v pindou_pindou-data:/source:ro -v "$PWD":/backup alpine \
  tar -czf /backup/pindou-data.tar.gz -C /source .
```

恢复前先停止应用写入，恢复数据库和文件卷后再启动应用。不要只备份 PostgreSQL。

## 升级策略

当前启动逻辑会创建新表，并为早期 SQLite 数据库幂等补充兼容字段，包括会话版本、任务心跳和取消标记。生产 PostgreSQL 的后续复杂结构变更应引入 Alembic 版本迁移，并在升级前进行数据库与图片卷快照。多主机部署时应把共享图片卷换成对象存储；API 与 Worker 不得使用各自独立的本地图片目录。
