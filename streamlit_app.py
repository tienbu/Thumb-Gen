import io, json, base64, zipfile, requests, re, difflib
from datetime import datetime
import streamlit as st
from PIL import Image
import tinify
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

# ───────────────────────────────
#  PAGE & SECRETS
# ───────────────────────────────
st.set_page_config(page_title="Game Tools", page_icon="🎮", layout="wide")
TINIFY_KEY  = st.secrets["TINIFY_API_KEY"]
SERVICE_B64 = st.secrets["GC_SERVICE_KEY_B64"]
LINEAR_URL  = "https://api.linear.app/graphql"
tinify.key  = TINIFY_KEY

# ───────────────────────────────
#  GOOGLE SHEETS CLIENT
# ───────────────────────────────
SA_INFO = json.loads(base64.b64decode(SERVICE_B64))
creds   = Credentials.from_service_account_info(SA_INFO)
sheets  = build("sheets", "v4", credentials=creds)

SHEET_ID      = "1-kEERrIfKvRBUSyEg3ibJnmgZktASdd9vaQhpDPOGtA"
PROV_RANGE    = "Sheet1!A:Z"
USER_KEY_TAB  = "user_keys!A:C"        # designer | linear_key | column

# ───────────────────────────────
#  DUPLICATE UTILITIES
# ───────────────────────────────
def _clean(txt: str) -> str:
    txt = txt.replace("–", "-").replace("—", "-")
    return re.sub(r"[^a-z0-9]", "", txt.lower())

def base_of(title: str) -> str:
    return title.split(" - ")[0].strip()

def build_duplicate_map(api_key: str) -> dict[str, list[str]]:
    """Fetch **all** open Game-Launch tickets once, build {clean_base: [url…]}."""
    query = """
query ($after:String){
  issues(
    filter:{
      labels:{name:{eq:"Game Launch"}},
    },
    first:250,
    after:$after
  ){
    nodes{ id title url }
    pageInfo{ hasNextPage endCursor }
  }
}"""
    hdr = {"Authorization": api_key, "Content-Type": "application/json"}
    after = None; dup: dict[str, list[str]] = {}
    while True:
        try:
            resp = requests.post(
                LINEAR_URL,
                json={"query": query, "variables": {"after": after}},
                headers=hdr, timeout=30
            )
            if resp is None:   # shouldn’t happen, but guard anyway
                break
            resp = resp.json()
        except requests.exceptions.RequestException as e:
            st.warning(f"Linear request failed: {e}")
            return dup
        if resp.get("errors"):
            st.warning("Linear error while building duplicate map:\n"
                       + json.dumps(resp["errors"], indent=2))
            return dup
        data = resp.get("data", {}).get("issues", {})
        for n in data.get("nodes", []):
            dup.setdefault(_clean(base_of(n["title"])), []).append(n["url"])
        pg = data.get("pageInfo", {})
        if not pg.get("hasNextPage"): break
        after = pg.get("endCursor")
    return dup

# ───────────────────────────────
#  PROVIDER & USER-KEY HELPERS
# ───────────────────────────────
def safe_nodes(resp: dict) -> list[dict]:
    if "errors" in resp and resp["errors"]:
        st.error("Linear API error:\n" + json.dumps(resp["errors"], indent=2))
        return []
    return resp.get("data", {}).get("issues", {}).get("nodes", [])

def load_user_keys():
    rows = sheets.spreadsheets().values().get(
        spreadsheetId=SHEET_ID, range=USER_KEY_TAB).execute().get("values", [])
    return {
        r[0].strip().lower(): {"key": r[1].strip(), "col": r[2].strip()}
        for r in rows[1:] if len(r) >= 3 and r[0].strip()
    }

def save_user_key(name: str, api_key: str, col: str):
    rows = sheets.spreadsheets().values().get(
        spreadsheetId=SHEET_ID, range=USER_KEY_TAB).execute().get("values", [])
    header, data = rows[0], rows[1:]
    idx = next((i for i, r in enumerate(data) if r[0].lower() == name), None)
    body = {"values": [[name, api_key, col]]}
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
    if not rows: return {}
    hdr = [h.strip().lower() for h in rows[0]]
    i_name, i_url  = hdr.index("provider name"), hdr.index("url")
    i_user, i_pass = hdr.index("username"), hdr.index("password")
    i_al = hdr.index("aliases") if "aliases" in hdr else None
    out = {}
    for r in rows[1:]:
        if len(r) <= i_name or not r[i_name].strip(): continue
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
#  SIDEBAR
# ───────────────────────────────
st.sidebar.title("Navigation")
view = st.sidebar.radio("Go to", ["Account", "Fetch Games", "Thumbnails"])

