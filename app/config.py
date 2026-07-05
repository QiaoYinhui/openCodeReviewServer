from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    SERVER_HOST: str = "0.0.0.0"
    SERVER_PORT: int = 8000

    GITHUB_BASE_URL: str = "https://api.github.com"
    GITHUB_PERSONAL_TOKEN: str = ""
    GITHUB_WEBHOOK_SECRET: str = ""

    OPENCODE_SCRIPT_PATH: str = ""
    OPENCODE_CONFIG_PATH: str = ""
    OPENCODE_REVIEW_CONFIG_PATH: str = ""
    OPENCODE_LOG_LEVEL: str = "info"

    REVIEW_TIMEOUT: int = 300
    TEMP_CODE_ROOT: str = "/tmp/opencode_review"

    BUN_MAX_HEAP_SIZE: int = 2684354560

    REVIEW_RULES: list[str] = Field(
        default=["code_style", "security", "logic_bug", "performance"]
    )

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
