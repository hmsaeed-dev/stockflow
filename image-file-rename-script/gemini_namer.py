"""
Gemini Vision AI module for image visual content analysis and descriptive name generation.

WORKFLOW OVERVIEW:
1. prepare_image_bytes(): Downscales images larger than 1024px and converts TIFF to JPEG in-memory to save API tokens and quota.
2. suggest_image_names_batch(): Sends a batch of images (e.g. 5 images) in a single Gemini API call with key rotation & model fallback.
3. suggest_image_name(): Single-image suggestion function supporting API key rotation and fallback models.
4. Structured Output: Uses Pydantic to enforce structured JSON responses for slug suggestions.
5. Key Rotation & Fallback: Automatically rotates through a pool of API keys and fallback models when hitting 429 quota errors.
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
FALLBACK_MODELS = ["gemini-2.0-flash", "gemini-1.5-flash", "gemini-2.0-flash-lite"]


# Pydantic schemas for single and batch AI responses
class ImageNameSuggestion(BaseModel):
    name_slug: str = Field(
        description="A 3 to 6 word descriptive, literal slug for the image in lowercase snake_case (e.g. cherry_blossom_rain_droplets). No brand names, no camera jargon, no words like photo or picture."
    )


class ImageBatchItemSuggestion(BaseModel):
    image_index: int = Field(description="1-based index matching the image prompt order (#1, #2, etc.)")
    name_slug: str = Field(
        description="A 3 to 6 word descriptive, literal slug for the image in lowercase snake_case."
    )


class BatchImageNameSuggestions(BaseModel):
    suggestions: list[ImageBatchItemSuggestion] = Field(description="List of suggestions for all provided images")


# Prompts instructing Gemini Vision on stock-photo style literal naming guidelines
SINGLE_PROMPT_TEMPLATE = """You are analyzing an image for a stock photo library. Look at the image and suggest a descriptive filename slug.

Rules:
1. Provide a 3 to 6 word description of the main subject, setting, or core action.
2. Separate words with single underscores (snake_case), e.g. "red_pomegranate_flower_bud".
3. Use only lowercase letters, numbers, and underscores.
4. Do NOT include brand names, trademarks, or company logos.
5. Do NOT include generic words like "image", "photo", "picture", "stock", "beautiful", "stunning", "macro".
6. Be literal and factual about what is physically in the image.
"""

BATCH_PROMPT_HEADER = """You are analyzing multiple images for a stock photo library.
For each provided image (Image #1, Image #2, etc.), suggest a descriptive filename slug.

Rules for each image:
1. Provide a 3 to 6 word description of the main subject, setting, or core action.
2. Separate words with single underscores (snake_case), e.g. "red_pomegranate_flower_bud".
3. Use only lowercase letters, numbers, and underscores.
4. Do NOT include brand names, trademarks, camera jargon, or generic words like "image", "photo", "picture", "stock".
5. Be literal and factual about what is physically in each image.

Return a JSON object containing a suggestion item for EVERY image in order.
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


def get_api_key_pool() -> list[str]:
    """
    Extract pool of API keys from GEMINI_API_KEYS (comma-separated) or GEMINI_API_KEY.
    """
    keys_str = os.environ.get("GEMINI_API_KEYS", "").strip()
    if keys_str:
        keys = [k.strip() for k in keys_str.split(",") if k.strip()]
        if keys:
            return keys
    single = os.environ.get("GEMINI_API_KEY", "").strip()
    return [single] if single else []


def prepare_image_bytes(image_path: Path, max_dim: int = 1024) -> tuple[bytes, str]:
    """
    Prepare image binary data and MIME type for Gemini API.

    - Downscales large images to max_dim (default 1024px) to drastically reduce token usage.
    - TIFF/TIF files are converted to JPEG in memory using PIL/Pillow.
    """
    lower = image_path.name.lower()
    is_tiff = lower.endswith((".tif", ".tiff"))

    with Image.open(image_path) as img:
        w, h = img.size
        # Downscale if image exceeds max dimension or is TIFF
        if w > max_dim or h > max_dim or is_tiff:
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")
            resample_fn = getattr(Image, "Resampling", Image).LANCZOS
            img.thumbnail((max_dim, max_dim), resample_fn)
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=85)
            return buf.getvalue(), "image/jpeg"

    # For web formats already within size limits, read direct bytes
    data = image_path.read_bytes()
    if lower.endswith(".png"):
        return data, "image/png"
    if lower.endswith(".webp"):
        return data, "image/webp"
    return data, "image/jpeg"


def extract_retry_delay(err: Exception) -> float | None:
    """
    Extract recommended retry delay in seconds from Gemini API error message.
    """
    err_str = str(err)
    match = re.search(r"retry in (\d+(?:\.\d+)?)s", err_str, re.IGNORECASE)
    if match:
        return float(match.group(1)) + 1.5
    match = re.search(r"['\"]retryDelay['\"]\s*:\s*['\"](\d+(?:\.\d+)?)s?['\"]", err_str, re.IGNORECASE)
    if match:
        return float(match.group(1)) + 1.5
    return None


