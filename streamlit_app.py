import io, zipfile, requests, base64, json
from datetime import datetime
from pathlib import Path

import streamlit as st
from PIL import Image
import tinify
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

# ─── Load Google service-account via Base64 secret ─────────
raw_sa = base64.b64decode(st.secrets["GC_SERVICE_KEY_B64"])
sa_info = json.loads(raw_sa)
creds = Credentials.from_service_account_info(sa_info)
sheets = build("sheets", "v4", credentials=creds)

SPREADSHEET_ID = "1-kEERrIfKvRBUSyEg3ibJnmgZktASdd9vaQhpDPOGtA"
RANGE_NAME     = "Sheet1!A:D"

def get_provider_credentials():
    rows = sheets.spreadsheets().values()\
        .get(spreadsheetId=SPREADSHEET_ID, range=RANGE_NAME)\
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

# ─── TinyPNG key ────────────────────────────────────────
tinify.key = st.secrets["TINIFY_API_KEY"]

# ─── UI config ──────────────────────────────────────────
st.set_page_config(page_title="Game Tools", page_icon="🎮", layout="wide")
st.sidebar.title("Navigation")
section = st.sidebar.radio("Go to", ["Account Details", "Game List Retriever", "Thumbnail Processor"])

# Initialize session state for Linear credentials
if "linear_key" not in st.session_state:
    st.session_state["linear_key"] = ""
if "linear_state" not in st.session_state:
    st.session_state["linear_state"] = ""

# ─── Account Details ────────────────────────────────────
if section == "Account Details":
    st.header("🔧 Account Details")
    st.session_state["linear_key"] = st.text_input("Linear API Key", type="password", value=st.session_state["linear_key"])
    st.session_state["linear_state"] = st.text_input("Linear Column/State", value=st.session_state["linear_state"])
    st.markdown("---")

# ─── Game List Retriever ────────────────────────────────
elif section == "Game List Retriever":
    st.header("📋 Game List Retriever")
    key = st.session_state["linear_key"]
    state = st.session_state["linear_state"]
    if not key or not state:
        st.error("Please set your API key and state under Account Details.")
    else:
        if st.button("Fetch my launches"):
            today = datetime.today().strftime("%Y-%m-%d")
            query = {
                "query": f"""
                query {{
                  issues(filter:{{
                    dueDate:{{eq:"{today}"}},
                    labels:{{name:{{eq:"Game Launch"}}}},
                    state:{{name:{{eq:"{state}"}}}}
                  }}){{nodes{{title}}}}
                }}"""
            }
            resp = requests.post(
                "https://api.linear.app/graphql",
                headers={"Authorization": key, "Content-Type": "application/json"},
                json=query
            )
            resp.raise_for_status()
            tasks = resp.json().get("data", {}).get("issues", {}).get("nodes", [])
            providers = get_provider_credentials()
            if not tasks:
                st.info("No launches today.")
            for t in tasks:
                prov = t["title"].split(" - ")[-1].strip().lower()
                match = next((providers[p] for p in providers if prov in p), None)
                st.markdown(f"**{t['title']}**")
                if match:
                    st.markdown(f"[Provider link]({match['url']})")
                    with st.expander("Credentials"):
                        st.code(f"User: {match['username']}\nPass: {match['password']}")
                else:
                    st.write("_No provider match_")
                st.markdown("---")

# ─── Thumbnail Processor ─────────────────────────────────
elif section == "Thumbnail Processor":
    st.header("🖼️ Thumbnail Processor")
    game = st.text_input("Game name *", key="game_name")
    uploads = st.file_uploader(
        "Upload portrait.jpg, landscape.png, box.jpg",
        type=["jpg", "jpeg", "png"],
        accept_multiple_files=True,
        key="uploader"
    )
    if st.button("Process thumbnails"):
        if not game:
            st.error("Game name is required."); st.stop()
        if len(uploads) < 3:
            st.error("Please upload portrait + landscape + box."); st.stop()

        spec = {"box": (".jpg", False), "portrait": (".jpg", True), "landscape": (".png", True)}
        bucket = {}
        for f in uploads:
            for k in spec:
                if k in f.name.lower():
                    bucket[k] = f
        if len(bucket) != 3:
            st.error("Files must include box, portrait & landscape."); st.stop()

        folders, zbuf = {"Box": {}, "Portrait": {}, "Landscape": {}}, {}
        for key, file in bucket.items():
            ext, compress = spec[key]
            data = file.read()
            if compress:
                data = tinify.from_buffer(data).to_buffer()
            folders[key.capitalize()][f"{game}{ext}"] = data
            if key != "box":
                img = Image.open(io.BytesIO(data))
                buf = io.BytesIO()
                img.save(buf, format="WEBP")
                folders[key.capitalize()][f"{game}.webp"] = buf.getvalue()

        for fold in ("Portrait", "Landscape"):
            buf = io.BytesIO()
            z = zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED)
            for name, blob in folders[fold].items():
                z.writestr(name, blob)
            z.close(); buf.seek(0)
            zbuf[fold] = buf

        bundle = io.BytesIO()
        big = zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED)
        for fold, files in folders.items():
            for name, blob in files.items():
                big.writestr(f"{fold}/{name}", blob)
        big.writestr("Portrait.zip",  zbuf["Portrait"].getvalue())
        big.writestr("Landscape.zip", zbuf["Landscape"].getvalue())
        big.close(); bundle.seek(0)

        st.success("✅ Thumbnails ready—download below:")
        st.download_button(
            "⬇️ Download bundle ZIP",
            bundle,
            file_name=f"{game}_bundle.zip",
            mime="application/zip"
        )
