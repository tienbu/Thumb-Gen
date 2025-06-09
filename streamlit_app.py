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
# Google Sheets client
# ───────────────────────────────
SA_INFO = json.loads(base64.b64decode(SERVICE_B64))
creds   = Credentials.from_service_account_info(SA_INFO)
sheets  = build("sheets", "v4", credentials=creds)

SHEET_ID      = "1-kEERrIfKvRBUSyEg3ibJnmgZktASdd9vaQhpDPOGtA"
PROV_RANGE    = "Sheet1!A:Z"
USER_KEY_TAB  = "user_keys!A:C"        # designer | linear_key | column

# ───────────────────────────────
# Provider-sheet helper
# ───────────────────────────────
def get_provider_credentials():
    rows = sheets.spreadsheets().values().get(
        spreadsheetId=SHEET_ID, range=PROV_RANGE
    ).execute().get("values", [])
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
        if len(r) <= i_name or not r[i_name]:
            continue
        key = r[i_name].strip().lower()
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
# user_keys helpers
# ───────────────────────────────
def load_user_keys():
    """Return dict {designer: {'key':…, 'col':…}} from user_keys tab."""
    rows = sheets.spreadsheets().values().get(
        spreadsheetId=SHEET_ID, range=USER_KEY_TAB
    ).execute().get("values", [])
    # rows[0] is header; skip it
    return {
        r[0].strip().lower(): {
            "key": r[1].strip() if len(r) > 1 else "",
            "col": r[2].strip() if len(r) > 2 else "",
        }
        for r in rows[1:]
        if r and r[0].strip()
    }

def save_user_key(name: str, key: str, col: str):
    """Insert or update a designer row in user_keys tab."""
    rows = sheets.spreadsheets().values().get(
        spreadsheetId=SHEET_ID, range=USER_KEY_TAB
    ).execute().get("values", [])
    header, data = rows[0], rows[1:]
    # find row (if exists)
    idx = next((i for i, r in enumerate(data) if r[0].lower() == name), None)
    row_vals = [name, key, col]
    body = {"values": [row_vals]}
    if idx is None:
        # append
        sheets.spreadsheets().values().append(
            spreadsheetId=SHEET_ID,
            range=USER_KEY_TAB,
            valueInputOption="RAW",
            body=body,
        ).execute()
    else:
        # update (offset by +2 for header + 1-index)
        rng = f"user_keys!A{idx+2}:C{idx+2}"
        sheets.spreadsheets().values().update(
            spreadsheetId=SHEET_ID,
            range=rng,
            valueInputOption="RAW",
            body=body,
        ).execute()

# ───────────────────────────────
# Sidebar
# ───────────────────────────────
st.sidebar.title("Navigation")
view = st.sidebar.radio("Go to", ["Account", "Fetch Games", "Thumbnails"])

# ───────────────────────────────
# ACCOUNT TAB
# ───────────────────────────────
if view == "Account":
    st.header("Account / credentials")

    users = load_user_keys()
    existing_names = list(users.keys())
    choice = st.selectbox("Designer", existing_names + ["<new designer>"])
    if choice == "<new designer>":
        designer = st.text_input("Enter your designer handle (lowercase)")
    else:
        designer = choice

    prev_key = users.get(designer, {}).get("key", "")
    prev_col = users.get(designer, {}).get("col", "")

    key   = st.text_input("🔑 Linear API Key", type="password", value=prev_key)
    col   = st.text_input("🗂️ Linear Column / State", value=prev_col)

    if st.button("Save / Update"):
        if not designer:
            st.error("Designer name is required.")
        elif not key or not col:
            st.error("Both key and column are required.")
        else:
            save_user_key(designer.lower(), key.strip(), col.strip())
            st.session_state["linear_key"]   = key.strip()
            st.session_state["linear_state"] = col.strip()
            st.session_state["designer"]     = designer.lower()
            st.success("Saved!  You may now use the other tabs.")
    st.stop()

# Guard credentials
if "linear_key" not in st.session_state or "linear_state" not in st.session_state:
    st.error("Go to **Account** tab first and save your credentials.")
    st.stop()

linear_key   = st.session_state["linear_key"]
linear_state = st.session_state["linear_state"]

