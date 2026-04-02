# 基于大语言模型的文档理解与模板提取系统

一套全栈、可私有化部署的智能文档信息提取平台，通过结构化模板驱动 LLM 进行精准字段抽取。

## 功能特性

- **多格式文档支持**：PDF（含扫描版 OCR）、Word (.docx)、Excel (.xlsx)、纯文本
- **模板驱动提取**：可视化定义提取字段（名称、类型、是否必填、描述），驱动 LLM 精准输出
- **多 LLM 提供商**：统一 OpenAI 兼容协议，支持 OpenAI、DeepSeek、Ollama 等，支持降级策略
- **异步任务队列**：Celery + Redis，文档解析与 LLM 提取异步化，支持优先级调度
- **实时进度推送**：WebSocket 推送任务进度，无需轮询
- **字段级置信度**：每个提取字段附带 LLM 置信度评分
- **结果导出**：支持 Excel、JSON、CSV 格式导出
- **RBAC 权限控制**：角色 + 权限双层模型，API Key 支持
- **分布式存储**：MinIO（S3 兼容）存储原始文档与结果

## 技术栈

| 层级 | 技术 |
|------|------|
| 后端框架 | FastAPI 0.115 + Python 3.11 |
| 数据库 | MySQL 8.0 + SQLAlchemy 2.0 (async) |
| 缓存 | Redis 7 |
| 任务队列 | Celery 5.4 |
| 对象存储 | MinIO |
| 文档解析 | PyMuPDF / python-docx / openpyxl |
| LLM | OpenAI SDK（兼容 DeepSeek / Ollama） |
| 前端 | Vue 3.5 + Element Plus 2.9 + Pinia |
| 构建 | Vite 6 |
| 容器 | Docker + Docker Compose + Nginx |

## 快速启动

### 前置条件

- Docker >= 24.0
- Docker Compose >= 2.20

### 1. 克隆并配置环境变量

```bash
git clone <repo_url>
cd Project1
cp .env.example .env
# 编辑 .env，至少填写 OPENAI_API_KEY（或其他 LLM 提供商）
```

### 2. 一键启动

```bash
docker compose up -d
```

等待所有服务就绪（约 1-2 分钟）：

```bash
docker compose ps       # 查看服务状态
docker compose logs -f  # 查看日志
```

### 3. 访问

| 服务 | 地址 |
|------|------|
| 前端应用 | http://localhost:8080 |
| API 文档 (Swagger) | http://localhost/docs |
| Celery Flower 监控 | http://localhost:5555 |
| MinIO 控制台 | http://localhost:9001 |

默认管理员账号：`admin` / `admin123`（首次启动自动创建）

### 前端文档入口

- 侧边栏新增「使用文档」菜单，登录后可直接查看操作指南
- 工作台「快捷操作」新增「使用文档」入口
- 前端路由地址：`/guide`
- 详细文档文件：`frontend/docs/usage-guide.md`

---

## 本地开发

### 后端

```bash
cd backend
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 启动依赖（MySQL / Redis / MinIO）
docker compose up -d mysql redis minio

# 复制并编辑配置
cp .env.example .env

# 数据库迁移
alembic upgrade head

# 启动 API 服务
uvicorn app.main:app --reload --port 8000

# 启动 Celery Worker（另开终端）
celery -A app.tasks.celery_app worker --loglevel=info -Q document,extraction,default
```

### 前端

```bash
cd frontend
npm install
npm run dev   # 启动开发服务器 http://localhost:5173
```

---

## 项目结构

```
Project1/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI 入口
│   │   ├── config.py            # 全局配置（pydantic-settings）
│   │   ├── database.py          # 异步数据库引擎
│   │   ├── models/              # SQLAlchemy ORM 模型
│   │   ├── schemas/             # Pydantic 数据模式
│   │   ├── api/v1/              # REST API 路由层
│   │   ├── services/            # 业务逻辑层
│   │   ├── core/                # 认证/缓存/存储/异常
│   │   ├── processors/          # 文档解析处理器
│   │   ├── llm/                 # LLM 适配层
│   │   ├── tasks/               # Celery 异步任务
│   │   └── websocket/           # WebSocket 处理器
│   ├── requirements.txt
│   ├── Dockerfile
│   └── .env.example
├── frontend/
│   ├── src/
│   │   ├── views/               # 页面视图
│   │   │   ├── Dashboard.vue
│   │   │   ├── guide/           # 使用文档页面
│   │   │   ├── template/        # 模板管理页面
│   │   │   ├── document/        # 文档管理页面
│   │   │   ├── extraction/      # 提取任务页面
│   │   │   └── system/          # 系统配置页面
│   │   ├── components/Layout/   # 应用布局
│   │   ├── api/                 # API 调用函数
│   │   ├── stores/              # Pinia 状态管理
│   │   ├── router/              # Vue Router 路由
│   │   └── utils/               # 工具函数
│   ├── docs/
│   │   └── usage-guide.md       # 前端使用手册（Markdown）
│   ├── Dockerfile
│   └── package.json
├── nginx/nginx.conf             # Nginx 反向代理配置
├── scripts/init.sql             # 数据库初始化
├── docker-compose.yml
└── .env.example
```

