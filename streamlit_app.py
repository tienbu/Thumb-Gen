# ─── Imports ──────────────────────────────────────────────
import json
import io, zipfile, requests
from datetime import datetime

import streamlit as st
from streamlit_js_eval import streamlit_js_eval
from PIL import Image
import tinify
from google.oauth2.service_account import Credentials

# ─── Google credentials loaded from Secrets ───────────────
creds = Credentials.from_service_account_info(
    json.loads(st.secrets["GOOGLE_SERVICE_JSON"])
)

# ─── TinyPNG shared key from Secrets ──────────────────────
tinify.key = st.secrets["TINIFY_API_KEY"]

creds = Credentials.from_service_account_info(st.secrets["google_service"])

# Google Sheet with provider creds
SPREADSHEET_ID = "1-kEERrIfKvRBUSyEg3ibJnmgZktASdd9vaQhpDPOGtA"
RANGE_NAME     = "Sheet1!A:D"

# ---------- helpers ----------------------------------------------------------
def get_provider_credentials():
    service = build("sheets", "v4", credentials=creds)
    rows = service.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID, range=RANGE_NAME).execute().get("values", [])
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

def get_linear_tasks(api_key, state_name):
    today = datetime.today().strftime('%Y-%m-%d')
    q = f"""
    query {{
      issues(filter:{{
        dueDate:{{eq:"{today}"}}
        labels:{{name:{{eq:"Game Launch"}}}}
        state:{{name:{{eq:"{state_name}"}}}}
      }}){{nodes{{title}}}}
    }}"""
    resp = requests.post(
        "https://api.linear.app/graphql",
        headers={"Authorization": api_key, "Content-Type": "application/json"},
        json={"query": q})
    return resp.json().get("data", {}).get("issues", {}).get("nodes", [])

# ---------- Streamlit UI -----------------------------------------------------
st.set_page_config("Game Tools", "🎮")
st.title("🎮 Game Thumbnail & Launch Helper")

# --- one-time per-browser storage of Linear API key & column
def remember(name, label):
    stored = streamlit_js_eval(f"localStorage.getItem('{name}');", key=f"get_{name}")
    if stored: st.session_state[name] = stored

    val = st.text_input(label, type="password" if 'key' in name else "default",
                        value=st.session_state.get(name, ""))
    if st.button(f"Save {name}"):
        if val.strip():
            streamlit_js_eval(f"localStorage.setItem('{name}', '{val.strip()}');",
                              key=f"set_{name}")
            st.session_state[name] = val.strip()
            st.experimental_rerun()  # reload with stored values
        st.stop()

remember("linear_api_key", "🔑  Linear API key")
remember("linear_state",   "📋  Linear column / state name")

# stop until both pieces exist
if "linear_api_key" not in st.session_state or "linear_state" not in st.session_state:
    st.stop()

# --- Thumbnail processor (same logic as before) ---
st.header("🖼️  Thumbnail Processor")
game = st.text_input("Game name *")
files = st.file_uploader("portrait.jpg / landscape.png / box.jpg",
                         type=["jpg","jpeg","png"], accept_multiple_files=True)
if st.button("Process thumbnails"):
    # ... (keep your thumbnail processing block unchanged)
    st.success("Thumbnails ready!")

# --- Linear launches ---
st.header("🎮  Today’s Game Launches")
if st.button("Fetch my launches"):
    tasks = get_linear_tasks(st.session_state["linear_api_key"],
                             st.session_state["linear_state"])
    creds_map = get_provider_credentials()
    if not tasks:
        st.info("No launches today.")
    for t in tasks:
        prov = t["title"].split(" - ")[-1].strip().lower()
        match = next((creds_map[p] for p in creds_map if prov in p), None)
        st.write(f"**{t['title']}**")
        if match:
            st.markdown(f"[Provider]({match['url']})")
            with st.expander("Credentials"): st.code(
                f"User: {match['username']}\nPass: {match['password']}")
        st.divider()
