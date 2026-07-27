"""
Thin wrapper around the Gemini API for a single image -> metadata call.
Isolated in its own module so the prompt, schema, and retry logic can be
tuned without touching the batch-processing loop in stockflow.py.
"""
import io
import time

from google.genai import types
from pydantic import BaseModel, Field
from PIL import Image

from limits import GEMINI_MODEL


class Metadata(BaseModel):
    title: str = Field(description="A factual, literal, descriptive title for the "
                                    "stock photo, written as a single sentence. "
                                    "No brand names, no camera settings, no "
                                    "flowery language.")
    keywords: list[str] = Field(description="20-40 single or compound words a "
                                             "buyer would search for, ordered from "
                                             "most to least relevant to the image's "
                                             "main subject.")
    categories: list[str] = Field(description="One or two categories for this "
                                               "image, chosen ONLY from the "
                                               "provided category list. Most "
                                               "images need only one.")


PROMPT_TEMPLATE = """You are tagging a photo for submission to Shutterstock as
a stock photography contributor. Look at the image and produce:

1. A title: one factual, literal sentence describing the subject matter.
   No brand names or product names. No camera/lens jargon. No superlatives
   like "beautiful" or "stunning" — just what is depicted.
2. Keywords: 20-40 words or short compound phrases a buyer would plausibly
   search for, ordered from most to least relevant. Include the obvious
   subject, but also setting, mood, colors, and likely commercial use
   cases (e.g. "copy space", "isolated on white") where genuinely
   applicable to what's in the image.
3. Categories: pick one, or at most two, from this exact list — do not
   invent categories or vary the spelling:

{categories}

Only output the structured fields requested. Do not include brand names,
trademarks, or identifiable logos in the title or keywords."""


def _prepare_image_bytes(image_path: str) -> tuple[bytes, str]:
    """
    Returns (bytes, mime_type). Gemini's image-understanding endpoint does
    not accept TIFF directly (supported: png, jpeg, webp, heic, heif), so
    TIFF inputs are converted to JPEG in memory before the call — this
    keeps TIFF as a supported *input* format per the PRD without needing
    Shutterstock or Gemini to change anything.
    """
    lower = image_path.lower()
    if lower.endswith((".tif", ".tiff")):
        with Image.open(image_path) as img:
            buf = io.BytesIO()
            img.convert("RGB").save(buf, format="JPEG", quality=95)
            return buf.getvalue(), "image/jpeg"

    with open(image_path, "rb") as f:
        data = f.read()
    if lower.endswith(".png"):
        return data, "image/png"
    if lower.endswith(".webp"):
        return data, "image/webp"
    return data, "image/jpeg"


def generate_metadata(
    client,
    image_path: str,
    valid_categories: list[str],
    max_retries: int = 3,
) -> Metadata:
    """
    Calls Gemini once for a single image and returns parsed Metadata.
    Retries with backoff on transient/rate-limit errors; raises on the
    final failure so the caller can flag the row and move on.
    """
    image_bytes, mime_type = _prepare_image_bytes(image_path)
    prompt = PROMPT_TEMPLATE.format(categories="\n".join(f"- {c}" for c in valid_categories))
    image_part = types.Part.from_bytes(data=image_bytes, mime_type=mime_type)

    last_error = None
    for attempt in range(max_retries):
        try:
            if hasattr(client, "models") and hasattr(client.models, "generate_content"):
                response = client.models.generate_content(
                    model=GEMINI_MODEL,
                    contents=[image_part, prompt],
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_schema=Metadata,
                    ),
                )
                raw_text = response.text
            elif hasattr(client, "interactions"):
                import base64
                interaction = client.interactions.create(
                    model=GEMINI_MODEL,
                    input=[
                        {"type": "text", "text": prompt},
                        {
                            "type": "image",
                            "data": base64.b64encode(image_bytes).decode("utf-8"),
                            "mime_type": mime_type,
                        },
                    ],
                    response_format={
                        "type": "text",
                        "mime_type": "application/json",
                        "schema": Metadata.model_json_schema(),
                    },
                )
                raw_text = interaction.output_text
            else:
                raise AttributeError("Client API structure not recognized")

            return Metadata.model_validate_json(raw_text)
        except Exception as e:  # noqa: BLE001 - want to retry on anything transient
            last_error = e
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)  # 1s, 2s, 4s
    raise RuntimeError(f"Gemini call failed after {max_retries} attempts: {last_error}")
