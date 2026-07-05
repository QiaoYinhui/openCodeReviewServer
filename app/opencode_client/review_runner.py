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

    stdin_data = json.dumps({
        "repo_path": repo_path,
        "diff_content": diff_content,
        "pr_info": {
            "repo_id": repo_id,
            "pr_number": pr_number,
            "source_branch": source_branch,
            "target_branch": target_branch,
        },
        "review_rules": settings.REVIEW_RULES,
    })

    cmd = [
        "bun",
        settings.OPENCODE_SCRIPT_PATH,
        "--print-logs",
        "--log-level", settings.OPENCODE_LOG_LEVEL,
        "--format", "json",
        "--agent", "review",
        "run",
    ]

    logger.info("opencode_review_starting", repo_path=repo_path, timeout=settings.REVIEW_TIMEOUT)

    try:
        result = subprocess.run(
            cmd,
            input=stdin_data,
            capture_output=True,
            text=True,
            timeout=settings.REVIEW_TIMEOUT,
            env=env,
        )

        if result.returncode != 0:
            logger.error(
                "opencode_review_failed",
                returncode=result.returncode,
                stderr=result.stderr[:2000],
            )
            return ReviewResult(
                success=False,
                raw_output=result.stdout,
                error_message=f"OpenCode exited with code {result.returncode}: {result.stderr[:500]}",
            )

        logger.info("opencode_review_completed", stdout_length=len(result.stdout))

        if result.stderr:
            logger.warning("opencode_stderr", stderr=result.stderr[:2000])

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
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        logger.error("opencode_output_json_parse_failed", output_preview=stdout[:1000])
        return ReviewResult(
            success=False,
            raw_output=stdout,
            error_message="Failed to parse OpenCode output as JSON",
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
        raw_output=stdout,
    )
