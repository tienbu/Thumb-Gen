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
RANGE    = "Sheet1!A:Z"   # Extended in case of more columns

def get_provider_credentials():
    rows = sheets.spreadsheets().values().get(spreadsheetId=SHEET_ID, range=RANGE).execute().get("values", [])
    if not rows:
        return {}

    headers = [h.strip().lower() for h in rows[0]]
    # Defensive: Find index for each field
    idx_name    = headers.index("provider name")
    idx_url     = headers.index("url")
    idx_user    = headers.index("username")
    idx_pass    = headers.index("password")
    idx_aliases = headers.index("aliases") if "aliases" in headers else None

    out = {}
    for r in rows[1:]:
        key = r[idx_name].strip().lower() if len(r) > idx_name else ""
        if not key:
            continue
        aliases = []
        if idx_aliases and len(r) > idx_aliases and r[idx_aliases].strip():
            aliases = [a.strip().lower() for a in r[idx_aliases].split(",")]
        out[key] = {
            "url":      r[idx_url].strip()     if len(r) > idx_url else "",
            "username": r[idx_user].strip()    if len(r) > idx_user else "",
            "password": r[idx_pass].strip()    if len(r) > idx_pass else "",
            "aliases":  aliases,
        }
    return out

# ───────────────────────────────
# Linear helpers (without upload, just zips)
# ───────────────────────────────

def post_comment(issue_id: str, body: str):
    mutation = "mutation($input:IssueCommentCreateInput!){issueCommentCreate(input:$input){success}}"
    vars = {"input": {"issueId": issue_id, "body": body}}
    headers = {"Authorization": st.session_state["linear_key"], "Content-Type": "application/json"}
    requests.post(LINEAR_URL, json={"query": mutation, "variables": vars}, headers=headers).raise_for_status()

# ───────────────────────────────
# Sidebar nav
# ───────────────────────────────
st.sidebar.title("Navigation")
view = st.sidebar.radio("Go to", ["Account", "Fetch Games", "Thumbnails"])

# ───────────────────────────────
# Account view
# ───────────────────────────────
if view == "Account":
    st.markdown("# 👋 Welcome to Game Tools")
    st.markdown("This app helps you fetch game launches and generate/upload thumbnails with one click.")
    with st.container():
        col1, col2 = st.columns([1, 3])
        with col1:
            st.image("https://linear.app/_next/static/media/linear-icon.svg", width=60)
        with col2:
            st.markdown("### Connect your Linear account")
            st.markdown("To use this tool, paste your Linear API key below.")

        with st.expander("How to get your Linear API Key (step-by-step)"):
            st.markdown("""
1️⃣ **Open Linear** and log in  
2️⃣ Click your profile icon (**top left**) → **Settings**  
3️⃣ Go to **Security & Access** > **Personal API Keys**  
4️⃣ Click **New API Key**, give it a name, and **copy the key**  
5️⃣ :warning: _Save your key somewhere safe—Linear only shows it once!_  
6️⃣ Paste your API key below.
""")
        st.info("Need help? Contact the admin.")

    key   = st.text_input("🔑 Linear API Key", type="password", value=st.session_state.get("linear_key", ""))
    state = st.text_input("🗂️ Linear Column / State", value=st.session_state.get("linear_state", ""))
    if st.button("Save"):
        st.session_state["linear_key"] = key.strip()
        st.session_state["linear_state"] = state.strip()
        st.success("✅ Saved!")
    st.stop()

# Guard for creds
if "linear_key" not in st.session_state or "linear_state" not in st.session_state:
    st.error("Set Linear credentials in Account tab first.")
    st.stop()

# ───────────────────────────────
# Fetch Games view
# ───────────────────────────────
if view == "Fetch Games":
    st.markdown("## 📋 Fetch Game Launches")
    # Use a calendar for date picking
    date_input = st.date_input("Choose a date", datetime.today())
    date_str = date_input.strftime("%Y-%m-%d")

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
            # Add direct link to Linear task
            issue_url = f"https://linear.app/issue/{st.session_state['issue_map'][n['title']]}"
            st.subheader(n["title"])
            st.markdown(f"[🔗 Open in Linear]({issue_url})")
            # Provider matching with aliases
            prov_names = n["title"].split(" - ")[-1].split("/")
            matches = []
            for pname in prov_names:
                key = pname.strip().lower()
                for prov, info in provs.items():
                    all_names = [prov] + info["aliases"]
                    if key in all_names:
                        matches.append(info)
                        break
            if matches:
                for match in matches:
                    st.markdown(f"[Provider link]({match['url']})")
                    if match['username'] or match['password']:
                        st.code(f"User: {match['username']}\nPass: {match['password']}")
            else:
                st.warning("No provider info found for: " + ", ".join(prov_names))
            st.divider()
    st.stop()

# ───────────────────────────────
# Thumbnails view
# ───────────────────────────────
if view == "Thumbnails":
    st.markdown("## 🖼️ Create & Download Thumbnail Bundles")
    if "issue_map" not in st.session_state:
        st.error("Fetch games first.")
        st.stop()

    issue_title = st.selectbox("Issue", list(st.session_state["issue_map"].keys()))
    issue_id    = st.session_state["issue_map"][issue_title]
    game_name = st.text_input("Game name", placeholder=issue_title)
    uploads   = st.file_uploader("Upload portrait, landscape, box", type=["jpg", "jpeg", "png"], accept_multiple_files=True)

    if st.button("Process"):
        spec = {"box": (".jpg", False), "portrait": (".jpg", True), "landscape": (".png", True)}
        bucket = {k: f for f in uploads or [] for k in spec if k in f.name.lower()}
        if len(bucket) != 3:
            st.error("Upload portrait, landscape, and box.")
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

        # Build zips and one mega zip
        zips = {}
        for fold in ("Portrait", "Landscape"):
            buf_zip = io.BytesIO()
            with zipfile.ZipFile(buf_zip, "w", zipfile.ZIP_DEFLATED) as zf:
                for fname, blob in folders[fold].items():
                    zf.writestr(fname, blob)
            buf_zip.seek(0)
            zips[fold] = buf_zip.read()

        mega_buf = io.BytesIO()
        with zipfile.ZipFile(mega_buf, "w", zipfile.ZIP_DEFLATED) as mega:
            for fold in folders:
                for fname, blob in folders[fold].items():
                    mega.writestr(f"{fold}/{fname}", blob)
            for fold in ("Portrait", "Landscape"):
                mega.writestr(f"{fold}.zip", zips[fold])
        mega_buf.seek(0)

        st.download_button("⬇️ Download Everything (zip)", mega_buf, file_name=f"{game_name}_bundle.zip", mime="application/zip")
        st.success("✅ Bundle ready! Download your assets.")

