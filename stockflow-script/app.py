#!/usr/bin/env python3
"""
StockFlow Studio — Comprehensive Shutterstock Contributor Automation Suite.
Combines:
  Step 1: Visual File Renamer (SEO Slug Generation & Rollback)
  Step 2: Metadata Generator (CSV Generation & Compliance Engine)
"""
import json
import os
import sys
import time
from pathlib import Path
import pandas as pd
from PIL import Image
import streamlit as st

# Setup sys.path to include stockflow-script and image-file-rename-script
current_dir = Path(__file__).resolve().parent
scripts_root = current_dir.parent
rename_dir = scripts_root / "image-file-rename-script"

for p in [str(current_dir), str(rename_dir)]:
    if p not in sys.path:
        sys.path.insert(0, p)

# Stockflow imports
from limits import SUPPORTED_EXTENSIONS
from stockflow import (
    CSV_HEADERS,
    find_images,
    load_env_file,
    process_folder,
    read_existing_csv,
)
from gemini_client import get_api_key_pool

# Renamer imports
from rename import (
    batch_rename_images,
    find_images as find_images_for_rename,
    undo_renames,
)

# Page Configuration
st.set_page_config(
    page_title="StockFlow Studio",
    page_icon=":material/photo_camera:",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Coherent Professional CSS System (Zero Emojis, Clean Typography, Refined Palette)
st.markdown(
    """
    <style>
    /* Global Typography */
    html, body, [class*="css"] {
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
    }
    
    /* Header Branding */
    .brand-header {
        display: flex;
        align-items: center;
        gap: 12px;
        margin-bottom: 4px;
    }
    .brand-title {
        font-size: 1.75rem;
        font-weight: 700;
        letter-spacing: -0.02em;
        color: #0f172a;
        margin: 0;
    }
    .brand-badge {
        font-size: 0.72rem;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        background: #e2e8f0;
        color: #475569;
        padding: 3px 8px;
        border-radius: 4px;
    }
    .brand-subtitle {
        font-size: 0.95rem;
        color: #64748b;
        margin-bottom: 20px;
    }

    /* Metric Cards */
    div[data-testid="stMetric"] {
        background: #ffffff;
        border: 1px solid #e2e8f0;
        padding: 14px 18px;
        border-radius: 8px;
        box-shadow: 0 1px 2px rgba(0,0,0,0.03);
    }
    div[data-testid="stMetricLabel"] {
        font-size: 0.8rem;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.04em;
        color: #64748b;
    }
    div[data-testid="stMetricValue"] {
        font-size: 1.5rem;
        font-weight: 700;
        color: #0f172a;
    }

    /* Status Pills */
    .status-pill-clean {
        display: inline-block;
        background: #ecfdf5;
        color: #047857;
        border: 1px solid #a7f3d0;
        padding: 2px 10px;
        border-radius: 12px;
        font-size: 0.8rem;
        font-weight: 600;
    }
    .status-pill-flagged {
        display: inline-block;
        background: #fffbeb;
        color: #b45309;
        border: 1px solid #fde68a;
        padding: 2px 10px;
        border-radius: 12px;
        font-size: 0.8rem;
        font-weight: 600;
    }
    .status-pill-failed {
        display: inline-block;
        background: #fef2f2;
        color: #b91c1c;
        border: 1px solid #fecaca;
        padding: 2px 10px;
        border-radius: 12px;
        font-size: 0.8rem;
        font-weight: 600;
    }

    /* Keyword & Category Chips */
    .keyword-chip {
        display: inline-block;
        background: #f1f5f9;
        color: #334155;
        padding: 3px 9px;
        margin: 2px 3px 2px 0;
        border-radius: 14px;
        font-size: 0.8rem;
        font-weight: 500;
        border: 1px solid #e2e8f0;
    }
    .category-chip {
        display: inline-block;
        background: #eff6ff;
        color: #1d4ed8;
        padding: 4px 10px;
        margin: 2px 4px 2px 0;
        border-radius: 6px;
        font-size: 0.82rem;
        font-weight: 600;
        border: 1px solid #bfdbfe;
    }

    /* Live Stream Card */
    .inspector-card {
        background: #ffffff;
        border: 1px solid #cbd5e1;
        border-radius: 10px;
        padding: 16px 20px;
        margin-top: 12px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.05);
    }

    /* Section Subheadings */
    .section-title {
        font-size: 1.1rem;
        font-weight: 700;
        color: #1e293b;
        letter-spacing: -0.01em;
        margin: 18px 0 10px 0;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# Load environment configuration
load_env_file(current_dir)

# Helper: Auto-discover photo folders in workspace
def discover_photo_folders() -> list[tuple[str, Path, int]]:
    discovered = []
    candidates = [p for p in scripts_root.iterdir() if p.is_dir() and not p.name.startswith(".") and p.name not in ["stockflow-script", "image-file-rename-script"]]
    for p in sorted(candidates):
        try:
            imgs = find_images(p)
            if imgs:
                discovered.append((p.name, p, len(imgs)))
        except Exception:
            continue
    return discovered

discovered_folders = discover_photo_folders()

# Sidebar: Engine Configuration
with st.sidebar:
    st.markdown("### Settings")
    st.caption("AI Engine & Credential Configuration")

    # API Key Input / Override
    env_keys = get_api_key_pool()
    api_key_input = st.text_input(
        "Gemini API Key (Override)",
        type="password",
        placeholder="Using key from .env" if env_keys else "Enter API key...",
        help="Leave blank to use GEMINI_API_KEY from .env.",
    )

    if api_key_input:
        os.environ["GEMINI_API_KEY"] = api_key_input.strip()
        active_keys_count = 1
        st.success("Session API key applied.")
    elif env_keys:
        active_keys_count = len(env_keys)
        st.info(f"{active_keys_count} API key(s) loaded from environment.")
    else:
        active_keys_count = 0
        st.error("No Gemini API key found in .env or input.")

    st.divider()

    st.markdown("### Performance & Execution")
    batch_size = st.slider(
        "Batch Size (Images per Request)",
        min_value=1,
        max_value=10,
        value=5,
        help="Number of images grouped into each multimodal API call. Default is 5.",
    )

    pacing_delay = st.slider(
        "Pacing Delay (Seconds)",
        min_value=1.0,
        max_value=10.0,
        value=5.0,
        step=0.5,
        help="Wait time between batch calls. 5.0s safely protects free-tier 15 RPM quota.",
    )

    st.divider()
    st.markdown("### Shutterstock Rules Summary")
    st.caption("• Titles: 5 to 200 characters, descriptive\n• Keywords: 20 to 40 relevant search terms\n• Categories: 1 or 2 standard categories\n• Safety: Strict trademark and brand denylist")

# Top Header Branding
st.markdown(
    """
    <div class="brand-header">
        <h1 class="brand-title">StockFlow Studio</h1>
        <span class="brand-badge">Automated Contributor Suite</span>
    </div>
    <div class="brand-subtitle">Visual AI photo renaming and Shutterstock bulk metadata generation engine.</div>
    """,
    unsafe_allow_html=True,
)

# Shared Folder Selection Section
st.markdown('<div class="section-title">Photo Folder Selection</div>', unsafe_allow_html=True)

# Quick Bookmarks
if discovered_folders:
    st.caption("Quick Bookmarks:")
    bm_cols = st.columns(min(len(discovered_folders), 5))
    for idx, (f_name, f_path, count) in enumerate(discovered_folders[:5]):
        with bm_cols[idx]:
            if st.button(f"{f_name} ({count} images)", key=f"btn_bm_{f_name}", use_container_width=True):
                st.session_state["target_folder"] = str(f_path.resolve())

# Folder Input
col_path, col_btn = st.columns([5, 1])
with col_path:
    default_dir = st.session_state.get(
        "target_folder",
        str(discovered_folders[0][1].resolve()) if discovered_folders else str(scripts_root / "01-stock")
    )
    folder_str = st.text_input("Folder Path", value=default_dir, label_visibility="collapsed", placeholder=r"D:\Work\projects\Shutterstock\01-stock")
    st.session_state["target_folder"] = folder_str.strip()

with col_btn:
    st.button("Refresh", icon=":material/refresh:", use_container_width=True)

folder_path = Path(folder_str.strip()) if folder_str.strip() else None
images_found: list[Path] = []
mapping_file = None

if folder_path and folder_path.is_dir():
    images_found = find_images(folder_path)
    mapping_file = folder_path / "rename_mapping.json"
    default_csv_name = f"{folder_path.name}_stockflow.csv" if folder_path.name else "stockflow_output.csv"
    output_csv_path = folder_path / default_csv_name
    existing_rows_map = read_existing_csv(output_csv_path)

    # Pre-Flight Status Bar
    pf_c1, pf_c2, pf_c3, pf_c4 = st.columns(4)
    pf_c1.metric("Supported Images", f"{len(images_found)}")
    
    # Format counts
    exts = set(p.suffix.lower() for p in images_found)
    pf_c2.metric("Formats", ", ".join(ext.upper().replace(".", "") for ext in sorted(exts)) if exts else "None")
    
    # Rename status
    has_mapping = mapping_file.exists()
    pf_c3.metric("Rename Status", "Renamed" if has_mapping else "Raw / Pending", delta="Mapping logged" if has_mapping else None)
    
    # Metadata status
    pf_c4.metric("Metadata CSV", f"{len(existing_rows_map)} tagged", delta=f"{len(images_found) - len(existing_rows_map)} remaining" if len(images_found) > len(existing_rows_map) else "Complete")

    # Image Preview Gallery
    if images_found:
        with st.expander(f"Folder Preview ({min(6, len(images_found))} of {len(images_found)} files)", expanded=False):
            img_cols = st.columns(min(6, len(images_found)))
            for idx, c in enumerate(img_cols):
                if idx < len(images_found):
                    p_img = images_found[idx]
                    try:
                        with Image.open(p_img) as im:
                            im.thumbnail((180, 180))
                            c.image(im, caption=p_img.name, use_container_width=True)
                    except Exception:
                        c.caption(p_img.name)
else:
    if folder_str.strip():
        st.warning("The specified folder does not exist. Please verify the folder path.")
    output_csv_path = current_dir / "stockflow_output.csv"

st.divider()

# Two-Step Workflow Navigation Tabs
tab_rename, tab_metadata, tab_audit = st.tabs([
    "Step 1: Visual File Renamer",
    "Step 2: Metadata Generator",
    "Rename Audit & Rollback",
])

# -----------------------------------------------------------------------------
# TAB 1: VISUAL FILE RENAMER
# -----------------------------------------------------------------------------
with tab_rename:
    st.markdown('<div class="section-title">Visual Photo Renamer</div>', unsafe_allow_html=True)
    st.caption("Visually inspects physical image content with Gemini AI Vision and renames files to clean SEO slugs.")

    ren_c1, ren_c2, ren_c3 = st.columns(3)
    with ren_c1:
        rename_mode = st.radio(
            "Execution Mode",
            options=["Dry Run (Preview Only)", "Live Rename (Modify Disk)"],
            index=0,
            help="Dry Run previews proposed filenames without altering files on disk. Live Rename applies changes immediately.",
        )
        is_dry_run = "Dry Run" in rename_mode

    with ren_c2:
        separator_choice = st.selectbox("Word Separator", options=["_ (snake_case)", "- (kebab-case)"], index=0)
        chosen_sep = "_" if "_" in separator_choice else "-"

    with ren_c3:
        prefix_input = st.text_input("Filename Prefix (Optional)", value="", placeholder="e.g. travel_")
        suffix_input = st.text_input("Filename Suffix (Optional)", value="", placeholder="e.g. _stock")

    can_rename = bool(folder_path and folder_path.is_dir() and images_found and active_keys_count > 0)
    btn_start_rename = st.button(
        "Run Visual Renamer",
        icon=":material/label:",
        type="primary",
        disabled=not can_rename or st.session_state.get("renaming_active", False),
    )

    rename_cockpit = st.container()
    rename_table_placeholder = st.empty()

    if btn_start_rename and folder_path:
        st.session_state["renaming_active"] = True
        
        with rename_cockpit:
            ren_progress = st.progress(0, text="Analyzing photos with Gemini AI...")
            ren_status = st.empty()

        proposed_list: list[dict] = []

        def on_rename_progress(event_data: dict):
            event = event_data.get("event")
            if event == "file_renamed":
                proposed_list.append({
                    "Original Filename": event_data.get("original_name"),
                    "Proposed Filename": event_data.get("new_name"),
                    "Collision Resolved": "Yes" if event_data.get("is_collision") else "No",
                    "Mode": "Preview" if event_data.get("dry_run") else "Renamed",
                })
                current = event_data.get("current", len(proposed_list))
                total = event_data.get("total", len(images_found))
                pct = min(1.0, current / max(1, total))
                ren_progress.progress(pct, text=f"Processed {current} of {total} images...")

                df_ren = pd.DataFrame(proposed_list)
                rename_table_placeholder.dataframe(df_ren, use_container_width=True, height=300)

            elif event == "batch_start":
                b_i = event_data.get("batch_idx")
                t_b = event_data.get("total_batches")
                ren_status.info(f"Processing Batch {b_i} of {t_b} ({event_data.get('batch_size')} images)...")

        def on_rename_log(msg: str):
            if "rate limit" in msg.lower() or "quota reset" in msg.lower():
                ren_status.warning(f"Rate-Limit Pause: {msg}")
            elif "error" in msg.lower():
                ren_status.error(msg)

        try:
            summary = batch_rename_images(
                folder=folder_path,
                dry_run=is_dry_run,
                separator=chosen_sep,
                prefix=prefix_input.strip(),
                suffix=suffix_input.strip(),
                batch_size=batch_size,
                pacing_delay=pacing_delay,
                progress_callback=on_rename_progress,
                log_callback=on_rename_log,
            )
            ren_progress.progress(1.0, text="Renaming workflow complete.")
            if is_dry_run:
                ren_status.info(f"Dry Run Finished: {summary['total']} images analyzed, {summary['renamed_count']} proposed changes. No files were renamed.")
            else:
                ren_status.success(f"Renaming Complete: {summary['renamed_count']} of {summary['total']} files renamed on disk. Audit log saved.")
        except Exception as e:
            ren_status.error(f"Renaming error: {e}")
        finally:
            st.session_state["renaming_active"] = False

# -----------------------------------------------------------------------------
# TAB 2: METADATA GENERATOR (STOCKFLOW)
# -----------------------------------------------------------------------------
with tab_metadata:
    st.markdown('<div class="section-title">Shutterstock Metadata Generator</div>', unsafe_allow_html=True)
    st.caption("Generates SEO descriptions, 20–40 keywords, and validates against Shutterstock compliance rules.")

    meta_c1, meta_c2 = st.columns([3, 1])
    with meta_c1:
        resume_mode = st.checkbox(
            "Resume Mode (Skip Already Processed Images)",
            value=True,
            help="Preserves previously completed rows in the CSV and only processes remaining images.",
        )
    with meta_c2:
        remaining_calc = len(images_found) - len(existing_rows_map) if folder_path and folder_path.is_dir() else 0
        st.caption(f"Unprocessed: {max(0, remaining_calc)} images")

    can_gen_metadata = bool(folder_path and folder_path.is_dir() and images_found and active_keys_count > 0)
    start_meta_btn = st.button(
        f"Generate Metadata ({max(0, remaining_calc)} Photos)",
        icon=":material/description:",
        type="primary",
        disabled=not can_gen_metadata or st.session_state.get("metadata_active", False),
    )

    meta_cockpit = st.container()
    meta_inspector = st.empty()

    if start_meta_btn and folder_path:
        st.session_state["metadata_active"] = True

        with meta_cockpit:
            m_progress = st.progress(0, text="Initializing metadata generation run...")
            m_eta = st.empty()
            m_radar = st.empty()

            m_cols = st.columns(4)
            m_total_val = m_cols[0].empty()
            m_clean_val = m_cols[1].empty()
            m_flagged_val = m_cols[2].empty()
            m_failed_val = m_cols[3].empty()

        live_meta_rows: list[list[str]] = []
        start_t = time.time()
        initial_cached = len(existing_rows_map) if resume_mode else 0

        def render_inspector_card(fname: str, row: list[str], status: str, reasons: list[str]):
            img_p = folder_path / fname
            title_text = row[1] if len(row) > 1 else ""
            kws = [k.strip() for k in row[2].split(",") if k.strip()] if len(row) > 2 else []
            cats = [c.strip() for c in row[3].split(",") if c.strip()] if len(row) > 3 else []

            with meta_inspector.container():
                st.markdown(f"**Latest Image Tagged**: `{fname}`")
                ic1, ic2 = st.columns([1, 3])
                with ic1:
                    if img_p.exists():
                        try:
                            with Image.open(img_p) as im:
                                im.thumbnail((260, 260))
                                st.image(im, use_container_width=True)
                        except Exception:
                            st.write(fname)
                with ic2:
                    if status == "CLEAN":
                        st.markdown('<span class="status-pill-clean">Status: Clean (Ready)</span>', unsafe_allow_html=True)
                    elif status == "FLAGGED":
                        st.markdown(f'<span class="status-pill-flagged">Flagged: {"; ".join(reasons)}</span>', unsafe_allow_html=True)
                    else:
                        st.markdown('<span class="status-pill-failed">Status: Generation Failed</span>', unsafe_allow_html=True)

                    st.markdown(f"**Description**: {title_text}")

                    if cats:
                        cats_html = " ".join(f'<span class="category-chip">{c}</span>' for c in cats)
                        st.markdown(f"**Categories**: {cats_html}", unsafe_allow_html=True)

                    if kws:
                        kws_html = " ".join(f'<span class="keyword-chip">{k}</span>' for k in kws[:24])
                        if len(kws) > 24:
                            kws_html += f" *(+{len(kws) - 24} more)*"
                        st.markdown(f"**Keywords ({len(kws)})**: {kws_html}", unsafe_allow_html=True)

        def on_meta_progress(event_data: dict):
            event = event_data.get("event")
            if event in ("image_cached", "image_processed"):
                r = event_data.get("row")
                if r:
                    live_meta_rows.append(r)

                curr = len(live_meta_rows)
                tot = event_data.get("total", len(images_found))
                pct = min(1.0, curr / max(1, tot))

                elapsed = time.time() - start_t
                if curr > initial_cached:
                    new_completed = curr - initial_cached
                    sec_per = elapsed / max(1, new_completed)
                    remaining = tot - curr
                    eta_sec = remaining * sec_per
                    m_eta.caption(f"Estimated Time Remaining: ~{int(eta_sec // 60)}m {int(eta_sec % 60):02d}s ({sec_per:.1f}s per photo)")
                else:
                    m_eta.caption("Loading existing metadata from disk...")

                m_progress.progress(pct, text=f"Processed {curr} of {tot} photos ({int(pct * 100)}%)...")

                m_total_val.metric("Total Tagged", curr)
                m_clean_val.metric("Clean (Ready)", event_data.get("ok_count", 0))
                m_flagged_val.metric("Flagged for Review", event_data.get("flagged_count", 0))
                m_failed_val.metric("Failed", event_data.get("failed_count", 0))

                if event == "image_processed" and r:
                    render_inspector_card(
                        fname=event_data.get("filename", ""),
                        row=r,
                        status=event_data.get("status", "CLEAN"),
                        reasons=event_data.get("reasons", []),
                    )

            elif event == "batch_start":
                b_idx = event_data.get("batch_idx")
                tot_b = event_data.get("total_batches")
                m_radar.info(f"Submitting Batch {b_idx} of {tot_b} to Gemini AI...")

        def on_meta_log(msg: str):
            if "rate limit" in msg.lower() or "quota reset" in msg.lower():
                m_radar.warning(f"Rate-Limit Radar: {msg}")
            elif "error" in msg.lower():
                m_radar.error(msg)

        try:
            summary = process_folder(
                folder=folder_path,
                output_path=output_csv_path,
                root_dir=current_dir,
                batch_size=batch_size,
                resume=resume_mode,
                pacing_delay=pacing_delay,
                progress_callback=on_meta_progress,
                log_callback=on_meta_log,
            )
            m_progress.progress(1.0, text="Metadata generation complete.")
            m_radar.success(f"Processing complete: {summary['total']} photos processed. Saved to {output_csv_path.name}.")
        except Exception as e:
            m_radar.error(f"Execution stopped: {e}")
        finally:
            st.session_state["metadata_active"] = False

    # Review & Export Section
    if output_csv_path.exists():
        st.markdown('<div class="section-title">Review & Curation</div>', unsafe_allow_html=True)
        try:
            df_res = pd.read_csv(output_csv_path)
            df_flag = df_res[df_res["Needs Review"].fillna("").str.strip() != ""]
            df_clean = df_res[df_res["Needs Review"].fillna("").str.strip() == ""]

            rev_tab1, rev_tab2, rev_tab3 = st.tabs([
                f"Needs Review ({len(df_flag)})",
                f"Clean & Ready ({len(df_clean)})",
                f"All Images ({len(df_res)})",
            ])

            with rev_tab1:
                if len(df_flag) > 0:
                    st.info(f"{len(df_flag)} photo(s) flagged for manual verification. Review specific reasons in the 'Needs Review' column.")
                    st.dataframe(df_flag[["Filename", "Needs Review", "Description", "Keywords", "Categories"]], use_container_width=True, height=280)
                else:
                    st.success("Zero flagged rows. All items passed Shutterstock validation rules.")

            with rev_tab2:
                if len(df_clean) > 0:
                    st.dataframe(df_clean[["Filename", "Description", "Keywords", "Categories"]], use_container_width=True, height=280)
                else:
                    st.info("No clean rows available.")

            with rev_tab3:
                st.dataframe(df_res, use_container_width=True, height=320)

            # Export Suite
            st.markdown('<div class="section-title">Export Suite</div>', unsafe_allow_html=True)
            with open(output_csv_path, "rb") as f_csv:
                csv_bytes = f_csv.read()

            ex_c1, ex_c2, ex_c3 = st.columns([2, 2, 3])
            with ex_c1:
                st.download_button(
                    label=f"Download {output_csv_path.name}",
                    icon=":material/download:",
                    data=csv_bytes,
                    file_name=output_csv_path.name,
                    mime="text/csv",
                    type="primary",
                    use_container_width=True,
                )
            with ex_c2:
                st.link_button(
                    "Open Shutterstock Catalog Manager",
                    icon=":material/open_in_new:",
                    url="https://submit.shutterstock.com/catalog",
                    use_container_width=True,
                )
            with ex_c3:
                st.caption(f"Saved on disk:\n`{output_csv_path.resolve()}`")

        except Exception as e:
            st.caption(f"CSV ready at {output_csv_path.name}.")

# -----------------------------------------------------------------------------
# TAB 3: RENAME AUDIT & ROLLBACK
# -----------------------------------------------------------------------------
with tab_audit:
    st.markdown('<div class="section-title">Rename Audit Log & Rollback</div>', unsafe_allow_html=True)
    st.caption("Inspect previous rename operations and restore original filenames with 1-click undo.")

    if mapping_file and mapping_file.exists():
        try:
            mapping_content = json.loads(mapping_file.read_text(encoding="utf-8"))
            st.info(f"Audit log found: {len(mapping_content)} renamed entries recorded in `{mapping_file.name}`.")

            df_mapping = pd.DataFrame(mapping_content)
            if not df_mapping.empty:
                df_mapping["Original Name"] = df_mapping["original"].apply(lambda p: Path(p).name)
                df_mapping["Current Name"] = df_mapping["target"].apply(lambda p: Path(p).name)
                st.dataframe(df_mapping[["Original Name", "Current Name"]], use_container_width=True, height=260)

            undo_col1, undo_col2 = st.columns([2, 4])
            with undo_col1:
                btn_undo = st.button("Undo Renaming (Restore Originals)", icon=":material/undo:", type="secondary")
            
            if btn_undo:
                res = undo_renames(mapping_file, dry_run=False)
                st.success(f"Rollback Complete: Restored {res['reverted']} of {res['total']} files to original names.")
                st.rerun()

        except Exception as e:
            st.error(f"Could not parse rename mapping: {e}")
    else:
        st.info("No active rename audit log found in this folder. Rename files in Step 1 to generate a rollback log.")
