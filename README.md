# StockFlow: Shutterstock Metadata & AI Visual Renaming Suite

**End-to-end computer vision pipeline for automated photo renaming, SEO slug generation, and Shutterstock-compliant bulk CSV metadata compilation.**

[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![AI Engine](https://img.shields.io/badge/Vision%20Engine-Gemini%20Vision-4285F4?style=flat-square&logo=google&logoColor=white)](https://aistudio.google.com/)
[![CSV Spec](https://img.shields.io/badge/Catalog-Shutterstock%20Approved-FF5500?style=flat-square)](https://submit.shutterstock.com/)
[![Interface](https://img.shields.io/badge/Interface-CLI%20%2B%20Streamlit%20Studio-FF4B4B?style=flat-square&logo=streamlit&logoColor=white)](#execution-modes)
[![License](https://img.shields.io/badge/License-MIT-blue.svg?style=flat-square)](LICENSE)

---

## The Contributor Bottleneck

Stock photography contributors capturing high-volume portfolios (macro insect studies, architecture, landscapes) face severe operational friction when submitting assets to commercial marketplaces:
1. **Opaque Camera Hashes:** Raw files exit cameras with unsearchable names (e.g. `DSC_0492.JPG`, `IMG_9102.RAW`).
2. **Keywording Overhead:** Shutterstock mandates 20–50 relevant keywords, strict 5-word minimum descriptions, and compliant category assignments per image.
3. **Rejection Risks:** Trademarked brand names, logos, or improperly tagged editorial assets cause batch rejections by stock reviewers.

**StockFlow** completely eliminates this bottleneck using multimodal vision AI. It analyzes the physical pixels of each image, renames the file to a descriptive SEO slug, and compiles a validated, upload-ready Shutterstock catalog CSV.

---

## Architectural Pipeline

```
[ Raw Photos: DSC_001.JPG ]
             │
             ▼
┌──────────────────────────────┐
│  STEP 1: AI Visual Renamer   │  ---> Visually identifies subjects and renames files
│  (image-file-rename-script)  │       e.g., macro_dragonfly_compound_eyes.jpg
└──────────────┬───────────────┘       (Generates rename_mapping.json for 1-click undo)
               │
               ▼
┌──────────────────────────────┐
│  STEP 2: StockFlow Engine    │  ---> Synthesizes 20–40 ranked keywords, titles,
│     (stockflow-script)       │       Shutterstock categories & checks brand denylists
└──────────────┬───────────────┘
               │
               ▼
[ Shutterstock Catalog CSV: Filename, Description, Keywords, Categories ]
```

---

## Output CSV Schema Specification

The generated CSV conforms strictly to the **Shutterstock Contributor Catalog Specification**:

| Column Name | Type / Format | Validation Rule | Example Value |
|---|---|---|---|
| **Filename** | String (`.jpg`, `.png`) | Must match renamed file on disk | `macro_dragonfly_compound_eyes.jpg` |
| **Description** | String (Sentence case) | 5–250 characters; descriptive context | `Extreme close-up macro of dragonfly compound eyes resting on foliage` |
| **Keywords** | Comma-delimited list | 20 to 50 relevant, ranked tags | `dragonfly, macro, compound eyes, insect, wildlife, taxila, nature, fauna` |
| **Categories** | Comma-delimited (Max 2) | Must match official Shutterstock list | `Animals/Wildlife, Nature` |
| **Illustration** | Enum (`yes` / `no`) | Automatic visual classification | `no` |
| **Mature Content** | Enum (`yes` / `no`) | Safety content scan | `no` |
| **Editorial** | Enum (`yes` / `no`) | Commercial vs editorial flag | `no` |
| **Needs Review** | Boolean (`True` / `False`) | Diagnostic flag for low tags or brands | `False` |

---

## Quickstart

### 1. Installation
Clone the repository and install required dependencies:

```bash
git clone https://github.com/hmsaeed-dev/stockflow.git
cd stockflow
pip install -r requirements.txt
```

### 2. Configure Environment Keys
Obtain a free API key from [Google AI Studio](https://aistudio.google.com/apikey). Copy `.env.example` to `.env` in the repository root:

```bash
cp .env.example .env
```

Inside `.env`:
```ini
# Primary Gemini API Key
GEMINI_API_KEY=your_gemini_api_key_here

# Optional: Gemini model override (default: gemini-2.5-flash)
GEMINI_MODEL=gemini-2.5-flash

# Optional: Batch size and request delays
BATCH_SIZE=5
REQUEST_DELAY_SECONDS=4.0
```

---

## Execution Modes

### Mode 1: Unified Web Studio (Streamlit)
Launch the comprehensive graphical browser dashboard for visual side-by-side reviews, one-click renames, and instant CSV generation:

```bash
python run_ui.py
# Alternatively: streamlit run stockflow-script/app.py
```

- **Features:** Folder bookmarks, live image preview grid, dry-run diff preview, 1-click rollback, real-time Gemini rate-limit radar with cooldown timers, and instant CSV downloads.

---

### Mode 2: Headless CLI Pipeline

#### Step 1: Rename Files with Visual AI
```bash
cd image-file-rename-script

# Dry Run: Preview proposed AI slugs without modifying files on disk
python rename.py /path/to/photos --dry-run

# Commit Renaming: Renames files and records rollback log
python rename.py /path/to/photos

# Undo / Rollback (Emergency restore):
python rename.py --undo /path/to/photos/rename_mapping.json
```

#### Step 2: Compile Bulk Metadata CSV
```bash
cd ../stockflow-script

# Generate catalog CSV with automatic checkpoint resumption
python stockflow.py /path/to/photos -o stockflow_output.csv
```

---

## Core Engineering Features

- **Pacing & Rate-Limit Radar:** Implements adaptive token-bucket delays and exponential backoff to ensure continuous batch operation within Gemini API free-tier quotas (15 RPM).
- **Trademark Denylist Enforcement:** Scans generated keywords against `config/brand_denylist.txt` to flag trademarked logos, vehicle brands, or tech hardware before marketplace submission.
- **Resilient Checkpointing:** If network interruption occurs, re-running `stockflow.py` reads existing CSV rows and automatically resumes from the exact unindexed image.
- **Non-Destructive Operations:** The renamer creates cryptographic-like JSON mappings of original paths, preventing unrecoverable file loss.

---

## Author & Credits

Architected and developed by **Hafiz Muhammad Saeed** ([@hmsaeed-dev](https://github.com/hmsaeed-dev)).

*System documentation maintained in personal knowledge vault at [`vault/03_SYSTEMS/StockFlow AI.md`](https://github.com/hmsaeed-dev/stockflow).*
