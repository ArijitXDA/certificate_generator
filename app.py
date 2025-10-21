# ======================================
# app.py — Certificate Generator (with Admin Login)
# ======================================

import streamlit as st
from pathlib import Path
import pandas as pd
from PIL import Image, ImageDraw, ImageFont
import unicodedata, re, zipfile, tempfile, io, os

# ------------------ Simple Admin Authentication ------------------
# Uses Streamlit secrets (set ADMIN_USERNAME and ADMIN_PASSWORD in Streamlit Cloud)
admin_username = st.secrets.get("ADMIN_USERNAME") if hasattr(st, "secrets") else None
admin_password = st.secrets.get("ADMIN_PASSWORD") if hasattr(st, "secrets") else None

def _check_credentials(u, p):
    if not u or not p:
        return False
    return (admin_username is not None and admin_password is not None and u == admin_username and p == admin_password)

if "logged_in" not in st.session_state:
    st.session_state.logged_in = False

if not st.session_state.logged_in:
    st.markdown("## 🔐 Admin login required")
    user = st.text_input("Username")
    pwd = st.text_input("Password", type="password")
    col1, col2 = st.columns([1,1])
    with col1:
        do_login = st.button("Login")
    with col2:
        if st.button("Help"):
            st.info("Enter admin username and password (provided by app owner).")
    if do_login:
        if _check_credentials(user, pwd):
            st.session_state.logged_in = True
            st.experimental_rerun()
        else:
            st.error("Invalid credentials.")
    st.stop()

# If logged in, show a Logout button
logout_col1, logout_col2 = st.columns([9,1])
with logout_col2:
    if st.button("Logout"):
        st.session_state.logged_in = False
        st.experimental_rerun()
# -----------------------------------------------------------------

# ------------------------------
# Utility functions
# ------------------------------
def sanitize_filename(s):
    s = str(s)
    s = unicodedata.normalize("NFKD", s)
    s = re.sub(r"[^\w\s\-_.]", "", s).strip()
    s = re.sub(r"[\s]+", "_", s)
    return s[:200] or "unknown"

def text_dimensions(draw, text, font):
    try:
        bbox = draw.textbbox((0, 0), text, font=font)
        return bbox[2] - bbox[0], bbox[3] - bbox[1]
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
    lines, cur = [], ""
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

