import streamlit as st, io, zipfile, tinify
from PIL import Image

# ─── YOUR shared TinyPNG key (set once in Streamlit Secrets) ───
tinify.key = st.secrets["TINIFY_API_KEY"].strip()

# ─── UI ───
st.set_page_config(page_title="Thumbnail Processor", page_icon="🎮")
st.title("🎮 One-Click Thumbnail Processor")

game = st.text_input("1️⃣  Game name *", max_chars=50)

files = st.file_uploader(
    "2️⃣  Upload **portrait.jpg  –  landscape.png  –  box.jpg**",
    type=["jpg", "jpeg", "png"],
    accept_multiple_files=True
)

if st.button("✨ Process"):

    # basic checks
    if not game:
        st.error("Please type the game name.")
        st.stop()
    if len(files) < 3:
        st.error("Upload all three images.")
        st.stop()

    # map expected keywords → (original_ext , needs_compress?)
    spec = {
        "box":        (".jpg", False),
        "portrait":   (".jpg", True),
        "landscape":  (".png", True),
    }
    bucket = {}

    # bucket the three required files
    for f in files:
        for key in spec:
            if key in f.name.lower():
                bucket[key] = f
                break

    if len(bucket) != 3:
        st.error("Filenames must contain **box**, **portrait**, and **landscape**.")
        st.stop()

    # helper: compress (if required) & optionally convert to webp
    def make_files(src_bytes: bytes, do_compress: bool, make_webp: bool, out_ext: str):
        if do_compress:
            try:
                src_bytes = tinify.from_buffer(src_bytes).to_buffer()
            except tinify.errors.Error as e:
                st.error(f"TinyPNG error: {e.message}")
                st.stop()
        outputs = [(out_ext, src_bytes)]
        if make_webp:
            im = Image.open(io.BytesIO(src_bytes))
            webp_buf = io.BytesIO()
            im.save(webp_buf, format="WEBP")
            outputs.append((".webp", webp_buf.getvalue()))
        return outputs

    # create three in-memory zips
    z_buf = {name: io.BytesIO() for name in ["Box", "Portrait", "Landscape"]}
    zips  = {n: zipfile.ZipFile(b, "w", zipfile.ZIP_DEFLATED) for n, b in z_buf.items()}

    # process each incoming file
    for key, f in bucket.items():
        orig_ext, do_comp = spec[key]
        file_bytes = f.read()
        outs = make_files(file_bytes, do_comp, key != "box", orig_ext)

        folder = key.capitalize()    # Box / Portrait / Landscape
        zip_handle = zips[folder]

        for ext, data in outs:
            filename = f"{game}{ext}"
            zip_handle.writestr(filename, data)

    # finalise and rewind buffers
    for z in zips.values():
        z.close()
    for b in z_buf.values():
        b.seek(0)

    # offer downloads
    st.success("Done — download your folders:")
    st.download_button("⬇️  Box.zip",        z_buf["Box"],        file_name="Box.zip")
    st.download_button("⬇️  Portrait.zip",   z_buf["Portrait"],   file_name="Portrait.zip")
    st.download_button("⬇️  Landscape.zip",  z_buf["Landscape"],  file_name="Landscape.zip")
