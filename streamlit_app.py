# ──────────────────────────────────────────────────────────────
#  Streamlit all-in-one app
#  • Thumbnail processor (TinyPNG → WebP → zipped bundle)
#  • Per-user Linear “Game Launch” checker
#  • Per-user Linear API key + column stored once in browser
# ──────────────────────────────────────────────────────────────

import io, json, zipfile, requests
from datetime import datetime
from pathlib import Path

import streamlit as st
from streamlit_js_eval import streamlit_js_eval        # local-storage helper
from PIL import Image
import tinify

# ───────── Google Sheets (provider credentials) ─────────
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

SERVICE_ACCOUNT_FILE = "linear-automation-54129d0ac6dc.json"   # <-- update path if needed
SPREADSHEET_ID       = "1-kEERrIfKvRBUSyEg3ibJnmgZktASdd9vaQhpDPOGtA"
RANGE_NAME           = "Sheet1!A:D"

# ───────── TinyPNG shared key (add in Streamlit Cloud ▸ Settings ▸ Secrets) ─────────
tinify.key = st.secrets["TINIFY_API_KEY"].strip()

# ───────── Utils ────────────────────────────────────────────
TODAY = datetime.today().strftime('%Y-%m-%d')

def get_provider_credentials():
    creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE)
    service = build("sheets", "v4", credentials=creds)
    rows = service.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID, range=RANGE_NAME).execute().get("values", [])

    data = {}
    for r in rows[1:]:
        if len(r) >= 2:
            provider = r[0].strip().lower()
            data[provider] = {
                "url":      r[1].strip(),
                "username": r[2].strip() if len(r) > 2 else "",
                "password": r[3].strip() if len(r) > 3 else "",
            }
    return data

def get_linear_tasks(api_key: str, state_name: str):
    url = "https://api.linear.app/graphql"
    headers = {"Authorization": api_key, "Content-Type": "application/json"}
    query = {
        "query": f"""
        query {{
          issues(
            filter: {{
              dueDate: {{ eq: "{TODAY}" }},
              labels: {{ name: {{ eq: "Game Launch" }} }},
              state:  {{ name: {{ eq: "{state_name}" }} }}
            }}
          ) {{
            nodes {{
              id title
            }}
          }}
        }}
        """
    }
    resp = requests.post(url, headers=headers, json=query)
    resp.raise_for_status()
    data = resp.json()
    return data.get("data", {}).get("issues", {}).get("nodes", [])

# ───────── App UI ────────────────────────────────────────────
st.set_page_config(page_title="Game Tools", page_icon="🎮")
st.title("🎮 Game Thumbnail & Launch Helper")

# ---------- store / recall Linear API key ----------
stored_key = streamlit_js_eval(
    js_expressions="localStorage.getItem('linear_api_key');",
    key="get_linear_key")
if stored_key: st.session_state["linear_key"] = stored_key

linear_key = st.text_input(
    "🔑  Your personal **Linear API key**",
    type="password",
    value=st.session_state.get("linear_key", "")
)
if st.button("Save Linear key"):
    if linear_key.strip():
        streamlit_js_eval(
            js_expressions=f"localStorage.setItem('linear_api_key', '{linear_key.strip()}');",
            key="set_linear_key")
        st.session_state["linear_key"] = linear_key.strip()
        st.success("Key saved locally.")
    st.stop()

# ---------- store / recall Linear state / column ----------
stored_state = streamlit_js_eval(
    js_expressions="localStorage.getItem('linear_state_name');",
    key="get_linear_state")
if stored_state: st.session_state["linear_state"] = stored_state

linear_state = st.text_input(
    "📋  Your **Linear column / state name** (exact)",
    value=st.session_state.get("linear_state", "")
)
if st.button("Save column name"):
    if linear_state.strip():
        streamlit_js_eval(
            js_expressions=f"localStorage.setItem('linear_state_name', '{linear_state.strip()}');",
            key="set_linear_state")
        st.session_state["linear_state"] = linear_state.strip()
        st.success("Column saved locally.")
    st.stop()

# stop until both pieces are stored
if "linear_key" not in st.session_state or "linear_state" not in st.session_state:
    st.info("Enter and save both your Linear key and column name above.")
    st.stop()

# ───────── Thumbnail processor ─────────
st.header("🖼️  Thumbnail Processor")

game = st.text_input("Game name *", key="game_name")
uploads = st.file_uploader(
    "Upload **portrait.jpg**, **landscape.png**, **box.jpg**",
    type=["jpg", "jpeg", "png"],
    accept_multiple_files=True,
    key="uploader"
)

if st.button("Process thumbnails"):

    # ----- validation -----
    if not game:
        st.error("Game name is required.")
        st.stop()
    if len(uploads) < 3:
        st.error("Please upload portrait, landscape, and box images.")
        st.stop()

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
                break
    if len(bucket) != 3:
        st.error("File names must include 'box', 'portrait', and 'landscape'.")
        st.stop()

    def assets(blob, compress, want_webp, ext):
        if compress:
            blob = tinify.from_buffer(blob).to_buffer()
        out = [(ext, blob)]
        if want_webp:
            img = Image.open(io.BytesIO(blob))
            buf = io.BytesIO(); img.save(buf, format="WEBP"); out.append((".webp", buf.getvalue()))
        return out

    folders   = {"Box": {}, "Portrait": {}, "Landscape": {}}
    z_buffers = {n: io.BytesIO() for n in ["Portrait", "Landscape"]}
    zips      = {
        "Portrait":  zipfile.ZipFile(z_buffers["Portrait"],  "w", zipfile.ZIP_DEFLATED),
        "Landscape": zipfile.ZipFile(z_buffers["Landscape"], "w", zipfile.ZIP_DEFLATED)
    }

    for key, f in bucket.items():
        ext, comp = spec[key]
        data = f.read()
        outputs = assets(data, comp, key != "box", ext)
        fold = key.capitalize()
        for ex, blob in outputs:
            fname = f"{game}{ex}"
            folders[fold][fname] = blob
            if fold in zips:
                zips[fold].writestr(fname, blob)

    for z in zips.values(): z.close()
    for b in z_buffers.values(): b.seek(0)

    # wrapper zip
    bundle = io.BytesIO()
    with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED) as big:
        for fold, files in folders.items():
            for name, blob in files.items():
                big.writestr(f"{fold}/{name}", blob)
        big.writestr("Portrait.zip",  z_buffers["Portrait"].getvalue())
        big.writestr("Landscape.zip", z_buffers["Landscape"].getvalue())
    bundle.seek(0)

    st.success("✅  Thumbnails ready:")
    st.download_button("⬇️  Download bundle",
                       bundle,
                       file_name=f"{game}_bundle.zip",
                       mime="application/zip")

# ───────── Linear “today’s launches” viewer ─────────
st.header("🎮  Today’s Game Launches")

if st.button("Fetch my launches"):
    tasks = get_linear_tasks(st.session_state["linear_key"],
                             st.session_state["linear_state"])
    creds = get_provider_credentials()

    if not tasks:
        st.info("No launches for today.")
    else:
        for t in tasks:
            prov_raw = t["title"].split(" - ")[-1].strip().lower()
            match = next((creds[p] for p in creds if prov_raw in p), None)

            st.markdown(f"**{t['title']}**")
            if match:
                st.markdown(f"🔗 [Provider link]({match['url']})")
                with st.expander("Credentials"):
                    st.code(f"User: {match['username']}\nPass: {match['password']}")
            else:
                st.write("_No provider credentials found_")
            st.write("---")
