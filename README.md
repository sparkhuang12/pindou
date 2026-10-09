# 豆格 Pindou

豆格把普通图片处理成可直接照着制作的拼豆色号图。项目同时提供浏览器工作台和命令行工具：

- 邮箱注册、登录、个人资料和项目历史。
- 用户用量统计、站内留言，以及管理员回复状态。
- PNG、JPG、WebP 上传，单张上限 20 MB。
- 在画布中拖动矩形框选主体，通过 OpenCV GrabCut 抠图。
- 抠图后可用保留/擦除笔刷人工修正轮廓，修正会自动重置后续旧结果。
- 无需联网的本地像素画处理，以及可选的远程图片模型接口。
- 把主体转换为锁定轮廓的方格画布，支持画笔、区域填充、橡皮、吸管、撤销与重做。
- 从 221 个色号中手动选色，或用无需联网的连贯色块算法随机配色。
- 可选 AI 一键配色。模型只提供颜色，主体轮廓和方格位置仍由本地程序锁定。
- 自定义 8-100 格宽高、边缘阈值、留白、断点连接和手头可用色号。
- 使用内置 221 色色板生成带编号图纸、色块预览和用量统计。
- 导出 PNG、JSON 和 CSV。
- 支持项目重命名、复制、删除、处理任务取消，以及账户改密、JSON 数据导出和密码确认注销。
- 内置项目数、存储量、每日任务数、并发任务数限制与基础请求限流。
- 独立管理员控制台，可查看和筛选用户、历史图片、操作审计、处理任务输入输出及用户消息。
- 响应式浅色/深色界面，桌面端优先，移动端自动切换为单列流程。

## 启动 Web 工作台

完整工作台现在采用前后端分离与独立 Worker，推荐直接使用下方 Docker Compose 启动。仅调试 API 或算法时，可以使用本地 eager 模式：

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
export PINDOU_TASK_MODE=eager
uvicorn backend.main:app --reload
```

该方式只启动 API，接口文档位于 <http://127.0.0.1:8000/docs>；前端不再由 Python 进程提供。首次启动会在 `data/` 中创建 SQLite 数据库、会话密钥和账户隔离的项目文件。

```bash
export PINDOU_DATA_DIR=/path/to/persistent/data
export PINDOU_SESSION_SECRET='replace-with-a-long-random-secret'
export PINDOU_TASK_MODE=eager
uvicorn backend.main:app --reload
```

本地未设置 `PINDOU_DATABASE_URL` 时使用 SQLite；设置后可连接 PostgreSQL。eager 模式会在 API 进程内立即执行任务，只允许本地开发和测试使用。Docker 和生产环境固定使用独立 Worker。

## Docker + PostgreSQL 部署

项目已提供独立 Nginx 前端、非 root FastAPI API、异步 Worker、PostgreSQL 16、健康检查、自动重启和两个独立持久化卷。先复制并修改环境文件：

```bash
cp .env.example .env
docker compose up --build -d
docker compose ps
```

打开 <http://127.0.0.1:8000>，管理员使用 `.env` 中的 `PINDOU_ADMIN_EMAIL` 和 `PINDOU_ADMIN_PASSWORD` 登录后，从顶部“管理端”进入 `/admin`。启动时若邮箱不存在会创建管理员；若已存在则只提升其角色，不会用环境变量覆盖已有密码。

生产部署至少要替换数据库密码、管理员密码和会话密钥，并启用 HTTPS：

```dotenv
PINDOU_COOKIE_SECURE=1
PINDOU_TRUST_PROXY=1
```

数据库和图片文件必须成对备份。详细的数据表、隐私边界、升级与备份恢复说明见 [数据库与部署说明](docs/database-and-deployment.md)。

常用运维命令：

```bash
docker compose logs -f api worker frontend
docker compose restart api worker frontend
docker compose down
```

`docker compose down` 会保留命名卷；不要附加 `-v`，除非明确要永久删除数据库和全部历史图片。

## 用户端与管理员端

普通用户只能读取自己的项目、原图、处理中间文件和导出结果，可以在个人资料中查看项目数、存储量、累计拼豆数及留言记录。

管理员控制台提供：

- 用户搜索、角色管理、账号停用及单个用户详情。
- 全站历史图片及管理员专用受鉴权预览地址。
- 请求审计记录，包括行为、状态、IP、浏览器、耗时和资源标识。
- 抠图、像素化、方格画、AI 配色和图纸生成任务的结构化输入、输出、模型与耗时。
- 用户消息的未读、处理中和已解决状态，以及管理员备注。

密码、会话 Cookie、模型 API 密钥和图片 Base64 不写入审计记录。管理员能够看到用户的处理参数、提示词和产物，正式运营时应在隐私政策中明确告知并设置数据保留期限。

## 项目架构

项目结构和后续修改规则以 [ARCHITECTURE.md](ARCHITECTURE.md) 为准。`AGENTS.md` 会要求后续自动化开发先读取这份文档。

```text
frontend/Nginx -> backend API -> PostgreSQL processing_jobs
                                      |
                                      v
                              independent Worker
                                      |
                                      v
                              image volume / model API
