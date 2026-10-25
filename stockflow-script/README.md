# StockFlow — AI Photo Metadata Generator 🏷️📸

Standalone AI metadata generation tool for **Shutterstock Contributors**, powered by **Google Gemini Vision**.  
Automatically inspects photo content and produces titles, 20–40 keywords, valid Shutterstock categories, and safety/compliance flags formatted for bulk CSV import.

---

## 🔄 Sequence in Workflow (Step 2)

```
[ Raw Photos ] ──> Step 1: AI Visual Renamer ──> [ Renamed Photos ] ──> Step 2: StockFlow ──> [ Shutterstock CSV ]
```

---

## 🚀 Quickstart Guide (3 Steps)

### Step 1: Install Dependencies
```bash
pip install -r requirements.txt
```

### Step 2: Set your Gemini API Key
Configure your key in the central `.env` file in the repository root (or copy `.env.example` to `.env`):

```bash
cp .env.example .env
```

Inside `.env`:
```ini
GEMINI_API_KEY=your_gemini_api_key_here
```

### Step 3: Run StockFlow!

#### Option A: Interactive Streamlit UI (Recommended)
Launch the browser UI:
```bash
streamlit run app.py
```
*Point it at your photo folder, click **Start Generating**, watch live progress and preview tables, and grab the CSV with 1-click download!*

#### Option B: Command-Line Interface (CLI)
```bash
python stockflow.py /path/to/your/photos -o stockflow_output.csv
```

---

## 🛠️ Command-Line Options

| Option | Short | Description | Default | Example |
|---|---|---|---|---|
| `folder` | | **(Required)** Path to folder containing image files | | `python stockflow.py ./photos` |
| `--output` | `-o` | Target CSV output file path | `stockflow_output.csv` | `python stockflow.py ./photos -o catalog.csv` |
| `--batch-size` | `-b` | Number of images per API call | `5` | `python stockflow.py ./photos -b 10` |
| `--delay` | `-d` | Pacing delay (seconds) between batch requests | `5.0` | `python stockflow.py ./photos -d 6.0` |
| `--no-resume` | | Overwrite existing output CSV instead of resuming | `False` | `python stockflow.py ./photos --no-resume` |


---

## 📋 CSV Output Format

StockFlow generates a CSV matching Shutterstock's official Bulk Import schema:

| Column Header | Description | Example |
|---|---|---|
| `Filename` | Exact filename on disk | `cherry_blossom_rain_droplets.jpg` |
| `Description` | Factual 1-sentence title describing main subject | `Close up of pink cherry blossom flowers with water droplets on branches.` |
| `Keywords` | 20–40 comma-separated keywords ordered by relevance | `cherry blossom, sakura, pink flower, water drops, spring, nature, macro, bloom, background...` |
| `Categories` | 1 or 2 standard Shutterstock categories (exact casing) | `Nature, Backgrounds/Textures` |
| `Illustration` | Indicates vector/illustration (`Yes`/`No`) | `No` |
| `Mature Content` | Flag for mature content (`Yes`/`No`) | `No` |
| `Editorial` | Flag for editorial submissions (`Yes`/`No`) | `No` |
| `Needs Review` | Flagged reasons if validation checks fail, or empty if clean | *(empty if clean)* |

---

## 🛡️ Validation & Compliance Engine

StockFlow runs every generated row through a strict rules engine prior to CSV export:

* **Keyword Count Guard**: Enforces 20–40 keywords per submission (Shutterstock allows 7–50).
* **Title Quality Control**: Flags missing titles, titles under 5 words, or titles over 200 characters.
* **Exact Category Casing**: Validates categories against Shutterstock's official category registry (`config/categories.txt`) preserving standard title casing (`Abstract`, `Animals/Wildlife`, etc.).
* **Trademark & Brand Safety**: Checks title and keywords against `config/brand_denylist.txt` using boundary-safe regex matching to detect brand names (including punctuated terms like `coca-cola` and `mcdonald's`) and prevent commercial IP rejection.

---

## ⚙️ Configuration Files

Configuration dictionaries are located inside `config/`:

* **[`config/categories.txt`](./config/categories.txt)**: List of official Shutterstock categories. Edit this file if Shutterstock updates its submission taxonomy.
* **[`config/brand_denylist.txt`](./config/brand_denylist.txt)**: List of trademarked brand terms to screen out from commercial submissions.

---

## ⚡ Performance & Reliability Features
 
 1. **Batch API Processing**: Groups multiple images into a single multimodal API payload (default 5 photos per call) reducing API calls by up to 80%.
 2. **Free-Tier 429 Quota Resilience**: Automatically parses Gemini quota retry delays and safely waits out the rate-limit window without crashing, losing progress, or discarding remaining images.
 3. **Smart Resume & Checkpointing**: Re-running on a folder checks the destination CSV and skips already processed images, allowing seamless resumption of interrupted or paused jobs.
 4. **API Key Rotation Pool**: Supports comma-separated keys in `GEMINI_API_KEYS` to automatically rotate keys upon hitting rate limits.
 5. **Model Fallback**: Automatically cascades across Gemini models (`gemini-2.5-flash` ➔ `gemini-2.0-flash` ➔ `gemini-1.5-flash`) if primary quota is reached.
 6. **Smart Downscaling**: Resizes large images to 1024px in memory before sending, drastically minimizing token overhead.

