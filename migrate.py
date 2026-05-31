#!/usr/bin/env python3
"""
Google Drive migration script: source account → destination account.
Handles owned files, shared-with-me files, folder structure, native Google formats,
and binary files. Resumable via migration_log.json.

Usage:
    python migrate.py --source-email you@work.com --dest-email you@gmail.com
    python migrate.py --source-email you@work.com --dest-email you@gmail.com --dry-run
"""

import argparse
import io
import json
import os
import sys
import time
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload

SCOPES = ["https://www.googleapis.com/auth/drive"]

MIME_EXPORT_MAP = {
    "application/vnd.google-apps.document": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".docx",
    ),
    "application/vnd.google-apps.spreadsheet": (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".xlsx",
    ),
    "application/vnd.google-apps.presentation": (
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ".pptx",
    ),
    "application/vnd.google-apps.drawing": ("image/png", ".png"),
}

GOOGLE_NATIVE_COPY_TYPES = {
    "application/vnd.google-apps.document",
    "application/vnd.google-apps.spreadsheet",
    "application/vnd.google-apps.presentation",
    "application/vnd.google-apps.drawing",
}

SKIP_TYPES = {
    "application/vnd.google-apps.folder",
    "application/vnd.google-apps.form",   # Forms can't be copied cross-account
    "application/vnd.google-apps.shortcut",
    "application/vnd.google-apps.site",
}

LOG_FILE = Path("migration_log.json")
CLIENT_SECRET_FILE = Path("client_secret.json")


def load_log() -> dict:
    if LOG_FILE.exists():
        return json.loads(LOG_FILE.read_text())
    return {"done": {}, "failed": {}, "folder_map": {}}


def save_log(log: dict):
    LOG_FILE.write_text(json.dumps(log, indent=2))


def get_credentials(token_file: str, label: str) -> Credentials:
    creds = None
    if Path(token_file).exists():
        creds = Credentials.from_authorized_user_file(token_file, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not CLIENT_SECRET_FILE.exists():
                print(f"ERROR: {CLIENT_SECRET_FILE} not found. See setup_instructions.md.")
                sys.exit(1)
            print(f"\n→ Opening browser to authenticate {label} account...")
            flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRET_FILE), SCOPES)
            creds = flow.run_local_server(port=0)
        Path(token_file).write_text(creds.to_json())
    return creds


def build_service(creds: Credentials):
    return build("drive", "v3", credentials=creds)


def retry(fn, *args, max_retries=5, **kwargs):
    """Call fn with exponential backoff on 429/500 errors."""
    for attempt in range(max_retries):
        try:
            return fn(*args, **kwargs)
        except HttpError as e:
            if e.resp.status in (429, 500, 503) and attempt < max_retries - 1:
                wait = 2 ** attempt
                print(f"  Rate limit/server error, retrying in {wait}s...")
                time.sleep(wait)
            else:
                raise


def list_all_files(service, after_date: str | None = None, before_date: str | None = None) -> list[dict]:
    """List all files accessible to the authenticated account."""
    files = []
    page_token = None
    query = "trashed = false"
    if after_date:
        query += f" and createdTime >= '{after_date}'"
    if before_date:
        query += f" and createdTime <= '{before_date}'"
    query += (
        " and ("
        "mimeType = 'application/vnd.google-apps.document' or "
        "mimeType = 'application/vnd.google-apps.spreadsheet' or "
        "mimeType = 'application/vnd.google-apps.presentation' or "
        "mimeType = 'application/vnd.google-apps.drawing' or "
        "mimeType = 'application/vnd.google-apps.folder'"
        ")"
    )
    print("Listing all files from source account...")
    while True:
        resp = retry(
            service.files().list(
                q=query,
                spaces="drive",
                fields="nextPageToken, files(id, name, mimeType, parents, owners, size, modifiedTime, createdTime)",
                pageSize=1000,
                includeItemsFromAllDrives=False,
                supportsAllDrives=False,
                pageToken=page_token,
            ).execute
        )
        batch = resp.get("files", [])
        files.extend(batch)
        page_token = resp.get("nextPageToken")
        print(f"  ...found {len(files)} files so far", end="\r")
        if not page_token:
            break
    print(f"\nTotal files found: {len(files)}")
    return files


