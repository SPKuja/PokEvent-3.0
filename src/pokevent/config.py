from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="POKEVENT_",
        env_file=".env",
        extra="ignore",
    )

    database_url: str = "sqlite+aiosqlite:////data/pokevent.db"
    discord_token: str | None = None
    public_base_url: str = "http://localhost:8080"

    community_name: str = "Pokémon League Swindon"
    home_name: str = "Swindon"
    home_latitude: float = 51.5615
    home_longitude: float = -1.7855
    default_radius_miles: float = 30.0

    sync_interval_minutes: int = 180


@lru_cache
def get_settings() -> Settings:
    return Settings()
