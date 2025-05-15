import streamlit as st, io, zipfile, tinify
from PIL import Image

tinify.key = st.secrets["TINIFY_API_KEY"].strip()

st.set_page_config(page_title="Thumbnail Processor", page_icon="🎮")
st.title("🎮 One-Click Thumbnail Processor")

game = st.text_input("1️⃣  Game name *", max_chars=50)

files = st.file_uploader(
    "2️⃣  Upload  portrait.jpg • landscape.png • box.jpg",
    type=["jpg", "jpeg", "png"],
    accept_multiple_files=True
)

if st.button("✨ Process"):

    if not game:
        st.error("Please type the game name.")
        st.stop()
    if len(files) < 3:
        st.error("Upload all three images.")
        st.stop()

    # expected → (original_ext, needs_compress?)
    spec = {
        "box":        (".jpg", False),
        "portrait":   (".jpg", True),
        "landscape":  (".png", True),
    }
    bucket = {}
    for f in files:
        for k in spec:
            if k in f.name.lower():
                bucket[k] = f
                break
    if len(bucket) != 3:
        st.error("Filenames must contain box / portrait / landscape.")
        st.stop()

    # helper to TinyPNG-compress + optional WebP conversion
    def make_assets(raw, must_compress, want_webp, ext):
        if must_compress:
            try:
                raw = tinify.from_buffer(raw).to_buffer()
            except tinify.errors.Error as e:
                st.error(f"TinyPNG error: {e.message}")
                st.stop()
        out = [(ext, raw)]
        if want_webp:
            img = Image.open(io.BytesIO(raw))
            buf = io.BytesIO()
            img.save(buf, format="WEBP")
            out.append((".webp", buf.getvalue()))
        return out

    # ─── build Portrait.zip and Landscape.zip first ───
    zip_buf = {n: io.BytesIO() for n in ["Portrait", "Landscape"]}
    z_portrait = zipfile.ZipFile(zip_buf["Portrait"], "w", zipfile.ZIP_DEFLATED)
    z_landscape = zipfile.ZipFile(zip_buf["Landscape"], "w", zipfile.ZIP_DEFLATED)

    # scratch dict to hold folder → {filename: bytes}
    folders = {"Box": {}, "Portrait": {}, "Landscape": {}}

    for key, file in bucket.items():
        orig_ext, must_comp = spec[key]
        raw_bytes = file.read()

        assets = make_assets(
            raw_bytes,
            must_compress=must_comp,
            want_webp=(key != "box"),
            ext=orig_ext
        )

        folder_name = key.capitalize()
        for ext, data in assets:
            fname = f"{game}{ext}"
            folders[folder_name][fname] = data
            if key == "portrait":
                z_portrait.writestr(fname, data)
            elif key == "landscape":
                z_landscape.writestr(fname, data)

    z_portrait.close(); z_landscape.close()
    for b in zip_buf.values():
        b.seek(0)

    # ─── build the master bundle ───
    bundle = io.BytesIO()
    with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED) as bigzip:
        # add folders & files
        for folder, files_dict in folders.items():
            for name, data in files_dict.items():
                bigzip.writestr(f"{folder}/{name}", data)
        # add the two sub-zips
        bigzip.writestr("Portrait.zip",  zip_buf["Portrait"].getvalue())
        bigzip.writestr("Landscape.zip", zip_buf["Landscape"].getvalue())
    bundle.seek(0)

    st.success("All set — download your complete package:")
    st.download_button(
        "⬇️  Download Game bundle",
        bundle,
        file_name=f"{game}_bundle.zip",
        mime="application/zip",
    )