# ------------------------------
# Certificate generation
# ------------------------------
def generate_certificates_from_inputs(df, template_path, fonts, signature_path, out_dir, config):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    base = Image.open(template_path).convert("RGBA")
    W, H = base.size
    created = []

    for _, row in df.iterrows():
        name = str(row["Name"]).strip()
        webinar = str(row["Webinar Name"]).strip()
        date = str(row["Webinar Date"]).strip()

        img = base.copy()
        draw = ImageDraw.Draw(img)

        # Webinar (top-right)
        webinar_font = get_font_file(fonts.get("webinar"), config["webinar_font_size"])
        wb_w, wb_h = text_dimensions(draw, webinar, webinar_font)
        draw.text((W - wb_w - config["webinar_right_margin"], config["webinar_y"]),
                  webinar, font=webinar_font, fill=(30,30,30))

        # Name (center)
        horiz_max_width = W - config["name_max_width_adjust"]
        if config.get("name_force_size"):
            chosen_font = get_font_file(fonts.get("name"), config["name_force_size"])
        else:
            chosen_font = None
            for size in range(config["name_max_size"], config["name_min_size"] - 1, -1):
                f = get_font_file(fonts.get("name"), size)
                nw, _ = text_dimensions(draw, name, f)
                if nw <= horiz_max_width:
                    chosen_font = f
                    break
            if chosen_font is None:
                chosen_font = get_font_file(fonts.get("name"), config["name_min_size"])

        name_w, name_h = text_dimensions(draw, name, chosen_font)
        name_x = ((W - name_w) // 2) + config["name_x_adjust"]
        draw.text((name_x, config["name_y"]), name, font=chosen_font, fill=(212,160,23))

        # Paragraph text
        para_font = get_font_file(fonts.get("para"), config["para_font_size"])
        lines = create_paragraph_lines(draw, name, webinar, date, para_font,
                                       config["para_wrap_width"], config["paragraph_template"])
        start_y = config["name_y"] + name_h + config["para_top_offset"]
        for ln in lines:
            lw, lh = text_dimensions(draw, ln, para_font)
            draw.text(((W - lw)//2 + config["para_x_adjust"], start_y), ln, font=para_font, fill=(60,60,60))
            start_y += lh + config["para_line_spacing"]

        # Date
        date_font = get_font_file(fonts.get("date"), config["date_font_size"])
        draw.text((config["date_x"], config["date_y"]), f"Date : {date}", font=date_font, fill=(60,60,60))

        # Signature (optional)
        if signature_path and Path(signature_path).exists():
            try:
                sig = Image.open(signature_path).convert("RGBA")
                max_sig_w = int(W * 0.18)
                if sig.width > max_sig_w:
                    sig = sig.resize((max_sig_w, int(sig.height * max_sig_w / sig.width)), Image.Resampling.LANCZOS)
                margin = int(W * 0.05)
                sx, sy = W - sig.width - margin, H - sig.height - margin
                img.paste(sig, (sx, sy), sig)
            except Exception:
                pass

        # Save
        fname = f"{sanitize_filename(webinar)}_{sanitize_filename(date)}_{sanitize_filename(name)}.{config['output_format'].lower()}"
        out_path = out_dir / fname
        img.convert("RGB").save(out_path, config['output_format'].upper(), quality=config.get("jpg_quality", 95))
        created.append(out_path)

    # Zip everything
    zip_path = out_dir / "certificates.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in created:
            zf.write(f, arcname=f.name)
    return created, zip_path

# ------------------------------
# Streamlit UI
# ------------------------------
st.set_page_config(page_title="Certificate Generator", layout="wide")
st.title("🎓 Certificate Generator — Web App")

# Sidebar: files & uploads
st.sidebar.header("Files & Uploads")

# default repo root so cloud app uses repo assets by default
REPO_ROOT = Path(__file__).parent.resolve()
base_dir = st.sidebar.text_input("Base directory (for template & fonts)", value=str(REPO_ROOT))
base_dir_p = Path(base_dir)

# auto-detect assets in base_dir
template_file = None
attendees_file_detected = None
fonts_dir = base_dir_p / "fonts"
signature_file = None

if base_dir_p.exists():
    for f in base_dir_p.glob("*.png"):
        if "template" in f.name.lower() or "certificate" in f.name.lower():
            template_file = f
            break
    if template_file is None:
        pngs = list(base_dir_p.glob("*.png"))
        if pngs:
            template_file = pngs[0]

    for f in base_dir_p.glob("*.xls*"):
        attendees_file_detected = f
        break
    if attendees_file_detected is None:
        csvs = list(base_dir_p.glob("*.csv"))
        attendees_file_detected = csvs[0] if csvs else None

    if (base_dir_p / "signature.png").exists():
        signature_file = base_dir_p / "signature.png"

st.sidebar.write("Detected (repo/base dir):")
st.sidebar.write("Template:", template_file)
st.sidebar.write("Attendees (detected):", attendees_file_detected)
st.sidebar.write("Fonts folder:", fonts_dir)
st.sidebar.write("Signature:", signature_file)

# allow overriding paths
template_path = st.sidebar.text_input("Template path (leave blank to use detected)", value=str(template_file) if template_file else "")
fonts_dir_path = st.sidebar.text_input("Fonts folder path (leave blank to use detected)", value=str(fonts_dir) if fonts_dir.exists() else "")

# attendees uploader (user uploads attendee file)
st.sidebar.markdown("**Attendees file (upload from your computer)**")
uploaded_attendees = st.sidebar.file_uploader("Upload attendees Excel/CSV", type=["xlsx", "xls", "csv"])

if uploaded_attendees is not None:
    tmp_att_file = tempfile.NamedTemporaryFile(delete=False, suffix=Path(uploaded_attendees.name).suffix)
    tmp_att_file.write(uploaded_attendees.read())
    tmp_att_file.close()
    attendees_path = str(tmp_att_file.name)
    st.sidebar.success("Attendees uploaded: " + uploaded_attendees.name)
else:
    attendees_path = str(attendees_file_detected) if attendees_file_detected else ""

# signature uploader (optional)
uploaded_signature = st.sidebar.file_uploader("Upload signature image (optional)", type=["png","jpg","jpeg"])
if uploaded_signature is not None:
    tmp_sig = tempfile.NamedTemporaryFile(delete=False, suffix=Path(uploaded_signature.name).suffix)
    tmp_sig.write(uploaded_signature.read())
    tmp_sig.close()
    signature_path = str(tmp_sig.name)
else:
    signature_path = st.sidebar.text_input("Signature path (optional - leave blank to use detected)", value=str(signature_file) if signature_file else "")

# ------------------------------
# Layout & controls
# ------------------------------
st.sidebar.header("Layout & Output")

st.sidebar.subheader("Webinar Title (top-right)")
webinar_size = st.sidebar.number_input("Font size (px)", value=28, min_value=8, max_value=300)
webinar_right_margin = st.sidebar.number_input("Right margin (px)", value=70, min_value=0, max_value=2000)
webinar_y = st.sidebar.number_input("Y (vertical px)", value=55, min_value=0, max_value=2000)

st.sidebar.subheader("Attendee Name (center)")
name_force_size = st.sidebar.number_input("Force name size (0 = auto-fit)", value=0, min_value=0, max_value=1000)
name_max_size = st.sidebar.number_input("Name max size", value=140, min_value=8, max_value=1500)
name_min_size = st.sidebar.number_input("Name min size", value=60, min_value=6, max_value=800)
name_x_adjust = st.sidebar.number_input("Name X adjust (px)", value=0, min_value=-2000, max_value=2000)
name_y = st.sidebar.number_input("Name Y (px)", value=300, min_value=0, max_value=2000)
name_max_width_adjust = st.sidebar.number_input("Name max width adjust (px)", value=300, min_value=0, max_value=2000)

st.sidebar.subheader("Paragraph Text")
para_font_size = st.sidebar.number_input("Paragraph font size (px)", value=16, min_value=6, max_value=200)
para_wrap_width = st.sidebar.number_input("Paragraph wrap width (px)", value=1100, min_value=200, max_value=3000)
para_top_offset = st.sidebar.number_input("Paragraph top offset (px)", value=20, min_value=0, max_value=1000)
para_line_spacing = st.sidebar.number_input("Paragraph line spacing (px)", value=6, min_value=0, max_value=100)
para_x_adjust = st.sidebar.number_input("Paragraph X adjust (px)", value=0, min_value=-1000, max_value=1000)

st.sidebar.subheader("Date (bottom-left)")
date_font_size = st.sidebar.number_input("Date font size (px)", value=20, min_value=6, max_value=200)
date_x = st.sidebar.number_input("Date X (px)", value=240, min_value=0, max_value=2000)
date_y = st.sidebar.number_input("Date Y (px)", value=480, min_value=0, max_value=2000)

output_format = st.sidebar.selectbox("Output format", ["PNG", "JPEG"])
jpg_quality = st.sidebar.slider("JPEG quality", 50, 100, 95)

# ------------------------------
# Main area / preview
# ------------------------------
st.header("Template preview")
if template_path and Path(template_path).exists():
    st.image(str(template_path), use_container_width=True)
else:
    st.info("No template file found. Provide Template path or add one in the repo root.")

# optional quick validation of uploaded attendees
if attendees_path:
    try:
        if str(attendees_path).lower().endswith((".xls", ".xlsx")):
            df_tmp = pd.read_excel(attendees_path, engine="openpyxl")
        else:
            df_tmp = pd.read_csv(attendees_path)
        missing = [c for c in ("Name", "Webinar Name", "Webinar Date") if c not in df_tmp.columns]
        if missing:
            st.sidebar.error("Uploaded attendees file missing columns: " + ", ".join(missing))
        else:
            st.sidebar.success(f"Attendees ready ({len(df_tmp)} rows).")
    except Exception as e:
        st.sidebar.error("Error reading attendees file: " + str(e))

# ------------------------------
# Generate Certificates
# ------------------------------
if st.button("Generate Certificates"):
    # Basic validations
    if not (template_path and Path(template_path).exists()):
        st.error("Template not found. Please provide a valid Template path or upload a template in the repo.")
    elif not (attendees_path and Path(attendees_path).exists()):
        st.error("Attendees file not found. Upload via the sidebar or provide a valid path.")
    else:
        # read attendees
        try:
            if str(attendees_path).lower().endswith((".xls", ".xlsx")):
                df = pd.read_excel(attendees_path, engine="openpyxl")
            else:
                df = pd.read_csv(attendees_path)
        except Exception as e:
            st.error("Failed to read attendees file: " + str(e))
            st.stop()

        for col in ("Name", "Webinar Name", "Webinar Date"):
            if col not in df.columns:
                st.error(f"Attendees file missing required column: {col}")
                st.stop()

        # fonts detection
        fonts_dir_used = Path(fonts_dir_path) if (fonts_dir_path and Path(fonts_dir_path).exists()) else (fonts_dir if fonts_dir.exists() else None)

        def pick_font(dirpath, preferred):
            if not dirpath:
                return None
            for n in preferred:
                f = Path(dirpath) / n
                if f.exists():
                    return f
            for f in Path(dirpath).glob("*.ttf"):
                return f
            return None

        FONT_PATH_NAME = pick_font(fonts_dir_used, ["PlayfairDisplay-Bold.ttf","PlayfairDisplay-Regular.ttf","PlayfairDisplay-ExtraBold.ttf"])
        FONT_PATH_WEBINAR = pick_font(fonts_dir_used, ["Montserrat-Bold.ttf","Montserrat-Regular.ttf"])
        FONT_PATH_PARA = pick_font(fonts_dir_used, ["Lora-Regular.ttf","Lora-Italic.ttf","Lora-Bold.ttf"])
        FONT_PATH_DATE = pick_font(fonts_dir_used, ["OpenSans-Regular.ttf","OpenSans-Bold.ttf"])        

        fonts = {"name": FONT_PATH_NAME, "webinar": FONT_PATH_WEBINAR, "para": FONT_PATH_PARA, "date": FONT_PATH_DATE}

        config = {
            "webinar_font_size": int(webinar_size),
            "webinar_right_margin": int(webinar_right_margin),
            "webinar_y": int(webinar_y),

            "name_force_size": int(name_force_size) if int(name_force_size) > 0 else None,
            "name_max_size": int(name_max_size),
            "name_min_size": int(name_min_size),
            "name_x_adjust": int(name_x_adjust),
            "name_y": int(name_y),
            "name_max_width_adjust": int(name_max_width_adjust),

            "para_font_size": int(para_font_size),
            "para_wrap_width": int(para_wrap_width),
            "para_line_spacing": int(para_line_spacing),
            "para_top_offset": int(para_top_offset),
            "para_x_adjust": int(para_x_adjust),

            "date_font_size": int(date_font_size),
            "date_x": int(date_x),
            "date_y": int(date_y),

            "paragraph_template": "This is to certify that {NAME} has participated in the {WEBINAR} Masterclass held on {DATE} under the guidance of a team of experienced trainers. We acknowledge {PRONOUN} dedication and commitment to completing this session.",
            "output_format": output_format,
            "jpg_quality": int(jpg_quality)
        }

        out_tmp = tempfile.mkdtemp(prefix="cert_out_")
        with st.spinner("Generating certificates..."):
            created, zip_path = generate_certificates_from_inputs(df, template_path, fonts, signature_path, out_tmp, config)

        st.success(f"✅ Created {len(created)} certificates.")
        with open(zip_path, "rb") as fh:
            st.download_button("📦 Download ZIP", fh.read(), file_name="certificates.zip", mime="application/zip")

        st.write("Preview:")
        cols = st.columns(min(3, len(created)))
        for c, p in zip(cols, created[:3]):
            c.image(str(p), use_container_width=True)
