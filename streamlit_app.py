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
# Duplicate
# ───────────────────────────────

def duplicate_exact(api_key: str, base_title: str, self_id: str) -> str | None:
    """
    Return the URL of another open Game-Launch ticket whose *full* title equals
    base_title (case-sensitive), or None if no duplicate.
    """
    query = """
query($ttl:String!,$self:String!){
  issues(
    filter:{
      title:{eq:$ttl},
      labels:{name:{eq:"Game Launch"}},
      state:{type:{neq:COMPLETED}},
      id:{neq:$self}
    },
    first:1
  ){ nodes{ url } }
}"""
    try:
        resp = requests.post(
            LINEAR_URL,
            json={"query": query, "variables": {"ttl": base_title, "self": self_id}},
            headers={"Authorization": api_key, "Content-Type": "application/json"},
            timeout=10,
        ).json()
        nodes = resp.get("data", {}).get("issues", {}).get("nodes", [])
        return nodes[0]["url"] if nodes else None
    except requests.exceptions.RequestException:
        return None


# ───────────────────────────────
# Helpers  ─ providers & user-keys
# ───────────────────────────────
import re, difflib

def clean(txt: str) -> str:
    """lower-case; keep alphanumerics only"""
    return re.sub(r"[^a-z0-9]", "", txt.lower())


def fuzzy_duplicate(api_key: str, full_title: str, self_id: str) -> str | None:
    """
    Return the URL of an *open* Game-Launch ticket whose BASE title
    is ≥80 % similar to this one (case/spacing/punctuation insensitive),
    or None if none found.
    """
    base = full_title.split(" - ")[0].strip()
    term = " ".join(base.split()[:4])            # first few words are enough

    query = """
query ($term:String!,$self:String!){
  issueSearch(
    term:$term,
    first:15,
    filter:{
      labels:{name:{eq:"Game Launch"}},
      state:{type:{neq:COMPLETED}},
      id:{neq:$self}
    }
  ){ nodes{ id title url } }
}"""
    try:
        resp = requests.post(
            LINEAR_URL,
            json={"query": query, "variables": {"term": term, "self": self_id}},
            headers={"Authorization": api_key, "Content-Type": "application/json"},
            timeout=10,
        ).json()
        nodes = resp.get("data", {}).get("issueSearch", {}).get("nodes", [])
        cb = clean(base)
        for n in nodes:
            other_base = n["title"].split(" - ")[0].strip()
            sim = difflib.SequenceMatcher(None, cb, clean(other_base)).ratio()
            if sim >= 0.80:                    # tweak threshold if needed
                return n["url"]
        return None
    except requests.exceptions.RequestException:
        return None

# ───────────────────────────────

def safe_nodes(resp: dict) -> list[dict]:
    """Return resp['data']['issues']['nodes'] or [] and surface errors."""
    if "errors" in resp and resp["errors"]:
        st.error("Linear API error:\n" + json.dumps(resp["errors"], indent=2))
        return []
    return resp.get("data", {}).get("issues", {}).get("nodes", [])


def load_user_keys():
    rows = sheets.spreadsheets().values().get(
        spreadsheetId=SHEET_ID, range=USER_KEY_TAB).execute().get("values", [])
    return {
        r[0].strip().lower(): {
            "key": r[1].strip() if len(r) > 1 else "",
            "col": r[2].strip() if len(r) > 2 else "",
        }
        for r in rows[1:] if r and r[0].strip()
    }


def save_user_key(name: str, key: str, col: str):
    rows = sheets.spreadsheets().values().get(
        spreadsheetId=SHEET_ID, range=USER_KEY_TAB).execute().get("values", [])
    header, data = rows[0], rows[1:]
    idx = next((i for i, r in enumerate(data) if r[0].lower() == name), None)
    body = {"values": [[name, key, col]]}
    if idx is None:
        sheets.spreadsheets().values().append(
            spreadsheetId=SHEET_ID, range=USER_KEY_TAB,
            valueInputOption="RAW", body=body).execute()
    else:
        rng = f"user_keys!A{idx+2}:C{idx+2}"
        sheets.spreadsheets().values().update(
            spreadsheetId=SHEET_ID, range=rng,
            valueInputOption="RAW", body=body).execute()


