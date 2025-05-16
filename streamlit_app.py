import io, zipfile, requests, base64, json
from datetime import datetime, timedelta
from pathlib import Path

import streamlit as st
from PIL import Image
import tinify
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

# ─── 1) Google Sheets service-account from Base64 secret ─────────
raw_sa  = base64.b64decode(st.secrets["GC_SERVICE_KEY_B64"])
sa_info = json.loads(raw_sa)
creds   = Credentials.from_service_account_info(sa_info)
sheets  = build("sheets", "v4", credentials=creds)

SPREADSHEET_ID = "1-kEERrIfKvRBUSyEg3ibJnmgZktASdd9vaQhpDPOGtA"
RANGE_NAME     = "Sheet1!A:D"

def get_provider_credentials():
    rows = (
        sheets.spreadsheets()
              .values()
              .get(spreadsheetId=SPREADSHEET_ID, range=RANGE_NAME)
              .execute()
              .get("values", [])
    )
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

# ─── 3) UI setup ─────────────────────────────────────────────
st.set_page_config(page_title="Game Tools", page_icon="🎮", layout="wide")
st.sidebar.title("Navigation")
section = st.sidebar.radio(
    "Go to",
    ["Account Details", "Game List Retriever", "Thumbnail Processor"]
)

# ─── 4) Simple per-session Linear credentials ────────────────
if section == "Account Details":
    st.header("🔧 Account Details")
    st.session_state.setdefault("linear_key", "")
    st.session_state.setdefault("linear_state", "")
    st.session_state["linear_key"]   = st.text_input(
        "Linear API Key",
        type="password",
        value=st.session_state["linear_key"]
    )
    st.session_state["linear_state"] = st.text_input(
        "Linear Column/State",
        value=st.session_state["linear_state"]
    )
    st.stop()

linear_key   = st.session_state.get("linear_key", "")
linear_state = st.session_state.get("linear_state", "")

# ─── 5) Game List Retriever ─────────────────────────────────
if section == "Game List Retriever":
    st.header("📋 Game List Retriever")

    if not linear_key or not linear_state:
        st.error("Please set your API key and state in Account Details.")
        st.stop()

    # —— New date selector ——
    date_choice = st.selectbox("Select date", ["Today", "Tomorrow"])
    fetch_date = datetime.today() if date_choice == "Today" else datetime.today() + timedelta(days=1)
    date_str = fetch_date.strftime("%Y-%m-%d")

    if st.button("Fetch launches for " + date_choice):
        # Build GraphQL query with the chosen date
        gql = {
            "query": f"""
            query {{
              issues(filter:{{
                dueDate:{{eq:"{date_str}"}},
                labels:{{name:{{eq:"Game Launch"}}}},
                state:{{name:{{eq:"{linear_state}"}}}}
              }}){{nodes{{title}}}}
            }}"""
        }
        resp = requests.post(
            "https://api.linear.app/graphql",
            headers={"Authorization": linear_key, "Content-Type": "application/json"},
            json=gql,
            timeout=20
        )
        resp.raise_for_status()
        tasks = resp.json().get("data",{}).get("issues",{}).get("nodes", [])

        providers = get_provider_credentials()
        if not tasks:
            st.info(f"No launches on {date_choice} ({date_str}).")
        for t in tasks:
            prov_key = t["title"].split(" - ")[-1].strip().lower()
            match = next((providers[p] for p in providers if prov_key in p), None)
            st.markdown(f"**{t['title']}**")
            if match:
                st.markdown(f"[Provider link]({match['url']})")
                with st.expander("Credentials"):
                    st.code(f"User: {match['username']}\nPass: {match['password']}")
            else:
                st.write("_No provider match_")
            st.markdown("---")
    st.stop()

# ─── 6) Thumbnail Processor ─────────────────────────────────
if section == "Thumbnail Processor":
    st.header("🖼️ Thumbnail Processor")

    game   = st.text_input("Game name *", key="game_name")
    uploads = st.file_uploader(
        "Upload portrait.jpg, landscape.png, box.jpg",
        type=["jpg","jpeg","png"], accept_multiple_files=True
    )

    if st.button("Process thumbnails"):
        if not game:
            st.error("Game name is required."); st.stop()
        if len(uploads) < 3:
            st.error("Upload portrait, landscape, and box."); st.stop()

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
            st.error("Files must include box, portrait & landscape."); st.stop()

        # Process & zip
        folders, zip_bufs = {"Box":{}, "Portrait":{}, "Landscape":{}}, {}
        for key, file in bucket.items():
            ext, compress = spec[key]
            data = file.read()
            if compress:
                data = tinify.from_buffer(data).to_buffer()
            folders[key.capitalize()][f"{game}{ext}"] = data
            if key != "box":
                img = Image.open(io.BytesIO(data))
                buf = io.BytesIO(); img.save(buf, format="WEBP")
                folders[key.capitalize()][f"{game}.webp"] = buf.getvalue()

        for fold in ("Portrait","Landscape"):
            buf = io.BytesIO()
            z   = zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED)
            for name, blob in folders[fold].items():
                z.writestr(name, blob)
            z.close(); buf.seek(0); zip_bufs[fold] = buf

        bundle = io.BytesIO()
        big    = zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED)
        for fold, files in folders.items():
            for name, blob in files.items():
                big.writestr(f"{fold}/{name}", blob)
        big.writestr("Portrait.zip",  zip_bufs["Portrait"].getvalue())
        big.writestr("Landscape.zip", zip_bufs["Landscape"].getvalue())
        big.close(); bundle.seek(0)

        st.success("✅ Thumbnails ready—download below:")
        st.download_button(
            "⬇️ Download bundle ZIP",
            bundle,
            file_name=f"{game}_bundle.zip",
            mime="application/zip"
        )
