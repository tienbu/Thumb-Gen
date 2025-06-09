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


def build_duplicate_map(api_key: str, allowed_states: list[str]) -> dict[str, list[str]]:
    """Return {clean_base: [url,…]} for open Game‑Launch tickets whose column name is in allowed_states."""

    CLOSED_KEYWORDS = ["archive", "cancel", "complete"]
    allow = [s.lower() for s in allowed_states]

    query = """
query ($after:String){
  issues(
    filter:{ labels:{name:{eq:\"Game Launch\"}} },
    first:250,
    after:$after
  ){
    nodes{ id title url state{ name } }
    pageInfo{ hasNextPage endCursor }
  }
}"""

    headers = {"Authorization": api_key, "Content-Type": "application/json"}
    after   = None
    dup: dict[str, list[str]] = {}

    while True:
        try:
            resp = requests.post(LINEAR_URL, json={"query": query, "variables": {"after": after}}, headers=headers, timeout=30)
            if resp is None:
                break
            resp = resp.json()
        except requests.exceptions.RequestException as e:
            st.warning(f"Linear request failed while building duplicate map: {e}")
            return dup
        if resp.get("errors"):
            st.warning("Linear error while building duplicate map:\n" + json.dumps(resp["errors"], indent=2))
            return dup

        data = resp.get("data", {}).get("issues", {})
        for n in data.get("nodes", []):
            state_name = n.get("state", {}).get("name", "").lower()
            if any(kw in state_name for kw in CLOSED_KEYWORDS):
                continue
            if state_name not in allow:
                continue
            dup.setdefault(_clean(base_of(n["title"])), []).append(n["url"])

        page = data.get("pageInfo", {})
        if not page.get("hasNextPage"):
            break
        after = page.get("endCursor")

    return dup

# ───────────────────────────────
#  PROVIDER & USER‑KEY HELPERS
# ───────────────────────────────

def safe_nodes(resp: dict) -> list[dict]:
    if resp.get("errors"):
        st.error("Linear error:\n" + json.dumps(resp["errors"], indent=2))
        return []
    return resp.get("data", {}).get("issues", {}).get("nodes", [])


def load_user_keys():
    rows = sheets.spreadsheets().values().get(spreadsheetId=SHEET_ID, range=USER_KEY_TAB).execute().get("values", [])
    return {r[0].lower(): {"key": r[1], "col": r[2]} for r in rows[1:] if len(r) >= 3}


def save_user_key(name: str, key: str, col: str):
    rows = sheets.spreadsheets().values().get(spreadsheetId=SHEET_ID, range=USER_KEY_TAB).execute().get("values", [])
    header, data = rows[0], rows[1:]
    idx = next((i for i, r in enumerate(data) if r[0].lower() == name), None)
    body = {"values": [[name, key, col]]}
    if idx is None:
        sheets.spreadsheets().values().append(spreadsheetId=SHEET_ID, range=USER_KEY_TAB, valueInputOption="RAW", body=body).execute()
    else:
        rng = f"user_keys!A{idx+2}:C{idx+2}"
        sheets.spreadsheets().values().update(spreadsheetId=SHEET_ID, range=rng, valueInputOption="RAW", body=body).execute()


def get_provider_credentials():
    rows = sheets.spreadsheets().values().get(spreadsheetId=SHEET_ID, range=PROV_RANGE).execute().get("values", [])
    if not rows:
        return {}
    hdr = [h.lower().strip() for h in rows[0]]
    ix = {c: hdr.index(c) for c in ["provider name", "url", "username", "password"]}
    i_al = hdr.index("aliases") if "aliases" in hdr else None
    out = {}
    for r in rows[1:]:
        name = r[ix["provider name"]].lower().strip() if len(r) > ix["provider name"] else ""
        if not name:
            continue
        aliases = []
        if i_al is not None and len(r) > i_al and r[i_al].strip():
            aliases = [a.strip().lower() for a in r[i_al].split(",")]
        out[name] = {
            "url":      r[ix["url"]]      if len(r) > ix["url"]      else "",
            "username": r[ix["username"]] if len(r) > ix["username"] else "",
            "password": r[ix["password"]] if len(r) > ix["password"] else "",
            "aliases":  aliases,
        }
    return out

# ───────────────────────────────
#  SIDEBAR & TAB NAVIGATION
# ───────────────────────────────
st.sidebar.title("Navigation")
view = st.sidebar.radio("Go to", ["Account", "Fetch Games", "Thumbnails"])

# ───────────────────────────────
#  ACCOUNT TAB
# ───────────────────────────────
if view == "Account":
    st.header("Account / credentials")
    users = load_user_keys()
    sel   = st.selectbox("Designer", list(users.keys()) + ["<new designer>"])
    designer = st.text_input("Designer handle", "" if sel == "<new designer>" else sel)
    prev = users.get(designer.lower(), {})
    api_key_in = st.text_input("Linear API key", type="password", value=prev.get("key", ""))
    col_in     = st.text_input("Column / State", value=prev.get("col", ""))
    if st.button("Save / Update"):
        if designer and api_key_in and col_in:
            save_user_key(designer.lower(), api_key_in.strip(), col_in.strip())
            st.session_state["linear_key"]   = api_key_in.strip()
            st.session_state["linear_state"] = col_in.strip()
            st.success("Saved. Reloading …")
            st.experimental_rerun()
        else:
            st.error("All fields required.")
    st.stop()

# ---- guard creds ----
if "linear_key" not in st.session_state or "linear_state" not in st.session_state:
    st.warning("Set credentials in *Account* tab first.")
    st.stop()

linear_key   = st.session_state["linear_key"]
linear_state = st.session_state["linear_state"]

ACTIVE_COLUMNS = [linear_state.lower(), "games", "games done"]  # tweak names if needed

# ───────────────────────────────
