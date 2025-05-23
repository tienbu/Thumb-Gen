import io, json, base64, zipfile, requests
from datetime import datetime, timedelta

import streamlit as st
from PIL import Image
import tinify
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

# ───────────────────────────────
# Page & secrets
# ───────────────────────────────
st.set_page_config(page_title="Game Tools", page_icon="🎮", layout="wide")
TINIFY_KEY  = st.secrets["TINIFY_API_KEY"]
SERVICE_B64 = st.secrets["GC_SERVICE_KEY_B64"]

tinify.key = TINIFY_KEY

# ───────────────────────────────
# Google Sheets helper
# ───────────────────────────────
SA_INFO = json.loads(base64.b64decode(SERVICE_B64))
creds   = Credentials.from_service_account_info(SA_INFO)
sheets  = build("sheets", "v4", credentials=creds)
SHEET_ID = "1-kEERrIfKvRBUSyEg3ibJnmgZktASdd9vaQhpDPOGtA"
RANGE    = "Sheet1!A:D"

def get_provider_credentials():
    rows = sheets.spreadsheets().values().get(
        spreadsheetId=SHEET_ID, range=RANGE).execute().get("values", [])
    headers = [h.strip().lower() for h in rows[0]]

    # Figure out indices we care about (case-insensitive)
    idx_name    = headers.index("provider name")
    idx_url     = headers.index("url")
    idx_user    = headers.index("username")
    idx_pass    = headers.index("password")
    idx_aliases = None
    if "aliases" in headers:
        idx_aliases = headers.index("aliases")

    out = []
    for r in rows[1:]:
        rec = {
            "providername": r[idx_name].strip().lower() if idx_name < len(r) else "",
            "url": r[idx_url].strip() if idx_url < len(r) else "",
            "username": r[idx_user].strip() if idx_user < len(r) else "",
            "password": r[idx_pass].strip() if idx_pass < len(r) else "",
            "aliases": []
        }
        if idx_aliases is not None and idx_aliases < len(r):
            rec["aliases"] = [a.strip().lower() for a in r[idx_aliases].split(",") if a.strip()]
        out.append(rec)
    return out

def find_provider(providers, title):
    parts = [p.strip().lower() for p in title.split("/")]

    for rec in providers:
        # Direct provider name match
        if rec["providername"] in parts:
            return rec
        # Alias match
        if any(p in rec["aliases"] for p in parts):
            return rec
        # Substring fallback (rare)
        if any(any(p in a for a in [rec["providername"]] + rec["aliases"]) for p in parts):
            return rec
    return None


# ───────────────────────────────
# Sidebar nav
# ───────────────────────────────
st.sidebar.title("Navigation")
view = st.sidebar.radio("Go to", ["Account", "Fetch Games", "Thumbnails"])

# ───────────────────────────────
# Account view
# ───────────────────────────────
if view == "Account":
    st.header("🔧 Account Details")
    with st.expander("How to get your Linear API key", expanded=True):
        st.markdown(
            """
            1. Open [Linear](https://linear.app/) and log in.
            2. Click your profile icon (top left) → **Settings**.
            3. Under **Security and Access**, find **Personal API**.
            4. Click **New API Key**, give it a name, and copy the key.
            5. Paste the API key below.
            """
        )
        st.info("Your Linear API key is secret—never share it with others.")
    key   = st.text_input("Linear API Key", type="password", value=st.session_state.get("linear_key", ""))
    state = st.text_input("Designer Name", value=st.session_state.get("linear_state", ""))
    if st.button("Save"):
        st.session_state["linear_key"] = key.strip()
        st.session_state["linear_state"] = state.strip()
        st.success("Saved!")
    st.stop()

# ───────────────────────────────
# Fetch Games view
# ───────────────────────────────
if view == "Fetch Games":
    st.header("📋 Fetch Game Launches")
    date_input = st.date_input("Pick a date to list game launches", value=datetime.today())
    date_str = date_input.strftime("%Y-%m-%d")

    LINEAR_URL = "https://api.linear.app/graphql"
    if st.button("Fetch"):
        query = {
            "query": f"""query{{issues(filter:{{dueDate:{{eq:\"{date_str}\"}},labels:{{name:{{eq:\"Game Launch\"}}}},state:{{name:{{eq:\"{st.session_state['linear_state']}\"}}}}}}){{nodes{{id title}}}}}}"""
        }
        r = requests.post(LINEAR_URL, headers={"Authorization": st.session_state["linear_key"], "Content-Type": "application/json"}, json=query)
        r.raise_for_status()
        nodes = r.json()["data"]["issues"]["nodes"]
        st.session_state["issue_map"] = {n["title"]: n["id"] for n in nodes}
        provs = get_provider_credentials()
        if not nodes:
            st.info("No launches.")
        for n in nodes:
            st.subheader(n["title"])
            prov_key = n["title"].split(" - ")[-1].strip().lower()
            match = next((provs[p] for p in provs if prov_key in p), None)
            if match:
                st.markdown(f"[Provider link]({match['url']})")
                st.code(f"User: {match['username']}\nPass: {match['password']}")
            st.divider()
    st.stop()

# ───────────────────────────────
# Thumbnails view
# ───────────────────────────────
if view == "Thumbnails":
    st.header("🖼️ Create Game Thumbnails Bundle")
    if "issue_map" not in st.session_state:
        st.error("Fetch games first.")
        st.stop()

    issue_title = st.selectbox("Issue", list(st.session_state["issue_map"].keys()))
    game_name = st.text_input("Game name", placeholder=issue_title)
    uploads   = st.file_uploader("portrait, landscape, box", type=["jpg", "jpeg", "png"], accept_multiple_files=True)

    if st.button("Process"):
        spec = {"box": (".jpg", False), "portrait": (".jpg", True), "landscape": (".png", True)}
        bucket = {k: f for f in uploads or [] for k in spec if k in f.name.lower()}
        if len(bucket) != 3:
            st.error("Upload portrait, landscape, box.")
            st.stop()

        # Prepare folders in memory
        folders = {"Box": {}, "Portrait": {}, "Landscape": {}}
        for k, f in bucket.items():
            ext, comp = spec[k]
            data = f.read()
            if comp:
                data = tinify.from_buffer(data).to_buffer()
            fold = k.capitalize()
            folders[fold][f"{game_name}{ext}"] = data
            if k != "box":
                buf = io.BytesIO()
                Image.open(io.BytesIO(data)).save(buf, format="WEBP")
                folders[fold][f"{game_name}.webp"] = buf.getvalue()

        # Make portrait.zip and landscape.zip
        zips = {}
        for fold in ("Portrait", "Landscape"):
            buf_zip = io.BytesIO()
            with zipfile.ZipFile(buf_zip, "w", zipfile.ZIP_DEFLATED) as zf:
                for fname, blob in folders[fold].items():
                    zf.writestr(fname, blob)
            buf_zip.seek(0)
            zips[fold] = buf_zip.read()

        # Bundle everything in one big zip
        bundle = io.BytesIO()
        with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED) as bigzip:
            # Add folders/files
            for fold, files in folders.items():
                for fname, blob in files.items():
                    bigzip.writestr(f"{fold}/{fname}", blob)
            # Add the zipped folders
            bigzip.writestr("landscape.zip", zips["Landscape"])
            bigzip.writestr("portrait.zip", zips["Portrait"])
        bundle.seek(0)

        st.download_button(
            "⬇️ Download All (ZIP)",
            data=bundle,
            file_name=f"{game_name}_bundle.zip",
            mime="application/zip",
        )
        st.success("Bundle ready! ✅")