def get_or_create_folder(dest_service, name: str, parent_id: str | None, folder_map: dict, log: dict) -> str:
    """Return destination folder ID, creating it if needed."""
    key = f"{parent_id}::{name}"
    if key in log["folder_map"]:
        return log["folder_map"][key]

    body = {
        "name": name,
        "mimeType": "application/vnd.google-apps.folder",
    }
    if parent_id:
        body["parents"] = [parent_id]

    folder = retry(
        dest_service.files().create(
            body=body,
            fields="id",
            supportsAllDrives=True,
        ).execute
    )
    fid = folder["id"]
    log["folder_map"][key] = fid
    save_log(log)
    return fid


def build_folder_path(file_id: str, all_files_by_id: dict, service) -> list[str]:
    """Return list of folder names from root to parent of file_id."""
    path = []
    current = all_files_by_id.get(file_id)
    while current:
        parents = current.get("parents", [])
        if not parents:
            break
        parent_id = parents[0]
        parent = all_files_by_id.get(parent_id)
        if parent and parent["mimeType"] == "application/vnd.google-apps.folder":
            path.insert(0, parent["name"])
            current = parent
        else:
            break
    return path


def ensure_dest_folder_path(dest_service, path_parts: list[str], log: dict) -> str | None:
    """Create nested folders in destination, return leaf folder ID."""
    parent_id = None
    for part in path_parts:
        parent_id = get_or_create_folder(dest_service, part, parent_id, {}, log)
    return parent_id


def share_file(src_service, file_id: str, dest_email: str) -> bool:
    """Share source file with destination account. Returns False if blocked."""
    try:
        retry(
            src_service.permissions().create(
                fileId=file_id,
                body={"type": "user", "role": "reader", "emailAddress": dest_email},
                supportsAllDrives=True,
                sendNotificationEmail=False,
            ).execute
        )
        return True
    except HttpError as e:
        if e.resp.status in (403, 400):
            return False
        raise


def copy_native_via_share(
    src_service, dest_service, file_id: str, name: str,
    dest_email: str, dest_parent_id: str | None, modified_time: str | None = None
) -> str | None:
    """
    Share file with dest account then have dest account copy it.
    Returns new file ID or None if failed.
    """
    if not share_file(src_service, file_id, dest_email):
        return None

    body = {"name": name}
    if dest_parent_id:
        body["parents"] = [dest_parent_id]
    if modified_time:
        body["modifiedTime"] = modified_time

    try:
        result = retry(
            dest_service.files().copy(
                fileId=file_id,
                body=body,
                supportsAllDrives=True,
                fields="id",
            ).execute
        )
        new_id = result["id"]
        # Force modifiedTime — Drive ignores it in copy body, must use update
        if modified_time:
            retry(
                dest_service.files().update(
                    fileId=new_id,
                    body={"modifiedTime": modified_time},
                    fields="id",
                ).execute
            )
        return new_id
    except HttpError:
        return None
    finally:
        # Clean up permission (best-effort)
        try:
            perms = src_service.permissions().list(
                fileId=file_id, fields="permissions(id,emailAddress)", supportsAllDrives=True
            ).execute()
            for p in perms.get("permissions", []):
                if p.get("emailAddress") == dest_email:
                    src_service.permissions().delete(
                        fileId=file_id, permissionId=p["id"], supportsAllDrives=True
                    ).execute()
                    break
        except Exception:
            pass


