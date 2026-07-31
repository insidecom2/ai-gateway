from dataclasses import dataclass
import os

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    api_token: str
    ollama_url: str
    host: str = "127.0.0.1"
    port: int = 8000
    timeout_seconds: float = 120.0

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            api_token=os.getenv("API_TOKEN", ""),
            ollama_url=os.getenv("OLLAMA_URL", "").rstrip("/"),
            host=os.getenv("HOST", cls.host),
            port=int(os.getenv("PORT", str(cls.port))),
            timeout_seconds=float(os.getenv("OLLAMA_TIMEOUT_SECONDS", str(cls.timeout_seconds))),
        )
