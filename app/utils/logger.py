import logging
import sys
import uuid

import structlog


def generate_request_id() -> str:
    return uuid.uuid4().hex[:12]


def setup_logger(level: str = "INFO") -> structlog.stdlib.BoundLogger:
    logging.basicConfig(
        format="%(message)s",
        level=getattr(logging, level.upper(), logging.INFO),
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    return get_logger("root")


def get_logger(module: str) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(module=module)


def bind_request_id(request_id: str) -> None:
    structlog.contextvars.bind_contextvars(request_id=request_id)


def unbind_request_id() -> None:
    structlog.contextvars.unbind_contextvars("request_id")
