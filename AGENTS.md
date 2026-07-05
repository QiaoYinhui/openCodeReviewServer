# AGENTS.md — openCodeReviewServer

## Project Identity

GitHub Webhook 驱动的多 Agent 自动代码评审服务。监听 PR 事件，克隆代码 + 生成 diff，调用 OpenCode v1 CLI 执行结构化评审，将结果回填到 PR 评论。

| 维度 | 内容 |
|------|------|
| 语言/框架 | Python 3.10+ / FastAPI / pydantic-settings / structlog / httpx / tenacity |
| 外部依赖 | Bun + OpenCode v1 CLI (packages/opencode) |
| 部署方式 | uvicorn 直接运行，反向代理可选 |
| 配置入口 | .env 经 pydantic-settings 加载 |

---

## System Architecture

```
GitHub Webhook POST /github/webhook/pr
  │
  ├─ handle_pr_webhook()
  │   ├─ verify_signature()        ← HMAC-SHA256, body 只读一次
  │   ├─ 过滤 action [opened/synchronize/reopened]
  │   ├─ 跳过 draft PR
  │   ├─ 提取 PRMeta dataclass
  │   └─ 返回 200 + request_id
  │
  └→ BackgroundTasks: execute_review_pipeline()
      ├─ ensure_temp_dir()
      ├─ clone_and_diff()
      │   ├─ git clone --branch source --single-branch --depth 50
      │   ├─ git fetch origin target:refs/remotes/origin/target --depth 50
      │   └─ git diff origin/target...origin/source
      ├─ run_opencode_review()
      │   ├─ 构建 stdin prompt（PR 上下文 + diff）
      │   ├─ subprocess(bun, --format json, --agent review)
      │   ├─ parse_review_output() → 拼接 text 事件 → 提取 JSON
      │   └─ 返回 ReviewResult
      ├─ post_review_comments()
      │   ├─ 总评 → issue comment
      │   └─ 行内 → PR review comment (side=RIGHT)
      └─ cleanup_temp_dir()
```

**同步/异步边界**：Webhook handler 同步返回 200，Pipeline 通过 `asyncio.to_thread` 将阻塞操作（git、subprocess）跑在线程池。

**错误传播**：每一层捕获自身异常 → `post_review_failure()` 通知 PR → 不阻塞后续链路。

---

## Module Reference

### `app/config.py`

| 符号 | 角色 |
|------|------|
| `Settings` | pydantic BaseSettings，从 `.env` 读取所有配置 |
| `settings = Settings()` | 全局单例，各模块 `from app.config import settings` 引用 |

### `app/webhook/pr_handler.py`

| 符号 | 角色 |
|------|------|
| `PRMeta` | dataclass: repo_id, pr_number, source_branch, target_branch, git_http_url, base_commit, head_commit, repo_full_name |
| `verify_signature(payload_body, signature)` | HMAC-SHA256 校验，比较用 `hmac.compare_digest` |
| `handle_pr_webhook(request, background_tasks)` | FastAPI endpoint，返回 `{"status":"accepted/ignored","request_id":xx}` |

**注意**：`request.body()` 后不能用 `await request.json()`，stream 已被消费，必须 `json.loads(payload_body)`。

### `app/git_client/repo_clone.py`

| 符号 | 角色 |
|------|------|
| `clone_and_diff(git_http_url, source, target, local_path) → (local_path, diff_str)` | 完整 git 操作流程 |
| `GitOperationError` | 自定义异常，git 任何步骤失败都抛此异常 |

**关键细节**：
- 克隆使用 `--single-branch --depth 50` 节省带宽
- 目标分支通过**显式 refspec** fetch：`git fetch origin main:refs/remotes/origin/main --depth 50`
- 原因：`--single-branch` 后默认不创建目标分支的 remote tracking ref
- diff 用三点语法 `origin/target...origin/source` 只显示 PR 新增变更

### `app/opencode_client/review_runner.py`

