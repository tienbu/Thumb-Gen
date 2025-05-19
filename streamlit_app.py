import io, zipfile, requests, base64, json
from datetime import datetime, timedelta
from pathlib import Path

import streamlit as st
from PIL import Image
import tinify
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from requests_toolbelt.multipart.encoder import MultipartEncoder

# ─── Page config ─────────────────────────────────────────────
st.set_page_config(page_title="Game Tools", page_icon="🎮", layout="wide")

# ─── 1) Load Google service-account from Base64 secret ───────
raw_sa  = base64.b64decode(st.secrets["GC_SERVICE_KEY_B64"])
sa_info = json.loads(raw_sa)
creds   = Credentials.from_service_account_info(sa_info)
sheets  = build("sheets", "v4", credentials=creds)

SPREADSHEET_ID = "1-kEERrIfKvRBUSyEg3ibJnmgZktASdd9vaQhpDPOGtA"
RANGE_NAME     = "Sheet1!A:D"

def get_provider_credentials():
    rows = sheets.spreadsheets().values() \
        .get(spreadsheetId=SPREADSHEET_ID, range=RANGE_NAME) \
        .execute().get("values", [])
    providers = {}
    for r in rows[1:]:
        if len(r) >= 2:
            key = r[0].strip().lower()
            providers[key] = {
                "url":      r[1].strip(),
                "username": r[2].strip() if len(r) > 2 else "",
                "password": r[3].strip() if len(r) > 3 else ""
            }
    return providers

# ─── 2) TinyPNG key ───────────────────────────────────────────
tinify.key = st.secrets["TINIFY_API_KEY"]

# ─── 3) Linear upload/post helpers ───────────────────────────
LINEAR_URL = "https://api.linear.app/graphql"

def upload_file_to_linear(issue_id: str, filename: str, data: bytes) -> str:
    operations = json.dumps({
        "query": """
        mutation($file: Upload!, $issueId: String!) {
          fileUpload(input: {
            entityType: ISSUE,
            entityId: $issueId,
            file: $file
          }) {
            url
          }
        }
        """,
        "variables": {"file": None, "issueId": issue_id}
    })
    file_map = json.dumps({"0": ["variables.file"]})

    multipart_data = MultipartEncoder(
        fields={
            "operations": operations,
            "map": file_map,
            "0": (filename, data, "application/zip")
        }
    )
    headers = {
        "Authorization": st.session_state["linear_key"],
        "Content-Type": multipart_data.content_type,
        "x-apollo-operation-name": "fileUpload"
    }
    resp = requests.post(LINEAR_URL, data=multipart_data, headers=headers, timeout=30)
    if resp.status_code != 200:
        try:
            st.error(resp.json())
        except Exception:
            st.error(resp.text)
        resp.raise_for_status()
    return resp.json()["data"]["fileUpload"]["url"]

def post_comment(issue_id: str, body: str):
    mutation = """
    mutation($input: IssueCommentCreateInput!) {
      issueCommentCreate(input: $input) {
        success
      }
    }"""
    variables = {"input": {"issueId": issue_id, "body": body}}
    headers = {"Authorization": st.session_state["linear_key"], "Content-Type": "application/json"}
    resp = requests.post(LINEAR_URL, json={"query": mutation, "variables": variables}, headers=headers)
    resp.raise_for_status()
    return resp.json()["data"]["issueCommentCreate"]["success"]

# ─── 4) Sidebar navigation ───────────────────────────────────
st.sidebar.title("Navigation")
section = st.sidebar.radio("Go to", ["Account Details", "Game List Retriever", "Thumbnail & Upload"])

# ─── 5) Account Details ──────────────────────────────────────
if section == "Account Details":
    st.header("🔧 Account Details")
    key_temp = st.text_input("Linear API Key", type="password", value=st.session_state.get("linear_key", ""))
    state_temp = st.text_input("Linear Column/State", value=st.session_state.get("linear_state", ""))
    if st.button("Save"):
        st.session_state["linear_key"] = key_temp.strip()
        st.session_state["linear_state"] = state_temp.strip()
        st.success("Account details saved.")
    st.stop()

# Ensure credentials
if not st.session_state.get("linear_key") or not st.session_state.get("linear_state"):
    st.error("Please save API key and column first.")
    st.stop()

# ─── 6) Game List Retriever ──────────────────────────────────
if section == "Game List Retriever":
    st.header("📋 Game List Retriever")
    date_choice = st.selectbox("Select date", ["Today", "Tomorrow"])
    fetch_date = datetime.today() if date_choice == "Today" else datetime.today() + timedelta(days=1)
    date_str = fetch_date.strftime("%Y-%m-%d")
    if st.button("Fetch launches"):
        query = {
            "query": f"""
            query {{
              issues(filter:{{dueDate:{{eq:\"{date_str}\"}}, labels:{{name:{{eq:\"Game Launch\"}}}}, state:{{name:{{eq:\"{st.session_state['linear_state']}\"}}}}}}){{nodes{{id title}}}}
            }}"""
        }
        resp = requests.post(LINEAR_URL, headers={"Authorization": st.session_state["linear_key"],"Content-Type":"application/json"}, json=query)
        resp.raise_for_status()
        tasks = resp.json().get("data", {}).get("issues", {}).get("nodes", [])
        st.session_state["issue_map"] = {t["title"]: t["id"] for t in tasks}
        providers = get_provider_credentials()
        if not tasks:
            st.info("No launches.")
        for t in tasks:
            st.markdown(f"**{t['title']}**")
            prov = t['title'].split(" - ")[-1].strip().lower()
            match = next((providers[p] for p in providers if prov in p), None)
            if match:
                st.markdown(f"[Provider link]({match['url']})")
                st.write(f"User: {match['username']}  Pass: {match['password']}")
            st.divider()
    st.stop()

# ─── 7) Thumbnail & Upload ───────────────────────────────────
if section == "Thumbnail & Upload":
    st.header("🖼️ Thumbnail & Upload")
    if "issue_map" not in st.session_state:
        st.error("Fetch games first.")
        st.stop()

    title = st.selectbox("Select issue", list(st.session_state["issue_map"].keys()))
    issue_id = st.session_state["issue_map"][title]
    game = st.text_input("Game name", value="", placeholder=title)
    files = st.file_uploader("Upload portrait, landscape, box", type=["jpg","jpeg","png"], accept_multiple_files=True)

    if st.button("Process"):
        spec = {"box": (".jpg", False), "portrait": (".jpg", True), "landscape": (".png", True)}
        bucket = {k: f for f in (files or []) for k in spec if k in f.name.lower()}
        if len(bucket) != 3:
            st.error("Need portrait, landscape, box.")
            st.stop()
        folders, subz = {"Box":{},"Portrait":{},"Landscape":{}},{}
        for k,f in bucket.items():
            ext, comp = spec[k]
            data = f.read(); data = tinify.from_buffer(data).to_buffer() if comp else data
            fold=k.capitalize(); folders[fold][f"{game}{ext}"]=data
            if k!="box":
                buf=io.BytesIO(); Image.open(io.BytesIO(data)).save(buf,"WEBP"); folders[fold][f"{game}.webp"]=buf.getvalue()
        for fold in ("Portrait","Landscape"):
            b=io.BytesIO(); z=zipfile.ZipFile(b,"w",zipfile.ZIP_DEFLATED);
            [z.writestr(n,bl) for n,bl