---

## API 接口总览

### 认证

| 方法 | 路径 | 描述 |
|------|------|------|
| POST | `/api/v1/auth/register` | 注册用户 |
| POST | `/api/v1/auth/login` | 登录获取 Token |
| POST | `/api/v1/auth/refresh` | 刷新 Token |
| GET  | `/api/v1/auth/me` | 获取当前用户信息 |

### 模板管理

| 方法 | 路径 | 描述 |
|------|------|------|
| GET  | `/api/v1/templates` | 列表（分页/搜索） |
| POST | `/api/v1/templates` | 创建模板 |
| GET  | `/api/v1/templates/{id}` | 模板详情 |
| PUT  | `/api/v1/templates/{id}` | 更新模板（自动版本化） |
| DELETE | `/api/v1/templates/{id}` | 归档模板 |
| POST | `/api/v1/templates/{id}/fields` | 添加字段 |

### 文档管理

| 方法 | 路径 | 描述 |
|------|------|------|
| POST | `/api/v1/documents/upload` | 上传文档（触发异步解析） |
| POST | `/api/v1/documents/batch-upload` | 批量上传 |
| GET  | `/api/v1/documents` | 文档列表 |
| GET  | `/api/v1/documents/{id}/status` | 解析状态 |
| GET  | `/api/v1/documents/{id}/download-url` | 获取预签名下载链接 |

### 提取任务

| 方法 | 路径 | 描述 |
|------|------|------|
| POST | `/api/v1/extractions` | 创建提取任务 |
| POST | `/api/v1/extractions/batch` | 批量创建 |
| GET  | `/api/v1/extractions` | 任务列表 |
| GET  | `/api/v1/extractions/{id}` | 任务详情+进度 |
| GET  | `/api/v1/extractions/{id}/results` | 字段级提取结果 |
| POST | `/api/v1/extractions/export` | 批量导出结果 |

### 系统

| 方法 | 路径 | 描述 |
|------|------|------|
| GET  | `/api/v1/system/health` | 健康检查（DB/Redis） |
| GET  | `/api/v1/system/stats` | 统计数据 |
| GET  | `/api/v1/system/llm-configs` | LLM 配置列表 |
| POST | `/api/v1/system/llm-configs/{id}/test` | 测试 LLM 连接 |

### WebSocket

| 端点 | 描述 |
|------|------|
| `ws://host/ws/processing-status/{task_id}?token=xxx` | 任务处理进度实时推送 |
| `ws://host/ws/upload-progress/{task_id}?token=xxx` | 上传进度推送 |
| `ws://host/ws/notifications/{user_id}?token=xxx` | 用户通知推送 |

---

## 环境变量说明

复制 `.env.example` 为 `.env` 并按需修改：

```env
# 数据库
DB_HOST=mysql
DB_PORT=3306
DB_USER=docuser
DB_PASSWORD=docpassword
DB_NAME=docextract

# Redis
REDIS_HOST=redis
REDIS_PORT=6379

# JWT
SECRET_KEY=your-very-long-secret-key-here

# MinIO
STORAGE_ENDPOINT=minio:9000
STORAGE_ACCESS_KEY=minioadmin
STORAGE_SECRET_KEY=minioadmin

# LLM（至少配置一个）
OPENAI_API_KEY=sk-xxx
OPENAI_BASE_URL=https://api.openai.com/v1
DEEPSEEK_API_KEY=sk-xxx
DEFAULT_LLM_PROVIDER=openai
DEFAULT_LLM_MODEL=gpt-4o
```

---

## 安全说明

- 所有 API 均需 JWT Bearer Token 认证（除登录/注册）
- 文件上传路径穿越防护（Path Traversal）
- SQL 注入防护（SQLAlchemy ORM 参数化查询）
- CORS 白名单配置
- 安全响应头（X-Content-Type-Options, X-Frame-Options 等）
- 密码使用 bcrypt 哈希存储
- JWT 黑名单（Redis）实现登出

## License

MIT
