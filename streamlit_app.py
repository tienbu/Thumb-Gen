import streamlit as st
from compressor import process_images

st.set_page_config(page_title="Thumbnail Processor", page_icon="🎮")

st.title("🎮 One-Click Thumbnail Optimiser")
st.markdown("Upload your **box, landscape, and portrait** PNGs – we’ll compress "
            "them with TinyPNG and hand you a zipped WebP ready for upload.")

uploaded = st.file_uploader("Select 3 files", type=["png"], accept_multiple_files=True)

if uploaded and st.button("✨ Process"):
    with st.spinner("Crunching…"):
        zip_buf = process_images(uploaded)
    st.success("Done! Download below.👇")
    st.download_button("Download ZIP", zip_buf, file_name="thumbnails.zip")
