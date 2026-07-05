import json
import os
import subprocess
from dataclasses import dataclass, field

from app.config import settings
from app.utils.logger import get_logger

logger = get_logger("opencode_client")


@dataclass
class ReviewIssue:
    agent: str
    file: str
    line: int
    level: str
    desc: str
    suggestion: str


@dataclass
class ReviewResult:
    success: bool
    summary: str = ""
    issues: list[ReviewIssue] = field(default_factory=list)
    raw_output: str = ""
    error_message: str = ""

    @property
    def issue_count(self) -> int:
        return len(self.issues)

    @property
    def error_count(self) -> int:
        return sum(1 for i in self.issues if i.level == "error")

    @property
    def warn_count(self) -> int:
        return sum(1 for i in self.issues if i.level == "warn")

    @property
    def info_count(self) -> int:
        return sum(1 for i in self.issues if i.level == "info")


def _build_review_prompt(
    diff_content: str,
    repo_id: int,
    pr_number: int,
    source_branch: str,
    target_branch: str,
) -> str:
    return f"""请对以下 Pull Request 的代码变更进行专业评审。

## PR 信息
- 仓库 ID: {repo_id}
- PR 编号: #{pr_number}
- 源分支: {source_branch}
- 目标分支: {target_branch}

## 代码变更 (git diff)
```
{diff_content}
```

按你已知的输出格式返回 JSON 评审结果。"""


def run_opencode_review(
    repo_path: str,
    diff_content: str,
    repo_id: int,
    pr_number: int,
    source_branch: str,
    target_branch: str,
) -> ReviewResult:
    env = os.environ.copy()
    env["OPENCODE_CONFIG"] = settings.OPENCODE_CONFIG_PATH
    if settings.OPENCODE_REVIEW_CONFIG_PATH:
        env["OPENCODE_REVIEW_CONFIG"] = settings.OPENCODE_REVIEW_CONFIG_PATH
    env["BUN_JSC_gcMaxHeapSize"] = str(settings.BUN_MAX_HEAP_SIZE)

    prompt = _build_review_prompt(diff_content, repo_id, pr_number, source_branch, target_branch)

    cmd = [
        "bun",
        settings.OPENCODE_SCRIPT_PATH,
        "--print-logs",
        "--log-level", settings.OPENCODE_LOG_LEVEL.upper(),
        "run",
        "--format", "json",
        "--agent", "review",
        "--dir", repo_path,
    ]

    logger.info(
        "opencode_review_starting",
        cmd=" ".join(cmd[:10]) + " ... [prompt]",
        repo_path=repo_path,
        timeout=settings.REVIEW_TIMEOUT,
        prompt_length=len(prompt),
    )

    try:
        result = subprocess.run(
            cmd,
            input=prompt,
            capture_output=True,
            text=True,
            timeout=settings.REVIEW_TIMEOUT,
            env=env,
        )

        logger.info(
            "opencode_subprocess_result",
            returncode=result.returncode,
            stdout_length=len(result.stdout),
            stderr_length=len(result.stderr),
        )

        if result.returncode != 0:
            logger.error(
                "opencode_review_failed",
                returncode=result.returncode,
                stderr=result.stderr[:5000],
            )
            return ReviewResult(
                success=False,
                raw_output=result.stdout,
                error_message=f"OpenCode exited with code {result.returncode}: {result.stderr[:2000]}",
            )

        logger.info(
            "opencode_review_completed",
            stdout_length=len(result.stdout),
            stdout_preview=result.stdout[:5000] if result.stdout else "(empty)",
        )

        if result.stderr:
            logger.warning("opencode_stderr", stderr=result.stderr[:5000])

        return parse_review_output(result.stdout)

    except subprocess.TimeoutExpired:
        logger.error("opencode_review_timeout", timeout=settings.REVIEW_TIMEOUT)
        return ReviewResult(
            success=False,
            error_message=f"OpenCode review timed out after {settings.REVIEW_TIMEOUT}s",
        )
    except FileNotFoundError:
        logger.error("opencode_binary_not_found", script=settings.OPENCODE_SCRIPT_PATH)
        return ReviewResult(
            success=False,
            error_message=f"OpenCode binary not found: {settings.OPENCODE_SCRIPT_PATH}",
        )
    except Exception as e:
        logger.exception("opencode_review_unexpected_error")
        return ReviewResult(
            success=False,
            error_message=f"Unexpected error: {str(e)}",
        )


def parse_review_output(stdout: str) -> ReviewResult:
    text_parts = []
    errors = []

    for line in stdout.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue

        event_type = event.get("type", "")

        if event_type == "text":
            part = event.get("part", {})
            text = part.get("text", "")
            if text:
                text_parts.append(text)

        if event_type == "error":
            errors.append(str(event.get("error", "")))

    full_text = "".join(text_parts)

    logger.info(
        "opencode_events_parsed",
        text_length=len(full_text),
        text_preview=full_text[:1000] if full_text else "(empty)",
        error_count=len(errors),
    )

    if errors:
        logger.error("opencode_session_errors", errors=errors)

    if not full_text:
        logger.error("opencode_no_text_output", stdout_preview=stdout[:3000])
        return ReviewResult(
            success=False,
            raw_output=stdout,
            error_message="OpenCode produced no text output",
        )

    json_start = full_text.find("{")
    json_end = full_text.rfind("}")
    if json_start == -1 or json_end == -1:
        logger.error("opencode_no_json_in_output", text_preview=full_text[:2000])
        return ReviewResult(
            success=False,
            raw_output=full_text,
            error_message="No JSON found in OpenCode output",
        )

    json_str = full_text[json_start:json_end + 1]

    try:
        data = json.loads(json_str)
    except json.JSONDecodeError:
        logger.error(
            "opencode_output_json_parse_failed",
            json_preview=json_str[:2000],
        )
        return ReviewResult(
            success=False,
            raw_output=full_text,
            error_message="Failed to parse review result as JSON",
        )

    summary = data.get("summary", "")
    raw_issues = data.get("issues", [])

    issues = []
    for item in raw_issues:
        if not item.get("file") or not item.get("desc"):
            continue
        issues.append(ReviewIssue(
            agent=item.get("agent", "unknown"),
            file=item.get("file", ""),
            line=int(item.get("line", 0)),
            level=item.get("level", "info"),
            desc=item.get("desc", ""),
            suggestion=item.get("suggestion", ""),
        ))

    level_order = {"error": 0, "warn": 1, "info": 2}
    issues.sort(key=lambda i: level_order.get(i.level, 3))

    logger.info("opencode_output_parsed", summary_len=len(summary), issue_count=len(issues))

    return ReviewResult(
        success=True,
        summary=summary,
        issues=issues,
        raw_output=full_text,
    )
