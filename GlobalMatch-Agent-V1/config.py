"""
GlobalMatch-Agent-V1 全局配置模块
启动时验证所有必需环境变量，缺失立即报错
"""
import os
import sys
import structlog
from pathlib import Path
from pydantic_settings import BaseSettings
from pydantic import Field, validator
from typing import Optional
from dotenv import load_dotenv

# 加载.env文件
load_dotenv()

logger = structlog.get_logger(__name__)


class Settings(BaseSettings):
    """全局配置，从环境变量读取，缺失必需项启动时立即报错"""

    # ---- 应用 ----
    APP_ENV: str = Field(default="development")
    APP_SECRET_KEY: str = Field(default="dev_secret_key_change_in_production")
    DEBUG: bool = Field(default=False)
    LOG_LEVEL: str = Field(default="INFO")

    # ---- Kimi API（必需）----
    KIMI_API_KEY: str = Field(...)
    KIMI_BASE_URL: str = Field(default="https://api.moonshot.cn/v1")
    KIMI_MODEL: str = Field(default="moonshot-v1-8k")

    # ---- Supabase（必需）----
    SUPABASE_URL: str = Field(...)
    SUPABASE_KEY: str = Field(...)
    SUPABASE_SERVICE_ROLE_KEY: Optional[str] = Field(default=None)

    # ---- Redis（必需）----
    REDIS_URL: str = Field(default="redis://localhost:6379/0")
    CELERY_BROKER_URL: str = Field(default="redis://localhost:6379/0")
    CELERY_RESULT_BACKEND: str = Field(default="redis://localhost:6379/1")

    # ---- SMTP邮件（可选，用户在设置页填）----
    SMTP_HOST: Optional[str] = Field(default=None)
    SMTP_PORT: int = Field(default=587)
    SMTP_USER: Optional[str] = Field(default=None)
    SMTP_PASSWORD: Optional[str] = Field(default=None)
    SMTP_USE_TLS: bool = Field(default=True)
    SMTP_FROM_NAME: str = Field(default="GlobalMatch")

    # ---- IMAP邮件（可选）----
    IMAP_HOST: Optional[str] = Field(default=None)
    IMAP_PORT: int = Field(default=993)
    IMAP_USER: Optional[str] = Field(default=None)
    IMAP_PASSWORD: Optional[str] = Field(default=None)
    IMAP_USE_SSL: bool = Field(default=True)

    # ---- Server酱微信通知（可选）----
    SERVERCHAN_SEND_KEY: Optional[str] = Field(default=None)

    # ---- WhatsApp（可选）----
    WHATSAPP_TOKEN: Optional[str] = Field(default=None)
    WHATSAPP_PHONE_NUMBER_ID: Optional[str] = Field(default=None)

    # ---- 爬虫配置 ----
    PLAYWRIGHT_HEADLESS: bool = Field(default=True)
    PLAYWRIGHT_TIMEOUT: int = Field(default=30000)
    SCRAPER_MAX_RETRIES: int = Field(default=3)
    SCRAPER_DELAY_MIN: float = Field(default=1.0)
    SCRAPER_DELAY_MAX: float = Field(default=3.0)
    MAX_RESULTS_PER_SOURCE: int = Field(default=50)

    # ---- Chainlit ----
    CHAINLIT_NO_AUTH: bool = Field(default=True)
    CHAINLIT_AUTH_SECRET: str = Field(default="dev_chainlit_secret")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True
        extra = "ignore"


def get_settings() -> Settings:
    """获取配置单例，启动时验证必需项"""
    try:
        settings = Settings()
        return settings
    except Exception as e:
        print(f"\n[FATAL] 环境变量配置错误，请检查 .env 文件:\n{e}\n")
        print("提示: 复制 .env.example 为 .env 并填入真实值\n")
        sys.exit(1)


# 全局单例
settings = get_settings()


# ---- 项目路径 ----
BASE_DIR = Path(__file__).parent
FALLBACK_DIR = BASE_DIR / "fallback"
FALLBACK_DIR.mkdir(exist_ok=True)

# ---- 数据源优先级列表（按容错顺序）----
DATA_SOURCES_PRIORITY = [
    "importyeti",        # 1. 北美进口商
    "kompass",           # 2. 全球商业目录
    "alibaba_rfq",       # 3. 阿里国际站RFQ
    "google",            # 4. Google搜索
    "europages",         # 5. 欧洲最大B2B
    "yellowpages",       # 6. 黄页
    "tradeindia",        # 7. 印度/东南亚B2B
    "ec21",              # 8. 全亚洲
    "linkedin",          # 9. LinkedIn公开页
    "piers",             # 10. 美国海关数据
    "thomasnet",         # 11. 美国工业买家
    "hoovers",           # 12. 邓白氏
    "wlw",               # 13. 德国工业买家
    "kellysearch",       # 14. 英国
    "zawya",             # 15. 中东
    "tradearabia",       # 16. 中东
    "exportersindia",    # 17. 印度出口商
    "tradekey",          # 18. 中东+非洲
    "tradewheel",        # 19. 买家询价
    "exporthub",         # 20. 全球补充
]

# ---- 爬虫用户代理池 ----
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.1 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36 Edg/130.0.0.0",
]

# ---- Celery任务配置 ----
CELERY_TASK_SOFT_TIME_LIMIT = 1800  # 30分钟软超时
CELERY_TASK_TIME_LIMIT = 2100       # 35分钟硬超时
CELERY_MAX_RETRIES = 3

# ---- 邮件发送限速 ----
EMAIL_RATE_LIMIT_PER_MINUTE = 5
EMAIL_DELAY_MIN = 5   # 秒
EMAIL_DELAY_MAX = 30  # 秒

# ---- 买家数据时效 ----
BUYER_DATA_EXPIRE_DAYS = 30

# ---- 单次任务最大总超时 ----
TASK_MAX_DURATION_SECONDS = 1800  # 30分钟

# ---- IMAP监控间隔 ----
IMAP_POLL_INTERVAL_MINUTES = 15
