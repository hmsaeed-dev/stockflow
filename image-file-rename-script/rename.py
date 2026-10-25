#!/usr/bin/env python3
"""
AI Photo Rename CLI — Standalone AI-Powered Image Renaming Tool.

Visually inspects image files using Google Gemini AI Vision and renames
photos based on their actual visual content (subject, scene, action).

FEATURES & OPTIMIZATIONS:
1. Batch Processing: Groups images (default: 5 per request) to reduce total API calls by up to 80%.
2. Key Rotation Pool: Supports GEMINI_API_KEYS pool to automatically rotate API keys on 429 quota exhaustion.
3. Model Fallback: Automatically falls back across Gemini models if a primary model hits limits.
4. Downscaling: Automatically resizes large images in memory before sending to minimize token consumption.
5. Immediate Checkpoint Log: Writes rename_mapping.json as files are processed so progress is never lost.
6. Undo Capability: Reverses any previous renaming operation using rename_mapping.json.
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

# Add script directory to sys.path for standalone portability
script_dir = Path(__file__).resolve().parent
if str(script_dir) not in sys.path:
    sys.path.insert(0, str(script_dir))


def load_env_file(root_dir: Path) -> None:
    """
    Auto-load environment variables from .env if present.
    Prioritizes central root .env before subfolder or working directory .env.
    """
    for env_file in [root_dir.parent / ".env", root_dir / ".env", Path.cwd() / ".env"]:
        if env_file.exists():
            for line in env_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, val = line.split("=", 1)
                    key = key.strip()
                    val = val.strip().strip("'\"")
                    if key and key not in os.environ:
                        os.environ[key] = val
            print(f"  • [Config] Loaded environment variables from '{env_file.name}'")
            break


# Load environment variables before importing dependent modules
load_env_file(script_dir)

from gemini_namer import get_api_key_pool, suggest_image_names_batch

# File extensions supported by this tool
SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff"}


def normalize_extension(ext: str) -> str:
    """
    Standardize extensions for cleaner file naming (.jpeg -> .jpg, .tiff -> .tif).
    """
    lower = ext.lower()
    if lower == ".jpeg":
        return ".jpg"
    if lower == ".tiff":
        return ".tif"
    return lower


def find_images(folder: Path, recursive: bool = False) -> list[Path]:
    """
    Find supported image files in target folder.
    Returns a sorted list of Path objects for all matching image files.
    """
    glob_fn = folder.rglob if recursive else folder.glob
    return sorted(
        [p for p in glob_fn("*") if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS],
        key=lambda p: p.name.lower(),
    )


def undo_renames(mapping_file: Path, dry_run: bool = False) -> None:
    """
    Undo renames using a saved JSON mapping log (rename_mapping.json).
    Iterates through recorded original -> target mappings in reverse order.
    """
    if not mapping_file.is_file():
        print(f"ERROR: Mapping file {mapping_file} not found.", file=sys.stderr)
        sys.exit(1)

    mapping = json.loads(mapping_file.read_text(encoding="utf-8"))
    mode_str = "[DRY RUN] " if dry_run else ""
    print("\n" + "=" * 70)
    print(f" {mode_str}UNDO FILE RENAMES")
    print(f" Mapping File: {mapping_file}")
    print(f" Total Entries: {len(mapping)}")
    print("=" * 70)

    print("\n[Step 1/2] Verifying and restoring filenames in reverse sequence...")
    print("-" * 70)

    reverted = 0
    for idx, entry in enumerate(reversed(mapping), start=1):
        orig = Path(entry["original"])
        target = Path(entry["target"])

        if target.exists():
            print(f"  [{idx}/{len(mapping)}] Reverting: {target.name} -> {orig.name}")
            if not dry_run and orig != target:
                target.rename(orig)
            reverted += 1
        else:
            print(f"  [{idx}/{len(mapping)}] [SKIP - File Not Found]: {target.name}")

    print("-" * 70)
    print(f"[Step 2/2] Revert Summary: Successfully restored {reverted} / {len(mapping)} files.")
    print("=" * 70 + "\n")
    return {"reverted": reverted, "total": len(mapping)}


def batch_rename_images(
    folder: Path,
    dry_run: bool = False,
    separator: str = "_",
    prefix: str = "",
    suffix: str = "",
    recursive: bool = False,
    batch_size: int = 5,
    pacing_delay: float = 4.0,
    progress_callback: object = None,
    log_callback: object = None,
) -> dict:
    """
    Main batch renaming workflow:
    1. Discovers matching images in the target directory.
    2. Groups images into batches (default: 5 photos per call) to save API requests.
    3. Calls Gemini Vision AI with Key Rotation and Model Fallback.
    4. Resolves filename collisions safely.
    5. Renames files on disk and incrementally updates rename_mapping.json.
    """
    mode_label = "[DRY RUN MODE]" if dry_run else "[LIVE MODE]"
    print("\n" + "=" * 70)
    print(f" AI PHOTO RENAME CLI — {mode_label}")
    print("=" * 70)
    print(" Execution Parameters:")
    print(f"  • Target Folder : {folder.resolve()}")
    print(f"  • Mode          : {'Dry Run (Preview Only, No Disk Changes)' if dry_run else 'Live Rename (Modifies Files on Disk)'}")
    print(f"  • Batch Size    : {batch_size} image(s) per API call")
    print(f"  • Word Separator: '{separator}'")
    print(f"  • Name Prefix   : '{prefix}'" if prefix else "  • Name Prefix   : (None)")
    print(f"  • Name Suffix   : '{suffix}'" if suffix else "  • Name Suffix   : (None)")
    print(f"  • Search Mode   : {'Recursive (Subdirectories Included)' if recursive else 'Flat (Top Directory Only)'}")
    print(f"  • Gemini Model       : {os.environ.get('GEMINI_MODEL', 'gemini-2.5-flash')}")
    print("=" * 70)

    def log(msg: str) -> None:
        print(msg)
        if callable(log_callback):
            log_callback(msg)

    # Step 1: API Key Verification
    log("\n[Step 1/4] Verifying API Credentials & Pool...")
    load_env_file(script_dir)
    api_keys = get_api_key_pool()
    if not api_keys:
        err_msg = "ERROR: GEMINI_API_KEY or GEMINI_API_KEYS environment variable is not set."
        print(err_msg, file=sys.stderr)
        if callable(log_callback):
            log_callback(err_msg)
        sys.exit(1)
    log(f"  • {len(api_keys)} Gemini API key(s) loaded into rotation pool.")

    # Step 2: Image Discovery
    log(f"\n[Step 2/4] Discovering Supported Images in '{folder.name}'...")
    images = find_images(folder, recursive=recursive)
    if not images:
        log(f"  • No supported images found in {folder} (supported formats: {', '.join(SUPPORTED_EXTENSIONS)})")
        return {"total": 0, "renamed_count": 0, "unchanged_count": 0, "proposed_renames": [], "mapping_data": [], "log_file": None, "dry_run": dry_run}
    log(f"  • Found {len(images)} image file(s) matching supported extensions.")

    total = len(images)
    proposed_renames = []
    used_filenames = set()
    log_file = folder / "rename_mapping.json"
    mapping_data = []

    # Step 3: Process Images in Batches
    log(f"\n[Step 3/4] Analyzing Images with Gemini Vision AI (in batches of {batch_size})...")
    log("=" * 70)

    image_batches = [images[i : i + batch_size] for i in range(0, total, batch_size)]
    processed_count = 0

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

        slug_mapping = suggest_image_names_batch(current_batch, api_keys=api_keys, log_callback=log_callback)

        for image_path in current_batch:
            processed_count += 1
            raw_slug = slug_mapping.get(image_path, image_path.stem)

            if separator != "_":
                raw_slug = raw_slug.replace("_", separator)

            ext = normalize_extension(image_path.suffix)
            base_name = f"{prefix}{raw_slug}{suffix}"

            candidate_name = f"{base_name}{ext}"
            counter = 1
            is_collision = False
            while candidate_name.lower() in used_filenames or (
                (image_path.parent / candidate_name).exists()
                and (image_path.parent / candidate_name) != image_path
                and candidate_name.lower() not in [p[1].name.lower() for p in proposed_renames]
            ):
                is_collision = True
                candidate_name = f"{base_name}{separator}{counter:02d}{ext}"
                counter += 1

            used_filenames.add(candidate_name.lower())
            target_path = image_path.parent / candidate_name

            if is_collision:
                log(f"  [{processed_count}/{total}] {image_path.name}  ==>  {candidate_name} (Collision resolved)")
            else:
                log(f"  [{processed_count}/{total}] {image_path.name}  ==>  {candidate_name}")

            proposed_renames.append((image_path, target_path))
            mapping_data.append({"original": str(image_path), "target": str(target_path)})

            if not dry_run and image_path != target_path:
                try:
                    image_path.rename(target_path)
                except Exception as e:
                    log(f"    [Error] Could not rename {image_path.name}: {e}")

            if callable(progress_callback):
                progress_callback({
                    "event": "file_renamed",
                    "original_name": image_path.name,
                    "new_name": candidate_name,
                    "is_collision": is_collision,
                    "original_path": str(image_path),
                    "target_path": str(target_path),
                    "current": processed_count,
                    "total": total,
                    "dry_run": dry_run,
                })

        if not dry_run:
            log_file.write_text(json.dumps(mapping_data, indent=2), encoding="utf-8")

        if b_idx < len(image_batches):
            log(f"  • Pacing delay ({pacing_delay}s) before next API batch request...")
            time.sleep(pacing_delay)

    # Step 4: Summary
    log("\n" + "=" * 70)
    changed_count = sum(1 for src, dst in proposed_renames if src != dst)
    log(f" Processing Complete: {total} photos analyzed, {changed_count} renamed.")

    if dry_run:
        log("\n [DRY RUN COMPLETE] No files were renamed on disk.")
    else:
        log(f" Audit log saved to: {log_file}")
        log(f" To undo this operation, run:\n   python rename.py --undo \"{log_file}\"")
    log("=" * 70 + "\n")

    return {
        "total": total,
        "renamed_count": changed_count,
        "unchanged_count": total - changed_count,
        "proposed_renames": proposed_renames,
        "mapping_data": mapping_data,
        "log_file": log_file,
        "dry_run": dry_run,
    }


def main():
    """CLI Argument Parser and execution dispatcher."""
    parser = argparse.ArgumentParser(description="Standalone AI-Powered Image File Renamer using Gemini Vision.")
    parser.add_argument("folder", type=Path, nargs="?", help="Folder containing images to analyze and rename")
    parser.add_argument("-d", "--dry-run", action="store_true", help="Preview proposed AI names without modifying files")
    parser.add_argument("-b", "--batch-size", type=int, default=5, help="Number of images to process per API request (default: 5)")
    parser.add_argument("-s", "--separator", choices=["_", "-"], default="_", help="Word separator for slugs (default: '_')")
    parser.add_argument("--prefix", default="", help="Optional prefix to add to AI names")
    parser.add_argument("--suffix", default="", help="Optional suffix to add to AI names")
    parser.add_argument("-r", "--recursive", action="store_true", help="Process subdirectories recursively")
    parser.add_argument("--undo", type=Path, help="Undo a previous rename using rename_mapping.json")

    args = parser.parse_args()

    # Dispatch to undo function if --undo flag is set
    if args.undo:
        undo_renames(args.undo, dry_run=args.dry_run)
        return

    # Ensure valid target folder argument is provided
    if not args.folder or not args.folder.is_dir():
        print("ERROR: Please specify a valid folder path.", file=sys.stderr)
        parser.print_help()
        sys.exit(1)

    # Dispatch to batch rename workflow
    batch_rename_images(
        args.folder,
        dry_run=args.dry_run,
        separator=args.separator,
        prefix=args.prefix,
        suffix=args.suffix,
        recursive=args.recursive,
        batch_size=args.batch_size,
    )


if __name__ == "__main__":
    main()
