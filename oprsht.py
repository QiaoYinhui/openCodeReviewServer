from fastapi import FastAPI, Request, BackgroundTasks

from app.config import settings
from app.utils.logger import setup_logger, get_logger
from app.webhook.pr_handler import handle_pr_webhook

setup_logger()
logger = get_logger("main")

app = FastAPI(title="OpenCode Review Service", version="1.0.0")


@app.on_event("startup")
async def startup():
    logger.info(
        "service_starting",
        host=settings.SERVER_HOST,
        port=settings.SERVER_PORT,
        temp_code_root=settings.TEMP_CODE_ROOT,
        review_timeout=settings.REVIEW_TIMEOUT,
    )
    if not settings.GITHUB_PERSONAL_TOKEN:
        logger.warning("github_token_not_configured")
    if not settings.OPENCODE_SCRIPT_PATH:
        logger.warning("opencode_script_path_not_configured")


@app.post("/github/webhook/pr")
async def github_webhook(request: Request, background_tasks: BackgroundTasks):
    return await handle_pr_webhook(request, background_tasks)


@app.get("/health")
async def health_check():
    return {"status": "ok"}
