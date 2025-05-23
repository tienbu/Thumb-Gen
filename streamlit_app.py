import io, json, base64, zipfile, requests
from datetime import datetime, timedelta

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

tinify.key = TINIFY_KEY

# ───────────────────────────────
# Google Sheets helper
# ───────────────────────────────
SA_INFO = json.loads(base64.b64decode(SERVICE_B64))
creds   = Credentials.from_service_account_info(SA_INFO)
sheets  = build("sheets", "v4", credentials=creds)
SHEET_ID = "1-kEERrIfKvRBUSyEg3ibJnmgZktASdd9vaQhpDPOGtA"
RANGE    = "Sheet1!A:D"

def get_provider_credentials():
    rows = sheets.spreadsheets().values().get(spreadsheetId=SHEET_ID, range=RANGE).execute().get("values", [])
    out  = {}
    for r in rows[1:]:
        if len(r) >= 2:
            key = r[0].strip().lower()
            out[key] = {
                "url":      r[1].strip(),
                "username": r[2].strip() if len(r) > 2 else "",
                "password": r[3].strip() if len(r) > 3 else "",
            }
    return out

# ───────────────────────────────
# Linear helpers (official two‑step upload)
# ───────────────────────────────

def upload_file_to_linear(issue_id: str, fname: str, data: bytes) -> str:
    """Upload a file to Linear using the pre‑signed URL flow and return the assetUrl."""
    meta_query = """
    mutation($input: FileUploadInput!) {
      fileUpload(input: $input) {
        uploadUrl
        assetUrl
        headers { name value }
      }
    }
    """
    variables = {
        "input": {
            "issueId": issue_id,
            "fileName": fname,
            "contentType": "application/zip",
            "size": len(data),
        }
    }
    meta = requests.post(
        LINEAR_URL,
        json={"query": meta_query, "variables": variables},
        headers={"Authorization": st.session_state["linear_key"], "Content-Type": "application/json"},
        timeout=20,
    )
    meta.raise_for_status()
    info = meta.json()["data"]["fileUpload"]

    # PUT file bytes to presigned URL
    put_headers = {h["name"]: h["value"] for h in info["headers"]}
    requests.put(info["uploadUrl"], data=data, headers=put_headers, timeout=60).raise_for_status()
    return info["assetUrl"]

def post_comment(issue_id: str, body: str):
    mutation = "mutation($input:IssueCommentCreateInput!){issueCommentCreate(input:$input){success}}"
    vars = {"input": {"issueId": issue_id, "body": body}}
    headers = {"Authorization": st.session_state["linear_key"], "Content-Type": "application/json"}
    requests.post(LINEAR_URL, json={"query": mutation, "variables": vars}, headers=headers).raise_for_status()

# ───────────────────────────────
# Sidebar nav
# ───────────────────────────────
st.sidebar.title("Navigation")
view = st.sidebar.radio("Go to", ["Account", "Fetch Games", "Thumbnails"])

# ───────────────────────────────
# Account view
# ───────────────────────────────
if view == "Account":
    st.header("🔧 Account Details")
    key   = st.text_input("Linear API Key", type="password", value=st.session_state.get("linear_key", ""))
    state = st.text_input("Linear Column / State", value=st.session_state.get("linear_state", ""))
    if st.button("Save"):
        st.session_state["linear_key"] = key.strip()
        st.session_state["linear_state"] = state.strip()
        st.success("Saved!")
    st.stop()

# Guard for creds
if "linear_key" not in st.session_state or "linear_state" not in st.session_state:
    st.error("Set Linear credentials in Account tab first.")
    st.stop()

