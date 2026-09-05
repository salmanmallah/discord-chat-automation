# Discord Automated Message Deleter v2.0

[![Python Version](https://img.shields.io/badge/python-3.8%2B-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Code Style](https://img.shields.io/badge/code%20style-pep8-green.svg)](https://www.python.org/dev/peps/pep-0008/)

A robust, interactive command-line automation tool built in Python to search for and bulk-delete your sent messages across **Discord Servers (Guilds)** and **Personal DMs / Group Chats**.

Equipped with an **Adaptive Rate-Limit Shield**, **Humanized Delays & Jitter**, and **Anti-Ban Cooldown Protections** to safeguard your account.

---

## Key Features

- **Anti-Ban & Rate-Limit Shield:**
  - Configurable safety delays (Default: `2.0s`).
  - Randomized human jitter on API requests to avoid automated detection.
  - Automatic handling of HTTP `429 Too Many Requests` responses with dynamic exponential backoff.
  - Automatic 5.0-second cooldown pauses every 15–20 deletions.

- **Personal DM & Group Chat Deletion:**
  - **Active DMs Queue:** Automatically cleans all open/active 1-on-1 and Group DMs sequentially.
  - **Deep Scan (Hidden / Closed DMs):** Safely discovers and cleans closed DMs with friends using ultra-slow humanized delays (`2.5s - 4.5s`).
  - **Target User ID Queue:** Enter one or multiple User IDs to delete messages in sequential order.
  - **Pick from List:** Interactively view and choose a specific DM conversation.

- **Discord Server (Guild) Deletion:**
  - Fast server-wide indexing via Discord Search API.
  - Automatic fallback to scanning text channels individually.
  - Support for manual Server ID input or choosing from your joined server list.

- **Security & Credentials Protection:**
  - Linux-style hidden token input (typing does not echo to terminal).
  - Credentials stored safely in local `.env` (ignored by git).
  - Positional argument and CLI flag support.

- **Dry-Run Mode:**
  - Preview messages that would be deleted without actually deleting anything.

- **Detailed Summary Reports:**
  - Clean formatted table report showing deleted counts, failed counts, and target scopes.

---

## Installation & Setup

### 1. Clone the Repository
```bash
git clone https://github.com/salmanmallah/discord-chat-automation.git
cd discord-chat-automation
```

### 2. Create Virtual Environment & Install Requirements
```bash
# Create virtual environment
python -m venv .venv

# Activate virtual environment
# On Windows (PowerShell):
.\.venv\Scripts\Activate.ps1
# On Linux / macOS:
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 3. (Optional) Configure `.env` File
Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```
Edit `.env` with your preferred settings:
```ini
# Discord Credentials & Target Configuration
DISCORD_USER_TOKEN=your_user_token_here
DISCORD_GUILD_ID=your_server_guild_id_here

# Optional Settings
# Delay between message deletions in seconds (Recommended: 2.0s for Anti-Ban Safety)
DELETE_DELAY=2.0

# Dry run mode (Set to true to preview without deleting)
DRY_RUN=false

# Auto-confirm mode (Skip y/N confirmation prompts)
AUTO_CONFIRM=false
```

---

## How to Get Your Discord Authorization Token

> [!WARNING]
> **Never share your Discord User Token with anyone.** Anyone with your token has full access to your account.

1. Open Discord in your Web Browser (Chrome, Firefox, Edge) or Discord Desktop app.
2. Press `Ctrl + Shift + I` (or `F12`) to open **Developer Tools**.
3. Navigate to the **Network** tab.
4. Type `/api` in the filter search box.
5. Click on any channel or message in Discord to trigger network activity.
6. Click on any request under the Network tab (e.g. `messages` or `@me`).
7. Under **Request Headers**, look for `Authorization`.
8. Copy the token string.

---

## Usage Guide

### 1. Interactive Menu (Recommended)
Run the script directly. It will guide you through all available scopes:
```bash
python discord_deleter.py
```
You will be prompted to paste your token (hidden input), followed by the interactive menu:
```
Select Deletion Scope:
  [1] Delete ALL Sent Messages in Active Open DMs (Safe Pace: 2-3s)
  [2] Deep Scan & Delete: Include Hidden Friends DMs (Ultra-Slow Safe Pace: 2.5s-4.5s)
  [3] Delete messages by User ID(s) (Single or Bulk Queue)
  [4] Delete messages from a specific Personal DM / Group Chat (Pick from list)
  [5] Delete messages from a Discord Server (Guild)
  [6] Exit
```

---

### 2. Command Line (CLI) Automation

#### Delete all messages across active DMs (No prompts):
```bash
python discord_deleter.py --all-dms -y
```

#### Delete messages with specific User ID(s) in queue:
```bash
python discord_deleter.py -u 123456789012345678 987654321098765432 -y
```

#### Delete messages across a Discord Server:
```bash
python discord_deleter.py -g "SERVER_GUILD_ID"
```

#### Delete messages in a specific channel:
```bash
python discord_deleter.py -c "CHANNEL_ID"
```

#### Preview deletions without deleting (Dry-Run Mode):
```bash
python discord_deleter.py --all-dms --dry-run
```

---

## CLI Options Reference

| Option | Short | Description |
|---|---|---|
| `--token` | `-t` | Discord User Authorization Token |
| `--guild` | `-g` | Discord Server (Guild) ID |
| `--channel` | `-c` | Specific Channel or DM ID |
| `--user` / `--users` | `-u` | Target User ID(s) for sequential queue deletion |
| `--all-dms` | | Clean all sent messages across active open DMs |
| `--deep-all-dms` | | Deep scan: includes hidden friends DMs with ultra-slow pacing |
| `--yes` | `-y` | Auto-confirm all prompts without asking confirmation |
| `--delay` | `-d` | Seconds between deletions (Default: `2.0s`) |
| `--dry-run` | | Preview messages without deleting |
| `--help` | `-h` | Show help message and exit |

---

## Disclaimer & Terms of Service

This tool is created solely for personal data management and privacy purposes (e.g. deleting your own past messages under GDPR/privacy rights). 

- Automating user accounts (Self-Botting) is against Discord's Terms of Service.
- Use this tool at your own discretion. The author and contributors are not responsible for any actions taken against your account (including rate limits, suspensions, or bans).
- Always keep delays at recommended values (`>= 2.0s`) to minimize automated detection.

---

## License

This project is licensed under the [MIT License](LICENSE).
