import os
import shutil

from app.config import settings
from app.utils.logger import get_logger

logger = get_logger("file_util")


def build_temp_dir(repo_id: int, pr_number: int) -> str:
    return os.path.join(settings.TEMP_CODE_ROOT, f"pr_{repo_id}_{pr_number}")


def ensure_temp_dir(repo_id: int, pr_number: int) -> str:
    path = build_temp_dir(repo_id, pr_number)
    if os.path.exists(path):
        cleanup_temp_dir(path)
    os.makedirs(path, exist_ok=True)
    logger.info("temp_dir_created", path=path)
    return path


def cleanup_temp_dir(path: str) -> None:
    if not os.path.exists(path):
        return
    try:
        shutil.rmtree(path)
        logger.info("temp_dir_cleaned", path=path)
    except Exception:
        logger.exception("temp_dir_cleanup_failed", path=path)
