import io, zipfile, requests, base64, json
from datetime import datetime, timedelta
from pathlib import Path

import streamlit as st
from PIL import Image
import tinify
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

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
    operations = {
        "query": """
        mutation($file: Upload!, $issueId: String!) {
          fileUpload(input:{
            entityType: ISSUE,
            entityId: $issueId,
            file: $file
          }) {
            url
          }
        }""",
        "variables": {"file": None, "issueId": issue_id}
    }
    file_map = {"0": ["variables.file"]}
    multipart_data = {
        "operations": json.dumps(operations),
        "map":        json.dumps(file_map)
    }
    files = {"0": (filename, io.BytesIO(data))}
    headers = {"Authorization": st.session_state["linear_key"]}
    resp = requests.post(LINEAR_URL, data=multipart_data, files=files, headers=headers)
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
    st.session_state.setdefault("linear_key", "")
    st.session_state.setdefault("linear_state", "")
    st.session_state["linear_key"] = st.text_input(
        "Linear API Key", type="password", value=st.session_state["linear_key"]
    )
    st.session_state["linear_state"] = st.text_input(
        "Linear Column/State", value=st.session_state["linear_state"]
    )
    st.stop()

# ensure credentials exist
if "linear_key" not in st.session_state or not st.session_state["linear_key"] \
   or "linear_state" not in st.session_state or not st.session_state["linear_state"]:
    st.error("Please set your API key and state in Account Details.")
    st.stop()

# ─── 6) Game List Retriever ──────────────────────────────────
if section == "Game List Retriever":
    st.header("📋 Game List Retriever")

    date_choice = st.selectbox("Select date", ["Today", "Tomorrow"])
    fetch_date = datetime.today() if date_choice == "Today" else datetime.today() + timedelta(days=1)
    date_str = fetch_date.strftime("%Y-%m-%d")

    if st.button(f"Fetch launches for {date_choice} ({date_str})"):
        gql = {
            "query": f"""
            query {{
              issues(filter:{{
                dueDate:{{eq:"{date_str}"}},
                labels:{{name:{{eq:"Game Launch"}}}},
                state:{{name:{{eq:"{st.session_state['linear_state']}"}}}}
              }}){{nodes{{id title}}}}
            }}"""
        }
        resp = requests.post(
            LINEAR_URL, 
            headers={"Authorization": st.session_state["linear_key"], "Content-Type": "application/json"},
            json=gql
        )
        resp.raise_for_status()
        nodes = resp.json().get("data", {}).get("issues", {}).get("nodes", [])
        issue_map = {n["title"]: n["id"] for n in nodes}
        st.session_state["issue_map"] = issue_map
        if nodes:
            st.success(f"Fetched {len(nodes)} launch(es).")
        else:
            st.info("No launches found.")

    if "issue_map" in st.session_state and st.session_state["issue_map"]:
        st.write("### Available launches:")
        for title in st.session_state["issue_map"]:
            st.write("- " + title)
    st.stop()

# ─── 7) Thumbnail & Upload ───────────────────────────────────
if section == "Thumbnail & Upload":
    st.header("🖼️ Thumbnail Processor & Linear Upload")

    if "issue_map" not in st.session_state or not st.session_state["issue_map"]:
        st.error("No issues fetched. Go to Game List Retriever first.")
        st.stop()

    chosen_title = st.selectbox("Choose a game to process", list(st.session_state["issue_map"].keys()))
    issue_id = st.session_state["issue_map"][chosen_title]

    game = st.text_input("Game name", value=chosen_title)
    uploads = st.file_uploader(
        "Upload portrait.jpg, landscape.png, box.jpg",
        type=["jpg","jpeg","png"], accept_multiple_files=True
    )

    if st.button("Process & Package"):
        spec = {
            "box": (".jpg", False),
            "portrait": (".jpg", True),
            "landscape": (".png", True),
        }
        bucket = {}
        for f in uploads:
            for k in spec:
                if k in f.name.lower():
                    bucket[k] = f
        if len(bucket) != 3:
            st.error("Please upload box, portrait, and landscape files.")
            st.stop()

        # build folders
        folders, zip_buf = {"Portrait":{}, "Landscape":{}}, {}
        # Box folder (no zip)
        box_data = bucket["box"].read()
        folders.setdefault("Box", {})[f"{game}.jpg"] = box_data

        # portrait & landscape
        for key in ("portrait", "landscape"):
            ext, compress = spec[key]
            data = bucket[key].read()
            if compress:
                data = tinify.from_buffer(data).to_buffer()
            folder = key.capitalize()
            folders.setdefault(folder, {})[f"{game}{ext}"] = data
            # webp
            img = Image.open(io.BytesIO(data))
            buf = io.BytesIO(); img.save(buf, format="WEBP")
            folders[folder][f"{game}.webp"] = buf.getvalue()

        # create sub-zip buffers
        subzips = {}
        for fold in ("Portrait", "Landscape"):
            buf = io.BytesIO()
            z = zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED)
            for name, blob in folders[fold].items():
                z.writestr(name, blob)
            z.close(); buf.seek(0)
            subzips[fold] = buf.read()

        # store in session
        st.session_state["portrait_zip"]  = subzips["Portrait"]
        st.session_state["landscape_zip"] = subzips["Landscape"]

        st.success("✅ Bundles ready!")

    if "portrait_zip" in st.session_state and "landscape_zip" in st.session_state:
        if st.button("Upload All to Linear"):
            with st.spinner("Uploading to Linear..."):
                p_url = upload_file_to_linear(issue_id, f"{game}_portrait.zip", st.session_state["portrait_zip"])
                l_url = upload_file_to_linear(issue_id, f"{game}_landscape.zip", st.session_state["landscape_zip"])
                # post a comment with the portrait preview
                comment_md = f"### Portrait Preview\n\n![]({p_url.replace('.zip','.jpg')})"
                post_comment(issue_id, comment_md)
            st.success("🎉 Uploaded ZIPs and posted comment!")

