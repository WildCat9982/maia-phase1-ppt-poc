"""Settings, read from environment variables (or a .env file).

Switching from OpenAI to the on-premise Qwen server is a config change:
set LLM_BASE_URL to the Qwen OpenAI-compatible endpoint and LLM_MODEL to its name.
"""

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


def _bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    # "openai" calls a real OpenAI-compatible endpoint; "mock" returns canned
    # answers so the POC can be demoed and tested without any model.
    llm_provider: str = os.getenv("LLM_PROVIDER", "openai")
    llm_base_url: str | None = os.getenv("LLM_BASE_URL") or None  # None = api.openai.com
    llm_api_key: str = os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY", "")
    llm_model: str = os.getenv("LLM_MODEL", "gpt-4o-mini")
    llm_timeout_s: float = float(os.getenv("LLM_TIMEOUT_S", "120"))
    llm_max_concurrency: int = int(os.getenv("LLM_MAX_CONCURRENCY", "4"))
    llm_json_mode: bool = _bool("LLM_JSON_MODE", True)

    mask_pii: bool = _bool("MASK_PII", True)
    max_upload_mb: int = int(os.getenv("MAX_UPLOAD_MB", "20"))
    # Optional default template (.pptx or .potx) used when the user uploads none.
    template_path: str | None = os.getenv("TEMPLATE_PATH") or None


settings = Settings()
