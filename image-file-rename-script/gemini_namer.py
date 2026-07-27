"""
Gemini Vision AI module for image visual content analysis and descriptive name generation.
"""
import io
import os
import re
import time
from pathlib import Path

from google import genai
from google.genai import types
from PIL import Image
from pydantic import BaseModel, Field

DEFAULT_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")


class ImageNameSuggestion(BaseModel):
    name_slug: str = Field(
        description="A 3 to 6 word descriptive, literal slug for the image in lowercase snake_case (e.g. cherry_blossom_rain_droplets). No brand names, no camera jargon, no words like photo or picture."
    )


PROMPT_TEMPLATE = """You are analyzing an image for a stock photo library. Look at the image and suggest a descriptive filename slug.

Rules:
1. Provide a 3 to 6 word description of the main subject, setting, or core action.
2. Separate words with single underscores (snake_case), e.g. "red_pomegranate_flower_bud".
3. Use only lowercase letters, numbers, and underscores.
4. Do NOT include brand names, trademarks, or company logos.
5. Do NOT include generic words like "image", "photo", "picture", "stock", "beautiful", "stunning", "macro".
6. Be literal and factual about what is physically in the image.
"""


def sanitize_slug(raw_slug: str) -> str:
    """Sanitize raw text into a clean snake_case slug."""
    slug = raw_slug.lower()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s-]+", "_", slug)
    slug = re.sub(r"_+", "_", slug)
    return slug.strip("_") or "unnamed_image"


def prepare_image_bytes(image_path: Path) -> tuple[bytes, str]:
    """Convert TIFF images if needed and return bytes + mime_type."""
    lower = image_path.name.lower()
    if lower.endswith((".tif", ".tiff")):
        with Image.open(image_path) as img:
            buf = io.BytesIO()
            img.convert("RGB").save(buf, format="JPEG", quality=95)
            return buf.getvalue(), "image/jpeg"

    data = image_path.read_bytes()
    if lower.endswith(".png"):
        return data, "image/png"
    if lower.endswith(".webp"):
        return data, "image/webp"
    return data, "image/jpeg"


def suggest_image_name(
    client: genai.Client,
    image_path: Path,
    model_name: str = DEFAULT_MODEL,
    max_retries: int = 3,
) -> str:
    """Analyze an image with Gemini Vision and return an AI-generated filename slug."""
    image_bytes, mime_type = prepare_image_bytes(image_path)
    image_part = types.Part.from_bytes(data=image_bytes, mime_type=mime_type)

    last_error = None
    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=[image_part, PROMPT_TEMPLATE],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=ImageNameSuggestion,
                ),
            )
            parsed = ImageNameSuggestion.model_validate_json(response.text)
            return sanitize_slug(parsed.name_slug)
        except Exception as e:
            last_error = e
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)

    raise RuntimeError(f"Gemini AI visual analysis failed after {max_retries} attempts: {last_error}")