| 符号 | 角色 |
|------|------|
| `run_opencode_review(...) → ReviewResult` | 构建 env → 构建 cmd → subprocess.run(stdin=prompt) → parse |
| `parse_review_output(stdout) → ReviewResult` | 解析 JSON 事件流，提取 agent 回复中的 JSON |
| `ReviewResult` | dataclass: success, summary, issues[], raw_output, error_message |
| `ReviewIssue` | dataclass: agent, file, line, level[error/warn/info], desc, suggestion |

**stdin 传 prompt**：OpenCode v1 通过 `process.stdin.isTTY` 检测，长 prompt 通过 `subprocess.run(cmd, input=prompt)` 传。不用命令行参数传长文本。

**`--format json` 输出格式**：逐行 JSON 事件，关键类型：
- `{"type":"text","part":{"text":"..."}}` → 拼接为 agent 完整回复
- agent 回复中嵌入的 JSON 结构由 system prompt 定义（见 opencode-review.json）

**`--log-level` 必须大写**：yargs choices = `["DEBUG","INFO","WARN","ERROR"]`，小写直接静默退出。

**ReviewResult 动态属性**：`.issue_count`, `.error_count`, `.warn_count`, `.info_count`

### `app/result_handler/github_comment.py`

| 符号 | 角色 |
|------|------|
| `post_review_comments(pr_meta, result)` | 发总评 + 逐条行内评论 |
| `post_review_failure(pr_meta, error_message)` | 发失败通知 |
| `_github_post(url, json_data)` | httpx POST + `@retry(stop=3, wait=1s)` |

**总评**：POST `/repos/{owner}/{repo}/issues/{pr_number}/comments`
**行内**：POST `/repos/{owner}/{repo}/pulls/{pr_number}/comments`，`side=RIGHT` 表示新代码行
**限制**：body 最大 65536 字符，超长截断；inline comment 依赖 `commit_id` 必须是 PR 最新 head SHA

### `app/utils/logger.py`

| 符号 | 角色 |
|------|------|
| `setup_logger()` | 配置 structlog，ConsoleRenderer |
| `bind_request_id(rid)` / `unbind_request_id()` | 通过 contextvars 注入/清理 request_id |
| `generate_request_id()` | uuid4 hex[:12] |

### `app/utils/file_util.py`

| 符号 | 角色 |
|------|------|
| `ensure_temp_dir(repo_id, pr_number) → str` | 创建 `/tmp/opencode_review/pr_{id}_{num}`，已存在则先清理 |
| `cleanup_temp_dir(path)` | `shutil.rmtree`，静默失败 |
| `build_temp_dir(repo_id, pr_number) → str` | 纯路径拼接 |

### `app/review_pipeline.py`

| 符号 | 角色 |
|------|------|
| `execute_review_pipeline(pr_meta, request_id)` | 编排所有步骤，`finally` 块保证清理 |

### `opencode-review.json`

Agent 配置：
- `agent.review.model`: 使用的模型（如 qwen3.7-plus）
- `agent.review.system`: system prompt，定义评审维度 + **JSON 输出格式 schema**
- `agent.review.mode`: primary
- `agent.review.permissions`: 当前只允许 read 和 git bash

**注意**：Agent system prompt 中的 JSON 输出格式必须与 Python 侧 `parse_review_output` 的解析逻辑一致。JSON schema 变更需同步更新两端。

---

## Critical Knowledge（踩过的坑）

### Webhook body 只读一次
```
payload_body = await request.body()     # 消费 stream
payload = await request.json()          # ❌ JSONDecodeError
payload = json.loads(payload_body)      # ✅ 正确
```

### `--log-level` 必须大写
yargs choices = `["DEBUG","INFO","WARN","ERROR"]`。传入小写时 yargs 直接 exit(1) 打印帮助，**无错误信息**。`run_opencode_review` 已通过 `.upper()` 处理，但 `.env` 建议直接用大写值。