# ────────────────────────────────────────────────────────────────
# FETCH GAMES  — duplicate check across ALL open Game Launches
# ────────────────────────────────────────────────────────────────
if view == "Fetch Games":
    st.header("📋 Fetch game launches")
    date_val = st.date_input("Pick a date", datetime.today())
    date_str = date_val.strftime("%Y-%m-%d")

    if st.button("Fetch"):
        ##############################
        # 1. issues for the selected day
        ##############################
        day_query = {
            "query": f"""query {{
  issues(filter:{{
    dueDate:{{eq:"{date_str}"}},
    labels:{{name:{{eq:"Game Launch"}}}},
    state:{{name:{{eq:"{linear_state}"}}}}
  }}, first:250){{nodes{{id title}}}}
}}"""}                                                     # noqa
        day_resp = requests.post(
            LINEAR_URL,
            headers={"Authorization": linear_key, "Content-Type": "application/json"},
            json=day_query,
        ).json()
        day_nodes = day_resp["data"]["issues"]["nodes"]
        st.session_state["issue_map"] = {n["title"]: n["id"] for n in day_nodes}

        ##############################
        # 2. every open Game Launch issue (across dates / columns)
        ##############################
        all_query = {
            "query": """query {
  issues(filter:{
    labels:{name:{eq:"Game Launch"}},
    state:{type:{neq:COMPLETED}}      # anything not Done/Canceled
  }, first:500){
    nodes{ id title }
  }}
"""}
        all_resp = requests.post(
            LINEAR_URL,
            headers={"Authorization": linear_key, "Content-Type": "application/json"},
            json=all_query,
        ).json()
        all_nodes = all_resp["data"]["issues"]["nodes"]

        # ----- duplicate detection across ALL open issues -----
        name_count = {}
        for n in all_nodes:
            gname = n["title"].split(" - ")[0].strip().lower()
            name_count[gname] = name_count.get(gname, 0) + 1
        dup_names = {n for n, c in name_count.items() if c > 1}
        if dup_names:
            st.warning("⚠️ Duplicate games exist: " + ", ".join(sorted(dup_names)))

        # ---------- show the day list (with 🚩 badge) ----------
        provs = get_provider_credentials()
        if not day_nodes:
            st.info("No launches for that date.")

        for n in day_nodes:
            issue_url = f"https://linear.app/issue/{st.session_state['issue_map'][n['title']]}"
            base_name = n["title"].split(" - ")[0].strip().lower()
            dup_badge = " **🚩 duplicate**" if base_name in dup_names else ""
            st.subheader(n["title"] + dup_badge)
            st.markdown(f"[🔗 Open in Linear]({issue_url})")

            # ----- provider info (unchanged) -----
            prov_parts = [p.strip().lower() for p in n["title"].split(" - ")[-1].split("/")]
            shown = set()
            for key in prov_parts[::-1]:
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
                st.warning("No provider info: " + ", ".join(prov_parts))
            st.divider()
    st.stop()

# ───────────────────────────────
# THUMBNAILS TAB (portrait-only)
# ───────────────────────────────
if view == "Thumbnails":
    st.header("🖼️ Create & download bundle")
    if "issue_map" not in st.session_state:
        st.error("Fetch games first.")
        st.stop()

    issue_title = st.selectbox("Issue", list(st.session_state["issue_map"].keys()))
    issue_id    = st.session_state["issue_map"][issue_title]
    st.markdown(f"[🔗 Open in Linear](https://linear.app/issue/{issue_id})")

    game_name = st.text_input("Game name", placeholder=issue_title)
    uploads   = st.file_uploader("Upload **portrait.jpg** & **box.jpg**",
                                 type=["jpg", "jpeg", "png"], accept_multiple_files=True)

    if st.button("Process"):
        spec = {"box": (".jpg", False), "portrait": (".jpg", True)}
        bucket = {k: f for f in uploads or [] for k in spec if k in f.name.lower()}
        if len(bucket) != 2:
            st.error("Please upload BOTH portrait.jpg and box.jpg")
            st.stop()

        folders = {"Box": {}, "Portrait": {}}
        for role, upl in bucket.items():
            ext, comp = spec[role]; data = upl.read()
            if comp:
                data = tinify.from_buffer(data).to_buffer()
            folders[role.capitalize()][f"{game_name}{ext}"] = data
            if role == "portrait":
                buf = io.BytesIO()
                Image.open(io.BytesIO(data)).save(buf, format="WEBP")
                folders["Portrait"][f"{game_name}.webp"] = buf.getvalue()

        p_zip = io.BytesIO()
        with zipfile.ZipFile(p_zip, "w", zipfile.ZIP_DEFLATED) as zf:
            for f, b in folders["Portrait"].items():
                zf.writestr(f, b)
        p_zip.seek(0)

        bundle = io.BytesIO()
        with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED) as zf:
            for fold, files in folders.items():
                for fname, blob in files.items():
                    zf.writestr(f"{fold}/{fname}", blob)
            zf.writestr("portrait.zip", p_zip.read())
        bundle.seek(0)

        st.download_button(
            "⬇️ Download bundle",
            bundle,
            file_name=f"{game_name or 'game'}_bundle.zip",
            mime="application/zip",
        )
        st.success("✅ Bundle ready!")
