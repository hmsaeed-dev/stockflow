"""
Gemini API client for image visual metadata generation (title, keywords, categories).

FEATURES & OPTIMIZATIONS:
1. prepare_image_bytes(): Downscales images larger than 1024px and converts TIFF to JPEG in-memory to save API tokens and quota.
2. generate_metadata_batch(): Sends a batch of images (e.g. 5 images) in a single Gemini API call with key rotation & model fallback.
3. generate_metadata(): Single-image suggestion function supporting API key rotation pool and fallback models.
4. Structured Output: Uses Pydantic to enforce structured JSON responses for Shutterstock metadata.
5. Key Rotation & Fallback: Automatically rotates through a pool of API keys and fallback models when hitting 429 quota errors.
"""
import io
import os
import re
import sys
import time
from pathlib import Path

try:
    from google.genai import types
except ImportError:
    print("ERROR: Could not import 'types' from 'google.genai'.", file=sys.stderr)
    print("Please make sure 'google-genai' is installed in your Python environment:", file=sys.stderr)
    print("    pip install google-genai", file=sys.stderr)
    sys.exit(1)

from PIL import Image
from pydantic import BaseModel, Field

from limits import GEMINI_MODEL

DEFAULT_MODEL = os.environ.get("GEMINI_MODEL", GEMINI_MODEL)
FALLBACK_MODELS = ["gemini-2.0-flash", "gemini-1.5-flash", "gemini-2.0-flash-lite"]


class Metadata(BaseModel):
    title: str = Field(
        description="A factual, literal, descriptive title for the stock photo, written as a single sentence. No brand names, no camera settings, no flowery language."
    )
    keywords: list[str] = Field(
        description="20-40 single or compound words a buyer would search for, ordered from most to least relevant to the image's main subject."
    )
    categories: list[str] = Field(
        description="One or two categories for this image, chosen ONLY from the provided category list. Most images need only one."
    )


class MetadataBatchItem(BaseModel):
    image_index: int = Field(description="1-based index matching the image prompt order (#1, #2, etc.)")
    title: str = Field(description="A factual, literal, descriptive title for the stock photo as a single sentence.")
    keywords: list[str] = Field(description="20-40 single or compound words ordered by relevance.")
    categories: list[str] = Field(description="One or two categories chosen from the provided list.")


class BatchMetadataSuggestions(BaseModel):
    suggestions: list[MetadataBatchItem] = Field(description="List of metadata items for all provided images")


SINGLE_PROMPT_TEMPLATE = """You are tagging a photo for submission to Shutterstock as a stock photography contributor. Look at the image and produce:

1. A title: one factual, literal sentence describing the subject matter.
   No brand names or product names. No camera/lens jargon. No superlatives like "beautiful" or "stunning" — just what is depicted.
2. Keywords: 20-40 words or short compound phrases a buyer would plausibly search for, ordered from most to least relevant. Include the obvious subject, setting, mood, colors, and likely commercial use cases (e.g. "copy space", "isolated on white").
3. Categories: pick one, or at most two, from this exact list — do not invent categories or vary spelling:

{categories}

Only output the structured fields requested. Do not include brand names, trademarks, or identifiable logos in the title or keywords."""


BATCH_PROMPT_HEADER = """You are tagging multiple photos for submission to Shutterstock as a stock photography contributor.
For each provided image (Image #1, Image #2, etc.), produce the requested metadata.

Rules for each image:
1. Title: one factual, literal sentence describing the subject matter. No brand names, product names, camera jargon, or superlatives.
2. Keywords: 20-40 words or short compound phrases a buyer would search for, ordered from most to least relevant.
3. Categories: pick one, or at most two, from this exact category list:

{categories}

Return a JSON object containing a suggestion item for EVERY image in order matching image_index.
"""


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


def _prepare_image_bytes(image_path: str, max_dim: int = 1024) -> tuple[bytes, str]:
    """
    Returns (bytes, mime_type).
    Downscales large images to max_dim (default 1024px) in memory to save tokens/quota.
    Converts TIFF/TIF files to JPEG in memory.
    """
    lower = image_path.lower()
    is_tiff = lower.endswith((".tif", ".tiff"))

    with Image.open(image_path) as img:
        w, h = img.size
        if w > max_dim or h > max_dim or is_tiff:
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")
            resample_fn = getattr(Image, "Resampling", Image).LANCZOS
            img.thumbnail((max_dim, max_dim), resample_fn)
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=85)
            return buf.getvalue(), "image/jpeg"

    with open(image_path, "rb") as f:
        data = f.read()
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


