#!/usr/bin/env python3
"""
StockFlow — AI metadata generation for Shutterstock contributor photo submissions.

Usage:
    export GEMINI_API_KEY=your-key-here
    # Or pool: export GEMINI_API_KEYS=key1,key2,key3
    python stockflow.py /path/to/photo/folder [-o output.csv] [-b BATCH_SIZE]

Walks the given folder for supported images, asks Gemini in batches for titles,
keyword lists, and category suggestions, validates results against Shutterstock's
rules and StockFlow's quality bar, and writes everything to CSV in Shutterstock's
bulk metadata import format:

    Filename,Description,Keywords,Categories,Illustration,Mature Content,Editorial,Needs Review
"""
import argparse
import csv
import os
import sys
import time
from pathlib import Path

# Add project directory to sys.path for robust module imports
project_root = Path(__file__).resolve().parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from gemini_client import generate_metadata_batch, get_api_key_pool
from limits import SUPPORTED_EXTENSIONS
from validation import load_brand_denylist, load_categories, validate_row


def load_env_file(root_dir: Path) -> None:
    """Helper to auto-load GEMINI_API_KEY / GEMINI_API_KEYS from .env if present.
    Prioritizes central root .env before subfolder or working directory .env.
    """
    for env_path in [root_dir.parent / ".env", root_dir / ".env", Path.cwd() / ".env"]:
        if env_path.exists():
            for line in env_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, val = line.split("=", 1)
                    key = key.strip()
                    val = val.strip().strip("'\"")
                    if key and key not in os.environ:
                        os.environ[key] = val
            print(f"  • [Config] Loaded environment variables from '{env_path.name}'")
            break


CSV_HEADERS = [
    "Filename", "Description", "Keywords", "Categories",
    "Illustration", "Mature Content", "Editorial", "Needs Review"
]


def find_images(folder: Path) -> list[Path]:
    return sorted(
        p for p in folder.iterdir()
        if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS
    )


