import streamlit as st, io, zipfile, tinify
from PIL import Image

tinify.key = st.secrets["TINIFY_API_KEY"]   # <─ single shared key

st.set_page_config("Thumbnail Processor", "🎮")
st.title("🎮 One-Click Thumbnail Processor")

game_name = st.text_input("Game (folder) name *", max_chars=50)

files = st.file_uploader(
    "Drop **box, landscape & portrait** artwork (PNG or JPEG)",
    type=["png", "jpg", "jpeg"],
    accept_multiple_files=True
)

if st.button("✨ Process"):

    if not game_name:
        st.error("Type the game name first.")
        st.stop()
    if len(files) < 3:
        st.error("Upload all three images.")
        st.stop()

    # bucket the three expected files
    buckets = {"box": None, "landscape": None, "portrait": None}
    for f in files:
        for k in buckets:
            if k in f.name.lower():
                buckets[k] = f
                break
    if None in buckets.values():
        st.error("File names must contain **box**, **landscape**, and **portrait**.")
        st.stop()

    zipped = io.BytesIO()
    with zipfile.ZipFile(zipped, "w") as z:
        for key, f in buckets.items():
            data = f.read()
            if key != "box":                      # compress only land/port
                try:
                    data = tinify.from_buffer(data).to_buffer()
                except tinify.errors.AccountError:
                    st.error("TinyPNG rejected the API key or the monthly "
                             "limit (500 images) is reached.")
                    st.stop()
            out_name = f.name.rsplit(".", 1)[0] + ".webp"
            folder = f"{game_name}_{key.capitalize()}/" if key != "box" else ""
            z.writestr(folder + out_name, data)
    zipped.seek(0)

    st.success("Done! Download your package ↓")
    st.download_button("Download ZIP",
                       zipped,
                       file_name=f"{game_name}_thumbnails.zip")
