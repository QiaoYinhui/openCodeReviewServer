# OpenCode 自动化代码评审服务

基于 OpenCode 多Agent 评审引擎的 GitHub PR 自动化代码审核服务。监听 GitHub Webhook PR 事件，自动拉取代码变更、调用 OpenCode 执行代码评审，并将评审结果回填至 GitHub PR 评论区。

## 核心功能

- 接收 GitHub PR 新建/更新 Webhook 事件
- 自动拉取源分支代码、生成 Diff
- 调用 OpenCode 多Agent 评审引擎执行代码审核
- 解析结构化评审结果（漏洞、规范、逻辑、性能）
- 自动向 GitHub PR 提交全局总结评论 + 代码行内精准评论
- 异步执行，支持并发 PR 评审

## 项目结构

```
code-review-service/
├── app/
│   ├── main.py                  # FastAPI 服务入口
│   ├── config.py                # 全局配置
│   ├── review_pipeline.py       # 异步评审编排
│   ├── webhook/pr_handler.py    # Webhook 接收与解析
│   ├── git_client/repo_clone.py # Git 代码拉取与 Diff 生成
│   ├── opencode_client/review_runner.py  # OpenCode 评审调用
│   ├── result_handler/github_comment.py  # GitHub 评论回填
│   └── utils/
│       ├── file_util.py         # 临时文件管理
│       └── logger.py            # 统一日志
├── .env.example                 # 环境变量模板
├── .gitignore
├── requirements.txt
└── README.md
```

## 快速开始

### 1. 环境要求

- Python 3.10+
- Bun 运行时（OpenCode 依赖）
- Git
- 已部署的 OpenCode 项目（源码方式部署）

### 2. 安装依赖

```bash
cd code-review-service
pip install -r requirements.txt
```

### 3. 配置环境变量

```bash
cp .env.example .env
```

编辑 `.env`，填入必要配置：

| 配置项 | 必填 | 说明 |
|--------|------|------|
| `GITHUB_PERSONAL_TOKEN` | 是 | GitHub Personal Access Token，需有 `repo` 权限 |
| `GITHUB_WEBHOOK_SECRET` | 是 | Webhook 签名密钥，需与 GitHub 仓库设置一致 |
| `OPENCODE_SCRIPT_PATH` | 是 | OpenCode CLI 入口脚本路径 |
| `OPENCODE_CONFIG_PATH` | 是 | OpenCode 配置文件路径 |
| `REVIEW_TIMEOUT` | 否 | 评审超时秒数，默认 300 |
| `TEMP_CODE_ROOT` | 否 | 临时代码目录，默认 `/tmp/opencode_review` |

完整配置项参见 `.env.example`。

### 4. 配置 GitHub Webhook

在 GitHub 仓库的 **Settings → Webhooks** 中添加：

- **Payload URL**: `http://your-server:8000/github/webhook/pr`
- **Content type**: `application/json`
- **Secret**: 与 `.env` 中 `GITHUB_WEBHOOK_SECRET` 一致
- **Events**: 选择 `Pull requests`

### 5. 启动服务

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### 6. 健康检查

```bash
curl http://localhost:8000/health
```

## 工作流程

```
GitHub PR 事件
    │
    ▼
Webhook 接收 (立即返回 200)
    │
    ▼
后台异步任务启动
    │
    ├─ 1. 克隆源分支代码到临时目录
    ├─ 2. 生成 Diff（目标分支 vs 源分支）
    ├─ 3. 调用 OpenCode subprocess 执行评审
    ├─ 4. 解析 JSON 结构化评审结果
    ├─ 5. 向 GitHub PR 提交全局总结 + 行内评论
    └─ 6. 清理临时目录
```

## API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/github/webhook/pr` | GitHub PR Webhook 回调 |
| GET | `/health` | 健康检查 |

## 评审结果格式

OpenCode 输出 JSON 结构：

```json
{
  "summary": "评审总结文本",
  "issues": [
    {
      "agent": "security",
      "file": "src/main.py",
      "line": 42,
      "level": "error",
      "desc": "问题描述",
      "suggestion": "修复建议"
    }
  ]
}
```

问题等级：`error` > `warn` > `info`

## 注意事项

- `.env` 文件包含敏感信息，已添加到 `.gitignore`，请勿提交到仓库
- 服务需要能够访问 GitHub API 和克隆目标仓库
- OpenCode 评审为阻塞操作，单次超时默认 300 秒
- 评审完成后临时目录会自动清理
- GitHub 评论失败会自动重试 2 次

## 技术栈

- **FastAPI**: Web 框架
- **pydantic-settings**: 配置管理
- **httpx**: GitHub API 调用
- **structlog**: 结构化日志
- **tenacity**: 重试机制
- **OpenCode**: 多Agent 代码评审引擎
# openCodeReviewServer

# ngrok使用步骤
1. 注册账号并配置 authtoken
- 打开 https://dashboard.ngrok.com/signup 注册
- 然后到 https://dashboard.ngrok.com/get-started/your-authtoken 复制 token
2. 配置authtoken
ngrok config add-authtoken <你的token>
3. ngrok port 8000，执行后显示的url即为公网可以访问的url
