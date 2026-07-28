# Shutterstock Contributor AI Automation Pipeline

An end-to-end AI automation suite for **Shutterstock Contributor** photo submissions powered by **Google Gemini Vision**.

---

## 🔄 Two-Step Sequential Pipeline

To prepare your photos for Shutterstock upload, run the two tools **in sequence**:

```
[ Raw Camera Photos ]
         │
         ▼
 ┌──────────────────────────────┐
 │  STEP 1: AI Visual Renamer   │  ---> Renames images to descriptive SEO slugs
 │  (image-file-rename-script)  │       (e.g., cherry_blossom_rain_droplets.jpg)
 └──────────────┬───────────────┘
                │
                ▼
 ┌───────────────────────────────┐
 │  STEP 2: AI Metadata Generator│ ---> Generates upload-ready Shutterstock CSV
 │     (stockflow-script)        │       (Filename, Description, Keywords, Categories)
 └──────────────┬────────────────┘
                │
                ▼
  [ Shutterstock Bulk Import CSV ]
```

---

## 📁 Repository Structure

* **[`image-file-rename-script/`](./image-file-rename-script)** — **Step 1 Tool**: Visually analyzes photo content and renames files to clean snake_case SEO slugs using Gemini AI Vision.
* **[`stockflow-script/`](./stockflow-script)** — **Step 2 Tool**: Generates Shutterstock-compliant titles, 20-40 keywords, categories, and runs safety validation checks.

---

## ⚡ Quickstart Guide

### 1. Installation

Clone this repository and install the shared dependencies:

```bash
git clone https://github.com/your-username/shutterstock-ai-automation.git
cd shutterstock-ai-automation
pip install -r requirements.txt
```

### 2. Configure API Key

Copy `.env.example` to `.env` in the project root and add your [Gemini API Key](https://aistudio.google.com/apikey):

```bash
cp .env.example .env
```

Inside `.env`:

```ini
GEMINI_API_KEY=your_gemini_api_key_here
```

---

## 🚀 Execution Guide

### STEP 1: Rename Photos with AI Vision

Before generating metadata, rename your raw photos so their filenames are descriptive and standardized:

```bash
cd image-file-rename-script

# Preview proposed AI names (Dry Run - no disk changes)
python rename.py /path/to/your/photos --dry-run

# Perform actual AI renaming
python rename.py /path/to/your/photos
```

### STEP 2: Generate Shutterstock Metadata CSV

Once your photos are renamed, generate the Shutterstock bulk metadata CSV:

```bash
cd ../stockflow-script

# Generate bulk import CSV
python stockflow.py /path/to/your/photos -o stockflow_output.csv
```

Now upload your renamed photos to Shutterstock via FTP/Web, and import `stockflow_output.csv` into the Shutterstock Contributor Catalog Manager!

---

## 🛡️ Safety & Features

* **Visual AI Recognition**: Uses Gemini Vision to see physical photo contents.
* **Non-Destructive Dry Run**: Preview proposed changes before committing to disk.
* **1-Click Undo**: `rename.py` writes a `rename_mapping.json` log to allow instant rollback (`--undo`).
* **Brand Denylist Safety**: Automatically flags trademark/brand names to protect commercial submission approval.
* **Shutterstock CSV Standard**: Exports standard `Filename, Description, Keywords, Categories, Illustration, Mature Content, Editorial, Needs Review` CSV columns.
