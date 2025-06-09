import io, json, base64, zipfile, requests
from datetime import datetime
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
tinify.key  = TINIFY_KEY

# ───────────────────────────────
# helper → remember creds in browser cookie
# ───────────────────────────────
COOKIE_AGE = 3600 * 24 * 365  # one year


def remember(field: str, label: str, *, pwd=False) -> str:
    saved = st.experimental_get_cookie(field)
    value = st.text_input(label, value=saved or "", type="password" if pwd else "default")
    if value and value != saved:
        st.experimental_set_cookie(field, value, max_age=COOKIE_AGE, secure=True, httponly=True)
    if saved and st.button(f"Clear saved {label.lower()}", key=f"clr_{field}"):
        st.experimental_set_cookie(field, "", max_age=0)
        st.session_state.pop(field, None)
        value = ""
        st.experimental_rerun()
    return value


# ───────────────────────────────
# Google-Sheets helper
# ───────────────────────────────
SA_INFO = json.loads(base64.b64decode(SERVICE_B64))
creds   = Credentials.from_service_account_info(SA_INFO)
sheets  = build("sheets", "v4", credentials=creds)
SHEET_ID = "1-kEERrIfKvRBUSyEg3ibJnmgZktASdd9vaQhpDPOGtA"
RANGE    = "Sheet1!A:Z"

def get_provider_credentials():
    rows = sheets.spreadsheets().values().get(spreadsheetId=SHEET_ID, range=RANGE).execute().get("values", [])
    if not rows:
        return {}
    hdr = [h.strip().lower() for h in rows[0]]
    i_name = hdr.index("provider name")
    i_url  = hdr.index("url")
    i_user = hdr.index("username")
    i_pass = hdr.index("password")
    i_al   = hdr.index("aliases") if "aliases" in hdr else None
    out = {}
    for r in rows[1:]:
        key = r[i_name].strip().lower() if len(r) > i_name else ""
        if not key:
            continue
        aliases = []
        if i_al is not None and len(r) > i_al and r[i_al].strip():
            aliases = [a.strip().lower() for a in r[i_al].split(",")]
        out[key] = {
            "url":      r[i_url].strip()  if len(r) > i_url  else "",
            "username": r[i_user].strip() if len(r) > i_user else "",
            "password": r[i_pass].strip() if len(r) > i_pass else "",
            "aliases":  aliases,
        }
    return out

# ───────────────────────────────
# Sidebar
# ───────────────────────────────
st.sidebar.title("Navigation")
view = st.sidebar.radio("Go to", ["Account", "Fetch Games", "Thumbnails"])

# ───────────────────────────────
# Account
# ───────────────────────────────
if view == "Account":
    st.markdown("# 👋 Welcome to Game Tools")

    with st.expander("How to get your Linear API key"):
        st.markdown("""
1. **Open Linear** → profile icon → **Settings**  
2. **Security & Access** → **Personal API keys**  
3. Create a key, copy it (Linear shows it only once!)  
4. Paste below.
        """)

    key   = remember("linear_key",   "🔑 Linear API Key", pwd=True)
    state = remember("linear_state", "🗂️ Linear Column / State")

    if key and state:
        st.success("Credentials saved in your browser 👍")
    st.stop()

# Guard creds
if not st.experimental_get_cookie("linear_key") or not st.experimental_get_cookie("linear_state"):
    st.error("Please set your Linear credentials in the **Account** tab.")
    st.stop()

linear_key   = st.experimental_get_cookie("linear_key")
linear_state = st.experimental_get_cookie("linear_state")