def suggest_image_name(
    client: genai.Client | None,
    image_path: Path,
    api_keys: list[str] | None = None,
    model_name: str | None = None,
    max_retries: int = 3,
) -> str:
    """
    Single-image suggestion helper with API Key Rotation and Model Fallback support.
    """
    if api_keys is None:
        api_keys = get_api_key_pool()
    if not api_keys:
        raise ValueError("No Gemini API keys found in environment.")

    models_to_try = [model_name or DEFAULT_MODEL]
    for m in FALLBACK_MODELS:
        if m not in models_to_try:
            models_to_try.append(m)

    image_bytes, mime_type = prepare_image_bytes(image_path)
    image_part = types.Part.from_bytes(data=image_bytes, mime_type=mime_type)

    last_error = None
    for target_model in models_to_try:
        for key_idx, key in enumerate(api_keys, start=1):
            active_client = client if (client and key_idx == 1) else genai.Client(api_key=key)
            for attempt in range(max_retries):
                try:
                    response = active_client.models.generate_content(
                        model=target_model,
                        contents=[image_part, SINGLE_PROMPT_TEMPLATE],
                        config=types.GenerateContentConfig(
                            response_mime_type="application/json",
                            response_schema=ImageNameSuggestion,
                        ),
                    )
                    parsed = ImageNameSuggestion.model_validate_json(response.text)
                    return sanitize_slug(parsed.name_slug)
                except Exception as e:
                    last_error = e
                    err_str = str(e)
                    if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
                        delay = extract_retry_delay(e)
                        if delay and delay < 15 and attempt < max_retries - 1:
                            print(f"  • [Rate Limit 429] Key #{key_idx} temporary delay ({delay:.1f}s)...")
                            time.sleep(delay)
                        else:
                            print(f"  • [Quota Exhausted] Key #{key_idx} hit 429 on model {target_model}. Switching key/model...")
                            break  # Switch key immediately
                    else:
                        backoff = 2 ** attempt
                        time.sleep(backoff)

    raise RuntimeError(f"Gemini AI visual analysis failed after trying all keys/models: {last_error}")


def suggest_image_names_batch(
    image_paths: list[Path],
    api_keys: list[str] | None = None,
    model_name: str | None = None,
) -> dict[Path, str]:
    """
    Analyze a batch of images (e.g. 5 photos) in a SINGLE Gemini API call.
    Includes API Key Rotation pool and Model Fallback.

    Returns dict mapping image Path -> sanitized name slug string.
    """
    if not image_paths:
        return {}

    if api_keys is None:
        api_keys = get_api_key_pool()
    if not api_keys:
        raise ValueError("No Gemini API keys found in environment.")

    models_to_try = [model_name or DEFAULT_MODEL]
    for m in FALLBACK_MODELS:
        if m not in models_to_try:
            models_to_try.append(m)

    # Build multimodal content payload for the batch
    contents: list[object] = [BATCH_PROMPT_HEADER]
    for idx, img_path in enumerate(image_paths, start=1):
        img_bytes, mime_type = prepare_image_bytes(img_path)
        img_part = types.Part.from_bytes(data=img_bytes, mime_type=mime_type)
        contents.append(f"\n--- Image #{idx} (Filename: {img_path.name}) ---")
        contents.append(img_part)

    last_error = None

    for target_model in models_to_try:
        for key_idx, key in enumerate(api_keys, start=1):
            client = genai.Client(api_key=key)
            for attempt in range(2):
                try:
                    print(
                        f"  • [AI Batch Request] Sending batch of {len(image_paths)} images using API Key #{key_idx}/{len(api_keys)} (Model: {target_model})..."
                    )
                    response = client.models.generate_content(
                        model=target_model,
                        contents=contents,
                        config=types.GenerateContentConfig(
                            response_mime_type="application/json",
                            response_schema=BatchImageNameSuggestions,
                        ),
                    )
                    parsed = BatchImageNameSuggestions.model_validate_json(response.text)

                    # Map results back to original image paths
                    results: dict[Path, str] = {}
                    sug_map = {item.image_index: item.name_slug for item in parsed.suggestions}

                    for idx, img_path in enumerate(image_paths, start=1):
                        raw_slug = sug_map.get(idx, f"image_{idx}")
                        results[img_path] = sanitize_slug(raw_slug)

                    return results

                except Exception as e:
                    last_error = e
                    err_str = str(e)
                    if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
                        delay = extract_retry_delay(e)
                        if delay and delay < 15 and attempt < 1:
                            print(f"  • [Rate Limit 429] Key #{key_idx} temporary delay ({delay:.1f}s)...")
                            time.sleep(delay)
                        else:
                            print(
                                f"  • [Quota Exhausted] Key #{key_idx} hit 429 quota on {target_model}. Rotating key/model..."
                            )
                            break  # Switch key immediately
                    else:
                        time.sleep(2 ** attempt)

    print("  • [Batch Fallback] Batch request failed across all keys/models. Falling back to single image calls...")

    # Fallback: Process images one by one if batch fails completely
    fallback_results: dict[Path, str] = {}
    for img_path in image_paths:
        try:
            fallback_results[img_path] = suggest_image_name(None, img_path, api_keys=api_keys, model_name=model_name)
        except Exception as e:
            fallback_results[img_path] = sanitize_slug(img_path.stem)
    return fallback_results
