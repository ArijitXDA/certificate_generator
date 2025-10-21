# app.py -- Certificate generator web UI (Streamlit)
import streamlit as st
from pathlib import Path
import tempfile
import zipfile
import shutil
import pandas as pd
from PIL import Image, ImageDraw, ImageFont
import unicodedata, re
import io
import os

st.set_page_config(page_title="Certificate Generator", layout="centered", initial_sidebar_state="expanded")

# ------------------------------
# Helpers (same logic as notebook)
# ------------------------------
def sanitize_filename(s):
    s = str(s)
    s = unicodedata.normalize("NFKD", s)
    s = re.sub(r"[^\w\s\-_.]", "", s).strip()
    s = re.sub(r"[\s]+", "_", s)
    return s[:200] or "unknown"

def text_dimensions(draw, text, font):
    try:
        bbox = draw.textbbox((0,0), text, font=font)
        return bbox[2]-bbox[0], bbox[3]-bbox[1]
    except Exception:
        return draw.textsize(text, font=font)

def get_font_file(path, size):
    try:
        if path and Path(path).exists():
            return ImageFont.truetype(str(path), size)
    except Exception:
        pass
    return ImageFont.load_default()

def wrap_text(draw, text, font, max_width):
    words = text.split()
    lines = []
    cur = ""
    for w in words:
        test = (cur + " " + w).strip()
        tw, _ = text_dimensions(draw, test, font)
        if tw <= max_width:
            cur = test
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines

def create_paragraph_lines(draw, name, webinar, date_str, font, max_width, template_paragraph):
    text = template_paragraph.format(NAME=name, WEBINAR=webinar, DATE=date_str, PRONOUN="their")
    return wrap_text(draw, text, font, max_width)

