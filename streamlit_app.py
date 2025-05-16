# ─────────────────────────────────────────────────────────
#  Streamlit All-in-One Tool
#  • Thumbnail compressor (TinyPNG → WebP → bundle.zip)
#  • Daily “Game Launch” list (Linear + Google Sheets)
#  • Simple Linear key/state inputs each session
# ─────────────────────────────────────────────────────────
import io, zipfile, requests, json
from datetime import datetime
from pathlib import Path

import streamlit as st
from PIL import Image
import tinify
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

# ─── Google Sheets setup ─────────────────────────────────
SERVICE_ACCOUNT_FILE = Path(__file__).parent / "linear-automation-62981b58cc22.json"
creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE)
sheets_srv = build("sheets", "v4", credentials=creds)

SPREADSHEET_ID = "1-kEERrIfKvRBUSyEg3ibJnmgZktASdd9vaQhpDPOGtA"
RANGE_NAME     = "Sheet1!A:D"

def get_provider_credentials():
    rows = sheets_srv.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID, range=RANGE_NAME
    ).execute().get("values", [])
    out = {}
    for r in rows[1:]:
        if len(r) >= 2:
            name = r[0].strip().lower()
            out[name] = {
                "url":      r[1].strip(),
                "username": r[2].strip() if len(r) > 2 else "",
                "password": r[3].strip() if len(r) > 3 else "",
            }
    return out

# ─── TinyPNG key from Streamlit Secrets ───────────────────
tinify.key = st.secrets["TINIFY_API_KEY"]

# ─── Streamlit UI setup ──────────────────────────────────
st.set_page_config(page_title="Game Tools", page_icon="🎮")
st.title("🎮 Game Thumbnail & Launch Helper")

# ─── Linear credentials (session‐only) ───────────────────
linear_key   = st.text_input("🔑 Linear API key", type="password")
linear_state = st.text_input("📋 Your Linear column/state name")

if not linear_key or not linear_state:
    st.info("Enter your Linear API key and state above to continue.")
    st.stop()

# ─── Thumbnail processor ──────────────────────────────────
st.header("🖼️ Thumbnail Processor")
game    = st.text_input("Game name *")
uploads = st.file_uploader(
    "Upload portrait.jpg, landscape.png, box.jpg",
    type=["jpg", "jpeg", "png"],
    accept_multiple_files=True
)

if st.button("Process thumbnails"):
    if not game:
        st.error("Game name is required."); st.stop()
    if len(uploads) < 3:
        st.error("Please upload portrait + landscape + box."); st.stop()

    spec = {"box": (".jpg", False),
            "portrait": (".jpg", True),
            "landscape": (".png", True)}
    bucket = {}
    for f in uploads:
        for k in spec:
            if k in f.name.lower():
                bucket[k] = f
    if len(bucket) != 3:
        st.error("Files must include box, portrait & landscape."); st.stop()

    # build folder dicts
    folders, zbuf = {"Box": {}, "Portrait": {}, "Landscape": {}}, {}
    for key, file in bucket.items():
        ext, compress = spec[key]
        data = file.read()
        if compress:
            data = tinify.from_buffer(data).to_buffer()
        # original
        folders[key.capitalize()][f"{game}{ext}"] = data
        # WebP
        if key != "box":
            img = Image.open(io.BytesIO(data))
            buf = io.BytesIO(); img.save(buf, format="WEBP")
            folders[key.capitalize()][f"{game}.webp"] = buf.getvalue()

    # portrait & landscape zips
    for fold in ("Portrait", "Landscape"):
        buf = io.BytesIO(); z = zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED)
        for name, blob in folders[fold].items():
            z.writestr(name, blob)
        z.close(); buf.seek(0); zbuf[fold] = buf

    # master bundle
    bundle = io.BytesIO(); big = zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED)
    for fold, files in folders.items():
        for name, blob in files.items():
            big.writestr(f"{fold}/{name}", blob)
    big.writestr("Portrait.zip",  zbuf["Portrait"].getvalue())
    big.writestr("Landscape.zip", zbuf["Landscape"].getvalue())
    big.close(); bundle.seek(0)

    st.success("✅ Thumbnails ready:")
    st.download_button(
        "⬇️ Download bundle",
        bundle,
        file_name=f"{game}_bundle.zip",
        mime="application/zip"
    )

# ─── Today’s launches from Linear ─────────────────────────
st.header("🎮 Today’s Game Launches")

if st.button("Fetch my launches"):
    # GraphQL query for issues due today with label + state
    today = datetime.today().strftime('%Y-%m-%d')
    query = {
        "query": f"""
        query {{
          issues(filter:{{
            dueDate:{{eq:"{today}"}},
            labels:{{name:{{eq:"Game Launch"}}}},
            state:{{name:{{eq:"{linear_state}"}}}}
          }}){{nodes{{title}}}}
        }}"""
    }
    resp = requests.post(
        "https://api.linear.app/graphql",
        headers={"Authorization": linear_key, "Content-Type": "application/json"},
        json=query
    )
    resp.raise_for_status()
    tasks = resp.json()["data"]["issues"]["nodes"]

    creds_map = get_provider_credentials()

    if not tasks:
        st.info("No launches today.")
    for t in tasks:
        prov = t["title"].split(" - ")[-1].strip().lower()
        match = next((creds_map[p] for p in creds_map if prov in p), None)
        st.markdown(f"**{t['title']}**")
        if match:
            st.markdown(f"[Provider link]({match['url']})")
            with st.expander("Credentials"):
                st.code(f"User: {match['username']}\nPass: {match['password']}")
        else:
            st.write("_No provider match_")
        st.divider()