# ───────────────────────────────
# Fetch Games view
# ───────────────────────────────
if view == "Fetch Games":
    st.header("📋 Fetch Game Launches")
    choice = st.selectbox("Date", ["Today", "Tomorrow"])
    target = datetime.today() if choice == "Today" else datetime.today() + timedelta(days=1)
    date_str = target.strftime("%Y-%m-%d")

    if st.button("Fetch"):
        query = {
            "query": f"""query{{issues(filter:{{dueDate:{{eq:\"{date_str}\"}},labels:{{name:{{eq:\"Game Launch\"}}}},state:{{name:{{eq:\"{st.session_state['linear_state']}\"}}}}}}){{nodes{{id title}}}}}}"""
        }
        r = requests.post(LINEAR_URL, headers={"Authorization": st.session_state["linear_key"], "Content-Type": "application/json"}, json=query)
        r.raise_for_status()
        nodes = r.json()["data"]["issues"]["nodes"]
        st.session_state["issue_map"] = {n["title"]: n["id"] for n in nodes}
        provs = get_provider_credentials()
        if not nodes:
            st.info("No launches.")
        for n in nodes:
            st.subheader(n["title"])
            prov_key = n["title"].split(" - ")[-1].strip().lower()
            match = next((provs[p] for p in provs if prov_key in p), None)
            if match:
                st.markdown(f"[Provider link]({match['url']})")
                st.code(f"User: {match['username']}\nPass: {match['password']}")
            st.divider()
    st.stop()

# ───────────────────────────────
# Thumbnails view
# ───────────────────────────────
if view == "Thumbnails":
    st.header("🖼️ Create & Upload Thumbnails")
    if "issue_map" not in st.session_state:
        st.error("Fetch games first.")
        st.stop()

    issue_title = st.selectbox("Issue", list(st.session_state["issue_map"].keys()))
    issue_id    = st.session_state["issue_map"][issue_title]

    game_name = st.text_input("Game name", placeholder=issue_title)
    uploads   = st.file_uploader("portrait, landscape, box", type=["jpg", "jpeg", "png"], accept_multiple_files=True)

    if st.button("Process"):
        spec = {"box": (".jpg", False), "portrait": (".jpg", True), "landscape": (".png", True)}
        bucket = {k: f for f in uploads or [] for k in spec if k in f.name.lower()}
        if len(bucket) != 3:
            st.error("Upload portrait, landscape, box.")
            st.stop()

        folders = {"Box": {}, "Portrait": {}, "Landscape": {}}
        for k, f in bucket.items():
            ext, comp = spec[k]
            data = f.read()
            if comp:
                data = tinify.from_buffer(data).to_buffer()
            fold = k.capitalize()
            folders[fold][f"{game_name}{ext}"] = data
            if k != "box":
                buf = io.BytesIO()
                Image.open(io.BytesIO(data)).save(buf, format="WEBP")
                folders[fold][f"{game_name}.webp"] = buf.getvalue()

        zips = {}
        for fold in ("Portrait", "Landscape"):
            buf_zip = io.BytesIO()
            with zipfile.ZipFile(buf_zip, "w", zipfile.ZIP_DEFLATED) as zf:
                for fname, blob in folders[fold].items():
                    zf.writestr(fname, blob)
            buf_zip.seek(0)
            zips[fold] = buf_zip.read()

        # save zips
        st.session_state["portrait_zip"]  = zips["Portrait"]
        st.session_state["landscape_zip"] = zips["Landscape"]
        st.success("✅ Bundles ready – click 'Upload All to Linear'.")

    # ── Upload button appears once zips are ready ────────────
    if st.session_state.get("portrait_zip") and st.session_state.get("landscape_zip"):
        if st.button("Upload All to Linear"):
            with st.spinner("Uploading to Linear…"):
                p_url = upload_file_to_linear(issue_id, f"{game_name}_portrait.zip", st.session_state["portrait_zip"])
                l_url = upload_file_to_linear(issue_id, f"{game_name}_landscape.zip", st.session_state["landscape_zip"])
                preview = p_url.replace(".zip", ".jpg")
                comment_body = f"### Portrait Preview\n\n![]({preview})"
                post_comment(issue_id, comment_body)
            st.success("🎉 Uploaded zips & posted comment!")
