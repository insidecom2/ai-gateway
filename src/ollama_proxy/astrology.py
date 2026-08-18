"""ดูดวง pipeline: ผูกดวง (Swiss Ephemeris) + ดึงความรู้ Turso + ถาม Ollama."""

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any

import httpx
import swisseph as swe

from .turso import TursoAdapter

ZODIAC_TH = [
    "เมษ", "พฤษภ", "เมถุน", "กรกฎ", "สิงห์", "กันย์",
    "ตุลย์", "พิจิก", "ธนู", "มังกร", "กุมภ์", "มีน",
]

THAI_PLANETS = [
    (swe.SUN, "อาทิตย์", "sun"),
    (swe.MOON, "จันทร์", "moon"),
    (swe.MARS, "อังคาร", "mars"),
    (swe.MERCURY, "พุธ", "mercury"),
    (swe.JUPITER, "พฤหัสบดี", "jupiter"),
    (swe.VENUS, "ศุกร์", "venus"),
    (swe.SATURN, "เสาร์", "saturn"),
]

THAI_CITIES = {
    "กรุงเทพ": (13.7563, 100.5018),
    "เชียงใหม่": (18.7883, 98.9853),
    "ภูเก็ต": (7.8804, 98.3923),
    "ชลบุรี": (13.3611, 100.9847),
    "ขอนแก่น": (16.4419, 102.8359),
    "สงขลา": (7.1756, 100.6141),
    "นครราชสีมา": (14.9799, 102.0977),
    "อุดรธานี": (17.413, 102.7895),
}

SYSTEM_PROMPT = """คุณคือผู้เชี่ยวชาญโหราศาสตร์ไทย ให้ใช้เฉพาะความรู้ที่กำหนดให้เท่านั้น
อย่าเดาหรือแต่งข้อเท็จจริงนอกบริบทที่ให้ คำตอบต้องอ้างอิงแหล่งที่มา (document_key / chunk_key / source_locator)
ถ้ามีข้อมูล "ดวงกำเนิด" ให้เริ่มวิเคราะห์จากตำแหน่งดาว ลัคนา และเรือนในดวงกำเนิดนั้นก่อนเสมอ
แล้วนำความรู้ที่กำหนดให้มาสนับสนุน พร้อมชี้จุดเด่น จุดที่ต้องระวัง และข้อแนะนำที่เป็นรูปธรรมจากดวง
อย่าให้คำตอบในเชิงรับประกันหรือวินิจฉัยทางการแพทย์/กฎหมาย/การเงิน"""

_THAI_STOPWORDS = [
    "อยากรู้", "อยากให้", "อยากดู", "อยาก", "วิเคราะห์ให้", "วิเคราะห์",
    "ดูดวง", "ดวง", "ของ", "ช่วย", "หน่อย", "ที", "เลย", "ให้", "ที่",
    "เรื่อง", "เกี่ยวกับ", "อย่างไร", "ยังไง", "ไหม", "มั้ย", "ครับ",
    "ค่ะ", "นะ", "แล้ว", "และ", "หรือ", "แต่", "ว่า", "ได้", "จะ",
    "คง", "นี่", "ปีนี้", "ปีที่แล้ว", "บอก", "ส่ง", "หา", "ข้อมูล",
    "ขอดู", "ขอ", "ผม", "ฉัน", "เป็น", "ให้หน่อย", "ไป",
]

_KEYWORD_SQL = """
SELECT c.content, c.content_summary, c.category, c.topic,
       c.planet_code, c.planet_name, c.house_number, c.zodiac_sign,
       c.keywords_json, c.chunk_key, d.document_key, c.source_locator
FROM knowledge_chunks c
JOIN documents d ON c.document_id = d.document_id
WHERE c.content LIKE ? OR c.topic LIKE ? OR c.category LIKE ?
ORDER BY c.chunk_id
LIMIT ?
"""

_CHART_ENTITIES_SQL = """
SELECT c.content, c.content_summary, c.category, c.topic,
       c.planet_code, c.planet_name, c.house_number, c.zodiac_sign,
       c.keywords_json, c.chunk_key, d.document_key, c.source_locator
FROM knowledge_chunks c
JOIN documents d ON c.document_id = d.document_id
WHERE {column} IN ({placeholders})
ORDER BY c.chunk_id
"""

SYSTEMS_SQL = """
SELECT display_name, description, house_method, ayanamsa_note
FROM astrology_systems
WHERE is_active = 1
"""


def _houses(jd_ut: float, lat: float, lon: float) -> tuple[float, list[float]]:
    cusps, ascmc = swe.houses(jd_ut, lat, lon, b"W")
    return float(ascmc[0]), list(cusps)


def _planet_house(asc: float, cusps: list[float], lon: float) -> int:
    for i in range(12):
        c1, c2 = cusps[i], cusps[(i + 1) % 12]
        span = (c2 - c1) % 360
        offset = (lon - c1) % 360
        if offset < span:
            return i + 1
    return 1


