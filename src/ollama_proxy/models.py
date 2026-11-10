import os

from dotenv import load_dotenv

load_dotenv()

"""Supported Ollama model names."""

MODEL_GEMMA_CELESTIAL = os.getenv("MODEL_GEMMA_CELESTIAL", "qwen2.5:3b")
MODEL_GEMMA_CODE_PRO = os.getenv("MODEL_GEMMA_CODE_PRO", "qwen2.5:3b")
MODEL_GEMMA4_CLOUD = os.getenv("MODEL_GEMMA4_CLOUD", "qwen2.5:3b")

SUPPORTED_MODELS = (
    MODEL_GEMMA_CELESTIAL,
    MODEL_GEMMA_CODE_PRO,
    MODEL_GEMMA4_CLOUD,
)