def export_and_upload(
    src_service, dest_service, file: dict, dest_parent_id: str | None, modified_time: str | None = None
) -> str | None:
    """Export Google-native file as Office format and upload to destination."""
    mime_type = file["mimeType"]
    if mime_type not in MIME_EXPORT_MAP:
        return None

    export_mime, ext = MIME_EXPORT_MAP[mime_type]
    name = file["name"] + ext

    buf = io.BytesIO()
    request = src_service.files().export_media(fileId=file["id"], mimeType=export_mime)
    downloader = MediaIoBaseDownload(buf, request)
    done = False
    while not done:
        _, done = retry(downloader.next_chunk)

    buf.seek(0)
    body = {"name": name}
    if dest_parent_id:
        body["parents"] = [dest_parent_id]
    if modified_time:
        body["modifiedTime"] = modified_time

    media = MediaIoBaseUpload(buf, mimetype=export_mime, resumable=True)
    result = retry(
        dest_service.files().create(
            body=body,
            media_body=media,
            fields="id",
            supportsAllDrives=True,
        ).execute
    )
    new_id = result["id"]
    if modified_time:
        retry(
            dest_service.files().update(
                fileId=new_id,
                body={"modifiedTime": modified_time},
                fields="id",
            ).execute
        )
    return new_id


def download_and_upload(
    src_service, dest_service, file: dict, dest_parent_id: str | None
) -> str | None:
    """Download binary file from source and upload to destination."""
    size = int(file.get("size", 0))
    if size > 5 * 1024 * 1024 * 1024:  # 5 GB limit
        print(f"  SKIP (file too large: {size // (1024**3)} GB)")
        return None

    buf = io.BytesIO()
    request = src_service.files().get_media(fileId=file["id"], supportsAllDrives=True)
    downloader = MediaIoBaseDownload(buf, request)
    done = False
    while not done:
        _, done = retry(downloader.next_chunk)

    buf.seek(0)
    body = {"name": file["name"], "mimeType": file["mimeType"]}
    if dest_parent_id:
        body["parents"] = [dest_parent_id]

    media = MediaIoBaseUpload(buf, mimetype=file["mimeType"], resumable=True)
    result = retry(
        dest_service.files().create(
            body=body,
            media_body=media,
            fields="id",
            supportsAllDrives=True,
        ).execute
    )
    return result["id"]


def create_root_folder(dest_service, name: str) -> str:
    """Create a top-level folder in destination Drive, return its ID."""
    result = retry(
        dest_service.files().create(
            body={"name": name, "mimeType": "application/vnd.google-apps.folder"},
            fields="id",
        ).execute
    )
    return result["id"]


