import io, zipfile, requests, base64, json
from datetime import datetime
from pathlib import Path

import streamlit as st
from PIL import Image
import tinify
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

# ─── 1) Google Sheets service-account from Base64 secret ─────────
raw_sa = base64.b64decode(st.secrets["GC_SERVICE_KEY_B64"])
sa_info = json.loads(raw_sa)
creds = Credentials.from_service_account_info(sa_info)
sheets = build("sheets", "v4", credentials=creds)

SPREADSHEET_ID = "1-kEERrIfKvRBUSyEg3ibJnmgZktASdd9vaQhpDPOGtA"
RANGE_NAME     = "Sheet1!A:D"

def get_provider_credentials():
    rows = sheets.spreadsheets().values() \
        .get(spreadsheetId=SPREADSHEET_ID, range=RANGE_NAME) \
        .execute().get("values", [])
    providers = {}
    for r in rows[1:]:
        if len(r) >= 2:
            key = r[0].strip().lower()
            providers[key] = {
                "url":      r[1].strip(),
                "username": r[2].strip() if len(r) > 2 else "",
                "password": r[3].strip() if len(r) > 3 else ""
            }
    return providers

# ─── 2) TinyPNG key from Secrets ─────────────────────────────
tinify.key = st.secrets["TINIFY_API_KEY"]

# ─── 3) Streamlit UI setup ──────────────────────────────────
st.set_page_config(page_title="Game Tools", page_icon="🎮")
st.markdown(
    "<h1 style='white-space: nowrap; font-size:2.5rem; margin-bottom:1rem;'>"
    "🎮 Game Thumbnail & Launch Helper"
    "</h1>",
    unsafe_allow_html=True,
)

# ─── 4) Linear credentials (per-session) ────────────────────
linear_key   = st.text_input("🔑 Linear API key", type="password")
linear_state = st.text_input("📋 Linear column/state name")

if not linear_key or not linear_state:
    st.info("Enter your Linear API key and state above to continue.")
    st.stop()

# ─── 5) Thumbnail processor ─────────────────────────────────
st.header("🖼️ Thumbnail Processor")

game = st.text_input("Game name *", key="game_name")
uploads = st.file_uploader(
    "Upload portrait.jpg, landscape.png, box.jpg",
    type=["jpg","jpeg","png"],
    accept_multiple_files=True,
    key="uploader"
)

if st.button("Process thumbnails"):
    if not game:
        st.error("Game name is required."); st.stop()
    if len(uploads) < 3:
        st.error("Please upload portrait + landscape + box."); st.stop()

    spec = {
        "box":       (".jpg", False),
        "portrait":  (".jpg", True),
        "landscape": (".png", True),
    }
    bucket = {}
    for f in uploads:
        for k in spec:
            if k in f.name.lower():
                bucket[k] = f
    if len(bucket) != 3:
        st.error("File names must include box, portrait & landscape."); st.stop()

    # collect files
    folders, zips = {"Box":{}, "Portrait":{}, "Landscape":{}}, {}
    for key, f in bucket.items():
        ext, do_compress = spec[key]
        data = f.read()
        if do_compress:
            data = tinify.from_buffer(data).to_buffer()
        # original
        folders[key.capitalize()][f"{game}{ext}"] = data
        # webp for portrait & landscape
        if key != "box":
            img = Image.open(io.BytesIO(data))
            buf = io.BytesIO()
            img.save(buf, format="WEBP")
            folders[key.capitalize()][f"{game}.webp"] = buf.getvalue()

    # create zips for Portrait & Landscape
    zip_buf = {}
    for fold in ("Portrait","Landscape"):
        buf = io.BytesIO()
        z = zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED)
        for name, blob in folders[fold].items():
            z.writestr(name, blob)
        z.close()
        buf.seek(0)
        zip_buf[fold] = buf

    # bundle everything into one ZIP
    bundle = io.BytesIO()
    big = zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED)
    for fold, files in folders.items():
        for name, blob in files.items():
            big.writestr(f"{fold}/{name}", blob)
    # include the sub-zips
    big.writestr("Portrait.zip",  zip_buf["Portrait"].getvalue())
    big.writestr("Landscape.zip", zip_buf["Landscape"].getvalue())
    big.close()
    bundle.seek(0)

    st.success("✅ Thumbnails ready—download below:")
    st.download_button(
        "⬇️ Download bundle ZIP",
        bundle,
        file_name=f"{game}_bundle.zip",
        mime="application/zip"
    )

# ─── 6) Today’s launches from Linear ─────────────────────────
st.header("🎮 Today’s Game Launches")

if st.button("Fetch my launches"):
    today = datetime.today().strftime("%Y-%m-%d")
    gql = {
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
        json=gql
    )
    resp.raise_for_status()
    tasks = resp.json().get("data",{}).get("issues",{}).get("nodes",[])

    provs = get_provider_credentials()
    if not tasks:
        st.info("No launches today.")
    for t in tasks:
        prov = t["title"].split(" - ")[-1].strip().lower()
        match = next((provs[k] for k in provs if prov in k), None)
        st.markdown(f"**{t['title']}**")
        if match:
            st.markdown(f"[Provider link]({match['url']})")
            with st.expander("Credentials"):
                st.code(f"User: {match['username']}\nPass: {match['password']}")
        else:
            st.write("_No provider match_")
        st.divider()
