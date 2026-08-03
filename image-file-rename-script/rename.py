#!/usr/bin/env python3
"""
AI Photo Rename CLI — Standalone AI-Powered Image Renaming Tool.

Visually inspects image files using Google Gemini AI Vision and renames
photos based on their actual visual content (subject, scene, action).

WORKFLOW SUMMARY:
1. CLI Entrypoint (main): Parses arguments for target folder, dry-run mode, word separators,
   prefixes/suffixes, recursion flag, or undo mode.
2. Environment Configuration (load_env_file): Reads .env file in script, parent, or working directory
   to extract GEMINI_API_KEY automatically.
3. Image Discovery (find_images): Filters target folder for supported extensions (.jpg, .png, .webp, .tif, etc.).
4. Vision AI Processing Loop (batch_rename_images):
   a. Sends image to gemini_namer.suggest_image_name() to get an AI visual slug.
   b. Applies user-selected separator ('_' or '-'), prefix, and suffix.
   c. Standardizes extensions (e.g., .jpeg -> .jpg, .tiff -> .tif).
   d. Collision Resolution: Appends _01, _02, etc., if a file with the target name already exists or is assigned.
5. Disk Modification & Audit Log:
   a. If --dry-run: Only previews target names without renaming.
   b. If normal mode: Performs physical rename on disk.
   c. Generates rename_mapping.json audit file storing original -> target path mappings.
6. Undo System (undo_renames): Reads rename_mapping.json and reverses file names back to original names.

Usage Examples:
    # Dry-run preview
    python rename.py /path/to/photos --dry-run

    # Perform actual rename with custom prefix
    python rename.py /path/to/photos --prefix "nature_"

    # Revert previous rename operation
    python rename.py --undo /path/to/photos/rename_mapping.json
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
    Auto-load GEMINI_API_KEY and GEMINI_MODEL from .env if present.

    Checks current folder, parent folder, and working directory for a .env file,
    parsing key=value pairs into os.environ.
    """
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


# Load environment variables before importing dependent modules
load_env_file(script_dir)

from google import genai
try:
    from google.genai import errors
    GEMINI_ERRORS = (RuntimeError, errors.APIError, errors.ClientError, Exception)
except ImportError:
    GEMINI_ERRORS = (RuntimeError, Exception)

from gemini_namer import suggest_image_name

# File extensions supported by this tool
SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff"}




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


def normalize_extension(ext: str) -> str:
    """
    Standardize extensions for cleaner file naming.

    Converts .jpeg to .jpg and .tiff to .tif.
    """
    lower = ext.lower()
    if lower == ".jpeg":
        return ".jpg"
    if lower == ".tiff":
        return ".tif"
    return lower


def undo_renames(mapping_file: Path, dry_run: bool = False) -> None:
    """
    Undo renames using a saved JSON mapping log (rename_mapping.json).

    Iterates through recorded original -> target mappings in reverse order
    to restore original filenames safely.
    """
    if not mapping_file.is_file():
        print(f"ERROR: Mapping file {mapping_file} not found.", file=sys.stderr)
        sys.exit(1)

    mapping = json.loads(mapping_file.read_text(encoding="utf-8"))
    prefix = "[DRY RUN] " if dry_run else ""
    print(f"\n{prefix}Reverting {len(mapping)} renamed files...")
    print("-" * 60)

    reverted = 0
    # Process in reverse order to handle any chained dependencies safely
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
    """
    Main batch renaming workflow:
    1. Loads environment & validates GEMINI_API_KEY.
    2. Discovers matching images in the target directory.
    3. Initializes Gemini Vision client.
    4. Loops through each image, querying Gemini AI for visual slug.
    5. Resolves filename collisions (appends _01, _02, etc. if needed).
    6. Renames files on disk (unless dry_run is True).
    7. Saves rename_mapping.json for future undo capability.
    """
    # Step 1: Environment & Key Verification
    load_env_file(script_dir)

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("ERROR: GEMINI_API_KEY environment variable is not set.", file=sys.stderr)
        print("Set it in your terminal or create a .env file with GEMINI_API_KEY=your_key", file=sys.stderr)
        sys.exit(1)

    # Step 2: Image Discovery
    images = find_images(folder, recursive=recursive)
    if not images:
        print(f"No supported images found in {folder} (supported: {', '.join(SUPPORTED_EXTENSIONS)})")
        return

    # Step 3: Initialize Gemini AI Client
    client = genai.Client(api_key=api_key)
    total = len(images)

    mode_title = "[DRY RUN] AI Visual Image Renaming:" if dry_run else "AI Visual Image Renaming:"
    print(f"\n{mode_title} ({total} photos)")
    print("=" * 70)

    proposed_renames = []
    used_filenames = set()

    # Step 4: Process Images One by One
    for idx, image_path in enumerate(images, start=1):
        print(f"[{idx}/{total}] Analyzing {image_path.name} ... ", end="", flush=True)
        try:
            # 4a. Call Gemini AI Vision module for descriptive name slug
            raw_slug = suggest_image_name(client, image_path)

            # 4b. Format separator if user specified kebab-case (-) instead of default (_)
            if separator != "_":
                raw_slug = raw_slug.replace("_", separator)

            # 4c. Normalize extension (.jpeg -> .jpg) and format final base filename
            ext = normalize_extension(image_path.suffix)
            base_name = f"{prefix}{raw_slug}{suffix}"

            # 4d. Duplicate / Collision Handling
            # If "sunset_beach.jpg" already exists or was assigned to a prior photo in this batch,
            # create "sunset_beach_01.jpg", "sunset_beach_02.jpg", etc.
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

        except GEMINI_ERRORS as err:
            # Gracefully log failure message, skip photo (keep original path), and continue batch
            print(f"FAILED ({err})")
            proposed_renames.append((image_path, image_path))

        # Free tier rate-limiting: Sleep 5s between requests to stay under 15 requests per minute limit
        if idx < total:
            time.sleep(5)

    print("=" * 70)
    changed_count = sum(1 for src, dst in proposed_renames if src != dst)
    print(f"Summary: {total} photos analyzed, {changed_count} to rename.")

    # Prepare audit log mapping structure
    mapping_data = []
    for src, dst in proposed_renames:
        mapping_data.append({"original": str(src), "target": str(dst)})

    # Step 5: Execute Disk Renames and Write Audit Log (if not dry run)
    if not dry_run and changed_count > 0:
        for src, dst in proposed_renames:
            if src != dst:
                src.rename(dst)

        # Write rename_mapping.json log file into target directory
        log_file = folder / "rename_mapping.json"
        log_file.write_text(json.dumps(mapping_data, indent=2), encoding="utf-8")
        print(f"\nSuccess! Renamed {changed_count} files.")
        print(f"Rename log saved to: {log_file}")
        print(f"To undo this operation later, run:\n  python rename.py --undo \"{log_file}\"")


def main():
    """CLI Argument Parser and execution dispatcher."""
    parser = argparse.ArgumentParser(description="Standalone AI-Powered Image File Renamer using Gemini Vision.")
    parser.add_argument("folder", type=Path, nargs="?", help="Folder containing images to analyze and rename")
    parser.add_argument("-d", "--dry-run", action="store_true", help="Preview proposed AI names without modifying files")
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
    )


if __name__ == "__main__":
    main()