def cast_chart(
    birth_date: str,
    birth_time: str,
    lat: float,
    lon: float,
    tz_hours: float = 7.0,
    sidereal: bool = True,
) -> dict[str, Any]:
    dt = datetime.strptime(f"{birth_date} {birth_time}", "%Y-%m-%d %H:%M")
    flag = swe.FLG_SWIEPH | swe.FLG_SPEED | swe.FLG_SIDEREAL if sidereal else swe.FLG_SWIEPH | swe.FLG_SPEED
    if sidereal:
        swe.set_sid_mode(swe.SIDM_LAHIRI)
    utc_time = swe.utc_time_zone(dt.year, dt.month, dt.day, dt.hour, dt.minute, 0, -tz_hours)
    jd_ut = swe.utc_to_jd(utc_time[0], utc_time[1], utc_time[2], utc_time[3], utc_time[4], utc_time[5])[1]

    asc, cusps = _houses(jd_ut, lat, lon)

    planets: dict[str, dict[str, Any]] = {}
    for body, thai, code in THAI_PLANETS + [(10, "ราหู", "rahu"), (11, "เกตุ", "ketu")]:
        xx, _ = swe.calc_ut(jd_ut, body, flag)
        lon_pos = xx[0]
        planets[code] = {
            "name_th": thai,
            "longitude": round(lon_pos, 4),
            "zodiac": ZODIAC_TH[int(lon_pos // 30) % 12],
            "zodiac_number": int(lon_pos // 30) % 12 + 1,
            "degree_in_sign": round(lon_pos % 30, 4),
            "house": _planet_house(asc, cusps, lon_pos),
        }

    return {
        "birth_date": birth_date,
        "birth_time": birth_time,
        "lat": lat,
        "lon": lon,
        "tz_hours": tz_hours,
        "sidereal": sidereal,
        "ascendant": {
            "longitude": round(asc, 4),
            "zodiac": ZODIAC_TH[int(asc // 30) % 12],
            "zodiac_number": int(asc // 30) % 12 + 1,
            "degree_in_sign": round(asc % 30, 4),
        },
        "planets": planets,
    }


def format_chart(chart: dict[str, Any]) -> str:
    lines = [
        f"เกิดวันที่ {chart['birth_date']} เวลา {chart['birth_time']} (UTC+{chart['tz_hours']:g}) "
        f"ที่ละติจูด {chart['lat']}, ลองจิจูด {chart['lon']}",
        f"ระบบ: {'นิรายนะ (Lahiri)' if chart['sidereal'] else 'สายนะ (Tropical)'}",
        f"ลัคนา (Ascendant): {chart['ascendant']['zodiac']} ราศี {chart['ascendant']['degree_in_sign']:.2f}°",
    ]
    lines.append("ตำแหน่งดาวนพเคราะห์:")
    for code, p in chart["planets"].items():
        lines.append(
            f"- {p['name_th']}: {p['zodiac']} {p['degree_in_sign']:.2f}° (เรือน {p['house']}, "
            f"ราศีที่ {p['zodiac_number']})"
        )
    return "\n".join(lines)


def _extract_keywords(question: str) -> list[str]:
    text = question.replace("?", "").replace("？", "").replace(".", " ")
    for w in sorted(_THAI_STOPWORDS, key=len, reverse=True):
        text = text.replace(w, " ")
    words = [w.strip() for w in text.split() if w.strip()]
    return words or [question]


async def _fetch_chart_entities(
    adapter: TursoAdapter,
    chart: dict[str, Any],
    all_knowledge: dict[str, dict[str, Any]],
) -> None:
    planet_names = sorted({p["name_th"] for p in chart["planets"].values()})
    houses = sorted({p["house"] for p in chart["planets"].values()})
    zodiacs = sorted({p["zodiac"] for p in chart["planets"].values()} | {chart["ascendant"]["zodiac"]})

    for column, values in (
        ("planet_name", planet_names),
        ("house_number", houses),
        ("zodiac_sign", zodiacs),
    ):
        if not values:
            continue
        placeholders = ", ".join("?" for _ in values)
        sql = _CHART_ENTITIES_SQL.format(column=column, placeholders=placeholders)
        result = await adapter.execute(sql, values)
        for row in result.rows:
            item = {col: row[col] for col in result.columns}
            all_knowledge.setdefault(item["chunk_key"], item)


async def fetch_context(
    adapter: TursoAdapter,
    query: str,
    limit: int,
    chart: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    all_knowledge: dict[str, dict[str, Any]] = {}
    systems: list[dict[str, Any]] = []

    for kw in _extract_keywords(query)[:6]:
        like = f"%{kw}%"
        result = await adapter.execute(_KEYWORD_SQL, [like, like, like, limit])
        for row in result.rows:
            item = {col: row[col] for col in result.columns}
            all_knowledge.setdefault(item["chunk_key"], item)

    if chart is not None:
        await _fetch_chart_entities(adapter, chart, all_knowledge)

    result = await adapter.execute(SYSTEMS_SQL)
    for row in result.rows:
        systems.append({col: row[col] for col in result.columns})

    return list(all_knowledge.values())[: limit * 2] + systems


def build_prompt(user_question: str, chunks: list[dict[str, Any]], chart_text: str | None = None) -> str:
    systems = [c for c in chunks if "display_name" in c]
    knowledge = [c for c in chunks if "content" in c]

    lines = ["### ระบบโหราศาสตร์ที่ใช้"]
    for s in systems:
        lines.append(
            f"- {s['display_name']}: {s['description']} (house_method={s['house_method']}, ayanamsa={s['ayanamsa_note']})"
        )

    if chart_text:
        lines.append("\n### ดวงกำเนิด (คำนวณจาก Swiss Ephemeris)")
        lines.append(chart_text)

    lines.append("\n### ความรู้ที่เกี่ยวข้อง (จากฐานข้อมูล)")
    for i, c in enumerate(knowledge, 1):
        tags = ", ".join(
            str(c[k])
            for k in ("category", "topic", "planet_name", "house_number", "zodiac_sign")
            if c.get(k)
        )
        lines.append(
            f"[{i}] {c['content']}\n"
            f"    metadata: {tags} | keywords: {c['keywords_json']}\n"
            f"    ที่มา: {c['document_key']} / {c['chunk_key']} / {c['source_locator']}"
        )

    lines.append("\n### คำถามจากผู้ใช้")
    lines.append(user_question)
    lines.append("\nจงตอบเป็นภาษาไทยโดยใช้ความรู้ด้านบน พร้อมระบุที่มา")
    if chart_text:
        lines.append("ถ้ามีดวงกำเนิด ให้เริ่มวิเคราะห์จากตำแหน่งดาว/เรือน/ลัคนาในดวงกำเนิดก่อน แล้วจึงเสริมด้วยความรู้")
    return "\n".join(lines)


def _resolve_birth(body: dict[str, Any]) -> tuple[str | None, str | None, float | None, float | None, float]:
    birth_date = body.get("birth_date")
    birth_time = body.get("birth_time")
    place = body.get("birth_place")
    lat = body.get("birth_lat")
    lon = body.get("birth_lon")
    tz_hours = float(body.get("birth_tz", 7.0))

    if place:
        if place in THAI_CITIES:
            lat, lon = THAI_CITIES[place]
        elif lat is None or lon is None:
            raise ValueError(f"ไม่รู้จัก birth_place '{place}' ใช้ birth_lat/birth_lon แทน")
    elif lat is None or lon is None:
        lat, lon = THAI_CITIES["กรุงเทพ"]

    return birth_date, birth_time, lat, lon, tz_hours


def _extract_question(body: dict[str, Any]) -> str | None:
    if body.get("prompt"):
        return str(body["prompt"])
    messages = body.get("messages")
    if isinstance(messages, list):
        for message in reversed(messages):
            if message.get("role") == "user":
                content = message.get("content")
                if isinstance(content, str):
                    return content
                if isinstance(content, list):
                    parts = [part.get("text", "") for part in content if isinstance(part, dict) and part.get("type") == "text"]
                    if parts:
                        return " ".join(parts)
    return None


async def _call_ollama(
    client: httpx.AsyncClient,
    ollama_url: str,
    model: str,
    prompt: str,
    stream: bool,
    num_predict: int | None = None,
) -> httpx.Response:
    options = {"num_predict": num_predict} if num_predict else None
    payload: dict[str, Any] = {"model": model, "prompt": prompt, "system": SYSTEM_PROMPT, "stream": stream}
    if options:
        payload["options"] = options
    return await client.post(
        f"{ollama_url}/api/generate",
        json=payload,
        timeout=httpx.Timeout(300.0),
    )


async def run_astrology(
    ollama_client: httpx.AsyncClient,
    ollama_url: str,
    model: str,
    body: dict[str, Any],
    top_k: int = 5,
) -> httpx.Response:
    question = _extract_question(body)
    if not question:
        raise ValueError("prompt หรือ messages ไม่พบ")

    chart_text: str | None = None
    birth_date, birth_time, lat, lon, tz_hours = _resolve_birth(body)
    if birth_date and birth_time and lat is not None and lon is not None:
        chart = cast_chart(birth_date, birth_time, lat, lon, tz_hours)
        chart_text = format_chart(chart)

    adapter = TursoAdapter.from_env()
    try:
        await adapter.connect()
        chunks = await fetch_context(adapter, question, top_k, chart)
    finally:
        await adapter.close()

    prompt = build_prompt(question, chunks, chart_text)
    stream = bool(body.get("stream", False))
    return await _call_ollama(ollama_client, ollama_url, model, prompt, stream)