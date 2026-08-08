"""
Validation pass. Every generated row runs through here before being
written to the CSV. Failures are flagged, never silently fixed or
dropped — see PRD §6 (Should have).
"""
from pathlib import Path

from limits import (
    MIN_KEYWORDS,
    MAX_KEYWORDS,
    MAX_CATEGORIES,
    FLAG_TITLE_MAX_CHARS,
    FLAG_TITLE_MIN_WORDS,
    CATEGORIES_FILE,
    BRAND_DENYLIST_FILE,
)


def load_word_list(path: str, project_root: str = ".", lower: bool = True) -> set[str]:
    """Load a config file of one entry per line, skipping blanks and comments."""
    p = Path(path)
    if not p.is_absolute():
        p = Path(project_root) / path

    if not p.exists():
        alt_p = Path(project_root) / Path(path).name
        if alt_p.exists():
            p = alt_p
        else:
            return set()

    words = set()
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        words.add(line.lower() if lower else line)
    return words


def load_categories(project_root: str = ".") -> set[str]:
    return load_word_list(CATEGORIES_FILE, project_root, lower=False)


def load_brand_denylist(project_root: str = ".") -> set[str]:
    return load_word_list(BRAND_DENYLIST_FILE, project_root, lower=True)


def validate_row(
    title: str,
    keywords: list[str],
    categories: list[str],
    valid_categories: set[str],
    brand_denylist: set[str],
) -> list[str]:
    """
    Returns a list of human-readable reasons the row was flagged.
    An empty list means the row passed clean.
    """
    reasons = []

    # Keyword count
    if len(keywords) < MIN_KEYWORDS:
        reasons.append(f"only {len(keywords)} keywords (min {MIN_KEYWORDS})")
    if len(keywords) > MAX_KEYWORDS:
        reasons.append(f"{len(keywords)} keywords (max {MAX_KEYWORDS})")

    # Title length / shape
    if not title or not title.strip():
        reasons.append("title missing")
    else:
        if len(title) > FLAG_TITLE_MAX_CHARS:
            reasons.append(f"title over {FLAG_TITLE_MAX_CHARS} chars")
        if len(title.split()) < FLAG_TITLE_MIN_WORDS:
            reasons.append(f"title under {FLAG_TITLE_MIN_WORDS} words")

    # Category presence / validity
    if not categories:
        reasons.append("category missing")
    else:
        if len(categories) > MAX_CATEGORIES:
            reasons.append(f"{len(categories)} categories (max {MAX_CATEGORIES})")
        valid_cats_lower = {c.lower() for c in valid_categories}
        for cat in categories:
            if cat.lower() not in valid_cats_lower:
                reasons.append(f"category '{cat}' not in category config")

    # Brand-name check across title + keywords (using boundary-safe regex matching for punctuated brand names)
    import re
    haystack = " ".join([title] + keywords).lower()
    hit_brands = sorted({
        b for b in brand_denylist
        if re.search(r"(?:^|(?<=[^a-z0-9]))" + re.escape(b) + r"(?:(?=[^a-z0-9])|$)", haystack)
    })
    if hit_brands:
        reasons.append(f"possible brand name(s): {', '.join(hit_brands)}")

    return reasons
