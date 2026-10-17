from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = PROJECT_ROOT / ".env"
ENV_EXAMPLE_FILE = PROJECT_ROOT / ".env.example"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ENV_FILE, env_file_encoding="utf-8", extra="ignore")

    app_name: str = "文献分类工作台"
    app_data_dir: Path = Path("data")
    database_url: str = "sqlite:///data/literature.db"
    max_upload_mb: int = 40
    classification_concurrency: int = 4
    typesafe_api_key: str = ""
    typesafe_model: str = "jev-latest"
    generation_api_key: str = ""
    generation_base_url: str = "https://api.siliconflow.cn/v1"
    generation_model: str = "deepseek-ai/DeepSeek-V4-Flash"

    @property
    def uploads_dir(self) -> Path:
        return self.app_data_dir / "uploads"

    def ensure_directories(self) -> None:
        self.app_data_dir.mkdir(parents=True, exist_ok=True)
        self.uploads_dir.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_directories()
    return settings


def update_model_env(values: dict[str, str]) -> None:
    lines = (
        ENV_FILE.read_text(encoding="utf-8").splitlines()
        if ENV_FILE.exists()
        else ENV_EXAMPLE_FILE.read_text(encoding="utf-8").splitlines()
    )
    remaining = dict(values)
    for index, line in enumerate(lines):
        stripped = line.lstrip()
        for key in list(remaining):
            if stripped.startswith(f"{key}="):
                indent = line[: len(line) - len(stripped)]
                lines[index] = f"{indent}{key}={_env_value(remaining.pop(key))}"
                break
    if remaining and lines and lines[-1]:
        lines.append("")
    lines.extend(f"{key}={_env_value(value)}" for key, value in remaining.items())

    temporary = ENV_FILE.with_name(".env.tmp")
    temporary.write_text("\n".join(lines) + "\n", encoding="utf-8")
    temporary.replace(ENV_FILE)


def _env_value(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'
