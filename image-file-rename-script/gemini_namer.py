"""
Gemini Vision AI module for image visual content analysis and descriptive name generation.

WORKFLOW OVERVIEW:
1. prepare_image_bytes(): Converts TIFF images (not natively supported by Gemini API) to JPEG in-memory. Reads direct bytes for PNG/WebP/JPEG.
2. suggest_image_name(): Constructs a multimodal payload (image bytes + prompt instructions) and calls Gemini API.
3. Structured Output: Uses Pydantic (ImageNameSuggestion) to force Gemini to return JSON with a clean 'name_slug'.
4. Retry Logic: Implements exponential backoff (1s, 2s, 4s...) up to max_retries if API call fails.
5. sanitize_slug(): Cleans text using regex to ensure strictly valid snake_case filenames.
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

# Default Gemini model used for visual inspection
DEFAULT_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")


# Schema enforcing structured JSON response from Gemini Vision AI
class ImageNameSuggestion(BaseModel):
    name_slug: str = Field(
        description="A 3 to 6 word descriptive, literal slug for the image in lowercase snake_case (e.g. cherry_blossom_rain_droplets). No brand names, no camera jargon, no words like photo or picture."
    )


# Prompt instructing Gemini Vision on stock-photo style literal naming guidelines
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
    """
    Sanitize raw AI output text into a clean snake_case slug.
    
    Removes special characters, converts spaces/dashes to underscores,
    and eliminates duplicate underscores.
    """
    slug = raw_slug.lower()
    # Strip non-alphanumeric/non-space/non-dash chars
    slug = re.sub(r"[^\w\s-]", "", slug)
    # Convert spaces and hyphens to underscores
    slug = re.sub(r"[\s-]+", "_", slug)
    # Collapse multiple consecutive underscores into one
    slug = re.sub(r"_+", "_", slug)
    # Return trimmed slug or fallback default name
    return slug.strip("_") or "unnamed_image"


def prepare_image_bytes(image_path: Path) -> tuple[bytes, str]:
    """
    Prepare image binary data and MIME type for Gemini API.
    
    TIFF/TIF files are converted to JPEG in memory using PIL/Pillow
    because Gemini Vision API expects standard web format bytes.
    """
    lower = image_path.name.lower()
    
    # Check for TIFF formats requiring PIL conversion
    if lower.endswith((".tif", ".tiff")):
        with Image.open(image_path) as img:
            buf = io.BytesIO()
            # Convert color space to RGB and encode as high-quality JPEG
            img.convert("RGB").save(buf, format="JPEG", quality=95)
            return buf.getvalue(), "image/jpeg"

    # For web formats, read binary data directly from file
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
    """
    Analyze an image with Gemini Vision and return an AI-generated filename slug.
    
    - Encapsulates image data into a Gemini Part object.
    - Requests structured JSON matching ImageNameSuggestion schema.
    - Retries automatically with exponential backoff in case of transient API errors.
    """
    # Step 1: Extract bytes and detect appropriate MIME type
    image_bytes, mime_type = prepare_image_bytes(image_path)
    image_part = types.Part.from_bytes(data=image_bytes, mime_type=mime_type)

    last_error = None
    # Step 2: Call Gemini Vision with retry loop
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
            # Step 3: Validate JSON response against Pydantic schema
            parsed = ImageNameSuggestion.model_validate_json(response.text)
            
            # Step 4: Sanitize and return final slug
            return sanitize_slug(parsed.name_slug)
        except Exception as e:
            last_error = e
            # Exponential backoff delay: 1s, 2s, 4s...
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)

    raise RuntimeError(f"Gemini AI visual analysis failed after {max_retries} attempts: {last_error}")