# Certificate generation function
def generate_certificates_from_inputs(df,
                                      template_path,
                                      fonts,
                                      signature_path,
                                      out_dir,
                                      config):
    """
    df: pandas DataFrame with columns 'Name','Webinar Name','Webinar Date'
    template_path: Path to PNG template
    fonts: dict with keys name, webinar, para, date -> Path or None
    signature_path: Path or None
    out_dir: Path to write certificates and certificates.zip
    config: dict containing sizes, positions, format
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    base = Image.open(template_path).convert("RGBA")
    W, H = base.size

    created = []
    for i, row in df.iterrows():
        name = str(row["Name"]).strip()
        webinar = str(row["Webinar Name"]).strip()
        date = str(row["Webinar Date"]).strip()

        img = base.copy()
        draw = ImageDraw.Draw(img)

        # Webinar top-right
        webinar_font = get_font_file(fonts.get("webinar"), config["webinar_font_size"])
        wb_w, wb_h = text_dimensions(draw, webinar, webinar_font)
        draw.text((W - wb_w - config["webinar_right_margin"], config["webinar_y"]),
                  webinar, font=webinar_font, fill=(30,30,30))

        # Name - auto-fit or forced
        horiz_max_width = W - config["name_max_width_adjust"]
        if config.get("name_force_size"):
            chosen_font = get_font_file(fonts.get("name"), config["name_force_size"])
        else:
            chosen_font = None
            for size in range(config["name_max_size"], config["name_min_size"]-1, -1):
                f = get_font_file(fonts.get("name"), size)
                nw, nh = text_dimensions(draw, name, f)
                if nw <= horiz_max_width:
                    chosen_font = f
                    break
            if chosen_font is None:
                chosen_font = get_font_file(fonts.get("name"), config["name_min_size"])

        name_w, name_h = text_dimensions(draw, name, chosen_font)
        name_x = ((W - name_w)//2) + config["name_x_adjust"]
        name_y = config["name_y"]
        draw.text((name_x, name_y), name, font=chosen_font, fill=(212,160,23))

        # Paragraph
        para_font = get_font_file(fonts.get("para"), config["para_font_size"])
        lines = create_paragraph_lines(draw, name, webinar, date, para_font, config["para_wrap_width"], config["paragraph_template"])
        start_y = name_y + name_h + config["para_top_offset"]
        for ln in lines:
            lw, lh = text_dimensions(draw, ln, para_font)
            draw.text(((W - lw)//2 + config["para_x_adjust"], start_y), ln, font=para_font, fill=(60,60,60))
            start_y += lh + config["para_line_spacing"]

        # Date
        date_font = get_font_file(fonts.get("date"), config["date_font_size"])
        draw.text((config["date_x"], config["date_y"]), f"Date : {date}", font=date_font, fill=(60,60,60))

        # Signature
        if signature_path and Path(signature_path).exists():
            try:
                sig = Image.open(signature_path).convert("RGBA")
                max_sig_w = int(W * 0.18)
                if sig.width > max_sig_w:
                    sig = sig.resize((max_sig_w, int(sig.height * max_sig_w / sig.width)), Image.Resampling.LANCZOS)
                margin = int(W * 0.05)
                sx, sy = W - sig.width - margin, H - sig.height - margin
                img.paste(sig, (sx, sy), sig)
            except Exception as e:
                st.warning(f"Signature paste failed: {e}")

        # Save
        fname = f"{sanitize_filename(webinar)}_{sanitize_filename(date)}_{sanitize_filename(name)}.{config['output_format'].lower()}"
        out_path = out_dir / fname
        if config['output_format'].upper() == "PNG":
            img.convert("RGB").save(out_path, "PNG")
        else:
            img.convert("RGB").save(out_path, "JPEG", quality=config.get("jpg_quality", 92))
        created.append(out_path)

    # Zip results
    zip_path = out_dir / "certificates.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in created:
            zf.write(f, arcname=f.name)

    return created, zip_path

# ------------------------------
# Streamlit UI
# ------------------------------
st.title("Certificate Generator — Web App")

st.sidebar.header("Source selection")
use_base_dir = st.sidebar.checkbox("Read from local Base Directory (server/local)", value=True)
uploaded_files_section = not use_base_dir

if use_base_dir:
    base_dir = st.sidebar.text_input("Base directory (absolute path)", value=str(Path.cwd()))
    st.sidebar.caption("This app must be running on the machine that has access to this path.")
    # fill inputs from that folder if files exist
    base_dir_p = Path(base_dir)
    template_from_dir = None
    attendees_from_dir = None
    fonts_from_dir = None
    signature_from_dir = None
    if base_dir_p.exists():
        # detect files
        for f in base_dir_p.glob("*.png"):
            # naive: choose first png that looks like template if names match existing
            if "template" in f.name.lower() or "certificate" in f.name.lower():
                template_from_dir = f
                break
        # fallback to any png
        if template_from_dir is None:
            pngs = list(base_dir_p.glob("*.png"))
            if pngs:
                template_from_dir = pngs[0]
        # attendees
        for f in base_dir_p.glob("*.xls*"):
            attendees_from_dir = f; break
        if attendees_from_dir is None:
            csvs = list(base_dir_p.glob("*.csv"))
            attendees_from_dir = csvs[0] if csvs else None
        # fonts folder
        fonts_dir = base_dir_p / "fonts"
        if fonts_dir.exists():
            fonts_from_dir = fonts_dir
        # signature
        sigf = base_dir_p / "signature.png"
        if sigf.exists():
            signature_from_dir = sigf

    st.write("Detected (if any):")
    st.write("Template:", template_from_dir)
    st.write("Attendees file:", attendees_from_dir)
    st.write("Fonts dir:", fonts_from_dir)
    st.write("Signature:", signature_from_dir)

    # Let user override or pick via file_uploader
    template_path = st.sidebar.text_input("Template path (or leave detected)", value=str(template_from_dir) if template_from_dir else "")
    attendees_path = st.sidebar.text_input("Attendees path (or leave detected)", value=str(attendees_from_dir) if attendees_from_dir else "")
    fonts_dir_path = st.sidebar.text_input("Fonts folder path (or leave detected)", value=str(fonts_from_dir) if fonts_from_dir else "")
    signature_path = st.sidebar.text_input("Signature path (optional)", value=str(signature_from_dir) if signature_from_dir else "")
else:
    st.sidebar.markdown("Upload files (template, attendees, signature optional, fonts ZIP optional)")
    template_file = st.sidebar.file_uploader("Template PNG", type=["png","jpg","jpeg"])
    attendees_file = st.sidebar.file_uploader("Attendees Excel/CSV", type=["xlsx","xls","csv"])
    signature_file = st.sidebar.file_uploader("Signature image (optional)", type=["png","jpg","jpeg"])
    fonts_zip = st.sidebar.file_uploader("Fonts ZIP (optional)", type=["zip"])

    template_path = None
    attendees_path = None
    fonts_dir_path = None
    signature_path = None

# Config UI
st.sidebar.header("Layout & Output")
col1, col2 = st.sidebar.columns(2)
with col1:
    st.session_state.webinar_size = st.number_input("Webinar font size", value=28, key="webinar_size")
    st.session_state.name_force_size = st.number_input("Force name size (0 = auto-fit)", value=0, key="name_force")
with col2:
    st.session_state.date_font_size = st.number_input("Date font size", value=20, key="date_size")
    st.session_state.para_font_size = st.number_input("Paragraph font size", value=16, key="para_size")

# advanced tuning
st.sidebar.subheader("Positions (advanced)")
NAME_Y_inp = st.sidebar.number_input("Name Y", value=300, key="name_y")
DATE_X_inp = st.sidebar.number_input("Date X", value=240, key="date_x")
DATE_Y_inp = st.sidebar.number_input("Date Y", value=480, key="date_y")

# Preview template (either detected or uploaded)
st.header("Template preview")
if not use_base_dir:
    if template_file:
        tbytes = template_file.read()
        st.image(tbytes, use_column_width=True)
        # make a temp file to pass to generator
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=Path(template_file.name).suffix)
        tmp.write(tbytes); tmp.close()
        template_path = tmp.name
    else:
        st.info("Upload template PNG or provide Base Directory.")
else:
    if template_path and Path(template_path).exists():
        st.image(str(template_path), use_column_width=True)
    else:
        st.warning("No template found - please provide Template path or upload via 'Upload' mode.")

# allow user to confirm or upload attendees if base_dir
if use_base_dir:
    if attendees_path and Path(attendees_path).exists():
        st.success("Attendees file ready: " + str(attendees_path))
    else:
        st.warning("Attendees file not found in base dir. Provide path or switch to upload mode.")
else:
    if attendees_file:
        # save temporary attendees file
        tmpa = tempfile.NamedTemporaryFile(delete=False, suffix=Path(attendees_file.name).suffix)
        tmpa.write(attendees_file.read()); tmpa.close()
        attendees_path = tmpa.name
        st.success("Attendees uploaded.")
    else:
        st.info("Upload attendees Excel/CSV in the sidebar.")

# Fonts handling
if use_base_dir and fonts_dir_path and Path(fonts_dir_path).exists():
    fonts_dir = Path(fonts_dir_path)
else:
    fonts_dir = None

# if user uploaded a fonts zip, extract it
if not use_base_dir and 'fonts_zip' in locals() and fonts_zip:
    ztmp = tempfile.mkdtemp()
    with zipfile.ZipFile(fonts_zip) as zf:
        zf.extractall(ztmp)
    fonts_dir = Path(ztmp)

# Collect font choices (prefer explicit files, else pick common names)
def pick_font(fonts_dir, preferred_names):
    if not fonts_dir:
        return None
    for name in preferred_names:
        candidate = fonts_dir / name
        if candidate.exists():
            return candidate
    # fallback to first ttf in folder
    for f in fonts_dir.glob("*.ttf"):
        return f
    return None

FONT_PATH_NAME = pick_font(fonts_dir, ["PlayfairDisplay-Bold.ttf","PlayfairDisplay-Regular.ttf","PlayfairDisplay-Italic.ttf"])
FONT_PATH_WEBINAR = pick_font(fonts_dir, ["Montserrat-Bold.ttf","Montserrat-Regular.ttf"])
FONT_PATH_PARA = pick_font(fonts_dir, ["Lora-Regular.ttf","Lora-Bold.ttf"])
FONT_PATH_DATE = pick_font(fonts_dir, ["OpenSans-Regular.ttf","OpenSans-Bold.ttf"])

st.sidebar.write("Using fonts:")
st.sidebar.write("Name:", FONT_PATH_NAME)
st.sidebar.write("Webinar:", FONT_PATH_WEBINAR)
st.sidebar.write("Paragraph:", FONT_PATH_PARA)
st.sidebar.write("Date:", FONT_PATH_DATE)

# Run generation
if st.button("Generate Certificates"):
    # validations
    if not template_path or not Path(template_path).exists():
        st.error("Template not available. Upload or provide valid path.")
    elif not attendees_path or not Path(attendees_path).exists():
        st.error("Attendees file not available. Upload or provide valid path.")
    else:
        # read attendees
        p = Path(attendees_path)
        if p.suffix.lower() in [".xls", ".xlsx"]:
            df = pd.read_excel(p, engine="openpyxl")
        else:
            df = pd.read_csv(p)
        # check columns
        for c in ("Name","Webinar Name","Webinar Date"):
            if c not in df.columns:
                st.error(f"Attendees file missing column: {c}")
                st.stop()

        # prepare fonts dict
        fonts = {"name": FONT_PATH_NAME, "webinar": FONT_PATH_WEBINAR, "para": FONT_PATH_PARA, "date": FONT_PATH_DATE}
        signature = signature_path if (signature_path and Path(signature_path).exists()) else None

        # prepare temp output dir
        out_tmp = tempfile.mkdtemp(prefix="cert_out_")
        config = {
            "webinar_font_size": st.session_state.webinar_size,
            "webinar_right_margin": WEBINAR_RIGHT_MARGIN,
            "webinar_y": WEBINAR_Y,
            "name_force_size": int(st.session_state.name_force) if st.session_state.name_force>0 else None,
            "name_max_size": NAME_MAX_SIZE,
            "name_min_size": NAME_MIN_SIZE,
            "name_x_adjust": NAME_X_ADJUST,
            "name_y": NAME_Y_inp,
            "name_max_width_adjust": NAME_MAX_WIDTH_ADJUST,
            "para_font_size": st.session_state.para_size,
            "para_wrap_width": PARA_WRAP_WIDTH,
            "para_line_spacing": PARA_LINE_SPACING,
            "para_top_offset": PARA_TOP_OFFSET,
            "para_x_adjust": PARA_X_ADJUST,
            "date_font_size": st.session_state.date_size,
            "date_x": DATE_X_inp,
            "date_y": DATE_Y_inp,
            "paragraph_template": DETAIL_PARAGRAPH_TEMPLATE,
            "output_format": OUTPUT_FORMAT,
            "jpg_quality": JPG_QUALITY
        }

        with st.spinner("Generating certificates..."):
            created, zip_path = generate_certificates_from_inputs(df,
                                                                 template_path,
                                                                 fonts,
                                                                 signature,
                                                                 out_tmp,
                                                                 config)
        # provide download
        st.success(f"Created {len(created)} certificates.")
        with open(zip_path, "rb") as fh:
            data = fh.read()
            st.download_button("Download ZIP", data, file_name="certificates.zip", mime="application/zip")
        st.write("Generated files preview:")
        # show a few generated thumbnails
        preview = created[:6]
        cols = st.columns(min(3, len(preview)))
        for c, pth in zip(cols, preview):
            c.image(str(pth), use_column_width=True)
