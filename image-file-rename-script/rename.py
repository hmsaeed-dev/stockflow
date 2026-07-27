#!/usr/bin/env python3
"""
AI Photo Rename CLI — Standalone AI-Powered Image Renaming Tool.

Visually inspects image files using Google Gemini AI Vision and renames
photos based on their actual visual content (subject, scene, action).

Usage:
    1. Set GEMINI_API_KEY in environment or .env file.
    2. Run:
       python rename.py /path/to/photo/folder [--dry-run]

Options:
    -d, --dry-run     Preview proposed AI renames without modifying disk.
    -s, --separator   Word separator: '_' (snake_case) or '-' (kebab-case). Default: '_'
    --prefix          Add prefix to AI-generated name.
    --suffix          Add suffix to AI-generated name.
    --undo MAPPING    Revert previous rename operation using rename_mapping.json.
"""
import argparse
import json
import os
import sys
from pathlib import Path

# Add script directory to sys.path for standalone portability
script_dir = Path(__file__).resolve().parent
if str(script_dir) not in sys.path:
    sys.path.insert(0, str(script_dir))

from google import genai
from gemini_namer import suggest_image_name

SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff"}


def load_env_file(root_dir: Path) -> None:
    """Auto-load GEMINI_API_KEY from .env if present."""
    for env_file in [root_dir / ".env", root_dir.parent / ".env", Path.cwd() / ".env"]:
        if env_file.exists():
            for line in env_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, val = line.split("=", 1)
                    key = key.strip()
                    val = val.strip().strip("'\"")
                    if key and key not in os.environ:
                        os.environ[key] = val
            break


def find_images(folder: Path, recursive: bool = False) -> list[Path]:
    """Find supported image files in folder."""
    glob_fn = folder.rglob if recursive else folder.glob
    return sorted(
        [p for p in glob_fn("*") if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS],
        key=lambda p: p.name.lower(),
    )


def normalize_extension(ext: str) -> str:
    """Standardize extensions (e.g. .jpeg -> .jpg)."""
    lower = ext.lower()
    if lower == ".jpeg":
        return ".jpg"
    if lower == ".tiff":
        return ".tif"
    return lower


def undo_renames(mapping_file: Path, dry_run: bool = False) -> None:
    """Undo renames using a saved JSON mapping log."""
    if not mapping_file.is_file():
        print(f"ERROR: Mapping file {mapping_file} not found.", file=sys.stderr)
        sys.exit(1)

    mapping = json.loads(mapping_file.read_text(encoding="utf-8"))
    prefix = "[DRY RUN] " if dry_run else ""
    print(f"\n{prefix}Reverting {len(mapping)} renamed files...")
    print("-" * 60)

    reverted = 0
    for entry in reversed(mapping):
        orig = Path(entry["original"])
        target = Path(entry["target"])

        if target.exists():
            print(f"  {target.name:<35} -> {orig.name}")
            if not dry_run and orig != target:
                target.rename(orig)
            reverted += 1
        else:
            print(f"  SKIP (Not found): {target.name}")

    print("-" * 60)
    print(f"Reverted {reverted} files successfully.")


def batch_rename_images(
    folder: Path,
    dry_run: bool = False,
    separator: str = "_",
    prefix: str = "",
    suffix: str = "",
    recursive: bool = False,
) -> None:
    """Perform AI visual analysis and batch rename images."""
    load_env_file(script_dir)

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("ERROR: GEMINI_API_KEY environment variable is not set.", file=sys.stderr)
        print("Set it in your terminal or create a .env file with GEMINI_API_KEY=your_key", file=sys.stderr)
        sys.exit(1)

    images = find_images(folder, recursive=recursive)
    if not images:
        print(f"No supported images found in {folder} (supported: {', '.join(SUPPORTED_EXTENSIONS)})")
        return

    client = genai.Client(api_key=api_key)
    total = len(images)

    mode_title = "[DRY RUN] AI Visual Image Renaming:" if dry_run else "AI Visual Image Renaming:"
    print(f"\n{mode_title} ({total} photos)")
    print("=" * 70)

    proposed_renames = []
    used_filenames = set()

    for idx, image_path in enumerate(images, start=1):
        print(f"[{idx}/{total}] Analyzing {image_path.name} ... ", end="", flush=True)
        try:
            raw_slug = suggest_image_name(client, image_path)
            if separator != "_":
                raw_slug = raw_slug.replace("_", separator)

            ext = normalize_extension(image_path.suffix)
            base_name = f"{prefix}{raw_slug}{suffix}"

            # Handle duplicate filename collisions across the batch
            candidate_name = f"{base_name}{ext}"
            counter = 1
            while candidate_name.lower() in used_filenames or (
                (image_path.parent / candidate_name).exists()
                and (image_path.parent / candidate_name) != image_path
                and candidate_name.lower() not in [p[1].name.lower() for p in proposed_renames]
            ):
                candidate_name = f"{base_name}{separator}{counter:02d}{ext}"
                counter += 1

            used_filenames.add(candidate_name.lower())
            target_path = image_path.parent / candidate_name

            proposed_renames.append((image_path, target_path))
            print(f"-> {candidate_name}")

        except Exception as err:
            print(f"FAILED ({err})")
            proposed_renames.append((image_path, image_path))

    print("=" * 70)
    changed_count = sum(1 for src, dst in proposed_renames if src != dst)
    print(f"Summary: {total} photos analyzed, {changed_count} to rename.")

    mapping_data = []
    for src, dst in proposed_renames:
        mapping_data.append({"original": str(src), "target": str(dst)})

    if not dry_run and changed_count > 0:
        for src, dst in proposed_renames:
            if src != dst:
                src.rename(dst)

        log_file = folder / "rename_mapping.json"
        log_file.write_text(json.dumps(mapping_data, indent=2), encoding="utf-8")
        print(f"\nSuccess! Renamed {changed_count} files.")
        print(f"Rename log saved to: {log_file}")
        print(f"To undo this operation later, run:\n  python rename.py --undo \"{log_file}\"")


def main():
    parser = argparse.ArgumentParser(description="Standalone AI-Powered Image File Renamer using Gemini Vision.")
    parser.add_argument("folder", type=Path, nargs="?", help="Folder containing images to analyze and rename")
    parser.add_argument("-d", "--dry-run", action="store_true", help="Preview proposed AI names without modifying files")
    parser.add_argument("-s", "--separator", choices=["_", "-"], default="_", help="Word separator for slugs (default: '_')")
    parser.add_argument("--prefix", default="", help="Optional prefix to add to AI names")
    parser.add_argument("--suffix", default="", help="Optional suffix to add to AI names")
    parser.add_argument("-r", "--recursive", action="store_true", help="Process subdirectories recursively")
    parser.add_argument("--undo", type=Path, help="Undo a previous rename using rename_mapping.json")

    args = parser.parse_args()

    if args.undo:
        undo_renames(args.undo, dry_run=args.dry_run)
        return

    if not args.folder or not args.folder.is_dir():
        print("ERROR: Please specify a valid folder path.", file=sys.stderr)
        parser.print_help()
        sys.exit(1)

    batch_rename_images(
        args.folder,
        dry_run=args.dry_run,
        separator=args.separator,
        prefix=args.prefix,
        suffix=args.suffix,
        recursive=args.recursive,
    )


if __name__ == "__main__":
    main()
