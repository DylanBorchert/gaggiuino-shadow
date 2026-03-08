from pydantic_settings import BaseSettings


class Config(BaseSettings):
    gaggiuino_url: str = "http://gaggiuino.local"
    poll_interval: int = 30
    full_sync_interval: int = 600
    db_path: str = "/data/gaggiuino_shadow.db"
    log_level: str = "INFO"
    status_history_max_age_days: int = 30
    health_history_max_age_days: int = 90
