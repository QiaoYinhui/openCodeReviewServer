import hashlib
import hmac
from dataclasses import dataclass

from fastapi import Request, HTTPException, BackgroundTasks

from app.config import settings
from app.utils.logger import get_logger, generate_request_id, bind_request_id

logger = get_logger("webhook")

ALLOWED_ACTIONS = {"opened", "synchronize", "reopened"}


@dataclass
class PRMeta:
    repo_id: int
    pr_number: int
    source_branch: str
    target_branch: str
    git_http_url: str
    base_commit: str
    head_commit: str
    repo_full_name: str


def verify_signature(payload_body: bytes, signature: str) -> bool:
    if not settings.GITHUB_WEBHOOK_SECRET:
        logger.warning("webhook_secret_not_configured")
        return False
    secret = settings.GITHUB_WEBHOOK_SECRET.encode("utf-8")
    expected = "sha256=" + hmac.new(secret, payload_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def parse_pr_event(payload: dict) -> PRMeta:
    pr = payload["pull_request"]
    repo = payload["repository"]
    return PRMeta(
        repo_id=repo["id"],
        pr_number=pr["number"],
        source_branch=pr["head"]["ref"],
        target_branch=pr["base"]["ref"],
        git_http_url=repo["clone_url"],
        base_commit=pr["base"]["sha"],
        head_commit=pr["head"]["sha"],
        repo_full_name=repo["full_name"],
    )


async def handle_pr_webhook(request: Request, background_tasks: BackgroundTasks) -> dict:
    request_id = generate_request_id()
    bind_request_id(request_id)

    signature = request.headers.get("X-Hub-Signature-256", "")
    payload_body = await request.body()

    if not verify_signature(payload_body, signature):
        logger.warning("webhook_signature_invalid")
        raise HTTPException(status_code=403, detail="Invalid signature")

    payload = await request.json()

    action = payload.get("action", "")
    if action not in ALLOWED_ACTIONS:
        logger.info("webhook_action_filtered", action=action)
        return {"status": "ignored", "reason": f"action={action}"}

    pr = payload.get("pull_request", {})
    if pr.get("draft", False):
        logger.info("webhook_draft_pr_skipped")
        return {"status": "ignored", "reason": "draft_pr"}

    pr_meta = parse_pr_event(payload)
    logger.info(
        "webhook_received",
        repo=pr_meta.repo_full_name,
        pr_number=pr_meta.pr_number,
        action=action,
        source_branch=pr_meta.source_branch,
        target_branch=pr_meta.target_branch,
    )

    from app.review_pipeline import execute_review_pipeline
    background_tasks.add_task(execute_review_pipeline, pr_meta, request_id)

    return {"status": "accepted", "request_id": request_id}
