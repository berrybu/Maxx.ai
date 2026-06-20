"""Business-card extraction -- read structured data after scanning a card."""

from __future__ import annotations

import json
import re
from typing import Any

from llm import OllamaUnavailable, chat_json, vision

SAMPLE_CARDS: dict[str, str] = {
    "bosch": (
        "BOSCH Mobility\nHans Mueller\nHead of Procurement\n"
        "hans.mueller@bosch-mobility.com\n+49 711 400 40990\n"
        "Robert-Bosch-Platz 1, 70839 Gerlingen, Germany"
    ),
    "continental": (
        "Continental AG\nNikolai Setzer — Chief Executive Officer\n"
        "n.setzer@continental.com\n+49 511 938 01\nHannover, Germany"
    ),
}

_EXTRACT_SYSTEM = (
    "You are a business-card information extractor. Given raw text OCR'd from a business card, "
    "extract the structured fields. Output JSON only, with fields: "
    "full_name, job_title, email, phone, company, country. Fill missing fields with null."
)


def _heuristic_extract(raw_text: str) -> dict[str, Any]:
    email = None
    phone = None
    m = re.search(r"[\w.\-+]+@[\w.\-]+\.\w+", raw_text)
    if m:
        email = m.group(0)
    m = re.search(r"\+?\d[\d\s().\-]{6,}\d", raw_text)
    if m:
        phone = m.group(0).strip()
    lines = [l.strip() for l in raw_text.splitlines() if l.strip()]
    company = lines[0] if lines else None
    full_name = None
    job_title = None
    if len(lines) >= 2:
        name_line = lines[1]
        if "—" in name_line or "-" in name_line:
            parts = re.split(r"[—-]", name_line, maxsplit=1)
            full_name = parts[0].strip()
            job_title = parts[1].strip() if len(parts) > 1 else None
        else:
            full_name = name_line
            if len(lines) >= 3 and "@" not in lines[2]:
                job_title = lines[2]
    country = None
    if re.search(r"germany", raw_text, re.I):
        country = "Germany"
    return {"full_name": full_name, "job_title": job_title, "email": email,
            "phone": phone, "company": company, "country": country}


def extract_card(raw_text: str, *, use_llm: bool = True) -> dict[str, Any]:
    if use_llm:
        try:
            data = chat_json([
                {"role": "system", "content": _EXTRACT_SYSTEM},
                {"role": "user", "content": raw_text},
            ])
            data["_method"] = "ollama"
            return data
        except (OllamaUnavailable, json.JSONDecodeError, Exception):
            pass
    data = _heuristic_extract(raw_text)
    data["_method"] = "heuristic"
    return data


def get_sample_card_text(key: str = "bosch") -> str:
    return SAMPLE_CARDS.get(key, SAMPLE_CARDS["bosch"])



_OCR_SYSTEM = (
    "You are a high-precision OCR engine. Output only the text recognized in the image, line by line, no translation, no explanation."
)


def ocr_image(image_b64, *, mime="image/jpeg"):
    """Real OCR: gpt-4o vision reads the business-card image -> raw text."""
    data_url = image_b64 if image_b64.startswith("data:") else f"data:{mime};base64,{image_b64}"
    text = vision(
        "Recognize all the text on this business card line by line, character by character, and output it verbatim.",
        data_url,
        system=_OCR_SYSTEM,
    )
    return text.strip()


def extract_card_image(image_b64, *, mime="image/jpeg"):
    raw = ocr_image(image_b64, mime=mime)
    data = extract_card(raw, use_llm=True)
    data["_ocr_text"] = raw
    data["_method"] = "vision"
    return data
