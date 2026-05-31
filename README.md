# Google Drive Migration Tool

Migrate Google Docs, Sheets, and Slides from one Google account to another — including files shared with you (not owned). Files are organized by year and preserve the original modification date.

## Prerequisites

- Python 3.10+
- A Google Cloud project with the Drive API enabled (see setup below)

## Setup

### 1. Clone the repo

```bash
git clone https://github.com/GadHornWix/drive-migration
cd drive-migration
```

### 2. Create a virtual environment and install dependencies

```bash
python3 -m venv venv
source venv/bin/activate
pip install -i https://pypi.org/simple/ -r requirements.txt
```

### 3. Set up Google Cloud credentials

Follow the step-by-step instructions in [setup_instructions.md](setup_instructions.md) to:
- Create a Google Cloud project
- Enable the Drive API
- Create OAuth credentials
- Download `client_secret.json` into this folder

## Usage

### Migrate a specific year

```bash
venv/bin/python3 migrate.py --source-email you@work.com --dest-email you@gmail.com --year 2025
```

### Migrate multiple years

```bash
for year in 2026 2025 2024 2023 2022 2021 2020 2019 2018; do
  echo "=== Migrating $year ==="
  venv/bin/python3 migrate.py --source-email you@work.com --dest-email you@gmail.com --year $year
done
```

### Dry run (preview files without copying)

```bash
venv/bin/python3 migrate.py --source-email you@work.com --dest-email you@gmail.com --year 2025 --dry-run
```

### Custom date range

```bash
venv/bin/python3 migrate.py --source-email you@work.com --dest-email you@gmail.com --after 2024-01-01 --before 2024-06-30
```

## What gets migrated

- ✅ Google Docs, Sheets, Slides
- ✅ Files you own
- ✅ Files shared with you (not owned)
- ✅ Folder structure preserved inside a per-year folder
- ✅ Original modification date preserved
- ✅ Creation date appended to filename (e.g. `My Doc [2024-03-15]`)
- ❌ Google Forms (Google limitation — cannot be copied cross-account)
- ❌ Shortcuts and binary files (by design)

## Resumable

If the script is interrupted, just re-run it. Progress is saved in `migration_log.json` and already-migrated files are skipped automatically.

## First run — browser authentication

On the first run, two browser windows will open:
1. Sign in with your **source** account
2. Sign in with your **destination** account

Tokens are saved locally so you won't be asked again on subsequent runs.