```

抠图、轮廓修正、像素化、轮廓生成、上色保存、AI 配色和图纸生成都会先返回 `202` 任务，再由前端轮询任务状态。API 不再执行耗时图片处理；本地 eager 模式为了测试会直接返回完成结果。

## 图片模型接口

本地像素画与随机配色始终可用。若要启用“模型精修”和“AI 一键配色”，配置一个图片模型网关：

```bash
export PINDOU_MODEL_API_URL=https://your-gateway.example.com/image/edit
export PINDOU_MODEL_API_KEY=your-secret
export PINDOU_MODEL_NAME=pixel-art-editor
```

豆格向该地址发送 JSON：

```json
{
  "model": "pixel-art-editor",
  "prompt": "处理要求",
  "image": "data:image/png;base64,..."
}
```

网关响应可使用以下任一形式：

```json
{"image_base64": "..."}
```

```json
{"data": [{"b64_json": "..."}]}
```

```json
{"data": [{"url": "https://.../result.png"}]}
```

API 密钥只在服务端读取，不会下发到浏览器。

AI 配色会先把当前主体渲染成方格线稿发送给同一网关，再将返回图片的颜色采样到原有轮廓中。模型输出不会新增或删除方格。未配置网关时，AI 配色入口会保留在界面中但处于禁用状态。

## 上色工作台

完成抠图后即可直接生成轮廓方格，也可以先做像素化再生成。宽高格数会同时用于上色画布和最终图纸。

- 画笔支持拖动连续上色；填充会处理相邻且颜色相同的区域。
- 橡皮只清除当前颜色，不破坏保存的主体轮廓；吸管可从画布取色。
- “清空颜色”可得到纯线稿，“随机配色”会在浏览器中按相邻区域计算连贯色块。
- 自定义颜色在生成图纸时会自动匹配到最近的可用色号。如果填写了“手头已有色号”，匹配、随机配色和 AI 配色都会限制在这些色号内。
- 上色数据保存为项目私有的 `coloring.json`，预览保存为透明背景 `painted.png`。修改上色会让旧图纸失效，避免导出过期结果。

## 账户与任务安全

个人资料中的账户安全区域支持密码修改、账户 JSON 导出和账户注销。密码修改会让旧登录会话失效；管理员不能自助注销。处理中的任务会显示取消按钮，Worker 会通过心跳检测异常任务并在有限次数内恢复，用户主动取消和项目删除不会重试。

账户限制通过 `.env` 配置：`PINDOU_MAX_PROJECTS_PER_USER`、`PINDOU_MAX_STORAGE_BYTES_PER_USER`、`PINDOU_MAX_JOBS_PER_DAY`、`PINDOU_MAX_CONCURRENT_JOBS_PER_USER` 和 `PINDOU_MAX_JOB_ATTEMPTS`。进程内限流适合单 API 实例；多实例部署应在网关或 Redis 层做共享限流。

## 命令行用法

原有离线管线保持兼容：

```bash
python3 -m pindou generate input.png --output-dir outputs/demo
```

典型输出文件：

- `pattern.png`：带坐标、色号和图例的最终图纸。
- `preview.png`：纯颜色拼豆预览。
- `mask.png`：主体蒙版。
- `matrix.csv`：色号矩阵，空白格为空。
- `pattern.json`：矩阵、色号用量和调色板元数据。

### 使用实际 221 色色卡

内置色板是近似的 A/B/C/D/E/F/G/H/M 221 色集合。需要精确匹配时，可从色卡图片提取颜色：

```bash
python3 -m pindou extract-palette color_chart.jpg --output palette.json
python3 -m pindou generate input.png --palette palette.json --output-dir outputs/demo
```

也可以生成时直接采样：

```bash
python3 -m pindou generate input.png \
  --palette-chart color_chart.jpg \
  --output-dir outputs/demo
```

### 常用参数

```bash
python3 -m pindou generate input.png \
  --size 50x60 \
  --coverage 0.32 \
  --padding 0.04 \
  --sample-size 14 \
  --mask-method auto \
  --cell-size 28 \
  --output-dir outputs/demo
```

- `--size`：输出格子尺寸，支持 `50x60`、`50*60` 或 `50,60`。
- `--cols` / `--width`：只覆盖列数。
- `--rows` / `--height`：只覆盖行数。
- `--coverage`：较低值保留更多边缘格，较高值产生更干净的轮廓。
- `--sample-size`：每个拼豆格的超采样尺寸。
- `--padding`：主体在格子中的留白比例。
- `--mask-method`：`auto`、`alpha`、`grabcut` 或 `background`。

## 验证

```bash
python3 verification/smoke_test.py
python3 verification/web_smoke_test.py
python3 verification/worker_smoke_test.py
python3 verification/architecture_check.py
# Compose 启动后：
python3 verification/docker_e2e_test.py
```

Web 验证覆盖注册登录、上传、框选抠图、人工修正轮廓、本地像素化、轮廓方格创建、上色保存、限定已有色号、图纸生成、文件下载、资料更新、历史统计、留言、账户间项目隔离、管理员权限、操作审计、处理任务输入输出、账号停用和安全删除。Worker 验证单独覆盖入队、原子抢占、执行和轮询协议。

## 主要代码

- `frontend/`：独立浏览器应用、Nginx 静态服务与 API 反向代理。
- `backend/api/`：按账户、项目、任务、管理员和系统拆分的 FastAPI 路由。
- `backend/services/`：API 与 Worker 共用的任务编排和图像处理服务。
- `backend/worker.py`：独立异步任务消费者。
- `pindou/web.py`：旧启动方式的兼容入口，不再包含业务路由。
- `pindou/storage.py`：SQLAlchemy 数据层，支持本地 SQLite 和部署环境 PostgreSQL。
- `pindou/stylize.py`：本地像素画及模型网关适配。
- `pindou/coloring.py`：轮廓方格、上色校验、AI 颜色采样和图纸转换。
- `pindou/segmentation.py`：自动分割与矩形选区 GrabCut。
- `pindou/quantize.py`：格子采样及色板匹配。
- `pindou/render.py`：图纸、预览和数据导出。
- `docker-compose.yml` / `Dockerfile`：前端、API、Worker、PostgreSQL 与持久化卷部署。
