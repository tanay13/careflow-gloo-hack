"""Runtime configuration loaded from environment variables (.env supported)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

try:
    from dotenv import load_dotenv

    _ROOT = Path(__file__).resolve().parent.parent
    load_dotenv(_ROOT / ".env")
    load_dotenv(Path(__file__).resolve().parent / ".env")
except Exception:  # pragma: no cover - dotenv is optional
    pass

BACKEND_DIR = Path(__file__).resolve().parent
REPO_ROOT = BACKEND_DIR.parent
DATA_DIR = REPO_ROOT / "data"


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    database_url: str = os.getenv("DATABASE_URL", f"sqlite:///{BACKEND_DIR / 'careflow.db'}")
    use_mock_llm: bool = _bool("USE_MOCK_LLM", True)
    llm_api_key: str = os.getenv("LLM_API_KEY", "")
    llm_base_url: str = os.getenv("LLM_BASE_URL", "")
    llm_model: str = os.getenv("LLM_MODEL", "")
    llm_timeout_s: float = float(os.getenv("LLM_TIMEOUT_S", "25"))
    # Cost per 1K tokens (USD) used for the cost estimate shown in the UI.
    llm_cost_input_per_1k: float = float(os.getenv("LLM_COST_INPUT_PER_1K", "0.00015"))
    llm_cost_output_per_1k: float = float(os.getenv("LLM_COST_OUTPUT_PER_1K", "0.0006"))
    # Visible pacing between orchestration steps so a live audience can follow
    # the agent. Real backend state changes at each step; set 0 for evals.
    demo_step_delay_ms: int = int(os.getenv("DEMO_STEP_DELAY_MS", "450"))
    # Fixed demo clock for deterministic schedules (ISO local time, America/Denver assumed).
    demo_now: str = os.getenv("DEMO_NOW", "2026-10-06T09:00:00")
    approval_secret: str = os.getenv("APPROVAL_SECRET", "careflow-demo-secret-change-me")
    cors_origins: str = os.getenv("CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000")


settings = Settings()

# Mutable runtime overrides (e.g. evals disable step delay) without touching env.
RUNTIME = {"step_delay_ms": settings.demo_step_delay_ms}