# ───────────────────────────────
# Fetch Games
# ───────────────────────────────
if view == "Fetch Games":
    st.markdown("## 📋 Fetch game launches")
    date_val = st.date_input("Pick a date", datetime.today())
    date_str = date_val.strftime("%Y-%m-%d")

    if st.button("Fetch"):
        q = {
            "query": f"""query {{
  issues(filter: {{
    dueDate: {{eq:"{date_str}"}},
    labels: {{name: {{eq:"Game Launch"}}}},
    state: {{name: {{eq:"{linear_state}"}}}}
  }}) {{ nodes {{ id title }} }}
}}"""
        }
        r = requests.post(LINEAR_URL,
                          headers={"Authorization": linear_key,
                                   "Content-Type": "application/json"},
                          json=q)
        r.raise_for_status()
        nodes = r.json()["data"]["issues"]["nodes"]
        st.session_state["issue_map"] = {n["title"]: n["id"] for n in nodes}

        provs = get_provider_credentials()
        if not nodes:
            st.info("No launches.")

        for n in nodes:
            issue_url = f"https://linear.app/issue/{st.session_state['issue_map'][n['title']]}"
            st.subheader(n["title"])
            st.markdown(f"[🔗 Open in Linear]({issue_url})")

            prov_parts = [p.strip().lower()
                          for p in n["title"].split(" - ")[-1].split("/")]
            shown = set()
            for key in prov_parts[::-1]:  # most-specific first
                for main, info in provs.items():
                    if key == main or key in info["aliases"]:
                        if main in shown:
                            continue
                        if info["url"]:
                            st.markdown(f"[Provider link]({info['url']})")
                        if info["username"] or info["password"]:
                            st.code(f"User: {info['username']}\nPass: {info['password']}")
                        shown.add(main)
                        break
            if not shown:
                st.warning("No provider info found for: " + ", ".join(prov_parts))
            st.divider()
    st.stop()

# ───────────────────────────────
# Thumbnails  (portrait-only)
# ───────────────────────────────
if view == "Thumbnails":
    st.markdown("## 🖼️ Create & download thumbnail bundle")
    if "issue_map" not in st.session_state:
        st.error("Fetch games first.")
        st.stop()

    issue_title = st.selectbox("Issue", list(st.session_state["issue_map"].keys()))
    issue_id    = st.session_state["issue_map"][issue_title]
    st.markdown(f"[🔗 Open in Linear](https://linear.app/issue/{issue_id})")

    game_name = st.text_input("Game name", placeholder=issue_title)
    uploads   = st.file_uploader("Upload **portrait.jpg** and **box.jpg**",
                                 type=["jpg", "jpeg", "png"],
                                 accept_multiple_files=True)

    if st.button("Process"):
        spec = {"box": (".jpg", False), "portrait": (".jpg", True)}
        bucket = {k: f for f in uploads or [] for k in spec if k in f.name.lower()}
        if len(bucket) != 2:
            st.error("Please upload BOTH files.")
            st.stop()

        folders = {"Box": {}, "Portrait": {}}
        for role, upl in bucket.items():
            ext, comp = spec[role]
            data = upl.read()
            if comp:
                data = tinify.from_buffer(data).to_buffer()
            folders[role.capitalize()][f"{game_name}{ext}"] = data
            if role == "portrait":
                buf = io.BytesIO()
                Image.open(io.BytesIO(data)).save(buf, format="WEBP")
                folders["Portrait"][f"{game_name}.webp"] = buf.getvalue()

        # portrait.zip
        p_zip = io.BytesIO()
        with zipfile.ZipFile(p_zip, "w", zipfile.ZIP_DEFLATED) as zf:
            for fname, blob in folders["Portrait"].items():
                zf.writestr(fname, blob)
        p_zip.seek(0)

        # master bundle
        bundle = io.BytesIO()
        with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED) as zf:
            for fold, files in folders.items():
                for fname, blob in files.items():
                    zf.writestr(f"{fold}/{fname}", blob)
            zf.writestr("portrait.zip", p_zip.read())
        bundle.seek(0)

        st.download_button(
            "⬇️ Download bundle (zip)",
            bundle,
            file_name=f"{game_name or 'game'}_bundle.zip",
            mime="application/zip",
        )
        st.success("✅ Bundle ready!")
