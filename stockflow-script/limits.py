"""
Named constants for Shutterstock's metadata rules and StockFlow's own
validation thresholds. Everything that might need to change when
Shutterstock updates its rules lives here — see PRD §8.
"""

# Shutterstock's hard requirements (see:
# https://submit.shutterstock.com/help/en/articles/10617427)
MIN_KEYWORDS = 7
MAX_KEYWORDS = 50
MAX_TITLE_CHARS = 2048          # Shutterstock's actual hard limit
MAX_CATEGORIES = 2

# StockFlow's own quality bar, stricter than Shutterstock's hard limits.
# A title that is technically legal (say, 6 characters) is still a bad
# stock photo title, so we flag well short of Shutterstock's own ceiling.
FLAG_TITLE_MAX_CHARS = 200
FLAG_TITLE_MIN_WORDS = 5

# Where the editable config files live, relative to the project root.
CATEGORIES_FILE = "config/categories.txt"
BRAND_DENYLIST_FILE = "config/brand_denylist.txt"

import os

# Gemini model used for metadata generation.
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.6-flash")


# Accepted input image extensions (must match Gemini's supported MIME types).
SUPPORTED_EXTENSIONS = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
}
