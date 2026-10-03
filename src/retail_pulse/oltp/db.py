from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL, create_engine
from sqlalchemy.orm import sessionmaker


class PostgresSettings(BaseSettings):
    """Đọc từ biến môi trường hoặc .env với tiền tố PG_ (PG_HOST, PG_USER, ...)."""

    model_config = SettingsConfigDict(env_file=".env", env_prefix="PG_", extra="ignore")

    host: str = "localhost"
    port: int = 5432
    user: str = "retail"
    password: str = "retail"
    db: str = "retail_oltp"

    @property
    def url(self) -> URL:
        return URL.create(
            "postgresql+psycopg",
            username=self.user,
            password=self.password,
            host=self.host,
            port=self.port,
            database=self.db,
        )


settings = PostgresSettings()
engine = create_engine(settings.url, pool_pre_ping=True)
SessionLocal = sessionmaker(engine, expire_on_commit=False)
