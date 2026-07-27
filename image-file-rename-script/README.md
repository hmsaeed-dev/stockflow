# AI Photo Renamer 📸🤖

Standalone, AI-powered image renaming tool using **Google Gemini Vision**.
Visually analyzes each image file and renames it based on its actual visual content into clean, SEO/stock-friendly filenames.

---

## 🚀 Quickstart Guide (3 Steps)

### Step 1: Install Dependencies
```bash
pip install -r requirements.txt
```

### Step 2: Set your Gemini API Key
Copy `.env.example` to `.env` and paste your key (Get a free API key at [AI Studio](https://aistudio.google.com/apikey)):

```bash
cp .env.example .env
```
Inside `.env`:
```ini
GEMINI_API_KEY=your_gemini_api_key_here
```

### Step 3: Run the Script!

#### 1. Preview AI Names (Dry Run - No files changed):
```bash
python rename.py /path/to/your/photos --dry-run
```

#### 2. Rename Images:
```bash
python rename.py /path/to/your/photos
```

---

## 🛠️ Options & Examples

| Option | Description | Example |
|---|---|---|
| `-d, --dry-run` | Preview proposed AI names without touching disk | `python rename.py ./photos -d` |
| `-s, --separator` | Word separator: `_` (default) or `-` | `python rename.py ./photos -s -` |
| `--prefix` | Add a prefix to AI names | `python rename.py ./photos --prefix nature_` |
| `--suffix` | Add a suffix to AI names | `python rename.py ./photos --suffix _v1` |
| `-r, --recursive` | Process subfolders recursively | `python rename.py ./photos -r` |
| `--undo` | Revert previous rename using JSON log | `python rename.py --undo ./photos/rename_mapping.json` |

---

## 💡 How It Works

1. **Visual Content Inspection**: Uses Gemini AI Vision (`gemini-2.5-flash`) to examine what is physically inside each photo.
2. **Stock-Friendly Slugs**: Produces short, descriptive 3–6 word slugs (e.g. `cherry_blossom_rain_droplets.jpg` instead of `IMG_100293.jpg`).
3. **Smart Deduplication**: If multiple photos depict identical subjects in a batch, auto-appends numbers (`_01`, `_02`).
4. **Safety Log & Undo**: Saves `rename_mapping.json` after every run so you can revert any rename with 1-click.
