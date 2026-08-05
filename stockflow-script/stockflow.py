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
    """Helper to auto-load GEMINI_API_KEY / GEMINI_API_KEYS from .env if present."""
    for env_path in [root_dir / ".env", root_dir.parent / ".env", Path.cwd() / ".env"]:
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


def find_images(folder: Path) -> list[Path]:
    return sorted(
        p for p in folder.iterdir()
        if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS
    )


def process_folder(folder: Path, output_path: Path, root_dir: Path, batch_size: int = 5) -> None:
    print("\n" + "=" * 70)
    print(" STOCKFLOW — Shutterstock Contributor Metadata Generator")
    print("=" * 70)
    print(" Execution Parameters:")
    print(f"  • Target Photo Folder: {folder.resolve()}")
    print(f"  • Output CSV Path    : {output_path.resolve()}")
    print(f"  • Batch Size         : {batch_size} image(s) per API call")
    print(f"  • Gemini Model       : {os.environ.get('GEMINI_MODEL', 'gemini-2.0-flash')}")
    print("=" * 70)

    # Step 1: Environment & API Key Verification
    print("\n[Step 1/5] Verifying API Credentials & Key Pool...")
    load_env_file(root_dir)

    api_keys = get_api_key_pool()
    if not api_keys:
        print("ERROR: GEMINI_API_KEY or GEMINI_API_KEYS is not set.", file=sys.stderr)
        sys.exit(1)
    print(f"  • {len(api_keys)} Gemini API key(s) loaded into rotation pool.")

    # Step 2: Configuration & Rule Engine Initialization
    print("\n[Step 2/5] Loading Configuration Rules and Dictionaries...")
    valid_categories = load_categories(str(root_dir))
    brand_denylist = load_brand_denylist(str(root_dir))
    if not valid_categories:
        print(f"ERROR: no categories loaded from {root_dir / 'config/categories.txt'}", file=sys.stderr)
        sys.exit(1)
    print(f"  • Loaded {len(valid_categories)} valid Shutterstock submission categories.")
    print(f"  • Loaded {len(brand_denylist)} trademarked terms into the brand denylist.")

    # Step 3: Image Discovery
    print(f"\n[Step 3/5] Scanning Folder '{folder.name}' for Supported Images...")
    images = find_images(folder)
    if not images:
        print(f"  • No supported images found in {folder} (supported formats: {', '.join(SUPPORTED_EXTENSIONS)})")
        return
    print(f"  • Found {len(images)} supported image file(s): {', '.join(SUPPORTED_EXTENSIONS)}")

    total = len(images)
    ok_count = 0
    flagged_count = 0
    failed_count = 0

    # Step 4: Setup CSV Writer
    print("\n[Step 4/5] Initializing Output CSV File...")
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "Filename", "Description", "Keywords", "Categories",
            "Illustration", "Mature Content", "Editorial", "Needs Review"
        ])
        f.flush()
        print("  • Created CSV output file with standard Shutterstock import headers.")

        # Step 5: Metadata Generation & Compliance Validation Loop in Batches
        print(f"\n[Step 5/5] Generating Metadata & Running Compliance Validation ({total} photos)...")
        print("=" * 70)

        image_batches = [images[i : i + batch_size] for i in range(0, total, batch_size)]
        processed_count = 0

        for b_idx, current_batch in enumerate(image_batches, start=1):
            print(f"\n--- Processing Batch {b_idx}/{len(image_batches)} ({len(current_batch)} images) ---")

            try:
                batch_metadata = generate_metadata_batch(
                    current_batch, sorted(valid_categories), api_keys=api_keys
                )
            except Exception as e:
                print(f"  • [Batch Error] Generation error: {e}")
                batch_metadata = {}

            for image_path in current_batch:
                processed_count += 1
                metadata = batch_metadata.get(image_path)

                if not metadata:
                    print(f"  [{processed_count}/{total}] {image_path.name} ==> [FAILED]")
                    writer.writerow([image_path.name, "", "", "", "No", "No", "No", "generation failed"])
                    failed_count += 1
                    continue

                reasons = validate_row(
                    metadata.title, metadata.keywords, metadata.categories,
                    valid_categories, brand_denylist,
                )
                writer.writerow([
                    image_path.name,
                    metadata.title,
                    ", ".join(metadata.keywords),
                    ", ".join(metadata.categories),
                    "No",
                    "No",
                    "No",
                    "; ".join(reasons),
                ])

                if reasons:
                    flagged_count += 1
                    print(f"  [{processed_count}/{total}] {image_path.name} ==> FLAGGED ({'; '.join(reasons[:2])})")
                else:
                    ok_count += 1
                    print(f"  [{processed_count}/{total}] {image_path.name} ==> CLEAN")

            # Flush rows to disk after each batch so progress is never lost
            f.flush()

            # Pacing delay between batch calls
            if b_idx < len(image_batches):
                print("  • Pacing delay (4s) before next API batch request...")
                time.sleep(4)

    print("\n" + "=" * 70)
    print(" STOCKFLOW EXECUTION SUMMARY")
    print("=" * 70)
    print(f"  • Total Images Processed: {total}")
    print(f"  • Clean (Submission Ready): {ok_count}")
    print(f"  • Flagged for Manual Review: {flagged_count}")
    print(f"  • Failed Generation        : {failed_count}")
    print(f"  • Final Output CSV Saved To: {output_path.resolve()}")
    print("=" * 70 + "\n")


def main():
    parser = argparse.ArgumentParser(description="Generate Shutterstock metadata for a folder of photos.")
    parser.add_argument("folder", type=Path, help="Folder of photos to process")
    parser.add_argument("-o", "--output", type=Path, default=Path("stockflow_output.csv"),
                         help="Output CSV path (default: stockflow_output.csv)")
    parser.add_argument("-b", "--batch-size", type=int, default=5,
                         help="Number of images to process per API call (default: 5)")
    args = parser.parse_args()

    if not args.folder.is_dir():
        print(f"ERROR: {args.folder} is not a folder", file=sys.stderr)
        sys.exit(1)

    process_folder(args.folder, args.output, project_root, batch_size=args.batch_size)


if __name__ == "__main__":
    main()
