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

    resp = requests.post(LINEAR_URL, data=multipart_data, headers=headers)

    if resp.status_code != 200:
        try:
            st.error(f"❌ Failed to upload '{filename}': {resp.json()}")
        except Exception:
            st.error(resp.text)
        resp.raise_for_status()

    return resp.json()["data"]["fileUpload"]["url"]

st.sidebar.title("Navigation")
section = st.sidebar.radio("Go to", ["Account Details", "Game List Retriever", "Thumbnail & Upload"])