def generate_metadata(
    client,
    image_path: str,
    valid_categories: list[str],
    api_keys: list[str] | None = None,
    max_retries: int = 3,
) -> Metadata:
    """
    Single image metadata generator with API Key Rotation and Model Fallback.
    """
    if api_keys is None:
        api_keys = get_api_key_pool()
    if not api_keys:
        raise ValueError("No Gemini API keys found in environment.")

    models_to_try = [os.environ.get("GEMINI_MODEL", DEFAULT_MODEL)]
    for m in FALLBACK_MODELS:
        if m not in models_to_try:
            models_to_try.append(m)

    image_bytes, mime_type = _prepare_image_bytes(image_path)
    prompt = SINGLE_PROMPT_TEMPLATE.format(categories="\n".join(f"- {c}" for c in valid_categories))
    image_part = types.Part.from_bytes(data=image_bytes, mime_type=mime_type)

    last_error = None
    for target_model in models_to_try:
        for key_idx, key in enumerate(api_keys, start=1):
            from google import genai
            active_client = genai.Client(api_key=key)
            for attempt in range(max_retries):
                try:
                    response = active_client.models.generate_content(
                        model=target_model,
                        contents=[image_part, prompt],
                        config=types.GenerateContentConfig(
                            response_mime_type="application/json",
                            response_schema=Metadata,
                        ),
                    )
                    return Metadata.model_validate_json(response.text)
                except Exception as e:
                    last_error = e
                    err_str = str(e)
                    if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
                        delay = extract_retry_delay(e)
                        if delay and delay < 15 and attempt < max_retries - 1:
                            time.sleep(delay)
                        else:
                            print(f"  • [Quota Exhausted] Key #{key_idx} hit 429 quota on {target_model}. Rotating key/model...")
                            break
                    else:
                        time.sleep(2 ** attempt)

    raise RuntimeError(f"Gemini call failed after trying all keys/models: {last_error}")


def generate_metadata_batch(
    image_paths: list[Path],
    valid_categories: list[str],
    api_keys: list[str] | None = None,
) -> dict[Path, Metadata]:
    """
    Generate metadata for a batch of images in a SINGLE Gemini API call.
    Includes Key Rotation pool and Model Fallback.
    """
    if not image_paths:
        return {}

    if api_keys is None:
        api_keys = get_api_key_pool()
    if not api_keys:
        raise ValueError("No Gemini API keys found in environment.")

    models_to_try = [os.environ.get("GEMINI_MODEL", DEFAULT_MODEL)]
    for m in FALLBACK_MODELS:
        if m not in models_to_try:
            models_to_try.append(m)

    cats_str = "\n".join(f"- {c}" for c in valid_categories)
    prompt_header = BATCH_PROMPT_HEADER.format(categories=cats_str)

    contents: list[object] = [prompt_header]
    for idx, img_path in enumerate(image_paths, start=1):
        img_bytes, mime_type = _prepare_image_bytes(str(img_path))
        img_part = types.Part.from_bytes(data=img_bytes, mime_type=mime_type)
        contents.append(f"\n--- Image #{idx} (Filename: {img_path.name}) ---")
        contents.append(img_part)

    last_error = None
    for target_model in models_to_try:
        for key_idx, key in enumerate(api_keys, start=1):
            from google import genai
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
                            response_schema=BatchMetadataSuggestions,
                        ),
                    )
                    parsed = BatchMetadataSuggestions.model_validate_json(response.text)

                    results: dict[Path, Metadata] = {}
                    meta_map = {item.image_index: item for item in parsed.suggestions}

                    for idx, img_path in enumerate(image_paths, start=1):
                        item = meta_map.get(idx)
                        if item:
                            results[img_path] = Metadata(
                                title=item.title,
                                keywords=item.keywords,
                                categories=item.categories,
                            )
                        else:
                            # Fallback if specific item was omitted in model output
                            results[img_path] = Metadata(
                                title=f"Photo of {img_path.stem.replace('_', ' ')}",
                                keywords=["stock", "photography", "photo", "image"],
                                categories=[valid_categories[0]] if valid_categories else ["Abstract"],
                            )
                    return results

                except Exception as e:
                    last_error = e
                    err_str = str(e)
                    if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
                        delay = extract_retry_delay(e)
                        if delay and delay < 15 and attempt < 1:
                            time.sleep(delay)
                        else:
                            print(
                                f"  • [Quota Exhausted] Key #{key_idx} hit 429 quota on {target_model}. Rotating key/model..."
                            )
                            break
                    else:
                        time.sleep(2 ** attempt)

    print("  • [Batch Fallback] Batch request failed across all keys/models. Processing individually...")
    fallback_results: dict[Path, Metadata] = {}
    for img_path in image_paths:
        try:
            fallback_results[img_path] = generate_metadata(None, str(img_path), valid_categories, api_keys=api_keys)
        except Exception as e:
            fallback_results[img_path] = Metadata(
                title=f"Photo of {img_path.stem.replace('_', ' ')}",
                keywords=["stock", "photo"],
                categories=[valid_categories[0]] if valid_categories else ["Abstract"],
            )
    return fallback_results
