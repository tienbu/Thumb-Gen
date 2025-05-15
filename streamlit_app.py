import streamlit as st, io, zipfile, tinify
from PIL import Image
from pathlib import Path

# ───────── TinyPNG key – single shared secret ─────────
tinify.key = st.secrets["TINIFY_API_KEY"].strip()

# ───────────── UI section ─────────────
st.set_page_config("Thumbnail Processor", "🎮")
st.title("🎮 One-Click Thumbnail Processor")

game = st.text_input("Game / common name *", max_chars=50)

files = st.file_uploader(
    "Upload **box, landscape & portrait** artwork (PNG or JPEG)",
    type=["png", "jpg", "jpeg"],
    accept_multiple_files=True
)

if st.button("✨ Process"):

    # Basic validation
    if not game:
        st.error("Type the game name first.")
        st.stop()
    if len(files) < 3:
        st.error("Upload all three images.")
        st.stop()

    # Bucket the three required files
    buckets = {"box": None, "landscape": None, "portrait": None}
    for f in files:
        for k in buckets:
            if k in f.name.lower():
                buckets[k] = f
                break
    if None in buckets.values():
        st.error("Filenames must contain **box**, **landscape**, and **portrait**.")
        st.stop()

    # ───── Process images & build the two ZIPs in memory ─────
    land_zip_buf = io.BytesIO()
    port_zip_buf = io.BytesIO()

    with zipfile.ZipFile(land_zip_buf, "w", zipfile.ZIP_DEFLATED) as land_zip, \
         zipfile.ZipFile(port_zip_buf, "w", zipfile.ZIP_DEFLATED) as port_zip:

        # Helper to compress (if needed) and write both original + webp
        def handle(img_file, zip_handle, out_ext):
            base = f"{game}{out_ext}"
            raw_bytes = img_file.read()

            # Compress via TinyPNG
            try:
                raw_bytes = tinify.from_buffer(raw_bytes).to_buffer()
            except tinify.errors.Error as e:
                st.error(f"TinyPNG error: {e.message}")
                st.stop()

            # Save compressed original
            zip_handle.writestr(base, raw_bytes)

            # Convert to WebP
            img = Image.open(io.BytesIO(raw_bytes))
            webp_io = io.BytesIO()
            img.save(webp_io, format="WEBP")
            webp_io.seek(0)
            zip_handle.writestr(f"{game}.webp", webp_io.read())

        # BOX  (no compression, no zip)
        box_file = buckets["box"]
        st.write("📦 Box handled (no compression).")

        # LANDSCAPE
        handle(buckets["landscape"], land_zip, ".png")
        st.write("🌄 Landscape compressed & added to ZIP.")

        # PORTRAIT
        handle(buckets["portrait"], port_zip, ".jpg")
        st.write("🧑 Portrait compressed & added to ZIP.")

    land_zip_buf.seek(0)
    port_zip_buf.seek(0)

    # ───── Offer the two ZIP downloads ─────
    st.success("Done! Download your two ZIPs below 👇")
    st.download_button("Download landscape.zip",
                       land_zip_buf, file_name="landscape.zip", mime="application/zip")
    st.download_button("Download portrait.zip",
                       port_zip_buf, file_name="portrait.zip", mime="application/zip")
