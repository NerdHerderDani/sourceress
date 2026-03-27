from pydantic import BaseModel
from dotenv import load_dotenv
import os

load_dotenv()

class Settings(BaseModel):
    env: str = os.getenv("ENV", "dev").strip().lower()  # dev|prod

    github_token: str = os.getenv("GITHUB_TOKEN", "").strip()
    # Prefer DATABASE_URL (common on hosting platforms), fallback to DB_URL for local/dev.
    db_url: str = (os.getenv("DATABASE_URL") or os.getenv("DB_URL") or "sqlite:///./data/app.db").strip()

    supabase_url: str = os.getenv("SUPABASE_URL", "").strip()
    supabase_anon_key: str = os.getenv("SUPABASE_ANON_KEY", "").strip()
    supabase_jwt_secret: str = os.getenv("SUPABASE_JWT_SECRET", "").strip()

    app_secret_key: str = os.getenv("APP_SECRET_KEY", "").strip()

    allowlist_emails: str = os.getenv("ALLOWLIST_EMAILS", "").strip()

    default_location: str = os.getenv("DEFAULT_LOCATION", "").strip()
    default_min_followers: int = int(os.getenv("DEFAULT_MIN_FOLLOWERS", "0"))
    default_active_days: int = int(os.getenv("DEFAULT_ACTIVE_DAYS", "180"))

    # Ashby public job postings API
    # Example endpoint: https://api.ashbyhq.com/posting-api/job-board/{JOB_BOARD_NAME}
    ashby_job_board_name: str = os.getenv("ASHBY_JOB_BOARD_NAME", "ava-labs").strip()
    ashby_include_compensation: bool = os.getenv("ASHBY_INCLUDE_COMPENSATION", "false").strip().lower() in ("1", "true", "yes", "y")

settings = Settings()