# ───────────────────────────────
#  ACCOUNT TAB
# ───────────────────────────────
if view == "Account":
    st.header("Account / credentials")
    users = load_user_keys()
    opt   = list(users.keys()) + ["<new designer>"]
    sel   = st.selectbox("Designer", opt)
    designer = st.text_input("Designer handle", value="" if sel == "<new designer>" else sel)

    prev = users.get(designer.lower(), {})
    api_key_in = st.text_input("Linear API key", type="password", value=prev.get("key", ""))
    col_in     = st.text_input("Column / State", value=prev.get("col", ""))

    if st.button("Save / Update"):
        if not designer or not api_key_in or not col_in:
            st.error("All fields required.")
        else:
            save_user_key(designer.lower(), api_key_in.strip(), col_in.strip())
            st.session_state["linear_key"]   = api_key_in.strip()
            st.session_state["linear_state"] = col_in.strip()
            st.success("Saved ✔ – reloads with your creds")
            st.experimental_rerun()
    st.stop()

# guard creds
if "linear_key" not in st.session_state or "linear_state" not in st.session_state:
    st.error("Go to **Account** first.")
    st.stop()

linear_key   = st.session_state["linear_key"]
linear_state = st.session_state["linear_state"]

# ───────────────────────────────
#  FETCH GAMES
# ───────────────────────────────
if view == "Fetch Games":
    st.header("📋 Fetch game launches")
    dt = st.date_input("Date", datetime.today())
    if st.button("Fetch"):
        with st.spinner("Building duplicate map…"):
            dup_map = build_duplicate_map(linear_key)

        with st.spinner("Fetching selected date…"):
            q = {"query": f"""query {{
  issues(filter:{{
    dueDate:{{eq:"{dt:%Y-%m-%d}"}},
    labels:{{name:{{eq:"Game Launch"}}}},
    state:{{name:{{eq:"{linear_state}"}}}}
  }}, first:250){{nodes{{id title}}}}
}}"""}  # noqa
            day_nodes = safe_nodes(
                requests.post(LINEAR_URL, json=q,
                              headers={"Authorization": linear_key,
                                       "Content-Type": "application/json"},
                              timeout=30).json()
            )

        provs = get_provider_credentials()
        if not day_nodes:
            st.info("None found for that date.")

        for n in day_nodes:
            key      = _clean(base_of(n["title"]))
            dup_urls = [u for u in dup_map.get(key, []) if not u.endswith(n["id"])]
            badge    = f" **🚩 duplicate** ([existing]({dup_urls[0]}))" if dup_urls else ""
            st.subheader(n["title"] + badge)
            st.markdown(f"[Open in Linear](https://linear.app/issue/{n['id']})")

            # provider info
            prov_tags = [p.strip().lower() for p in n["title"].split(" - ")[-1].split("/")]
            shown = set()
            for tag in prov_tags[::-1]:
                for main, info in provs.items():
                    if tag == main or tag in info["aliases"]:
                        if main in shown: continue
                        if info["url"]: st.markdown(f"[Provider link]({info['url']})")
                        if info["username"] or info["password"]:
                            st.code(f"User: {info['username']}\nPass: {info['password']}")
                        shown.add(main); break
            if not shown:
                st.warning("No provider info: " + ", ".join(prov_tags))
            st.divider()
    st.stop()

# ───────────────────────────────
#  THUMBNAILS TAB  (portrait-only)
# ───────────────────────────────
if view == "Thumbnails":
    st.header("🖼️ Create & download bundle")
    if "issue_map" not in st.session_state:
        st.error("Fetch games first.")
        st.stop()

    title = st.selectbox("Issue", list(st.session_state["issue_map"].keys()))
    issue_id = st.session_state["issue_map"][title]
    st.markdown(f"[Open in Linear](https://linear.app/issue/{issue_id})")

    game_name = st.text_input("Game name", placeholder=title)
    uploads   = st.file_uploader("portrait.jpg & box.jpg",
                                 type=["jpg","jpeg","png"], accept_multiple_files=True)

    if st.button("Process"):
        spec = {"box":(".jpg",False), "portrait":(".jpg",True)}
        bucket = {k:f for f in uploads or [] for k in spec if k in f.name.lower()}
        if len(bucket)!=2:
            st.error("Both files required."); st.stop()

        folders = {"Box":{}, "Portrait":{}}
        for role,upl in bucket.items():
            ext,compress = spec[role]; data=upl.read()
            if compress: data = tinify.from_buffer(data).to_buffer()
            folders[role.capitalize()][f"{game_name}{ext}"]=data
            if role=="portrait":
                buf=io.BytesIO()
                Image.open(io.BytesIO(data)).save(buf, format="WEBP")
                folders["Portrait"][f"{game_name}.webp"]=buf.getvalue()

        pzip = io.BytesIO()
        with zipfile.ZipFile(pzip,"w",zipfile.ZIP_DEFLATED) as z:
            for fn,bl in folders["Portrait"].items(): z.writestr(fn,bl)
        pzip.seek(0)

        bundle=io.BytesIO()
        with zipfile.ZipFile(bundle,"w",zipfile.ZIP_DEFLATED) as z:
            for fold,files in folders.items():
                for fn,bl in files.items():
                    z.writestr(f"{fold}/{fn}",bl)
            z.writestr("portrait.zip", pzip.read())
        bundle.seek(0)

        st.download_button("⬇️ Download bundle",
                           bundle, file_name=f"{game_name or 'game'}_bundle.zip",
                           mime="application/zip")
        st.success("✅ Bundle ready!")
