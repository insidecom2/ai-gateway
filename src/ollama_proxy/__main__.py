import uvicorn

from .config import Settings


if __name__ == "__main__":
    settings = Settings.from_env()
    uvicorn.run("ollama_proxy.app:app", host=settings.host, port=settings.port)