### 分支克隆策略
`--single-branch` 后 `origin/main` 不存在，必须用 `git fetch origin main:refs/remotes/origin/main` 显式创建 remote tracking ref。diff 用三点语法 `origin/target...origin/source`。

### OpenCode v1 ≠ v2
- **v1**（本服务使用）：`packages/opencode/src/index.ts`，直接 subprocess + stdin，支持 `--format json`、`--agent`
- **v2**：`packages/cli/src/index.ts`，HTTP 客户端-服务端模式，不支持上述参数
- 不能互换，参数架构完全不同

### Agent/Prompt 分工

| 层级 | 文件 | 角色 | 内容 |
|------|------|------|------|
| System prompt | opencode-review.json | Agent 身份 + 评审维度 + **JSON schema** | 长期稳定，基本不变 |
| User message | Python 运行时构建 | 本次评审上下文 | PR 信息 + diff，每次不同 |

两端 JSON schema 必须一致，否则 parse 失败。

### stdout 事件解析逻辑

```python
# OpenCode --format json 输出逐行 JSON
# 1. 过滤 type=text 的事件
# 2. 拼接所有 part.text → 得到 agent 完整回复
# 3. 从中提取第一个 { ... } JSON 块
# 4. 解析为 {"summary": str, "issues": [...]}
# 5. issues 按 error < warn < info 排序
```

### 订阅模式选择

| 模式 | 适用场景 |
|------|---------|
| `openCodeReviewServer`（当前） | 只收 Repository 事件，所有 PR 都推送到单一 service |
| `开放服务器`（单个 project） | 可精确配置，但需要 service scope |

当前 `source_branch` 是从 `pull_request.head.ref` 提取，`target_branch` 从 `pull_request.base.ref` 提取。

---

## Configuration Reference

| 变量 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `SERVER_HOST` | str | "0.0.0.0" | 监听地址 |
| `SERVER_PORT` | int | 8000 | 监听端口 |
| `GITHUB_BASE_URL` | str | "https://api.github.com" | GitHub API |
| `GITHUB_PERSONAL_TOKEN` | str | "" | GitHub Token (repo scope) |
| `GITHUB_WEBHOOK_SECRET` | str | "" | HMAC 密钥 |
| `OPENCODE_SCRIPT_PATH` | str | "" | v1 入口 ts 路径 |
| `OPENCODE_CONFIG_PATH` | str | "" | 全局 opencode.jsonc |
| `OPENCODE_REVIEW_CONFIG_PATH` | str | "" | agent 配置 json |
| `OPENCODE_LOG_LEVEL` | str | "info" | 代码内 .upper() |
| `REVIEW_TIMEOUT` | int | 300 | subprocess 超时秒 |
| `TEMP_CODE_ROOT` | str | "/tmp/opencode_review" | 临时目录根 |
| `BUN_MAX_HEAP_SIZE` | int | 2684354560 | Bun GC 堆上限 |
| `REVIEW_RULES` | list[str] | ["code_style","security","logic_bug","performance"] | 评审维度（当前未使用） |

---

## Future Optimization

1. **多 Agent 并行评审**：当前只跑 `review` 一个 agent。可拆分为 `security`、`performance`、`style` 等 agent 并发调用，合并结果。
1. **GitHub App 模式**：替代 Personal Token，支持安装级别权限、自动创建 check run。
1. **Webhook 幂等去重**：基于 request_id / commit_sha 做去重，防止重复评审。
1. **增量更新评论**：当前每次全量发新评论，可改为查找已有评论并更新 / 删除重建。
1. **git submodule 支持**：在 clone 步骤添加 `git submodule update --init --recursive`。
1. **评审缓存**：相同 diff SHA 的评审结果可缓存，减少 OpenCode 调用。
1. **更细粒度的 GitHub Checks API 支持**：用 check run 替代 issue comment，更规范。
1. **diff 过滤**：排除 `package-lock.json` 等非代码文件，减少 token 消耗。
1. **行内评论分页**：当 issue 数超过 GitHub API 限制时分批提交。
