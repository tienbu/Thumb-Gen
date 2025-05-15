import streamlit as st, io, zipfile, os, tinify
from PIL import Image

tinify.key = st.secrets["TINIFY_API_KEY"]

st.set_page_config(page_title="Thumbnail Processor", page_icon="🎮")
st.title("🎮 One-Click Thumbnail Processor")

# ---- 1. ask for the game / folder name ----
game_name = st.text_input("Game (folder) name *", max_chars=50)

# ---- 2. upload the three images ----
files = st.file_uploader(
    "Drop **box, landscape & portrait** artwork (PNG or JPEG)",
    type=["png", "jpg", "jpeg"],
    accept_multiple_files=True
)

# ---- 3. run when the button is pressed ----
if st.button("✨ Process"):

    # basic validation
    if not game_name:
        st.error("Please type the game name first.")
        st.stop()
    if len(files) < 3:
        st.error("Please upload all three images.")
        st.stop()

    # sort incoming files into our three buckets
    buckets = {"box": None, "landscape": None, "portrait": None}
    for f in files:
        lower = f.name.lower()
        for key in buckets:
            if key in lower:
                buckets[key] = f
                break

    if None in buckets.values():
        st.error("Files must include **box**, **landscape**, and **portrait** in their names.")
        st.stop()

    # ---- 4. process & build the output zip in-memory ----
    zipped = io.BytesIO()

    with zipfile.ZipFile(zipped, "w") as z:
        # two sub-folders exactly like the Windows script
        landscape_folder = f"{game_name}_Landscape/"
        portrait_folder  = f"{game_name}_Portrait/"

        for key, f in buckets.items():
            data = f.read()
            # compress landscape & portrait, leave box untouched
            if key in ("landscape", "portrait"):
                data = tinify.from_buffer(data).to_buffer()

            # convert extension to .webp
            base = f.name.rsplit(".", 1)[0] + ".webp"
            if key == "landscape":
                z.writestr(landscape_folder + base, data)
            elif key == "portrait":
                z.writestr(portrait_folder + base, data)
            else:  # box
                z.writestr(base, data)

    zipped.seek(0)

    # ---- 5. serve the zip ----
    st.success("Done! Download your ready-to-upload package👇")
    zip_name = f"{game_name}_thumbnails.zip"
    st.download_button("Download ZIP", zipped, file_name=zip_name)