def migrate(source_email: str, dest_email: str, dry_run: bool, after_date: str | None = None,
            before_date: str | None = None, year: int | None = None):
    if year:
        after_date = f"{year}-01-01"
        before_date = f"{year}-12-31"

    print("=== Google Drive Migration ===")
    print(f"Source: {source_email}")
    print(f"Destination: {dest_email}")
    if after_date:
        print(f"Date range: {after_date} → {before_date or 'now'}")
    if dry_run:
        print("DRY RUN — no files will be copied\n")

    print("\n[1/2] Authenticating source account...")
    src_creds = get_credentials("source_token.json", f"SOURCE ({source_email})")
    src_service = build_service(src_creds)

    print("[2/2] Authenticating destination account...")
    dest_creds = get_credentials("dest_token.json", f"DESTINATION ({dest_email})")
    dest_service = build_service(dest_creds)

    log = load_log()
    all_files = list_all_files(src_service, after_date=after_date, before_date=before_date)

    # Build lookup map for folder traversal
    all_files_by_id = {f["id"]: f for f in all_files}

    # Separate folders and files
    folders = [f for f in all_files if f["mimeType"] == "application/vnd.google-apps.folder"]
    files = [f for f in all_files if f["mimeType"] not in SKIP_TYPES and
             f["mimeType"] != "application/vnd.google-apps.folder"]

    print(f"\nFolders: {len(folders)}  |  Files to migrate: {len(files)}")

    if dry_run:
        print("\nFiles that would be migrated:")
        for f in files:
            owned = any(o.get("me") for o in f.get("owners", []))
            tag = "[owned]" if owned else "[shared]"
            print(f"  {tag} {f['name']}  ({f['mimeType']})")
        print("\nDry run complete.")
        return

    # Create a top-level year (or generic) folder in destination
    root_label = str(year) if year else (after_date[:4] if after_date else "migrated")
    root_folder_key = f"__root_{root_label}__"
    if root_folder_key not in log["folder_map"]:
        print(f"\nCreating destination folder: '{root_label}'...")
        root_folder_id = create_root_folder(dest_service, root_label)
        log["folder_map"][root_folder_key] = root_folder_id
        save_log(log)
    root_folder_id = log["folder_map"][root_folder_key]

    succeeded = 0
    failed = 0
    skipped = 0

    for i, file in enumerate(files, 1):
        file_id = file["id"]
        name = file["name"]
        mime = file["mimeType"]

        if file_id in log["done"]:
            skipped += 1
            continue

        modified_time = file.get("modifiedTime")
        created_time = file.get("createdTime")
        if created_time:
            date_tag = created_time[:10]  # e.g. 2023-03-15
            name = f"{name} [{date_tag}]"
        print(f"\n[{i}/{len(files)}] {name[:60]}  ({mime.split('.')[-1]})")

        # Determine destination parent: year root folder + original subfolder structure
        parents = file.get("parents", [])
        dest_parent_id = root_folder_id
        if parents:
            parent_id = parents[0]
            parent = all_files_by_id.get(parent_id)
            if parent and parent["mimeType"] == "application/vnd.google-apps.folder":
                path_parts = build_folder_path(file_id, all_files_by_id, src_service)
                if path_parts:
                    # Nest subfolders inside the root year folder
                    sub_parent = root_folder_id
                    for part in path_parts:
                        sub_parent = get_or_create_folder(dest_service, part, sub_parent, {}, log)
                    dest_parent_id = sub_parent

        new_id = None
        method_used = None

        try:
            if mime in GOOGLE_NATIVE_COPY_TYPES:
                # Try share+copy first (preserves Google format)
                new_id = copy_native_via_share(
                    src_service, dest_service, file_id, name, dest_email, dest_parent_id, modified_time
                )
                method_used = "share+copy"

                if not new_id:
                    # Fallback: export as Office format
                    print("  Sharing blocked, falling back to export...")
                    new_id = export_and_upload(src_service, dest_service, file, dest_parent_id, modified_time)
                    method_used = "export+upload"

            else:
                new_id = download_and_upload(src_service, dest_service, file, dest_parent_id)
                method_used = "download+upload"

        except Exception as e:
            print(f"  ERROR: {e}")
            log["failed"][file_id] = {"name": name, "error": str(e)}
            save_log(log)
            failed += 1
            continue

        if new_id:
            log["done"][file_id] = {"name": name, "new_id": new_id, "method": method_used}
            save_log(log)
            succeeded += 1
            print(f"  ✓ {method_used}")
        else:
            log["failed"][file_id] = {"name": name, "error": "copy returned None"}
            save_log(log)
            failed += 1
            print("  ✗ failed (no ID returned)")

    print(f"\n=== Done ===")
    print(f"Succeeded: {succeeded}")
    print(f"Failed:    {failed}")
    print(f"Skipped (already done): {skipped}")
    print(f"Log: {LOG_FILE.resolve()}")

    if failed:
        print(f"\nFailed files are in {LOG_FILE} under 'failed'. Re-run the script to retry.")


def main():
    parser = argparse.ArgumentParser(description="Migrate Google Drive files between accounts")
    parser.add_argument("--source-email", required=True, help="Source account email")
    parser.add_argument("--dest-email", required=True, help="Destination account email")
    parser.add_argument("--dry-run", action="store_true", help="List files without copying")
    parser.add_argument("--after", default=None, help="Only migrate files created after this date (e.g. 2026-01-01)")
    parser.add_argument("--before", default=None, help="Only migrate files created before this date (e.g. 2026-06-01)")
    parser.add_argument("--year", type=int, default=None, help="Migrate files created in this year (e.g. 2025)")
    args = parser.parse_args()
    migrate(args.source_email, args.dest_email, args.dry_run, after_date=args.after, before_date=args.before, year=args.year)


if __name__ == "__main__":
    main()
