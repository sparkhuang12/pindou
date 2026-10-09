# 豆格架构守则

本文是项目后续开发的强制约束。任何新增功能、修复或重构都必须保持“独立前端 + 模块化 API + 异步 Worker + 可复用图像核心”的边界；如果确实需要改变边界，必须先修改本文、说明迁移方案，并补齐架构和回归测试。

## 1. 顶层结构

```text
frontend/                 浏览器应用与 Nginx 配置
backend/
  api/                    FastAPI 路由：鉴权、校验、HTTP 响应
  services/               业务编排与任务执行，可被 API/Worker 复用
  config.py               环境配置
  dependencies.py         鉴权和请求依赖
  middleware.py           请求审计等横切逻辑
  serializers.py          API 输出映射
  state.py                Store 生命周期
  worker.py               独立任务消费者进程
pindou/                   与 Web 框架无关的图像算法、CLI 和持久化实现
verification/             CLI、API、Worker 与架构约束验证
```

部署时必须是四个独立职责：

```text
浏览器 -> frontend(Nginx) -> api(FastAPI) -> PostgreSQL
                                 |
                                 v
                         processing_jobs 队列
                                 |
                                 v
                              worker -> 共享图片卷 / 模型 API
```

## 2. 依赖方向

允许的依赖方向只有：

```text
frontend -> HTTP /api
backend.api -> backend.services / backend.dependencies / backend.serializers
backend.worker -> backend.services
backend.services -> pindou 图像核心 / Store
pindou CLI -> pindou 图像核心
```

强制规则：

1. `frontend/` 不得依赖 Python 模板渲染，不得读取数据库或文件卷，只能调用 `/api`。
2. `backend/api/` 只负责 HTTP、Pydantic 校验、权限和业务服务调用。新的 OpenCV、量化、模型调用或长耗时逻辑不得写进路由。
3. `backend/services/` 不得导入 FastAPI，不得返回 `Response` 或抛出 `HTTPException`。
4. `backend/worker.py` 只消费任务并调用服务；不得复制路由逻辑。
5. `pindou/` 图像算法不得反向导入 `backend` 或 FastAPI。`pindou/web.py` 仅是短期兼容入口，不得继续增加路由。
6. 路由和 Worker 不得直接拼写 SQL；所有持久化通过 `Store`。图片二进制保存在受控文件卷，数据库只保存路径与元数据。

## 3. 异步任务协议

抠图、抠图轮廓人工修正、像素化、轮廓方格生成、上色保存、AI 配色和最终图纸生成都属于后台任务。新增的 CPU 密集、模型调用或预计超过 500 ms 的工作也必须进入 Worker。

标准流程：

1. API 校验用户、项目和前置资产。
2. 在 `processing_jobs` 写入 `queued` 任务，立即返回 HTTP `202` 和任务 ID。
3. Worker 原子抢占任务，状态改为 `running`，执行 `backend.services`。
4. 成功写入产物和结构化输出并标记 `completed`；失败保存可展示的错误并标记 `failed`。
5. 前端轮询 `GET /api/jobs/{job_id}`，完成后使用统一结果更新界面。

任务状态只允许正常方向：

```text
queued -> running -> completed
                  -> failed

Worker 会定期写入 `last_heartbeat_at`。异常任务只在心跳超时且未达到最大尝试次数时重新排队；运行中任务通过 `cancel_requested` 协作取消，不能因为取消或项目已删除而自动重试。
```

Worker 启动时会将超过 `PINDOU_WORKER_STALE_SECONDS` 的异常中断任务重新排队。任务实现应尽量幂等：使用固定项目产物路径并在全部计算成功后更新项目记录。

`PINDOU_TASK_MODE=eager` 只用于本地开发和自动化测试。Docker、测试环境和生产环境必须使用 `worker`，并运行独立 Worker 容器。

## 4. API、权限和数据规则

- 普通用户资源查询必须带当前 `user_id`，跨用户资源统一返回 404 或 403。
- 管理接口必须位于 `/api/admin` 并依赖 `CurrentAdmin`。
- 用户图片只能通过受鉴权资产接口读取，禁止由 Nginx 直接暴露文件卷。
- 密码、Cookie、数据库凭据、模型 API Key 和图片 Base64 禁止进入审计日志或任务输入输出。
- 处理参数、提示词和模型名称可以进入任务记录，但新增字段前要判断是否包含个人敏感信息。
- API 的破坏性变更必须更新前端调用、README、本文和验证脚本；优先保持现有路径兼容。
- 项目支持重命名、复制、删除时取消关联任务；账户支持改密、JSON 数据导出和密码确认注销。账户注销会删除其项目文件，管理员账户不能自助注销。
- `/api/projects/{id}/mask/refine` 接收归一化笔刷点并入队 `refine_mask` 任务；处理结果会重置该项目的后续像素化、上色和图纸资产。

## 5. 数据库变更

当前 `Store` 兼容 PostgreSQL 与本地 SQLite。新增字段或表时必须同时完成：

1. 更新 SQLAlchemy 表定义和索引。
2. 为已存在数据库提供幂等迁移逻辑。
3. 更新 `docs/database-and-deployment.md`。
4. 同时验证 SQLite 与 Docker PostgreSQL。

当迁移复杂度超过单字段补充时，应引入 Alembic；不得在生产说明中要求用户手工修改表。

## 6. 完成标准

每次涉及架构或处理流程的修改至少运行：

```bash
python3 verification/architecture_check.py
python3 verification/smoke_test.py
python3 verification/web_smoke_test.py
python3 verification/worker_smoke_test.py
python3 verification/docker_e2e_test.py  # Compose 启动后
python3 -m ruff check backend pindou verification
node --check frontend/app.js
node --check frontend/admin.js
docker compose --env-file .env.example config --quiet
```

涉及容器、数据库或 Worker 的修改，还必须构建镜像并进行一次 PostgreSQL + API + Worker + Frontend 的 Compose 健康检查。
