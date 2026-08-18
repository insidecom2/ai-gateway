import argparse
import asyncio
import json
import os

import httpx
from dotenv import load_dotenv

from ollama_proxy.astrology import THAI_CITIES, build_prompt, cast_chart, fetch_context, format_chart
from ollama_proxy.turso import TursoAdapter

load_dotenv()

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
PROXY_URL = os.getenv("PROXY_URL", "http://127.0.0.1:8000")
API_TOKEN = os.getenv("API_TOKEN", "")


async def ask_ollama(client: httpx.AsyncClient, model: str, prompt: str, stream: bool) -> str:
    url = f"{PROXY_URL}/api/generate"
    headers = {"Authorization": f"Bearer {API_TOKEN}", "Content-Type": "application/json"}
    payload = {"model": model, "prompt": prompt, "stream": stream}
    resp = await client.post(url, headers=headers, json=payload, timeout=180)
    resp.raise_for_status()
    if stream:
        full = ""
        for line in resp.iter_lines():
            if not line:
                continue
            data = json.loads(line)
            full += data.get("response", "")
            if data.get("done"):
                break
        return full
    return resp.json().get("response", "")


async def main() -> None:
    parser = argparse.ArgumentParser(description="ค้นความรู้ดูดวงจาก Turso แล้วถาม Ollama")
    parser.add_argument("question", nargs="+", help="คำถามที่อยากให้วิเคราะห์")
    parser.add_argument("--model", default=os.getenv("OLLAMA_MODEL", "qwen-coder-3b:latest"))
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--stream", action="store_true")
    parser.add_argument("--direct", action="store_true", help="ข้าม proxy ไปหา Ollama ตรง ๆ")
    parser.add_argument("--date", help="วันเกิด YYYY-MM-DD (ผูกดวงก่อนถาม)")
    parser.add_argument("--time", help="เวลาเกิด HH:MM")
    parser.add_argument("--place", help="เมืองเกิด (เช่น กรุงเทพ) หรือระบุ --lat --lon")
    parser.add_argument("--lat", type=float)
    parser.add_argument("--lon", type=float)
    parser.add_argument("--tz", type=float, default=7.0)
    args = parser.parse_args()

    chart_text = None
    chart = None
    if args.date and args.time:
        if args.place:
            if args.place not in THAI_CITIES:
                raise SystemExit(f"ไม่รู้จักเมือง '{args.place}' ใช้ --lat/--lon แทน")
            lat, lon = THAI_CITIES[args.place]
        elif args.lat is not None and args.lon is not None:
            lat, lon = args.lat, args.lon
        else:
            raise SystemExit("ต้องระบุ --place หรือ --lat + --lon")
        chart = cast_chart(args.date, args.time, lat, lon, args.tz)
        chart_text = format_chart(chart)

    ollama_url = OLLAMA_URL if args.direct else PROXY_URL
    question = " ".join(args.question)
    async with httpx.AsyncClient() as client:
        adapter = TursoAdapter.from_env()
        try:
            await adapter.connect()
            chunks = await fetch_context(adapter, question, args.top_k, chart)
        finally:
            await adapter.close()
        if not any("content" in c for c in chunks):
            print("ไม่พบความรู้ที่เกี่ยวข้องในฐานข้อมูล")
            return
        prompt = build_prompt(question, chunks, chart_text)
        print(f"--- context ({len([c for c in chunks if 'content' in c])} chunks) ---")
        answer = await ask_ollama(client, args.model, prompt, args.stream)
    print("\n--- คำตอบจาก Ollama ---")
    print(answer)


if __name__ == "__main__":
    asyncio.run(main())