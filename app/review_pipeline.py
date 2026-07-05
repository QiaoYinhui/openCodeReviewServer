import asyncio

from app.webhook.pr_handler import PRMeta
from app.git_client.repo_clone import clone_and_diff, GitOperationError
from app.opencode_client.review_runner import run_opencode_review, ReviewResult
from app.result_handler.github_comment import post_review_comments, post_review_failure
from app.utils.file_util import ensure_temp_dir, cleanup_temp_dir
from app.utils.logger import get_logger, bind_request_id, unbind_request_id

logger = get_logger("pipeline")


async def execute_review_pipeline(pr_meta: PRMeta, request_id: str) -> None:
    bind_request_id(request_id)
    temp_path = None

    try:
        logger.info(
            "pipeline_started",
            repo=pr_meta.repo_full_name,
            pr=pr_meta.pr_number,
        )

        temp_path = ensure_temp_dir(pr_meta.repo_id, pr_meta.pr_number)

        try:
            local_path, diff_content = await asyncio.to_thread(
                clone_and_diff,
                pr_meta.git_http_url,
                pr_meta.source_branch,
                pr_meta.target_branch,
                temp_path,
            )
        except GitOperationError as e:
            logger.error("pipeline_git_clone_failed", error=str(e))
            post_review_failure(pr_meta, f"代码拉取失败: {str(e)}")
            return

        logger.info("pipeline_git_done", diff_length=len(diff_content))

        review_result: ReviewResult = await asyncio.to_thread(
            run_opencode_review,
            local_path,
            diff_content,
            pr_meta.repo_id,
            pr_meta.pr_number,
            pr_meta.source_branch,
            pr_meta.target_branch,
        )

        if not review_result.success:
            logger.error(
                "pipeline_review_failed",
                error=review_result.error_message,
            )
            post_review_failure(pr_meta, review_result.error_message)
            return

        logger.info(
            "pipeline_review_done",
            issues=review_result.issue_count,
            errors=review_result.error_count,
        )

        try:
            await asyncio.to_thread(post_review_comments, pr_meta, review_result)
        except Exception:
            logger.exception("pipeline_comment_failed")

        logger.info("pipeline_completed", repo=pr_meta.repo_full_name, pr=pr_meta.pr_number)

    except Exception:
        logger.exception("pipeline_unexpected_error")
        try:
            post_review_failure(pr_meta, "评审流程出现未知异常")
        except Exception:
            logger.exception("pipeline_failure_notice_failed")
    finally:
        if temp_path:
            cleanup_temp_dir(temp_path)
        unbind_request_id()
