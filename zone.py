"""
Zone Label Generator
=====================
- Upload a master sheet (Excel/CSV) with columns:
    Zone | Part No | Part Description | Storage Location | Delivery Location
- App generates one A4-landscape-strip label per unique Zone (297mm x 210mm
  frame as in the sample image), each with a QR code.
- Scanning the QR code opens this same app with ?zone=<zone name> in the URL,
  which switches the app into "scan view" and shows ONLY the rows belonging
  to that zone (Zone, Part No, Part Description, Storage Location, Delivery
  Location) — i.e. scanning the "MID RISE ZONE" label only ever shows MID
  RISE ZONE data, never other zones.

Run locally:
    streamlit run app.py

Deploy (e.g. Streamlit Community Cloud) so the QR codes point to a real,
scannable URL — see the "App URL" field in the sidebar.
"""

import io
import os
import zipfile
from pathlib import Path

import pandas as pd
import qrcode
import streamlit as st
from PIL import Image, ImageDraw, ImageFont

# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------
REQUIRED_COLUMNS = [
    "Zone",
    "Part No",
    "Part Description",
    "Storage Location",
    "Delivery Location",
]

DATA_STORE = Path("data")
DATA_STORE.mkdir(exist_ok=True)
MASTER_FILE = DATA_STORE / "mastersheet.csv"

DPI = 300
MM_TO_PX = DPI / 25.4
LABEL_WIDTH_MM = 297
LABEL_HEIGHT_MM = 210

# Ship the font with the app (system font paths aren't guaranteed to exist
# on every deployment target, e.g. Streamlit Community Cloud).
_APP_DIR = Path(__file__).parent
_BUNDLED_FONT = _APP_DIR / "fonts" / "DejaVuSerif-Bold.ttf"
_SYSTEM_FONT = Path("/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf")

if _BUNDLED_FONT.exists():
    FONT_BOLD = str(_BUNDLED_FONT)
elif _SYSTEM_FONT.exists():
    FONT_BOLD = str(_SYSTEM_FONT)
else:
    FONT_BOLD = None  # fall back to PIL's default bitmap font

st.set_page_config(page_title="Zone Label Generator", layout="wide")


def mm_to_px(mm: float) -> int:
    return int(mm * MM_TO_PX)


# --------------------------------------------------------------------------
# Persistence helpers (so a scanned QR works in a *different* browser/
# session than the one that uploaded the file, as long as it's the same
# deployed app)
# --------------------------------------------------------------------------
def save_master(df: pd.DataFrame) -> None:
    df.to_csv(MASTER_FILE, index=False)


def load_master() -> pd.DataFrame | None:
    if MASTER_FILE.exists():
        return pd.read_csv(MASTER_FILE)
    return None


# --------------------------------------------------------------------------
# Label rendering
# --------------------------------------------------------------------------
def fit_font(draw: ImageDraw.ImageDraw, text: str, max_width: int, max_size: int):
    """Shrink font size until the text fits within max_width."""
    if FONT_BOLD is None:
        return ImageFont.load_default()
    size = max_size
    while size > 10:
        font = ImageFont.truetype(FONT_BOLD, size)
        bbox = draw.textbbox((0, 0), text, font=font)
        if (bbox[2] - bbox[0]) <= max_width:
            return font
        size -= 2
    return ImageFont.truetype(FONT_BOLD, 10)


def generate_label(zone_name: str, qr_data: str) -> Image.Image:
    W, H = mm_to_px(LABEL_WIDTH_MM), mm_to_px(LABEL_HEIGHT_MM)
    img = Image.new("RGB", (W, H), "white")
    draw = ImageDraw.Draw(img)

    # Double border, matching the reference image
    outer_margin = int(W * 0.015)
    draw.rectangle(
        [outer_margin, outer_margin, W - outer_margin, H - outer_margin],
        outline="black",
        width=max(2, int(W * 0.003)),
    )
    inner_margin = outer_margin + int(W * 0.012)
    draw.rectangle(
        [inner_margin, inner_margin, W - inner_margin, H - inner_margin],
        outline="black",
        width=max(1, int(W * 0.0015)),
    )

    # Title text, centered, auto-shrunk to fit
    text = zone_name.upper()
    max_text_width = W - 2 * inner_margin - int(W * 0.06)
    font = fit_font(draw, text, max_text_width, int(H * 0.20))
    bbox = draw.textbbox((0, 0), text, font=font)
    text_w, text_h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(
        ((W - text_w) / 2 - bbox[0], H * 0.12 - bbox[1]),
        text,
        fill="black",
        font=font,
    )

    # QR code, centered below the title
    qr = qrcode.QRCode(box_size=10, border=2)
    qr.add_data(qr_data)
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    qr_size = int(H * 0.42)
    qr_img = qr_img.resize((qr_size, qr_size))
    img.paste(qr_img, (int((W - qr_size) / 2), int(H * 0.42)))

    return img


