# Team Manage：GPT Team 服务台与兑换码管理系统

Team Manage 是一个基于 **FastAPI + SQLite + Jinja2 + 原生 JavaScript** 的 ChatGPT Team 管理后台与前台服务台。项目围绕 Team 账号导入、兑换码发放、用户自动拉人、质保订单、号池、库存预警、前台内容配置和本地导入工具展开，适合以 Docker 或本机开发模式部署。

> 本项目处于开发阶段；生产部署前务必修改默认密钥、管理员密码，并确保数据目录和 `.env` 不进入版本库。

---

## 目录

- [核心能力](#核心能力)
- [技术栈](#技术栈)
- [快速启动](#快速启动)
- [常用命令](#常用命令)
- [项目结构](#项目结构)
- [运行时架构](#运行时架构)
- [核心业务流程](#核心业务流程)
- [页面与接口地图](#页面与接口地图)
- [配置说明](#配置说明)
- [数据库模型概览](#数据库模型概览)
- [测试与验证](#测试与验证)
- [部署要点](#部署要点)
- [安全注意事项](#安全注意事项)
- [故障排查](#故障排查)

---

## 核心能力

### 前台用户能力

- 兑换码服务台：用户输入邮箱与兑换码，系统校验后提交后台拉人队列。
- 质保服务台：支持按邮箱查询质保订单、刷新订单对应 Team 状态并提交质保补发。
- 质保名单判定模式：可按邮箱命中/未命中展示不同富文本模板，并可对接 Sub2API 自动生成订阅兑换码。
- 绑定邮箱查询：用户可查询兑换码当前绑定邮箱状态；前台自助撤销接口已保留但默认拒绝。
- 购买入口、公告、客服模块：后台可配置前台购买链接、公告通知、客服二维码/链接/文字。
- Codex API 登录教程页：`/codex-guide` 提供独立教程页面与静态素材。
- 移动端适配：前台页面使用响应式 CSS，适配手机访问与触控操作。

### 管理员能力

- Team 管理：单个/批量导入 Team，支持 AT / RT / Session Token / Client ID，自动解析邮箱与 Account ID。
- 统一控制台 Team 池：普通 Team 统一进入控制台池；开启独立号池后，前台兑换优先使用号池 Team。
- Team 操作：刷新信息、批量刷新、批量删除、批量设置最大人数、开启设备代码身份验证、成员列表、拉人、踢人、撤销邀请。
- 兑换码管理：单个/批量生成、普通/质保兑换码、过期时间、质保时长（支持秒级）、质保次数、批量编辑、批量删除、文本/Excel 导出。
- 使用记录：按邮箱、兑换码、Team、时间等维度查询；支持后台撤回记录。
- 质保管理：质保邮箱列表、质保提交记录、质保超级码、质保名单判定配置、Sub2API 兑换码生成记录。
- 邮箱白名单：全局邮箱白名单用于自动清理保护，可与质保邮箱列表同步。
- 子管理员：总管理员可创建导入型子管理员；子管理员只能访问导入页和自己的导入概览。
- 自动化：Team 自动刷新、质保到期自动踢出、库存预警 Webhook、前台拉人队列。
- 本地工具：`/local-tools`、`/local-tools/records`、`/local-tools/email-accounts` 提供浏览器本地数据处理与验证码页面读取辅助。

### 集成能力

- 库存预警 Webhook：当可用车位低于阈值时向第三方系统发送补货通知。
- API Key 导入：第三方系统可通过 `X-API-Key` 调用 `/admin/teams/import` 自动导入 Team。
- Sub2API：质保名单判定命中后可调用 Sub2API Admin API 创建订阅兑换码。

---

## 技术栈

| 层级 | 组件 |
| --- | --- |
| Web 框架 | FastAPI、Uvicorn、Starlette SessionMiddleware |
| 数据库 | SQLite、SQLAlchemy 2.x async、aiosqlite、WAL 模式 |
| 模板与静态资源 | Jinja2、HTML、CSS、原生 JavaScript |
| HTTP 客户端 | curl-cffi（ChatGPT API 浏览器指纹）、httpx（Webhook / 本地工具 / Sub2API） |
| 鉴权 | Session 登录、bcrypt 密码哈希、可选 `X-API-Key` |
| 安全与内容处理 | cryptography / Fernet token 加密、PyJWT、bleach 富文本净化 |
| 导出 | xlsxwriter |
| 容器化 | Docker、Docker Compose |
| 测试 | pytest + FastAPI/TestClient/服务层单元测试 |

---

## 快速启动

### 方式一：Docker 部署（推荐）

```bash
git clone https://github.com/Saksk-IT/team-manage.git
cd team-manage
cp .env.example .env
# 按需编辑 .env，至少生产环境要修改 SECRET_KEY 和 ADMIN_PASSWORD
docker compose up -d --build
```

访问：

- 前台服务台：<http://localhost:8008/>
- 管理员登录：<http://localhost:8008/login>
- 管理后台：<http://localhost:8008/admin>
- 健康检查：<http://localhost:8008/health>

Docker Compose 默认将端口绑定到 `127.0.0.1:${APP_PORT:-8008}`，并把数据库与上传文件持久化到 `./data`。

### 方式二：Docker 本机开发热重载

```bash
git clone https://github.com/Saksk-IT/team-manage.git
cd team-manage
cp .env.example .env
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build
```

查看日志：

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml logs -f
```

停止：

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml down
```

开发覆盖文件会把项目目录挂载进容器，并使用 `uvicorn --reload` 监听 `app/` 目录。

### 方式三：本机 Python 开发

```bash
git clone https://github.com/Saksk-IT/team-manage.git
cd team-manage
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python init_db.py
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8008
```

> 本机开发推荐把 `.env` 中的 `DATABASE_URL` 改为 `sqlite+aiosqlite:///./data/team_manage.db`，以便和 Docker 的 `./data` 持久化目录保持一致。

### 默认管理员

- 用户名：`admin`
- 初始密码：`.env` 中的 `ADMIN_PASSWORD`，示例默认为 `admin123`

首次登录后请立即在后台“系统设置”中修改密码。

---

## 常用命令

```bash
# 查看服务日志
docker compose logs -f --tail=100

# 停止服务
docker compose down

# 更新并重建
git pull
docker compose up -d --build

# 检查 Compose 配置
docker compose config

# 本机运行完整测试
pytest

# 只运行某个测试文件
pytest tests/test_token_parser.py

# Python 语法/导入级检查
python -m compileall app tests
```

更多部署与线上排查命令见 [DEPLOY_COMMANDS.md](DEPLOY_COMMANDS.md)。

---

## 项目结构

```text
team-manage/
├── app/
│   ├── main.py                         # FastAPI 入口、生命周期、路由注册、静态资源挂载
│   ├── config.py                       # Pydantic Settings，读取 .env
│   ├── database.py                     # SQLAlchemy async engine/session/Base
│   ├── db_migrations.py                # SQLite 自动迁移与历史数据兼容
│   ├── models.py                       # 所有数据库模型
│   ├── dependencies/
│   │   └── auth.py                     # Session/API Key 权限依赖
│   ├── routes/
│   │   ├── user.py                     # 前台首页、Codex 教程页
│   │   ├── redeem.py                   # 兑换码验证、绑定邮箱查询、确认兑换
│   │   ├── warranty.py                 # 质保查询、质保提交、设备认证
│   │   ├── invite_jobs.py              # 前台拉人任务状态查询
│   │   ├── auth.py                     # 登录、登出、修改密码
│   │   ├── admin.py                    # 管理后台页面与管理 API
│   │   ├── api.py                      # 轻量 API，如 Team 刷新
│   │   └── local_tools.py              # 本地工具页与临时网页读取
│   ├── services/
│   │   ├── auth.py                     # 管理员/子管理员认证服务
│   │   ├── chatgpt.py                  # ChatGPT Team 后端 API 调用封装
│   │   ├── encryption.py               # Token 加密/解密
│   │   ├── team.py                     # Team 导入、刷新、成员、清理、统计
│   │   ├── redemption.py               # 兑换码生成、校验、使用、记录、导出查询
│   │   ├── redeem_flow.py              # 用户兑换与 Team 选择流程
│   │   ├── invite_queue.py             # 前台拉人队列、席位预占、重试与轮询
│   │   ├── warranty.py                 # 质保订单、名单判定、超级码、Sub2API 调用编排
│   │   ├── settings.py                 # 数据库配置项读写与默认值
│   │   ├── notification.py             # 库存预警 Webhook
│   │   ├── team_auto_refresh.py        # Team 自动刷新后台任务
│   │   ├── warranty_expiry_cleanup.py  # 质保到期自动踢出后台任务
│   │   ├── team_member_snapshot.py     # 成员快照服务
│   │   ├── team_refresh_record.py      # Team 刷新记录服务
│   │   ├── team_cleanup_record.py      # 自动清理记录服务
│   │   ├── email_whitelist.py          # 邮箱白名单服务
│   │   └── sub2api_warranty_client.py  # Sub2API Admin API 客户端
│   ├── templates/
│   │   ├── base.html                   # 后台基础布局
│   │   ├── auth/                       # 登录页
│   │   ├── admin/                      # 后台页面模板
│   │   ├── user/                       # 前台服务台与 Codex 教程
│   │   └── tools/                      # 本地工具页面
│   ├── static/
│   │   ├── css/                        # 后台/前台/工具页样式
│   │   ├── js/                         # 后台/前台/工具页脚本
│   │   ├── img/codex-guide/            # Codex 教程图片素材
│   │   └── favicon.png
│   └── utils/
│       ├── token_parser.py             # Team 导入文本解析
│       ├── jwt_parser.py               # ChatGPT AT 解析与过期判断
│       ├── rich_text.py                # 富文本净化与纯文本转换
│       ├── storage.py                  # 上传目录与展示 URL 工具
│       └── time_utils.py               # 时区时间工具
├── tests/                              # pytest 测试集
├── data/                               # 本地/容器持久化数据目录（不应提交）
├── init_db.py                          # 手动初始化数据库脚本
├── test_webhook.py                     # 库存预警 Webhook 手动测试脚本
├── requirements.txt                    # Python 依赖
├── Dockerfile
├── docker-compose.yml                  # 生产/常规部署 Compose
├── docker-compose.dev.yml              # 本机热重载覆盖配置
├── .env.example                        # 环境变量示例
├── integration_docs.md                 # Webhook 与自动导入对接文档
├── DEPLOY_COMMANDS.md                  # 部署与线上排查命令
├── CHANGELOG.md                        # 更新日志
└── README.md
```

---

## 运行时架构

应用入口为 `app/main.py`。

启动阶段（`lifespan`）：

1. 确保数据库目录存在。
2. 调用 `init_db()` 创建表并启用 SQLite WAL。
3. 运行 `app/db_migrations.py` 中的自动迁移，兼容历史字段与表结构。
4. 初始化总管理员密码哈希。
5. 启动三个后台任务：
   - `team_auto_refresh_service`：按配置周期刷新 Team 状态。
   - `warranty_expiry_cleanup_service`：开启后清理到期质保订单对应成员/白名单。
   - `invite_queue_service`：处理前台兑换与质保拉人任务。

请求阶段：

- `/static` 提供静态资源。
- `/uploads` 提供持久化上传资源（客服二维码、质保名单判定富文本图片等）。
- 后台页面统一使用 `base.html`、Session 登录和侧边栏配置。
- 前台服务台直接读取数据库配置，动态决定兑换、质保、公告、客服和购买入口展示。

关闭阶段：

1. 停止拉人队列。
2. 停止质保到期清理。
3. 停止 Team 自动刷新。
4. 关闭数据库连接池。

---

## 核心业务流程

### 1. Team 导入

入口：`POST /admin/teams/import`

- 支持 `single` 和 `batch` 两种导入方式。
- 单个导入至少提供 `access_token`、`refresh_token` 或 `session_token` 之一。
- 批量导入由 `TokenParser` 从自由文本、JSON、分隔符格式中提取 AT / RT / ST / Client ID / 邮箱 / Account ID。
- 导入后 Team 统一进入控制台 Team 池；兑换码不再固定绑定某个 Team。
- 子管理员只能访问导入能力，总管理员可访问完整后台。

### 2. 兑换码生成与管理

入口：后台“兑换码管理”或 `POST /admin/codes/generate`

- 支持普通兑换码和质保兑换码。
- 普通兑换码用于前台兑换并加入 Team。
- 质保兑换码可配置质保时长与质保次数。
- 质保时长支持天数兼容字段，也支持秒级字段用于小时/分钟精度。
- 生成前会校验当前可用席位容量，避免生成数量超过可用库存。
- 支持筛选、批量删除、批量编辑、质保剩余时间/次数批量调整、Excel 或文本导出。

### 3. 前台兑换拉人

入口：`POST /redeem/verify`、`POST /redeem/confirm`

1. 用户在 `/` 输入邮箱和兑换码。
2. `RedeemFlowService` 校验兑换码并读取可用 Team。
3. 确认兑换时创建 `InviteJob`，先预占席位，再由队列后台处理。
4. `InviteQueueService` 自动选择 Team：
   - 未开启号池：使用控制台普通 Team。
   - 开启号池：普通兑换使用独立号池 Team。
5. `ChatGPTService` 调用 ChatGPT Team API 发送邀请。
6. 成功后写入使用记录、更新兑换码状态、同步质保资格（如该兑换码带质保）。
7. 前台通过 `/invite-jobs/{job_id}` 轮询任务状态。

### 4. 质保订单与补发

入口：`POST /warranty/check`、`POST /warranty/claim`

- 普通模式：按邮箱查询可用质保订单，展示剩余时间/次数、最近 Team 状态和可提交状态。
- 质保提交会创建拉人队列任务，成功后写入质保提交记录并更新订单关联 Team。
- 可开启“前台质保模拟成功”，用于特殊场景展示成功并扣减模拟席位。
- 可开启“质保到期自动踢出”，后台任务会清理到期订单对应 Team 成员，并写入自动清理记录。

### 5. 质保名单判定模式

入口：后台“质保名单判定”、前台 `POST /warranty/check`

- 开启后，传统订单查询和质保提交流程会关闭。
- 按邮箱判断是否在质保邮箱列表中，分别展示命中/未命中的富文本模板。
- 支持多个模板，系统会为邮箱锁定首次命中的模板，避免重复查询时内容漂移。
- 可配置 Sub2API：命中后自动创建订阅兑换码并记录在“兑换码生成记录”。
- 支持质保名单判定超级兑换码，用于特殊校验入口。

### 6. Team 刷新、快照与清理

- 手动刷新：后台单个/批量刷新 Team，记录到 `team_refresh_records`。
- 自动刷新：后台任务按周期刷新可用 Team，遇到异常也会写入失败刷新记录。
- 成员快照：刷新或成员操作时同步 `team_member_snapshots`，后台可按邮箱、Team、状态查询。
- 自动清理：Team 刷新或质保到期清理可删除非绑定成员、撤销邀请、停用白名单，并写入 `team_cleanup_records`。

### 7. 本地工具

入口：

- `/local-tools`
- `/local-tools/records`
- `/local-tools/email-accounts`

这些页面主要使用浏览器本地存储处理导入资料、邮箱记录和验证码信息。服务端仅提供受限的临时网页读取接口 `/local-tools/fetch-page`，并阻止读取 localhost、内网和非法 URL。

---

## 页面与接口地图

### 前台页面

| 路径 | 说明 |
| --- | --- |
| `GET /` | 用户兑换/质保服务台 |
| `GET /codex-guide` | Codex API 登录对接教程 |
| `GET /health` | 健康检查 |
| `GET /local-tools` | 本地快捷导入工具 |
| `GET /local-tools/records` | 本地记录工作台 |
| `GET /local-tools/email-accounts` | 邮箱账户工作台 |

### 前台 API

| 方法与路径 | 说明 |
| --- | --- |
| `POST /redeem/verify` | 校验兑换码并返回可用 Team |
| `POST /redeem/confirm` | 提交兑换并创建拉人任务 |
| `POST /redeem/bound-email` | 查询兑换码绑定邮箱 |
| `POST /redeem/bound-email/withdraw` | 前台撤销接口，当前默认拒绝 |
| `GET /invite-jobs/{job_id}` | 查询拉人任务状态 |
| `POST /warranty/check` | 质保订单查询或名单判定 |
| `POST /warranty/order-status` | 刷新单个质保订单 Team 状态 |
| `POST /warranty/claim` | 提交质保补发任务 |
| `POST /warranty/enable-device-auth` | 用户侧开启设备身份验证 |
| `POST /warranty/fake-success/validate` | 模拟成功模式资格校验 |
| `POST /warranty/fake-success/complete` | 模拟成功模式扣减展示席位 |

### 管理后台页面

| 路径 | 说明 |
| --- | --- |
| `GET /login` | 管理员登录页 |
| `GET /admin` | 控制台 Team 池 |
| `GET /admin/number-pool` | 独立号池（开启后显示） |
| `GET /admin/pending-teams` | 导入记录/历史兼容页面 |
| `GET /admin/import-only` | 子管理员导入页 |
| `GET /admin/sub-admins` | 子管理员管理 |
| `GET /admin/codes` | 兑换码管理 |
| `GET /admin/code-generation-records` | Sub2API 兑换码生成记录 |
| `GET /admin/records` | 使用记录 |
| `GET /admin/email-whitelist` | 邮箱白名单 |
| `GET /admin/warranty-emails` | 质保邮箱列表 |
| `GET /admin/warranty-email-check` | 质保名单判定配置 |
| `GET /admin/warranty-claim-records` | 质保提交记录 |
| `GET /admin/team-member-snapshots` | 成员快照 |
| `GET /admin/team-refresh-records` | Team 刷新记录 |
| `GET /admin/team-cleanup-records` | 自动清理记录 |
| `GET /admin/front-page` | 前台页面配置 |
| `GET /admin/settings` | 系统设置 |

### 管理/集成 API 摘要

| 方法与路径 | 说明 |
| --- | --- |
| `POST /auth/login` | 登录 |
| `POST /auth/logout` | 登出 |
| `POST /auth/change-password` | 修改总管理员密码 |
| `POST /admin/teams/import` | 单个/批量导入 Team，支持 Session 或 `X-API-Key` |
| `GET /api/teams/{team_id}/refresh` | 刷新 Team 信息 |
| `POST /admin/teams/{team_id}/update` | 更新 Team 信息/Token/人数/状态 |
| `POST /admin/teams/{team_id}/transfer` | 在控制台池与号池间转移 Team |
| `GET /admin/teams/{team_id}/members/list` | 查看成员与邀请列表 |
| `POST /admin/teams/{team_id}/members/add` | 后台手动添加成员 |
| `POST /admin/teams/{team_id}/members/{user_id}/delete` | 删除成员 |
| `POST /admin/teams/{team_id}/invites/revoke` | 撤销邀请 |
| `POST /admin/teams/batch-*` | 批量刷新、删除、设置人数、开启设备认证等 |
| `POST /admin/codes/*` | 兑换码生成、编辑、删除、导出、批量操作 |
| `POST /admin/settings/*` | 代理、日志、Webhook、自动刷新、号池、服务开关等配置 |
| `POST /admin/front-page/*` | 前台公告、客服、购买链接配置 |
| `POST /admin/warranty-*` | 质保邮箱、超级码、名单判定等配置 |

完整 Webhook 与自动导入对接请看 [integration_docs.md](integration_docs.md)。

---

## 配置说明

### 环境变量

`.env.example` 提供了基础配置示例：

| 变量 | 说明 | 默认/示例 |
| --- | --- | --- |
| `APP_NAME` | 应用名称 | `GPT Team 管理系统` |
| `APP_VERSION` | 应用版本 | `0.1.0` |
| `APP_HOST` | 本机运行监听地址 | `0.0.0.0` |
| `APP_PORT` | 服务端口 | `8008` |
| `DEBUG` | 调试模式 | `True` |
| `DATABASE_URL` | SQLAlchemy 数据库连接 | Docker 中强制为 `/app/data/team_manage.db` |
| `SECRET_KEY` | Session 签名与 Token 加密派生密钥 | 生产必须修改并长期保持稳定 |
| `ADMIN_PASSWORD` | 首次初始化总管理员密码 | 生产必须修改 |
| `LOG_LEVEL` | 日志级别 | `INFO` |
| `DATABASE_ECHO` | 是否打印 SQL | `False` |
| `PROXY_ENABLED` | 是否启用代理 | `False` |
| `PROXY` | ChatGPT API 代理地址 | 支持 `http://`、`socks5://`、`socks5h://` |
| `JWT_VERIFY_SIGNATURE` | JWT 是否验签 | 开发常为 `False` |
| `TIMEZONE` | 展示时区 | `Asia/Shanghai` |
| `INVITE_QUEUE_WORKER_COUNT` | 拉人队列 worker 数 | `3` |
| `INVITE_QUEUE_POLL_INTERVAL_SECONDS` | 队列轮询间隔 | `1` |
| `INVITE_QUEUE_PROCESSING_TIMEOUT_SECONDS` | 处理中任务超时 | `600` |
| `INVITE_QUEUE_ACTIVE_TEAM_LIMIT` | 队列活跃 Team 窗口 | `10` |

### 数据库配置项

以下配置存储在 `settings` 表，并可通过后台页面调整：

- 代理地址与开关。
- 日志级别。
- 库存预警 Webhook URL、阈值、API Key。
- Team 自动刷新开关与刷新周期。
- 质保到期自动踢出开关。
- Team 默认最大人数。
- 独立号池开关。
- 前台兑换服务、质保服务、质保模拟成功开关。
- 前台购买链接、公告、客服模块。
- 管理后台侧边栏排序。
- 质保名单判定模板、富文本内容、Sub2API 地址/Admin API Key/分组 ID/兑换码前缀。
- 质保超级兑换码与限制值。

---

## 数据库模型概览

| 模型 | 表 | 作用 |
| --- | --- | --- |
| `AdminUser` | `admin_users` | 子管理员账号 |
| `Team` | `teams` | Team 主表，保存加密 Token、状态、人数、类型、导入来源等 |
| `TeamAccount` | `team_accounts` | Team 下 Account ID 关联 |
| `TeamMemberSnapshot` | `team_member_snapshots` | Team 成员/邀请快照 |
| `RedemptionCode` | `redemption_codes` | 普通/质保兑换码 |
| `RedemptionRecord` | `redemption_records` | 用户兑换使用记录 |
| `InviteJob` | `invite_jobs` | 前台兑换/质保拉人队列任务 |
| `Setting` | `settings` | 后台配置项 |
| `WarrantyEmailEntry` | `warranty_email_entries` | 质保订单/邮箱资格记录 |
| `WarrantyEmailTemplateLock` | `warranty_email_template_locks` | 质保名单判定模板锁定与 Sub2API 兑换码记录 |
| `EmailWhitelistEntry` | `warranty_team_whitelist_entries` | 全局邮箱白名单（历史表名兼容） |
| `WarrantyClaimRecord` | `warranty_claim_records` | 质保提交记录 |
| `TeamCleanupRecord` | `team_cleanup_records` | 自动清理记录 |
| `TeamRefreshRecord` | `team_refresh_records` | Team 刷新记录 |

---

## 测试与验证

项目当前测试覆盖了后台页面、兑换码、Team 导入/刷新、质保流程、Sub2API、前台页面、本地工具和自动化服务等多个模块。

常用验证命令：

```bash
# 全量测试
pytest

# 语法和导入级检查
python -m compileall app tests

# 示例：只验证 Token 解析
pytest tests/test_token_parser.py

# 示例：只验证质保服务开关
pytest tests/test_warranty_service_toggle_route.py
```

建议改动范围对应的最小验证：

- 修改 README / 文档：检查 Markdown 内容、链接和关键命令是否与代码一致。
- 修改路由或模板：运行对应 `tests/test_*_page.py` 或 `tests/test_*_route.py`。
- 修改 Team / 兑换 / 质保服务：运行对应服务测试和相关路由测试。
- 修改前端交互：除 pytest 外，建议用浏览器访问目标页面做一次手动验证。

---

## 部署要点

1. 生产环境建议使用 Docker Compose，并通过 Nginx/Caddy 等反向代理对外暴露 HTTPS。
2. `docker-compose.yml` 默认只绑定本机 `127.0.0.1`，适合反向代理部署。
3. 数据库和上传文件位于 `./data`，部署、迁移和升级前应备份该目录。
4. `.env` 必须单独保管，不要提交到 Git。
5. `SECRET_KEY` 会影响已加密 Token 的解密能力：生产启用后不要随意更换；如必须更换，需要重新导入 Team Token。
6. 应用启动会自动运行轻量 SQLite 迁移；升级前仍建议备份数据库。
7. 线上更新可参考：

```bash
git fetch origin
git reset --hard origin/main
docker compose up -d --build
```

---

## 安全注意事项

- 生产环境必须修改 `SECRET_KEY` 和 `ADMIN_PASSWORD`。
- 不要提交 `.env`、数据库、上传文件、日志、截图或任何包含 Token/API Key 的文件。
- Team Token 使用 Fernet 加密后存库，但密钥派生自 `SECRET_KEY`，请妥善保管。
- `X-API-Key` 拥有自动导入权限，应只发给可信系统并定期轮换。
- 代理配置会影响所有 ChatGPT API 请求，变更后系统会清理 ChatGPT 会话池。
- 本地工具的网页读取接口已阻止内网/本机地址，但仍建议仅在可信环境使用。
- 富文本内容会通过 `bleach` 净化，上传图片限制类型、大小和文件签名。
- ChatGPT Team 管理涉及第三方服务账号与邀请能力，请确保用途合法并遵守相关服务条款。

---

## 故障排查

### 1. 管理员无法登录

- 确认 `.env` 中 `ADMIN_PASSWORD` 只在首次初始化时生效。
- 如数据库已初始化，需在后台修改密码；或备份后重建数据库。
- 检查 `settings` 表中是否存在 `admin_password_hash`。

### 2. 数据库初始化或迁移失败

```bash
# 本机开发可先备份再重建
cp data/team_manage.db data/team_manage.db.bak.$(date +%F-%H%M%S)
python init_db.py
```

Docker 部署请优先备份 `./data` 后再操作。

### 3. SQLite `database is locked`

- 确认没有多个本机进程同时写同一个数据库。
- Docker 和本机 Python 不要同时指向同一 SQLite 文件。
- 等待当前批量任务结束，或停止多余进程后重试。

### 4. Team 导入失败

- 确认至少提供 AT、RT 或 Session Token 之一。
- 检查 Token 是否过期、账号是否仍有 Team 权限。
- 检查代理配置是否可用。
- 查看容器日志：`docker compose logs -f --tail=100`。

### 5. 前台兑换一直处理中

- 查看 `/invite-jobs/{job_id}` 返回的错误信息。
- 检查 Team 是否已满、Token 是否失效、ChatGPT API 是否返回风控/账单/封禁错误。
- 后台查看 Team 刷新记录、自动清理记录和成员快照。

### 6. 库存预警 Webhook 不触发

- 后台“系统设置”确认 Webhook URL、阈值和 API Key。
- 当前逻辑按总可用车位触发，只有可用车位 `<= low_stock_threshold` 时才发送。
- 可用 `python test_webhook.py` 在开发环境手动测试；该脚本会修改数据库配置，生产谨慎使用。

### 7. Sub2API 未生成兑换码

- 确认“质保名单判定”已开启，并正确配置 Sub2API 基础地址、Admin API Key、订阅分组 ID 和兑换码前缀。
- 确认邮箱命中质保邮箱列表，且没有因为 Team 正常可用、缺少质保兑换码或兑换码错误而跳过生成。
- 查看“兑换码生成记录”和服务日志中的 Sub2API 错误。

---

## 相关文档

- [integration_docs.md](integration_docs.md)：库存预警 Webhook 与自动导入对接。
- [DEPLOY_COMMANDS.md](DEPLOY_COMMANDS.md)：部署、更新、备份和线上检查命令。
- [CHANGELOG.md](CHANGELOG.md)：项目更新日志。
- [AGENTS.md](AGENTS.md)：AI 助手在本仓库内工作的工程规则。

---

## 许可证与声明

本项目仅供学习、研究和合法的 Team 管理场景使用。使用者应自行确认业务流程、账号来源、第三方 API 调用和用户通知方式符合当地法律法规及相关服务条款。
