import subprocess

from app.utils.logger import get_logger

logger = get_logger("git_client")


class GitOperationError(Exception):
    pass


def _run_git(args: list[str], cwd: str | None = None, timeout: int = 120) -> str:
    cmd = ["git"] + args
    logger.info("git_command", cmd=" ".join(cmd), cwd=cwd)
    try:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode != 0:
            logger.error("git_command_failed", cmd=" ".join(cmd), stderr=result.stderr)
            raise GitOperationError(f"git command failed: {result.stderr.strip()}")
        return result.stdout
    except subprocess.TimeoutExpired:
        logger.error("git_command_timeout", cmd=" ".join(cmd), timeout=timeout)
        raise GitOperationError(f"git command timed out after {timeout}s")


def clone_and_diff(
    git_http_url: str,
    source_branch: str,
    target_branch: str,
    local_path: str,
) -> tuple[str, str]:
    _run_git([
        "clone",
        "--branch", source_branch,
        "--depth", "50",
        "--single-branch",
        git_http_url,
        local_path,
    ])
    logger.info("git_clone_done", source_branch=source_branch, path=local_path)

    _run_git(
        ["fetch", "origin", target_branch, "--depth", "50"],
        cwd=local_path,
    )
    logger.info("git_fetch_target_done", target_branch=target_branch)

    diff_content = _run_git(
        ["diff", f"origin/{target_branch}...origin/{source_branch}"],
        cwd=local_path,
    )
    logger.info("git_diff_generated", diff_length=len(diff_content))

    return local_path, diff_content
