import io
import json
import zipfile
from datetime import datetime, timedelta

import requests
import streamlit as st
import tinify
from PIL import Image
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from requests_toolbelt.multipart.encoder import MultipartEncoder

# ──────────────────────────────────────────────────────────────
# Streamlit page setup
# ──────────────────────────────────────────────────────────────
st.set_page_config(page_title="Game Tools", page_icon="🎮", layout="wide")

# ──────────────────────────────────────────────────────────────
# Secrets & third‑party keys
# ──────────────────────────────────────────────────────────────
TINIFY_KEY = st.secrets["TINIFY_API_KEY"]
SA_B64     = st.secrets["GC_SERVICE_KEY_B64"]
LINEAR_URL = "https://api.linear.app/graphql"

tinify.key = TINIFY_KEY

# ──────────────────────────────────────────────────────────────
# Google Sheets helper
# ──────────────────────────────────────────────────────────────
SA_INFO = json.loads(io.BytesIO(base64.b64decode(SA_B64)).read())
creds   = Credentials.from_service_account_info(SA_INFO)
sheets  = build("sheets", "v4", credentials=creds)

SPREADSHEET_ID = "1-kEERrIfKvRBUSyEg3ibJnmgZktASdd9vaQhpDPOGtA"
RANGE          = "Sheet1!A:D"

def get_provider_credentials():
    rows = (
        sheets.spreadsheets()
        .values()
        .get(spreadsheetId=SPREADSHEET_ID, range=RANGE)
        .execute()
        .get("values", [])
    )
    out = {}
    for r in rows[1:]:
        if len(r) >= 2:
            key = r[0].strip().lower()
            out[key] = {
                "url": r[1].strip(),
                "username": r[2].strip() if len(r) > 2 else "",
                "password": r[3].strip() if len(r) > 3 else "",
            }
    return out

# ──────────────────────────────────────────────────────────────
# Linear helpers
# ──────────────────────────────────────────────────────────────

def upload_file_to_linear(issue_id: str, filename: str, data: bytes) -> str:
    """Upload ZIP to Linear and return the hosted URL."""
    operations = json.dumps(
        {
            "query": """
            mutation($file: Upload!, $issueId: String!) {
              fileUpload(
                input: { entityType: ISSUE, entityId: $issueId, file: $file }
              ) { url }
            }
            """,
            "variables": {"file": None, "issueId": issue_id},
        }
    )
    file_map = json.dumps({"0": ["variables.file"]})

    mp = MultipartEncoder(
        fields={
            "operations": operations,
            "map": file_map,
            "0": (filename, data, "application/zip"),
        }
    )

    headers = {
        "Authorization": st.session_state["linear_key"],
        "Content-Type": mp.content_type,
        "x-apollo-operation-name": "fileUpload",
    }
    resp = requests.post(LINEAR_URL, data=mp, headers=headers, timeout=30)
    if resp.status_code != 200:
        st.error(resp.text)
        resp.raise_for_status()
    return resp.json()["data"]["fileUpload"]["url"]

def post_comment(issue_id: str, body: str):
    mutation = """
    mutation($input: IssueCommentCreateInput!) {
      issueCommentCreate(input: $input) { success }
    }
    """
    variables = {"input": {"issueId": issue_id, "body": body}}
    headers = {
        "Authorization": st.session_state["linear_key"],
        "Content-Type": "application/json",
    }
    requests.post(LINEAR_URL, json={"query": mutation, "variables": variables}, headers=headers).raise_for_status()

# ──────────────────────────────────────────────────────────────
# Sidebar navigation
# ──────────────────────────────────────────────────────────────
st.sidebar.title("Navigation")
view = st.sidebar.radio("Go to", ["Account", "Fetch Games", "Thumbnails"])

# ──────────────────────────────────────────────────────────────
# 1) Account view
# ──────────────────────────────────────────────────────────────
if view == "Account":
    st.header("🔧 Account Details")
    key   = st.text_input("Linear API Key", type="password", value=st.session_state.get("linear_key", ""))
    state = st.text_input("Linear Column/State", value=st.session_state.get("linear_state", ""))
    if st.button("Save"):
        st.session_state["linear_key"] = key.strip()
        st.session_state["linear_state"] = state.strip()
        st.success("Saved!")
    st.stop()

# Guard: need API creds
if "linear_key" not in st.session_state or "linear_state" not in st.session_state:
    st.error("Set Linear credentials in Account tab first.")
    st.stop()

# ──────────────────────────────────────────────────────────────
# 2) Fetch Games view
# ──────────────────────────────────────────────────────────────
if view == "Fetch Games":
    st.header("📋 Today's / Tomorrow's Launches")
    choice = st.selectbox("Date", ["Today", "Tomorrow"])
    tgt     = datetime.today() if choice == "Today" else datetime.today() + timedelta(days=1)
    date_str = tgt.strftime("%Y-%m-%d")

    if st.button("Fetch"):
        query = {
            "query": f"""
            query {{
              issues(filter: {{
                dueDate: {{eq: \"{date_str}\"}},
                labels: {{name: {{eq: \"Game Launch\"}}}},
                state: {{name: {{eq: \"{st.session_state['linear_state']}\"}}}}
              }}) {{ nodes {{ id title }} }}
            }}"""
        }
        r = requests.post(LINEAR_URL, headers={"Authorization": st.session_state["linear_key"], "Content-Type": "application/json"}, json=query)
        r.raise_for_status()
        nodes = r.json()["data"]["issues"]["nodes"]
        st.session_state["issue_map"] = {n["title"]: n["id"] for n in nodes}

        provs = get_provider_credentials()
        if not nodes:
            st.info("No launches found.")
        for n in nodes:
            st.subheader(n["title"])
            prov_key = n["title"].split(" - ")[-1].strip().lower()
            match = next((provs[p] for p in provs if prov_key in p), None)
            if match:
                st.markdown(f"[Provider link]({match['url']})")
                st.code(f"User: {match['username']}\nPass: {match['password']}")
            st.divider()
    st.stop()

# ──────────────────────────────────────────────────────────────
# 3) Thumbnail view
# ──────────────────────────────────────────────────────────────
if view == "Thumbnails":
    st.header("🖼️ Create & Upload Thumbnails")

    if "issue_map" not in st.session_state:
        st.error("Fetch games first.")
        st.stop()

    issue_title = st.selectbox("Select issue", list(st.session_state["issue_map"].keys()))
    issue_id    = st.session_state["issue_map"][issue_title]

    game_name   = st.text_input("Game name", placeholder=issue_title)
    uploaded    = st.file_uploader("portrait.jpg, landscape.png, box.jpg", type=["jpg", "jpeg", "png"], accept_multiple_files=True)

    if st.button("Process"):
        spec = {"box": (".jpg", False), "portrait": (".jpg", True), "landscape": (".png", True)}
        files = {k: f for f in uploaded or [] for k in spec if k in f.name.lower()}
        if len(files) != 3:
            st.error("Please upload portrait, landscape, box.")
            st.stop()

        folders = {"Box": {}, "Portrait": {}, "Landscape": {}}
        for k, f in files.items():
            ext, comp = spec[k]
            data = f.read()
            if comp:
                data = tinify.from_buffer(data).to_buffer()
            fold = k.capitalize()
            folders[fold][f"{game
