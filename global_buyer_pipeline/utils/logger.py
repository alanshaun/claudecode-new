"""structlog 日志配置（兼容 GitHub Actions / PrintLogger 无 disabled 问题）"""
import logging
import structlog

# 使用 stdlib Logger，避免 filter_by_level 访问 logger.disabled 时 AttributeError
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer(),
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)
logging.basicConfig(format="%(message)s", level=logging.INFO)


def get_logger():
    return structlog.get_logger()