# --------------------------------------------------------------------------
# SCAN VIEW — shown when the URL has ?zone=... (i.e. after a QR scan)
# --------------------------------------------------------------------------
query_params = st.query_params
scanned_zone = query_params.get("zone")

if scanned_zone:
    st.title(f"📋 {scanned_zone}")
    df = load_master()

    if df is None:
        st.error(
            "No master sheet has been uploaded to this app yet. "
            "Ask the admin to upload it from the main page."
        )
        st.stop()

    filtered = df[df["Zone"].astype(str).str.strip().str.lower() == scanned_zone.strip().lower()]

    if filtered.empty:
        st.warning(f"No records found for zone: **{scanned_zone}**")
    else:
        st.success(f"{len(filtered)} record(s) found for **{scanned_zone}**")
        st.dataframe(filtered[REQUIRED_COLUMNS], use_container_width=True, hide_index=True)

    st.caption("This view only ever shows rows for the zone printed on the scanned label.")
    st.stop()

# --------------------------------------------------------------------------
# MAIN VIEW — upload master sheet & generate labels
# --------------------------------------------------------------------------
st.title("🏷️ Zone Label Generator")
st.write(
    "Upload the master sheet once. The app creates one printable A4 label "
    "per zone; scanning a label's QR code shows only that zone's rows."
)

with st.sidebar:
    st.header("Settings")
    default_url = st.session_state.get("app_url", "")
    app_url = st.text_input(
        "Public App URL (for QR codes)",
        value=default_url,
        placeholder="https://your-app.streamlit.app",
        help="The QR codes will link to <this URL>/?zone=<zone name>. "
        "Must be the address people's phones can actually reach — "
        "not 'localhost' — for scanning to work.",
    )
    st.session_state["app_url"] = app_url

uploaded_file = st.file_uploader(
    "Upload Master Sheet", type=["xlsx", "xls", "csv"]
)

# Load whichever data is current: freshly uploaded, or previously saved
df = None
if uploaded_file is not None:
    try:
        if uploaded_file.name.lower().endswith(".csv"):
            df = pd.read_csv(uploaded_file)
        else:
            df = pd.read_excel(uploaded_file)
    except Exception as e:
        st.error(f"Could not read file: {e}")
        st.stop()

    # normalize column whitespace
    df.columns = [str(c).strip() for c in df.columns]
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        st.error(
            f"Uploaded sheet is missing required column(s): {missing}. "
            f"Expected columns: {REQUIRED_COLUMNS}"
        )
        st.stop()

    save_master(df)
    st.success(f"Master sheet saved — {len(df)} rows loaded.")
else:
    df = load_master()
    if df is not None:
        st.info(f"Using previously uploaded master sheet ({len(df)} rows). Upload a new file to replace it.")

if df is None:
    st.stop()

with st.expander("Preview data", expanded=False):
    st.dataframe(df[REQUIRED_COLUMNS], use_container_width=True, hide_index=True)

zones = sorted(df["Zone"].dropna().astype(str).str.strip().unique().tolist())
st.write(f"**{len(zones)} zone(s) found:** {', '.join(zones)}")

if not app_url:
    st.warning(
        "Enter your app's public URL in the sidebar before generating labels, "
        "otherwise the QR codes won't be scannable from a phone."
    )

if st.button("Generate Labels", type="primary", disabled=not app_url):
    zip_buffer = io.BytesIO()
    cols = st.columns(2)

    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for i, zone in enumerate(zones):
            qr_url = f"{app_url.rstrip('/')}/?zone={zone}"
            label_img = generate_label(zone, qr_url)

            img_buffer = io.BytesIO()
            label_img.save(img_buffer, format="PNG", dpi=(DPI, DPI))
            safe_name = "".join(c if c.isalnum() or c in " _-" else "_" for c in zone)
            zf.writestr(f"{safe_name}.png", img_buffer.getvalue())

            with cols[i % 2]:
                st.image(label_img, caption=zone, use_container_width=True)

    st.download_button(
        "⬇️ Download All Labels (ZIP, print-ready PNGs @ 300 DPI, A4 landscape)",
        data=zip_buffer.getvalue(),
        file_name="zone_labels.zip",
        mime="application/zip",
    )
