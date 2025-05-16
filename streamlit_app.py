# ─────────────────────────────────────────────────────────
#  Streamlit All-in-One Tool
#  • Thumbnail compressor (TinyPNG → WebP → bundle.zip)
#  • Daily “Game Launch” list (Linear + Google Sheet creds)
#  • Linear key & column stored once in browser localStorage
# ─────────────────────────────────────────────────────────
import io, zipfile, requests, json
from datetime import datetime
from pathlib import Path

import streamlit as st
from streamlit_js_eval import streamlit_js_eval
from PIL import Image
import tinify

# ─── Google Sheets setup ─────────────────────────────────
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

SERVICE_ACCOUNT_FILE = Path(__file__).parent / "linear-automation-62981b58cc22.json"
creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE)

SPREADSHEET_ID = "1-kEERrIfKvRBUSyEg3ibJnmgZktASdd9vaQhpDPOGtA"
RANGE_NAME     = "Sheet1!A:D"
sheets_srv     = build("sheets", "v4", credentials=creds)

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

# ─── TinyPNG API key ─────────────────────────────────────
tinify.key = st.secrets["TINIFY_API_KEY"]

# ─── Linear helpers ──────────────────────────────────────
TODAY = datetime.today().strftime('%Y-%m-%d')

def linear_graphql(api_key: str, column: str):
    query = {
        "query": f"""
        query {{
          issues(filter:{{
            dueDate:{{eq:"{TODAY}"}},
            labels:{{name:{{eq:"Game Launch"}}}},
            state:{{name:{{eq:"{column}"}}}}
          }}){{nodes{{title}}}}
        }}"""
    }
    resp = requests.post(
        "https://api.linear.app/graphql",
        headers={"Authorization": api_key, "Content-Type": "application/json"},
        json=query, timeout=20)
    resp.raise_for_status()
    return resp.json()["data"]["issues"]["nodes"]

# ─── Streamlit UI ────────────────────────────────────────
st.set_page_config("Game Tools", "🎮")
st.title("🎮 Game Thumbnail & Launch Helper")

# — store Linear key & column once per browser —
def remember(field, label, pwd=False):
    cached = streamlit_js_eval(f"localStorage.getItem('{field}');", key=f"get_{field}")
    if cached: st.session_state[field] = cached
    value = st.text_input(label, type="password" if pwd else "default",
                          value=st.session_state.get(field, ""))
    if st.button(f"Save {field}"):
        if value.strip():
            streamlit_js_eval(
                f"localStorage.setItem('{field}', '{value.strip()}');",
                key=f"set_{field}")
            st.session_state[field] = value.strip()
            st.experimental_rerun()
        st.stop()

remember("linear_key",   "🔑  Linear API key",    pwd=True)
remember("linear_state", "📋  Your Linear column (state)")

if "linear_key" not in st.session_state or "linear_state" not in st.session_state:
    st.stop()

# ─── Thumbnail processor ─────────────────────────────────
st.header("🖼️  Thumbnail Processor")

game = st.text_input("Game name *")
uploads = st.file_uploader(
    "Upload portrait.jpg, landscape.png, box.jpg",
    type=["jpg", "jpeg", "png"], accept_multiple_files=True)

if st.button("Process thumbnails"):
    if not game:
        st.error("Game name required."); st.stop()
    if len(uploads) < 3:
        st.error("Please upload portrait + landscape + box."); st.stop()

    spec = {"box": (".jpg", False), "portrait": (".jpg", True), "landscape": (".png", True)}
    bucket = {}
    for f in uploads:
        for k in spec:
            if k in f.name.lower(): bucket[k] = f
    if len(bucket) != 3:
        st.error("File names must include box / portrait / landscape."); st.stop()

    folders, zbuf = {"Box": {}, "Portrait": {}, "Landscape": {}}, {}
    for key, file in bucket.items():
        ext, compress = spec[key]
        data = file.read()
        if compress:
            data = tinify.from_buffer(data).to_buffer()
        folders[key.capitalize()][f"{game}{ext}"] = data
        if key != "box":
            img = Image.open(io.BytesIO(data)); buf = io.BytesIO()
            img.save(buf, format="WEBP"); folders[key.capitalize()][f"{game}.webp"] = buf.getvalue()

    for fold in ("Portrait", "Landscape"):
        temp = io.BytesIO(); z = zipfile.ZipFile(temp, "w", zipfile.ZIP_DEFLATED)
        for name, blob in folders[fold].items(): z.writestr(name, blob)
        z.close(); temp.seek(0); zbuf[fold] = temp

    bundle = io.BytesIO(); big = zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED)
    for fold, files in folders.items():
        for name, blob in files.items():
            big.writestr(f"{fold}/{name}", blob)
    big.writestr("Portrait.zip",  zbuf["Portrait"].getvalue())
    big.writestr("Landscape.zip", zbuf["Landscape"].getvalue())
    big.close(); bundle.seek(0)

    st.success("Ready! Download bundle:")
    st.download_button("⬇️ Download",
                       bundle, file_name=f"{game}_bundle.zip",
                       mime="application/zip")

# ─── Today’s launches ────────────────────────────────────
st.header("🎮  Today’s Game Launches")

if st.button("Fetch my launches"):
    tasks = linear_graphql(st.session_state["linear_key"],
                           st.session_state["linear_state"])
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
