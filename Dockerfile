FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml uv.lock* ./
COPY src ./src

RUN pip install --no-cache-dir .

ENV HOST=0.0.0.0 \
    PORT=8000

EXPOSE 8000

CMD ["python", "-m", "ollama_proxy"]