def read_existing_csv(output_path: Path) -> dict[str, list[str]]:
    """
    Reads an existing output CSV to support resuming interrupted jobs.
    Returns a dict mapping filename -> raw row list.
    Rows with 'generation failed' are excluded so they get re-attempted.
    """
    if not output_path.exists():
        return {}
    completed: dict[str, list[str]] = {}
    try:
        with open(output_path, "r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            header = next(reader, None)
            if not header:
                return {}
            for row in reader:
                if row and len(row) >= 8:
                    fname = row[0].strip()
                    needs_review = row[7].strip()
                    if fname and needs_review != "generation failed":
                        completed[fname] = row
    except Exception as e:
        print(f"  • [Resume Warning] Could not read existing CSV '{output_path.name}': {e}")
    return completed


def process_folder(
    folder: Path,
    output_path: Path,
    root_dir: Path,
    batch_size: int = 5,
    resume: bool = True,
    pacing_delay: float = 5.0,
    progress_callback: object = None,
    log_callback: object = None,
) -> dict:
    print("\n" + "=" * 70)
    print(" STOCKFLOW — Shutterstock Contributor Metadata Generator")
    print("=" * 70)
    print(" Execution Parameters:")
    print(f"  • Target Photo Folder: {folder.resolve()}")
    print(f"  • Output CSV Path    : {output_path.resolve()}")
    print(f"  • Batch Size         : {batch_size} image(s) per API call")
    print(f"  • Pacing Delay       : {pacing_delay}s between API calls")
    print(f"  • Resume Mode        : {'Enabled (skip previously processed)' if resume else 'Disabled (overwrite)'}")
    print(f"  • Gemini Model       : {os.environ.get('GEMINI_MODEL', 'gemini-2.5-flash')}")
    print("=" * 70)

    def log(msg: str) -> None:
        print(msg)
        if callable(log_callback):
            log_callback(msg)

    # Step 1: Environment & API Key Verification
    log("\n[Step 1/5] Verifying API Credentials & Key Pool...")
    load_env_file(root_dir)

    api_keys = get_api_key_pool()
    if not api_keys:
        err_msg = "ERROR: GEMINI_API_KEY or GEMINI_API_KEYS is not set."
        print(err_msg, file=sys.stderr)
        if callable(log_callback):
            log_callback(err_msg)
        sys.exit(1)
    log(f"  • {len(api_keys)} Gemini API key(s) loaded into rotation pool.")

    # Step 2: Configuration & Rule Engine Initialization
    log("\n[Step 2/5] Loading Configuration Rules and Dictionaries...")
    valid_categories = load_categories(str(root_dir))
    brand_denylist = load_brand_denylist(str(root_dir))
    if not valid_categories:
        err_msg = f"ERROR: no categories loaded from {root_dir / 'config/categories.txt'}"
        print(err_msg, file=sys.stderr)
        if callable(log_callback):
            log_callback(err_msg)
        sys.exit(1)
    log(f"  • Loaded {len(valid_categories)} valid Shutterstock submission categories.")
    log(f"  • Loaded {len(brand_denylist)} trademarked terms into the brand denylist.")

    # Step 3: Image Discovery
    log(f"\n[Step 3/5] Scanning Folder '{folder.name}' for Supported Images...")
    all_images = find_images(folder)
    if not all_images:
        msg = f"  • No supported images found in {folder} (supported formats: {', '.join(SUPPORTED_EXTENSIONS)})"
        log(msg)
        return {"total": 0, "ok_count": 0, "flagged_count": 0, "failed_count": 0, "output_path": output_path}
    log(f"  • Found {len(all_images)} supported image file(s): {', '.join(SUPPORTED_EXTENSIONS)}")

    total = len(all_images)
    ok_count = 0
    flagged_count = 0
    failed_count = 0

    # Resume Check: Read existing output if available
    existing_completed: dict[str, list[str]] = {}
    if resume and output_path.exists():
        existing_completed = read_existing_csv(output_path)
        if existing_completed:
            log(f"  • [Resume] Found {len(existing_completed)} previously completed image(s) in CSV. Skipping them.")

    # Determine which images need processing
    to_process: list[Path] = []
    initial_rows: list[list[str]] = []

    for img in all_images:
        if img.name in existing_completed:
            row = existing_completed[img.name]
            initial_rows.append(row)
            reasons_str = row[7].strip()
            if reasons_str:
                flagged_count += 1
            else:
                ok_count += 1
            if callable(progress_callback):
                progress_callback({
                    "event": "image_cached",
                    "filename": img.name,
                    "row": row,
                    "ok_count": ok_count,
                    "flagged_count": flagged_count,
                    "failed_count": failed_count,
                    "total": total,
                })
        else:
            to_process.append(img)

    processed_count = len(initial_rows)

    # Step 4: Setup CSV Writer
    log(f"\n[Step 4/5] Initializing Output CSV File '{output_path.name}'...")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(CSV_HEADERS)
        for row in initial_rows:
            writer.writerow(row)
        f.flush()

        # Step 5: Metadata Generation & Compliance Validation Loop in Batches
        if not to_process:
            log(f"  • All {total} images were already completed in '{output_path.name}'. Nothing to do!")
        else:
            log(f"\n[Step 5/5] Generating Metadata & Running Compliance Validation ({len(to_process)} new photos)...")
            log("=" * 70)

            image_batches = [to_process[i : i + batch_size] for i in range(0, len(to_process), batch_size)]

            for b_idx, current_batch in enumerate(image_batches, start=1):
                log(f"\n--- Processing Batch {b_idx}/{len(image_batches)} ({len(current_batch)} images) ---")

                if callable(progress_callback):
                    progress_callback({
                        "event": "batch_start",
                        "batch_idx": b_idx,
                        "total_batches": len(image_batches),
                        "batch_size": len(current_batch),
                        "processed_count": processed_count,
                        "total": total,
                    })

                try:
                    batch_metadata = generate_metadata_batch(
                        current_batch,
                        sorted(valid_categories),
                        api_keys=api_keys,
                        log_callback=log_callback,
                    )
                except Exception as e:
                    log(f"  • [Batch Error] Generation error: {e}")
                    batch_metadata = {}

                for image_path in current_batch:
                    processed_count += 1
                    metadata = batch_metadata.get(image_path)

                    if not metadata:
                        log(f"  [{processed_count}/{total}] {image_path.name} ==> [FAILED]")
                        row = [image_path.name, "", "", "", "No", "No", "No", "generation failed"]
                        writer.writerow(row)
                        failed_count += 1
                        if callable(progress_callback):
                            progress_callback({
                                "event": "image_processed",
                                "filename": image_path.name,
                                "status": "FAILED",
                                "reasons": ["generation failed"],
                                "row": row,
                                "ok_count": ok_count,
                                "flagged_count": flagged_count,
                                "failed_count": failed_count,
                                "total": total,
                                "current": processed_count,
                            })
                        continue

                    reasons = validate_row(
                        metadata.title, metadata.keywords, metadata.categories,
                        valid_categories, brand_denylist,
                    )
                    row = [
                        image_path.name,
                        metadata.title,
                        ", ".join(metadata.keywords),
                        ", ".join(metadata.categories),
                        "No",
                        "No",
                        "No",
                        "; ".join(reasons),
                    ]
                    writer.writerow(row)

                    if reasons:
                        flagged_count += 1
                        log(f"  [{processed_count}/{total}] {image_path.name} ==> FLAGGED ({'; '.join(reasons[:2])})")
                        status = "FLAGGED"
                    else:
                        ok_count += 1
                        log(f"  [{processed_count}/{total}] {image_path.name} ==> CLEAN")
                        status = "CLEAN"

                    if callable(progress_callback):
                        progress_callback({
                            "event": "image_processed",
                            "filename": image_path.name,
                            "status": status,
                            "reasons": reasons,
                            "row": row,
                            "ok_count": ok_count,
                            "flagged_count": flagged_count,
                            "failed_count": failed_count,
                            "total": total,
                            "current": processed_count,
                        })

                # Flush rows to disk after each batch so progress is never lost
                f.flush()

                # Pacing delay between batch calls to remain safely under free-tier 15 RPM
                if b_idx < len(image_batches):
                    log(f"  • Pacing delay ({pacing_delay}s) before next API batch request...")
                    time.sleep(pacing_delay)

    log("\n" + "=" * 70)
    log(" STOCKFLOW EXECUTION SUMMARY")
    log("=" * 70)
    log(f"  • Total Images Processed: {total}")
    log(f"  • Clean (Submission Ready): {ok_count}")
    log(f"  • Flagged for Manual Review: {flagged_count}")
    log(f"  • Failed Generation        : {failed_count}")
    log(f"  • Final Output CSV Saved To: {output_path.resolve()}")
    log("=" * 70 + "\n")

    summary = {
        "total": total,
        "ok_count": ok_count,
        "flagged_count": flagged_count,
        "failed_count": failed_count,
        "output_path": output_path,
    }
    if callable(progress_callback):
        progress_callback({"event": "completed", **summary})

    return summary


def main():
    parser = argparse.ArgumentParser(description="Generate Shutterstock metadata for a folder of photos.")
    parser.add_argument("folder", type=Path, help="Folder of photos to process")
    parser.add_argument("-o", "--output", type=Path, default=Path("stockflow_output.csv"),
                        help="Output CSV path (default: stockflow_output.csv)")
    parser.add_argument("-b", "--batch-size", type=int, default=5,
                        help="Number of images to process per API call (default: 5)")
    parser.add_argument("-d", "--delay", type=float, default=5.0,
                        help="Pacing delay in seconds between batch API calls (default: 5.0)")
    parser.add_argument("--no-resume", action="store_true",
                        help="Overwrite existing output CSV instead of resuming")
    args = parser.parse_args()

    if not args.folder.is_dir():
        print(f"ERROR: {args.folder} is not a folder", file=sys.stderr)
        sys.exit(1)

    process_folder(
        args.folder,
        args.output,
        project_root,
        batch_size=args.batch_size,
        resume=not args.no_resume,
        pacing_delay=args.delay,
    )


if __name__ == "__main__":
    main()

