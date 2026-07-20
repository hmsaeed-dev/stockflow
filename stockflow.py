#!/usr/bin/env python3
"""
StockFlow — Phase 1: AI metadata generation for Shutterstock contributor
submissions.

Usage:
    export GEMINI_API_KEY=your-key-here
    python stockflow.py /path/to/photo/folder [-o output.csv]

Walks the given folder for supported images, asks Gemini for a title,
keyword list, and category suggestion for each one, validates the result
against Shutterstock's rules and StockFlow's own quality bar, and writes
everything to a CSV in Shutterstock's bulk metadata import format:

    Filename,Description,Keywords,Categories,Needs Review

A row that fails validation is still written (never dropped), with the
failure reasons in the Needs Review column so it's easy to filter and
fix by hand instead of getting lost in a large batch.
"""
import argparse
import csv
import os
import sys
from pathlib import Path

from google import genai

from limits import SUPPORTED_EXTENSIONS
from gemini_client import generate_metadata
from validation import load_categories, load_brand_denylist, validate_row


def find_images(folder: Path) -> list[Path]:
    return sorted(
        p for p in folder.iterdir()
        if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS
    )


def process_folder(folder: Path, output_path: Path, project_root: Path) -> None:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("ERROR: set the GEMINI_API_KEY environment variable first.", file=sys.stderr)
        sys.exit(1)

    valid_categories = load_categories(str(project_root))
    brand_denylist = load_brand_denylist(str(project_root))
    if not valid_categories:
        print(f"ERROR: no categories loaded from {project_root / 'config/categories.txt'}",
              file=sys.stderr)
        sys.exit(1)

    images = find_images(folder)
    if not images:
        print(f"No supported images found in {folder} "
              f"(supported: {', '.join(SUPPORTED_EXTENSIONS)})")
        return

    client = genai.Client(api_key=api_key)
    total = len(images)
    ok_count = 0
    flagged_count = 0
    failed_count = 0

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["Filename", "Description", "Keywords", "Categories", "Needs Review"])

        for i, image_path in enumerate(images, start=1):
            print(f"[{i}/{total}] {image_path.name} ... ", end="", flush=True)
            try:
                metadata = generate_metadata(
                    client, str(image_path), sorted(valid_categories)
                )
            except Exception as e:  # noqa: BLE001 - keep the batch going
                print(f"FAILED ({e})")
                writer.writerow([image_path.name, "", "", "", f"generation failed: {e}"])
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
                "; ".join(reasons),
            ])

            if reasons:
                flagged_count += 1
                print(f"flagged ({'; '.join(reasons)})")
            else:
                ok_count += 1
                print("ok")

    print()
    print(f"Done. {ok_count} clean, {flagged_count} flagged for review, "
          f"{failed_count} failed to generate. Output: {output_path}")


def main():
    parser = argparse.ArgumentParser(description="Generate Shutterstock metadata for a folder of photos.")
    parser.add_argument("folder", type=Path, help="Folder of photos to process")
    parser.add_argument("-o", "--output", type=Path, default=Path("stockflow_output.csv"),
                         help="Output CSV path (default: stockflow_output.csv)")
    args = parser.parse_args()

    if not args.folder.is_dir():
        print(f"ERROR: {args.folder} is not a folder", file=sys.stderr)
        sys.exit(1)

    project_root = Path(__file__).resolve().parent
    process_folder(args.folder, args.output, project_root)


if __name__ == "__main__":
    main()
