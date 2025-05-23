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
LINEAR_URL  = "https://api.linear.app/graphql"

tinify.key = TINIFY_KEY

# ───────────────────────────────
# Google Sheets helper
# ───────────────────────────────
SA_INFO = json.loads(base64.b64decode(SERVICE_B64))
creds   = Credentials.from_service_account_info(SA_INFO)
sheets  = build("sheets", "v4", credentials=creds)
SHEET_ID = "1-kEERrIfKvRBUSyEg3ibJnmgZktASdd9vaQhpDPOGtA"
RANGE    = "Sheet1!A:F"  # expand if you have more columns

def get_provider_credentials():
    rows = sheets.spreadsheets().values().get(spreadsheetId=SHEET_ID, range=RANGE).execute().get("values", [])
    if not rows:
        return {}
    headers = [h.strip().lower() for h in rows[0]]
    idx_name = headers.index("provider name")
    idx_url = headers.index("url")
    idx_user = headers.index("username")
    idx_pass = headers.index("password")
    idx_alias = headers.index("aliases")
    out = {}
    for r in rows[1:]:
        # Fill missing cells with empty string
        while len(r) < len(headers):
            r.append("")
        all_names = [r[idx_name].strip().lower()]
        # Add aliases if present
        aliases = r[idx_alias].split(",") if r[idx_alias] else []
        all_names += [a.strip().lower() for a in aliases if a.strip()]
        # Save provider info for every possible name/alias
        for name in all_names:
            out[name] = {
                "url":      r[idx_url].strip(),
                "username": r[idx_user].strip(),
                "password": r[idx_pass].strip(),
            }
    return out

# ───────────────────────────────
# Linear helpers (official two‑step upload)
# ───────────────────────────────

def upload_file_to_linear(issue_id: str, fname: str, data: bytes) -> str:
    # This function is left as a stub since upload to Linear is currently disabled.
    return ""

def post_comment(issue_id: str, body: str):
    pass  # No-op since uploads/comments are disabled

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
    st.markdown("""
    **How to get your Linear API key:**  
    1. Go to [Linear Settings > API](https://linear.app/settings/api).
    2. Click "Create API Key".
    3. Copy the key and paste below.
    """)
    key   = st.text_input("Linear API Key", type="password", value=st.session_state.get("linear_key", ""))
    state = st.text_input("Linear Column / State", value=st.session_state.get("linear_state", ""))
    if st.button("Save"):
        st.session_state["linear_key"] = key.strip()
        st.session_state["linear_state"] = state.strip()
        st.success("Saved!")
    st.stop()

if "linear_key" not in st.session_state or "linear_state" not in st.session_state:
    st.error("Set Linear credentials in Account tab first.")
    st.stop()

# ───────────────────────────────
# Fetch Games view
# ───────────────────────────────
if view == "Fetch Games":
    st.header("📋 Fetch Game Launches")
    import datetime
    choice = st.date_input("Pick a date to list game launches", datetime.date.today())
    date_str = choice.strftime("%Y-%m-%d")

    if st.button("Fetch"):
        query = {
            "query": f"""query{{issues(filter:{{dueDate:{{eq:\"{date_str}\"}},labels:{{name:{{eq:\"Game Launch\"}}}},state:{{name:{{eq:\"{st.session_state['linear_state']}\"}}}}}}){{nodes{{id title}}}}}}"""
        }
        r = requests.post(
            LINEAR_URL,
            headers={
                "Authorization": st.session_state["linear_key"],
                "Content-Type": "application/json",
            },
            json=query,
        )
        r.raise_for_status()
        nodes = r.json()["data"]["issues"]["nodes"]
        st.session_state["issue_map"] = {n["title"]: n["id"] for n in nodes}
        provs = get_provider_credentials()
        if not nodes:
            st.info("No launches.")

        for n in nodes:
            st.subheader(n["title"])
            # Get provider keys (split on /, always lowercase)
            prov_names = [x.strip().lower() for x in n["title"].split(" - ")[-1].split("/")]
            # Only use the last provider (per your requirements)
            key = prov_names[-1]
            match = provs.get(key)
            if match:
                if match["url"]:
                    st.markdown(f"[Provider link]({match['url']})")
                if match["username"] or match["password"]:
                    st.code(f"User: {match['username']}\nPass: {match['password']}")
            else:
                st.warning(f"No provider info found for: {key.title()}")
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
    issue_id    = st.session_state["issue_map"][issue_title]
    # Direct link to Linear
    linear_link = f"https://linear.app/issue/{issue_id}"

    game_name = st.text_input("Game name", placeholder=issue_title)
    uploads   = st.file_uploader("portrait, landscape, box", type=["jpg", "jpeg", "png"], accept_multiple_files=True)

    if st.button("Process"):
        spec = {"box": (".jpg", False), "portrait": (".jpg", True), "landscape": (".png", True)}
        bucket = {k: f for f in uploads or [] for k in spec if k in f.name.lower()}
        if len(bucket) != 3:
            st.error("Upload portrait, landscape, box.")
            st.stop()

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

        # ZIP logic
        zips = {}
        for fold in ("Portrait", "Landscape"):
            buf_zip = io.BytesIO()
            with zipfile.ZipFile(buf_zip, "w", zipfile.ZIP_DEFLATED) as zf:
                for fname, blob in folders[fold].items():
                    zf.writestr(fname, blob)
            buf_zip.seek(0)
            zips[fold] = buf_zip.read()

        # Build master zip with all
        bundle = io.BytesIO()
        with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED) as zf:
            # Folders
            for fold in folders:
                for fname, blob in folders[fold].items():
                    zf.writestr(f"{fold}/{fname}", blob)
            # Zips
            zf.writestr("portrait.zip", zips["Portrait"])
            zf.writestr("landscape.zip", zips["Landscape"])
        bundle.seek(0)
        st.success(f"✅ Bundles ready. [Go to task in Linear]({linear_link})")
        st.download_button("⬇️ Download all (ZIP)", bundle, file_name=f"{game_name or issue_title}_bundle.zip")
