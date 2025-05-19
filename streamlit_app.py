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
raw_sa = base64.b64decode(st.secrets["GC_SERVICE_KEY_B64"])
sa_info = json.loads(raw_sa)
creds = Credentials.from_service_account_info(sa_info)
sheets = build("sheets", "v4", credentials=creds)

SPREADSHEET_ID = "1-kEERrIfKvRBUSyEg3ibJnmgZktASdd9vaQhpDPOGtA"
RANGE_NAME = "Sheet1!A:D"

def get_provider_credentials():
    rows = (
        sheets.spreadsheets()
        .values()
        .get(spreadsheetId=SPREADSHEET_ID, range=RANGE_NAME)
        .execute()
        .get("values", [])
    )
    providers = {}
    for r in rows[1:]:
        if len(r) >= 2:
            key = r[0].strip().lower()
            providers[key] = {
                "url": r[1].strip(),
                "username": r[2].strip() if len(r) > 2 else "",
                "password": r[3].strip() if len(r) > 3 else "",
            }
    return providers

# ─── 2) TinyPNG ──────────────────────────────────────────────
tinify.key = st.secrets["TINIFY_API_KEY"]

# ─── 3) Linear helpers ──────────────────────────────────────
LINEAR_URL = "https://api.linear.app/graphql"

def upload_file_to_linear(issue_id: str, filename: str, data: bytes) -> str:
    operations = json.dumps(
        {
            "query": """
            mutation($file: Upload!, $issueId: String!) {
              fileUpload(input:{entityType:ISSUE,entityId:$issueId,file:$file}){url}
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
        try:
            st.error(resp.json())
        except Exception:
            st.error(resp.text)
        resp.raise_for_status()
    return resp.json()["data"]["fileUpload"]["url"]

def post_comment(issue_id: str, body: str):
    mutation = """
    mutation($input:IssueCommentCreateInput!){issueCommentCreate(input:$input){success}}
    """
    variables = {"input": {"issueId": issue_id, "body": body}}
    headers = {
        "Authorization": st.session_state["linear_key"],
        "Content-Type": "application/json",
    }
    resp = requests.post(LINEAR_URL, json={"query": mutation, "variables": variables}, headers=headers)
    resp.raise_for_status()
    return resp.json()["data"]["issueCommentCreate"]["success"]

# ─── 4) Sidebar nav ─────────────────────────────────────────
st.sidebar.title("Navigation")
section = st.sidebar.radio("Go to", ["Account Details", "Game List Retriever", "Thumbnail & Upload"])

# ─── 5) Account Details ─────────────────────────────────────
if section == "Account Details":
    st.header("🔧 Account Details")
    key_temp = st.text_input("Linear API Key", type="password", value=st.session_state.get("linear_key", ""))
    col_temp = st.text_input("Linear Column/State", value=st.session_state.get("linear_state", ""))
    if st.button("Save"):
        st.session_state["linear_key"] = key_temp.strip()
        st.session_state["linear_state"] = col_temp.strip()
        st.success("Saved!")
    st.stop()

if not st.session_state.get("linear_key") or not st.session_state.get("linear_state"):
    st.error("Set API key & column in Account Details first.")
    st.stop()

# ─── 6) Game List Retriever ─────────────────────────────────
if section == "Game List Retriever":
    st.header("📋 Game List Retriever")
    date_choice = st.selectbox("Date", ["Today", "Tomorrow"])
    target = datetime.today() if date_choice == "Today" else datetime.today() + timedelta(days=1)
    date_str = target.strftime("%Y-%m-%d")
    if st.button("Fetch launches"):
        q = {
            "query": f"""
            query{{issues(filter:{{dueDate:{{eq:\"{date_str}\"}},labels:{{name:{{eq:\"Game Launch\"}}}},state:{{name:{{eq:\"{st.session_state['linear_state']}\"}}}}}}){{nodes{{id title}}}}}}"""
        }
        r = requests.post(LINEAR_URL, headers={"Authorization": st.session_state["linear_key"], "Content-Type": "application/json"}, json=q)
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

# ─── 7) Thumbnail & Upload ──────────────────────────────────
if section == "Thumbnail & Upload":
    st.header("🖼️ Thumbnail & Upload")
    if "issue_map" not in st.session_state:
        st.error("Fetch launches first.")
        st.stop()

    title = st.selectbox("Issue", list(st.session_state["issue_map"].keys()))
    issue_id = st.session_state["issue_map"][title]
    game = st.text_input("Game name", placeholder=title)
    uploads = st.file_uploader("portrait.jpg, landscape.png, box.jpg", type=["jpg","jpeg","png"], accept_multiple_files=True)

    if st.button("Process"):
        spec = {"box": (".jpg", False), "portrait": (".jpg", True), "landscape": (".png", True)}
        bucket = {k: f for f in uploads or [] for k in spec if k in f.name.lower()}
        if len(bucket) != 3:
            st.error("Upload 3 files (portrait, landscape, box)")
            st.stop()
        folders = {"Box": {}, "Portrait": {}, "Landscape": {}}
        for k, f in bucket.items():
            ext, comp = spec[k]
            data = f.read()
            if comp:
                data = tinify.from_buffer(data).to_buffer()
            fold = k.capitalize()
            folders[fold][f"{game}{ext}"] = data
            if k != "box":
                buf = io.BytesIO(); Image.open(io.BytesIO(data)).save(buf, format="WEBP")
                folders[fold][f"{game}.webp"] = buf.getvalue()
        subzip = {}
        for fold in ("Portrait", "Landscape"):
            buf = io.BytesIO()
                        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
                for name, blob in folders[fold].items():
                    z.writestr(name, blob)
            buf.seek(0)
                        subzip[fold] = buf.read()

        # store zips in session for later upload
        st.session_state["portrait_zip"] = subzip["Portrait"]
        st.session_state["landscape_zip"] = subzip["Landscape"]
                st.success("Bundles ready – upload when ready!")

    if st.session_state.get("portrait_zip") and st.session_state.get("landscape_zip"):
        if st.button("Upload All to Linear"):
            with st.spinner("Uploading to Linear..."):
                p_url = upload_file_to_linear(issue_id, f"{game}_portrait.zip", st.session_state["portrait_zip"])
                l_url = upload_file_to_linear(issue_id, f"{game}_landscape.zip", st.session_state["landscape_zip"])
                comment = f"### Portrait Preview

![]({p_url.replace('.zip', '.jpg')})"
                post_comment(issue_id, comment)
            st.success("🎉 Uploaded and commented!")
