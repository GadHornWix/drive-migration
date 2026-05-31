# Google Drive Migration — Setup Instructions

## Step 1: Create a Google Cloud Project

> **Use your personal Gmail account** to create the project — Workspace (corporate) accounts may have restrictions that prevent creating OAuth apps.

1. Go to https://console.cloud.google.com/
2. Sign in with your **personal Gmail account**
3. Click the project dropdown at the top → **New Project**
4. Name it `drive-migration` → **Create**
5. Wait ~10 seconds, then make sure `drive-migration` is selected in the top dropdown

## Step 2: Enable the Google Drive API

1. Go to: https://console.cloud.google.com/apis/library/drive.googleapis.com
2. Make sure `drive-migration` is the selected project
3. Click **Enable**

## Step 3: Configure OAuth Consent Screen

1. Go to: https://console.cloud.google.com/apis/credentials/consent
2. **If you see an External / Internal choice** → choose **External** → **Create**
   **If you don't see that choice** (common for personal Gmail) → you'll go straight to the form — that's fine
3. Fill in:
   - App name: `Drive Migration`
   - User support email: your email from the dropdown
   - Developer contact email: your email
4. Click **Save and Continue**
5. On the **Scopes** page → click **Save and Continue** (no need to add scopes)
6. On the **Test users** page (if it appears):
   - Click **+ Add Users**
   - Add both your source and destination email addresses
   - Click **Save and Continue**
   > **If the Test users page doesn't appear** (common for personal Gmail) — skip this step
7. Click through to finish. If you don't see a "Back to Dashboard" button, just click **Credentials** in the left sidebar to proceed to Step 4.

## Step 4: Create OAuth Credentials

1. Go to: https://console.cloud.google.com/apis/credentials
2. Click **+ Create Credentials → OAuth client ID**
3. Application type: **Desktop app**
4. Name: `drive-migration`
5. Click **Create** → then **Download JSON**
6. Rename the downloaded file to `client_secret.json`
7. Move it into the project folder: `drive-migration/client_secret.json`

## Step 5: Install Dependencies

```bash
cd drive-migration
python3 -m venv venv
source venv/bin/activate
pip install -i https://pypi.org/simple/ -r requirements.txt
```

> **Note:** The `-i https://pypi.org/simple/` flag ensures packages are installed from the public PyPI registry. This is needed if your machine is configured to use a corporate package registry that may not be reachable.

## Step 6: Run the Migration

```bash
# Dry run first — lists files without copying anything
venv/bin/python3 migrate.py --source-email you@work.com --dest-email you@gmail.com --year 2025 --dry-run

# Actual migration
venv/bin/python3 migrate.py --source-email you@work.com --dest-email you@gmail.com --year 2025
```

### First run — browser authentication

Two browser windows will open one after the other:
1. **First window** → sign in with your **source** account (e.g. corporate)
2. **Second window** → sign in with your **destination** account (e.g. Gmail)

> **If the browser window doesn't open automatically**, check your Dock for a bouncing browser icon, or look in the terminal for a long `https://accounts.google.com/...` URL and paste it manually into your browser.

> **If you see "Error 403: access_denied"**, your accounts aren't added as test users. Go back to https://console.cloud.google.com/apis/credentials/consent, find the Test users section, and add both email addresses.

Tokens are saved to `source_token.json` and `dest_token.json` so you won't be asked again on subsequent runs.

> **If the wrong account was authenticated** (files listed are from the wrong account), delete the token files and re-authenticate:
> ```bash
> rm source_token.json dest_token.json
> ```

## Step 7: If the Script Is Interrupted

Just re-run the same command. Progress is saved in `migration_log.json` and already-completed files are skipped automatically.

## Notes

- **Files not owned by you**: The script temporarily shares each file with your destination account, copies it, then removes the share. If your source org blocks external sharing, it automatically falls back to exporting as Office format (.docx/.xlsx/.pptx).
- **Google Forms**: Cannot be copied cross-account (Google limitation) — skipped.
- **Shortcuts**: Skipped.
- **Folder structure**: Recreated inside a per-year folder in your destination Drive root.
- **Timestamps**: Original modification date is preserved in the "Last modified" column. Creation date is appended to each filename (e.g. `My Doc [2024-03-15]`).
- **Speed**: ~2,000 files takes 1–2 hours. Keep the terminal open or run in a `screen`/`tmux` session.

## Troubleshooting

| Error | Fix |
|-------|-----|
| `ModuleNotFoundError: No module named 'google'` | Run using `venv/bin/python3` not `python3` |
| `Could not find a version that satisfies the requirement` | Add `-i https://pypi.org/simple/` to your pip install command |
| `Error 403: access_denied` | Add both emails as Test users in the OAuth consent screen |
| `redirect_uri_mismatch` | Make sure you chose "Desktop app" in Step 4 |
| Files listed are from the wrong account | Delete `source_token.json` and `dest_token.json` and re-authenticate |
| Quota exceeded | Google limits API calls per day. Wait 24 hours and re-run (already-migrated files are skipped) |
