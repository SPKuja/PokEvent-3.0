from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="POKEVENT_",
        env_file=".env",
        extra="ignore",
    )

    database_url: str = "sqlite+aiosqlite:///./data/pokevent.db"
    discord_token: str | None = None
    public_base_url: str = "http://localhost:8080"

    community_name: str = "Pokémon League Swindon"

    # Stable Play! Pokémon League IDs mapped to human-friendly names.
    # Discord routing and organisation identity use the ID; the name is display only.
    leagues: dict[str, str] = Field(default_factory=dict)

    # Discovery is service-level, not guild-level. It lets PokEvent find nearby
    # Leagues that are not in the explicit league registry yet.
    home_name: str = "Swindon"
    home_latitude: float = 51.5615
    home_longitude: float = -1.7855
    default_radius_miles: float = 30.0

    event_source: str = "pokedata"
    sync_interval_minutes: int = 180


@lru_cache
def get_settings() -> Settings:
    return Settings()
