import httpx
from tenacity import retry, stop_after_attempt, wait_fixed, retry_if_exception_type

from app.config import settings
from app.opencode_client.review_runner import ReviewResult
from app.webhook.pr_handler import PRMeta
from app.utils.logger import get_logger

logger = get_logger("github_comment")

MAX_COMMENT_BODY = 65000


@retry(
    stop=stop_after_attempt(3),
    wait=wait_fixed(1),
    retry=retry_if_exception_type(httpx.HTTPError),
    reraise=True,
)
def _github_post(url: str, json_data: dict) -> dict:
    headers = {
        "Authorization": f"token {settings.GITHUB_PERSONAL_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
    }
    with httpx.Client(timeout=30) as client:
        resp = client.post(url, json=json_data, headers=headers)
        resp.raise_for_status()
        return resp.json()


def _build_summary_comment(pr_meta: PRMeta, result: ReviewResult) -> str:
    lines = [
        "## OpenCode 自动代码评审报告",
        "",
        f"**仓库**: {pr_meta.repo_full_name}",
        f"**PR**: #{pr_meta.pr_number}",
        f"**分支**: `{pr_meta.source_branch}` → `{pr_meta.target_branch}`",
        "",
        "---",
        "",
        "### 评审总览",
        "",
        result.summary or "无总结信息",
        "",
        "### 问题统计",
        "",
        "| 等级 | 数量 |",
        "|------|------|",
        f"| 🔴 Error | {result.error_count} |",
        f"| 🟡 Warning | {result.warn_count} |",
        f"| 🔵 Info | {result.info_count} |",
        f"| **合计** | **{result.issue_count}** |",
        "",
        "### 整体结论",
        "",
    ]

    if result.error_count > 0:
        lines.append("> ⚠️ 发现 **Error** 级别问题，建议修复后再合并。")
    elif result.warn_count > 0:
        lines.append("> 发现 Warning 级别问题，建议关注并酌情修复。")
    elif result.issue_count > 0:
        lines.append("> 发现 Info 级别建议，代码整体质量良好。")
    else:
        lines.append("> ✅ 未发现问题，代码质量良好。")

    lines.extend([
        "",
        "---",
        "*由 OpenCode 多Agent 自动评审生成*",
    ])
    return "\n".join(lines)


def _build_inline_comment(issue) -> str:
    lines = [
        f"**[{issue.level.upper()}]** {issue.desc}",
    ]
    if issue.suggestion:
        lines.extend([
            "",
            f"**建议**: {issue.suggestion}",
        ])
    lines.extend([
        "",
        f"*检测Agent: `{issue.agent}`*",
    ])
    return "\n".join(lines)


def post_review_comments(pr_meta: PRMeta, result: ReviewResult) -> None:
    owner_repo = pr_meta.repo_full_name

    summary_body = _build_summary_comment(pr_meta, result)
    summary_url = f"{settings.GITHUB_BASE_URL}/repos/{owner_repo}/issues/{pr_meta.pr_number}/comments"

    try:
        _github_post(summary_url, {"body": summary_body})
        logger.info("github_summary_posted", pr=pr_meta.pr_number)
    except Exception:
        logger.exception("github_summary_post_failed")

    inline_url = f"{settings.GITHUB_BASE_URL}/repos/{owner_repo}/pulls/{pr_meta.pr_number}/comments"

    posted = 0
    for issue in result.issues:
        if not issue.file or issue.line <= 0:
            continue
        body = _build_inline_comment(issue)
        if len(body) > MAX_COMMENT_BODY:
            body = body[:MAX_COMMENT_BODY] + "\n\n*(内容过长已截断)*"
        try:
            _github_post(inline_url, {
                "body": body,
                "commit_id": pr_meta.head_commit,
                "path": issue.file,
                "line": issue.line,
                "side": "RIGHT",
            })
            posted += 1
        except Exception:
            logger.exception(
                "github_inline_comment_failed",
                file=issue.file,
                line=issue.line,
            )

    logger.info("github_inline_comments_done", posted=posted, total=result.issue_count)


def post_review_failure(pr_meta: PRMeta, error_message: str) -> None:
    owner_repo = pr_meta.repo_full_name
    url = f"{settings.GITHUB_BASE_URL}/repos/{owner_repo}/issues/{pr_meta.pr_number}/comments"

    body = "\n".join([
        "## ⚠️ OpenCode 自动代码评审失败",
        "",
        f"**仓库**: {owner_repo}",
        f"**PR**: #{pr_meta.pr_number}",
        "",
        f"评审过程出现异常，未能完成代码审核。",
        "",
        f"**错误信息**: `{error_message}`",
        "",
        "---",
        "*由 OpenCode 多Agent 自动评审生成*",
    ])

    try:
        _github_post(url, {"body": body})
        logger.info("github_failure_notice_posted", pr=pr_meta.pr_number)
    except Exception:
        logger.exception("github_failure_notice_failed")
