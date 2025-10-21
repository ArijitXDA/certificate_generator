# ======================================
# Certificate Generator Web App (Streamlit)
# ======================================

import streamlit as st
from pathlib import Path
import pandas as pd
from PIL import Image, ImageDraw, ImageFont
import unicodedata, re, zipfile, tempfile

# ----------------------------------------------------------
# Utility functions
# ----------------------------------------------------------

def sanitize_filename(s):
    s = str(s)
    s = unicodedata.normalize("NFKD", s)
    s = re.sub(r"[^\w\s\-_.]", "", s).strip()
    s = re.sub(r"[\s]+", "_", s)
    return s[:200] or "unknown"

def text_dimensions(draw, text, font):
    try:
        bbox = draw.textbbox((0, 0), text, font=font)
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

# ----------------------------------------------------------
# Core Certificate Generator
# ----------------------------------------------------------

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
                  webinar, font=webinar_font, fill=(30, 30, 30))

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
        name_x = ((W - name_w)//2) + config["name_x_adjust"]
        draw.text((name_x, config["name_y"]), name, font=chosen_font, fill=(212, 160, 23))

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

        # Signature
        if signature_path and Path(signature_path).exists():
            sig = Image.open(signature_path).convert("RGBA")
            max_sig_w = int(W * 0.18)
            if sig.width > max_sig_w:
                sig = sig.resize((max_sig_w, int(sig.height * max_sig_w / sig.width)), Image.Resampling.LANCZOS)
            margin = int(W * 0.05)
            sx, sy = W - sig.width - margin, H - sig.height - margin
            img.paste(sig, (sx, sy), sig)

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

# ----------------------------------------------------------
# Streamlit Web App
# ----------------------------------------------------------

st.set_page_config(page_title="Certificate Generator", layout="wide")
st.title("🎓 Certificate Generator — Web App")

# Sidebar inputs
st.sidebar.header("File Sources")
base_dir = st.sidebar.text_input("Base directory", value=str(Path.cwd()))
base_dir_p = Path(base_dir)

# Auto-detect common files
template_file = None
attendees_file = None
fonts_dir = base_dir_p / "fonts"
signature_file = None

if base_dir_p.exists():
    pngs = list(base_dir_p.glob("*.png"))
    if pngs:
        template_file = pngs[0]
    excels = list(base_dir_p.glob("*.xls*"))
    if excels:
        attendees_file = excels[0]
    sigf = base_dir_p / "signature.png"
    if sigf.exists():
        signature_file = sigf

# Display detection
st.sidebar.caption("Auto-detected paths (if any):")
st.sidebar.text(f"Template: {template_file}")
st.sidebar.text(f"Attendees: {attendees_file}")
st.sidebar.text(f"Fonts: {fonts_dir}")
st.sidebar.text(f"Signature: {signature_file}")

template_path = st.sidebar.text_input("Template path", value=str(template_file or ""))
attendees_path = st.sidebar.text_input("Attendees Excel path", value=str(attendees_file or ""))
fonts_dir_path = st.sidebar.text_input("Fonts folder path", value=str(fonts_dir or ""))
signature_path = st.sidebar.text_input("Signature path (optional)", value=str(signature_file or ""))

# ----------------------------------------------------------
# Layout Controls
# ----------------------------------------------------------
st.sidebar.header("Layout & Output")

st.sidebar.subheader("Webinar Title (top-right)")
webinar_size = st.sidebar.number_input("Font size", value=28)
webinar_right_margin = st.sidebar.number_input("Right margin (px)", value=70)
webinar_y = st.sidebar.number_input("Y (vertical)", value=55)

st.sidebar.subheader("Attendee Name (center)")
name_force_size = st.sidebar.number_input("Force font size (0 = auto-fit)", value=0)
name_max_size = st.sidebar.number_input("Max font size (auto-fit start)", value=140)
name_min_size = st.sidebar.number_input("Min font size (auto-fit end)", value=60)
name_x_adjust = st.sidebar.number_input("X adjust (move right + / left -)", value=0)
name_y = st.sidebar.number_input("Y (vertical position)", value=300)
name_max_width_adjust = st.sidebar.number_input("Max width adjust", value=300)

st.sidebar.subheader("Paragraph Text")
para_font_size = st.sidebar.number_input("Font size", value=16)
para_wrap_width = st.sidebar.number_input("Wrap width (px)", value=1100)
para_top_offset = st.sidebar.number_input("Top offset from name (px)", value=20)
para_line_spacing = st.sidebar.number_input("Line spacing (px)", value=6)
para_x_adjust = st.sidebar.number_input("X adjust (px)", value=0)

st.sidebar.subheader("Date (bottom-left)")
date_font_size = st.sidebar.number_input("Font size", value=20)
date_x = st.sidebar.number_input("X position", value=240)
date_y = st.sidebar.number_input("Y position", value=480)

output_format = st.sidebar.selectbox("Output format", ["PNG", "JPEG"])
jpg_quality = st.sidebar.slider("JPEG quality", 50, 100, 95)

# ----------------------------------------------------------
# Main area
# ----------------------------------------------------------
st.header("Template Preview")
if template_path and Path(template_path).exists():
    st.image(str(template_path), use_column_width=True)
else:
    st.info("Upload or select a valid template file.")

# ----------------------------------------------------------
# Generate Button
# ----------------------------------------------------------
if st.button("Generate Certificates"):
    if not Path(template_path).exists():
        st.error("Template not found.")
    elif not Path(attendees_path).exists():
        st.error("Attendees file not found.")
    else:
        df = pd.read_excel(attendees_path)
        for col in ["Name", "Webinar Name", "Webinar Date"]:
            if col not in df.columns:
                st.error(f"Missing column: {col}")
                st.stop()

        fonts = {
            "name": fonts_dir / "PlayfairDisplay-Bold.ttf",
            "webinar": fonts_dir / "Montserrat-Bold.ttf",
            "para": fonts_dir / "Lora-Regular.ttf",
            "date": fonts_dir / "OpenSans-Regular.ttf"
        }

        config = {
            "webinar_font_size": int(webinar_size),
            "webinar_right_margin": int(webinar_right_margin),
            "webinar_y": int(webinar_y),
            "name_force_size": int(name_force_size) if name_force_size > 0 else None,
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

        out_tmp = tempfile.mkdtemp(prefix="cert_output_")
        with st.spinner("Generating certificates..."):
            created, zip_path = generate_certificates_from_inputs(
                df, template_path, fonts, signature_path, out_tmp, config
            )

        st.success(f"✅ Generated {len(created)} certificates.")
        with open(zip_path, "rb") as f:
            st.download_button("📦 Download ZIP", f, file_name="certificates.zip", mime="application/zip")

        cols = st.columns(min(3, len(created)))
        for c, p in zip(cols, created[:3]):
            c.image(str(p), use_column_width=True)
