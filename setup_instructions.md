# Google Drive Migration — Setup Instructions

## Step 1: Create a Google Cloud Project

1. Go to https://console.cloud.google.com/
2. Click **New Project** → name it `drive-migration` → **Create**
3. Make sure the new project is selected in the top dropdown

## Step 2: Enable the Google Drive API

1. Go to **APIs & Services → Library**
2. Search for "Google Drive API" → click it → **Enable**

## Step 3: Configure OAuth Consent Screen

1. Go to **APIs & Services → OAuth consent screen**
2. Choose **External** → **Create**
3. Fill in:
   - App name: `Drive Migration`
   - User support email: your email
   - Developer contact email: your email
4. Click **Save and Continue** through all screens (you don't need to add scopes here)
5. On the **Test users** screen, click **Add users** and add BOTH email addresses:
   - Your source (Workspace) email
   - Your destination (Gmail) email
6. **Save and Continue** → **Back to Dashboard**

## Step 4: Create OAuth Credentials

1. Go to **APIs & Services → Credentials**
2. Click **Create Credentials → OAuth client ID**
3. Application type: **Desktop app**
4. Name: `drive-migration-client`
5. Click **Create**
6. Click **Download JSON** on the created credential
7. Rename the downloaded file to `client_secret.json`
8. Move it into this folder: `/Users/gadh/drive_migrate/client_secret.json`

## Step 5: Install Dependencies

```bash
cd /Users/gadh/drive_migrate
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Step 6: Run the Migration

```bash
cd /Users/gadh/drive_migrate
source venv/bin/activate

# First do a dry run to see what will be migrated:
python migrate.py --source-email you@work.com --dest-email you@gmail.com --dry-run

# Then run the actual migration:
python migrate.py --source-email you@work.com --dest-email you@gmail.com
```

When you run it:
- A browser window will open for the **source** account login — sign in with your Workspace account
- A second browser window will open for the **destination** account — sign in with your Gmail account
- Tokens are saved locally so you won't be asked again if you restart

## Step 7: If the Script Is Interrupted

Just re-run the same command. The script saves progress to `migration_log.json` and skips already-completed files.

## Notes

- **Files not owned by you**: The script will attempt to copy them. For Google-native files, it shares the file temporarily with your destination account, copies it, then removes the share. If your Workspace admin has blocked external sharing, it will fall back to exporting as Office format (.docx/.xlsx/.pptx).
- **Google Forms**: Cannot be copied cross-account (Google limitation) — these are skipped.
- **Shortcuts**: Skipped (they'd point to files in the old account).
- **Folder structure**: Recreated in your destination Drive root.
- **File size limit**: Files over 5 GB are skipped (Google Drive API limitation for downloads).
- **Speed**: Large migrations (15 GB+) may take several hours. Keep the terminal open or run in a screen/tmux session.

## Troubleshooting

- **"Access Not Configured"**: The Drive API isn't enabled — check Step 2.
- **"redirect_uri_mismatch"**: Make sure you chose "Desktop app" in Step 4.
- **403 errors on sharing**: Your Workspace org blocks external sharing. The script will auto-fallback to export mode.
- **Quota exceeded**: Google limits API calls. The script has automatic retry with backoff. If you hit daily quota, wait 24 hours and re-run (already-migrated files are skipped).