def get_provider_credentials():
    rows = sheets.spreadsheets().values().get(
        spreadsheetId=SHEET_ID, range=PROV_RANGE).execute().get("values", [])
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
        if len(r) <= i_name or not r[i_name].strip():
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
# Linear helper — paginate all open Game-Launch issues
# ───────────────────────────────
def fetch_all_open_game_launches(api_key: str) -> list[dict]:
    query = """
query ($after:String){
  issues(
    filter:{
      labels:{name:{eq:"Game Launch"}},
      state:{type:{neq:COMPLETED}}
    },
    first:250,
    after:$after
  ){
    nodes{ id title }
    pageInfo{ hasNextPage endCursor }
  }
}"""
    headers = {"Authorization": api_key, "Content-Type": "application/json"}
    after = None
    nodes: list[dict] = []
    while True:
        resp = requests.post(
            LINEAR_URL,
            json={"query": query, "variables": {"after": after}},
            headers=headers,
            timeout=30,
        ).json()
        page_nodes = safe_nodes(resp)
        nodes.extend(page_nodes)
        pg = resp["data"]["issues"]["pageInfo"]
        if not pg["hasNextPage"]:
            break
        after = pg["endCursor"]
    return nodes

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
    existing = list(users.keys())
    choice = st.selectbox("Designer", existing + ["<new designer>"])
    designer = st.text_input("Designer handle (lowercase)",
                             value="" if choice == "<new designer>" else choice)

    prev = users.get(designer.lower(), {})
    key  = st.text_input("🔑 Linear API Key", type="password", value=prev.get("key", ""))
    col  = st.text_input("🗂️ Column / State", value=prev.get("col", ""))

    if st.button("Save / Update"):
        if not designer or not key or not col:
            st.error("Designer, key and column are required.")
        else:
            save_user_key(designer.lower(), key.strip(), col.strip())
            st.session_state["linear_key"]   = key.strip()
            st.session_state["linear_state"] = col.strip()
            st.success("Saved!  You may now use the other tabs.")
    st.stop()

# guard creds
if "linear_key" not in st.session_state or "linear_state" not in st.session_state:
    st.error("Go to **Account** and save credentials first.")
    st.stop()

linear_key   = st.session_state["linear_key"]
linear_state = st.session_state["linear_state"]

# ───────────────────────────────
# FETCH GAMES – fuzzy duplicate flag
# ───────────────────────────────
if view == "Fetch Games":
    st.header("📋 Fetch game launches")
    date_val = st.date_input("Pick a date", datetime.today())
    date_str = date_val.strftime("%Y-%m-%d")

    if st.button("Fetch"):
        with st.spinner("Loading day’s list…"):
            day_q = {"query": f"""query {{
  issues(filter:{{
    dueDate:{{eq:"{date_str}"}},
    labels:{{name:{{eq:"Game Launch"}}}},
    state:{{name:{{eq:"{linear_state}"}}}}
  }}, first:250){{nodes{{id title}}}}
}}"""}  # noqa
            day_nodes = safe_nodes(
                requests.post(
                    LINEAR_URL,
                    json=day_q,
                    headers={"Authorization": linear_key,
                             "Content-Type": "application/json"},
                    timeout=30,
                ).json()
            )
            st.session_state["issue_map"] = {n["title"]: n["id"] for n in day_nodes}

        provs = get_provider_credentials()
        if not day_nodes:
            st.info("No launches for that date.")

        for n in day_nodes:
            dup_url = fuzzy_duplicate(linear_key, n["title"], n["id"])
            badge   = f" **🚩 duplicate**  ([existing]({dup_url}))" if dup_url else ""
            my_url  = f"https://linear.app/issue/{n['id']}"

            st.subheader(n["title"] + badge)
            st.markdown(f"[🔗 Open in Linear]({my_url})")

            # ---------- provider info ----------
            prov_parts = [p.strip().lower()
                          for p in n["title"].split(" - ")[-1].split("/")]
            shown = set()
            for k in prov_parts[::-1]:
                for main, info in provs.items():
                    if k == main or k in info["aliases"]:
                        if main in shown:
                            continue
                        if info["url"]:
                            st.markdown(f"[Provider link]({info['url']})")
                        if info["username"] or info["password"]:
                            st.code(f"User: {info['username']}\nPass: {info['password']}")
                        shown.add(main); break
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
            for fname, blob in folders["Portrait"].items():
                zf.writestr(fname, blob)
        p_zip.seek(0)

        bundle = io.BytesIO()
        with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED) as zf:
            for fold, files in folders.items():
                for fname, blob in files.items():
                    zf.writestr(f"{fold}/{fname}", blob)
            zf.writestr("portrait.zip", p_zip.read())
        bundle.seek(0)

        st.download_button("⬇️ Download bundle",
                           bundle,
                           file_name=f"{game_name or 'game'}_bundle.zip",
                           mime="application/zip")
        st.success("✅ Bundle ready!")
