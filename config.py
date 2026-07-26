from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date
from zoneinfo import ZoneInfo


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


@dataclass(frozen=True)
class Config:
    app_secret: str = os.getenv("APP_SECRET", "dev-only-change-me")
    app_password: str = os.getenv("APP_PASSWORD", "")
    timezone_name: str = os.getenv("APP_TIMEZONE", "Asia/Shanghai")
    start_date: str = os.getenv("START_DATE", "2024-09-01")
    user_name: str = os.getenv("USER_NAME", "断云去")
    ai_name: str = os.getenv("AI_NAME", "余天骋")

    api_url: str = os.getenv("API_URL", "").rstrip("/")
    api_key: str = os.getenv("API_KEY", "")
    api_model: str = os.getenv("API_MODEL", "")
    system_prompt: str = os.getenv(
        "SYSTEM_PROMPT",
        "你是余天骋，正在与断云去自然地生活和聊天。",
    )

    supabase_url: str = os.getenv("SUPABASE_URL", "")
    supabase_key: str = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    storage_bucket: str = os.getenv("SUPABASE_STORAGE_BUCKET", "home-attachments")

    ombre_url: str = os.getenv("OMBRE_BRAIN_MCP_URL", "").rstrip("/")
    ombre_token: str = os.getenv("OMBRE_BRAIN_ACCESS_TOKEN", "")
    ombre_enabled: bool = env_bool("OMBRE_BRAIN_ENABLED", False)

    reading_url: str = os.getenv("CO_READING_URL", "").rstrip("/")
    reading_mcp_url: str = os.getenv("CO_READING_MCP_URL", "").rstrip("/")
    reading_token: str = os.getenv("CO_READING_ACCESS_TOKEN", "")

    image_provider: str = os.getenv("IMAGE_PROVIDER", "").strip().lower()
    image_url: str = os.getenv("IMAGE_API_URL", "").rstrip("/")
    image_key: str = os.getenv("IMAGE_API_KEY", "")
    image_model: str = os.getenv("IMAGE_MODEL", "")
    nai_sampler: str = os.getenv("NAI_SAMPLER", "k_euler_ancestral")
    nai_steps: int = env_int("NAI_STEPS", 28)
    nai_scale: float = env_float("NAI_SCALE", 5.0)

    weather_latitude: str = os.getenv("WEATHER_LATITUDE", "31.2304")
    weather_longitude: str = os.getenv("WEATHER_LONGITUDE", "121.4737")
    weather_location: str = os.getenv("WEATHER_LOCATION", "上海")

    proactive_enabled: bool = env_bool("PROACTIVE_ENABLED", False)
    proactive_idle_minutes: int = env_int("PROACTIVE_MIN_IDLE_MINUTES", 180)
    cron_secret: str = os.getenv("CRON_SECRET", "")

    @property
    def timezone(self) -> ZoneInfo:
        try:
            return ZoneInfo(self.timezone_name)
        except Exception:
            return ZoneInfo("Asia/Shanghai")

    @property
    def start_day(self) -> date:
        try:
            return date.fromisoformat(self.start_date)
        except ValueError:
            return date(2024, 9, 1)

    @property
    def ai_ready(self) -> bool:
        return bool(self.api_url and self.api_key and self.api_model)

    @property
    def supabase_ready(self) -> bool:
        return bool(self.supabase_url and self.supabase_key)

    @property
    def image_ready(self) -> bool:
        return bool(
            self.image_provider
            and self.image_url
            and self.image_key
            and self.image_model
        )
