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
    """Fetch open Game‑Launch tickets in *allowed* columns once, build {clean_base:[url…]}."""

    CLOSED_KEYWORDS = ["archive", "cancel", "complete"]  # we keep "done" allowed now

    query = """
query ($after:String){
  issues(
    filter:{ labels:{name:{eq:"Game Launch"}} },
    first:250,
    after:$after
  ){
    nodes{ id title url state{ name } }
    pageInfo{ hasNextPage endCursor }
  }
}"""
    hdr = {"Authorization": api_key, "Content-Type": "application/json"}
    after = None; dup: dict[str, list[str]] = {}
    allow = [s.lower() for s in allowed_states]
    while True:
        try:
            resp = requests.post(
                LINEAR_URL,
                json={"query": query, "variables": {"after": after}},
                headers=hdr, timeout=30
            )
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
                continue  # skip archived/cancelled etc.
            if state_name not in allow:
                continue  # outside target columns
            dup.setdefault(_clean(base_of(n["title"])), []).append(n["url"])

        pg = data.get("pageInfo", {})
        if not pg.get("hasNextPage"):
            break
        after = pg.get("endCursor")
    return dup

# ───────────────────────────────
#  (Provider, user‑key helpers unchanged below)
# ───────────────────────────────
# [rest of code unchanged – Fetch Games will pass allowed_states]
