# StockFlow (Phase 1)

AI metadata generation for Shutterstock contributor photo submissions.
Points at a folder of photos, asks Gemini for a title/keywords/category
per image, validates the result, and writes a CSV ready for
Shutterstock's bulk metadata import.

## Setup

```bash
pip install -r requirements.txt
export GEMINI_API_KEY=your-key-here   # get one at https://aistudio.google.com/apikey
```

## Usage

```bash
python stockflow.py /path/to/photo/folder
```

By default this writes `stockflow_output.csv` in the current directory.
To choose a different output path:

```bash
python stockflow.py /path/to/photo/folder -o my_batch.csv
```

Supported input formats: JPEG, PNG, WEBP, TIFF. (TIFF files are
converted to JPEG in memory before being sent to Gemini, since Gemini's
image-understanding endpoint doesn't accept TIFF directly — Shutterstock
still gets the original TIFF file when you upload it separately; this
tool only ever reads it, never modifies it.)

## Output format

`stockflow_output.csv` has five columns:

| Column | Notes |
|---|---|
| `Filename` | Exact match to the image file's name |
| `Description` | The generated title |
| `Keywords` | Comma-separated, in one cell |
| `Categories` | One or two, comma-separated, in one cell |
| `Needs Review` | Empty if the row passed validation; otherwise a semicolon-separated list of reasons |

The first four columns are what Shutterstock's bulk import expects.
Drop the `Needs Review` column before import, or just review/delete
those rows first — either way, filter on that column to find what needs
a human look before you skim the rest.

## Editing the rules

Two things are designed to be edited without touching any code:

- **`config/categories.txt`** — the valid Shutterstock category list.
  If Shutterstock adds, renames, or removes a category, edit this file.
- **`config/brand_denylist.txt`** — words that get a row flagged for a
  manual brand-name check. This is a starter list, not exhaustive — add
  to it as you notice brands showing up in your own photos.

Numeric limits (min/max keywords, title length) live in `limits.py` as
named constants, not scattered through the code.

## Known limitations (Phase 1)

- **Brand-name check is a naive substring match.** It will have false
  positives on words that are also brand names (e.g. "apple" the fruit
  vs. Apple the company, "puma" the animal vs. Puma the brand). That's
  intentional — it only ever flags for manual review, never auto-removes
  anything, so a false positive just costs you one glance at that row.
- **No cost/rate-limit handling beyond basic retry.** Each image is
  processed one at a time with exponential backoff on failure (3
  attempts). For large batches, watch your Gemini API quota — see
  PRD §8.
- **Title length limit is stricter than Shutterstock's own.**
  Shutterstock allows up to 2048 characters, but this tool flags
  anything over 200, since a 2000-character "title" is a bad stock photo
  title even if Shutterstock would technically accept it.
- Video, vector/illustration files, and multi-agency support are
  explicitly out of scope for this phase — see the PRD's Non-goals.
