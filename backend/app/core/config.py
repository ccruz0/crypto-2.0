from pydantic_settings import BaseSettings
import os

class Settings(BaseSettings):
    # Database
    POSTGRES_USER: str = "trader"
    POSTGRES_PASSWORD: str = "traderpass"
    POSTGRES_DB: str = "atp"
    POSTGRES_HOST: str = "db"
    POSTGRES_PORT: str = "5432"
    
    @property
    def DATABASE_URL(self) -> str:
        return f"postgresql://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"

settings = Settings()
