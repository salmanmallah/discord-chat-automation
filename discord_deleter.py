import sys
import time
import argparse
import os
import getpass
import re
import random
import base64
import json
from typing import List, Dict, Any, Optional
import requests
from dotenv import load_dotenv
from colorama import init, Fore, Style

# Initialize colorama
init(autoreset=True)

# Discord API Base URL
DISCORD_API_BASE = "https://discord.com/api/v9"

# ═══════════════════════════════════════════════════════════════════
# Anti-Ban Configuration Constants
# ═══════════════════════════════════════════════════════════════════
MAX_API_RETRIES = 5                    # Max retries on rate-limit before giving up
SESSION_DELETE_LIMIT = 500             # Warn after this many deletions per session
COOLDOWN_BATCH_MIN = 12                # Randomized cooldown every 12-25 deletions
COOLDOWN_BATCH_MAX = 25
COOLDOWN_PAUSE_MIN = 4.0              # Cooldown pause range in seconds
COOLDOWN_PAUSE_MAX = 8.0
BASE_SCAN_DELAY = 1.8                 # Delay between channel scan pages
BASE_SEARCH_DELAY = 2.5               # Delay between search API pages
BASE_DELETE_DELAY = 2.0               # Minimum delay between deletions
DEEP_SCAN_DELAY_MIN = 3.0             # Deep scan friend check delays
DEEP_SCAN_DELAY_MAX = 6.0
BETWEEN_CHAT_REST_MIN = 4.0           # Rest between different DM chats
BETWEEN_CHAT_REST_MAX = 8.0
BETWEEN_USER_REST_MIN = 3.0           # Rest between user ID queue items
BETWEEN_USER_REST_MAX = 6.0

def safe_sleep(seconds: float, jitter: float = 1.0):
    """Sleeps with wide randomized human-like jitter to avoid automated bot detection patterns."""
    jitter_amount = random.uniform(0.2, jitter)
    actual_delay = max(0.5, seconds + jitter_amount)
    # Occasionally add a longer "human thinking" pause (~5% chance) for realism
    if random.random() < 0.05:
        actual_delay += random.uniform(1.5, 4.0)
    time.sleep(actual_delay)

def print_banner():
    print(f"\n{Fore.CYAN}+---------------------------------------------------------+{Style.RESET_ALL}")
    print(f"{Fore.CYAN}| {Fore.MAGENTA}          DISCORD AUTOMATED MESSAGE DELETER v2.0        {Fore.CYAN}|{Style.RESET_ALL}")
    print(f"{Fore.CYAN}| {Fore.YELLOW}       [ Server Guilds & Personal DMs Automation ]       {Fore.CYAN}|{Style.RESET_ALL}")
    print(f"{Fore.CYAN}| {Fore.GREEN}        (Enhanced Anti-Ban & Rate-Limit Shield)          {Fore.CYAN}|{Style.RESET_ALL}")
    print(f"{Fore.CYAN}+---------------------------------------------------------+{Style.RESET_ALL}\n")

def log_info(msg: str):
    print(f"{Fore.CYAN}[*]{Style.RESET_ALL} {msg}")

def log_success(msg: str):
    print(f"{Fore.GREEN}[+]{Style.RESET_ALL} {msg}")

def log_warn(msg: str):
    print(f"{Fore.YELLOW}[!]{Style.RESET_ALL} {msg}")

def log_error(msg: str):
    print(f"{Fore.RED}[-]{Style.RESET_ALL} {msg}")

def get_headers(token: str) -> Dict[str, str]:
    """Returns HTTP headers mimicking a real Discord client to reduce detection risk."""
    super_properties = base64.b64encode(json.dumps({
        "os": "Windows",
        "browser": "Chrome",
        "device": "",
        "system_locale": "en-US",
        "browser_user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "browser_version": "124.0.0.0",
        "os_version": "10",
        "referrer": "",
        "referring_domain": "",
        "referrer_current": "",
        "referring_domain_current": "",
        "release_channel": "stable",
        "client_build_number": 291963,
        "client_event_source": None
    }, separators=(',', ':')).encode()).decode()

    return {
        "Authorization": token.strip(),
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "X-Super-Properties": super_properties,
        "X-Discord-Locale": "en-US",
        "X-Discord-Timezone": "America/New_York",
        "X-Debug-Options": "bugReporterEnabled",
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"Windows"',
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
    }

def verify_token(headers: Dict[str, str]) -> Optional[Dict[str, Any]]:
    """Verifies the authorization token and returns user details."""
    try:
        res = requests.get(f"{DISCORD_API_BASE}/users/@me", headers=headers, timeout=10)
        if res.status_code == 200:
            return res.json()
        elif res.status_code == 401:
            log_error("Invalid or expired Discord User Token!")
            return None
        else:
            log_error(f"Authentication failed. HTTP {res.status_code}: {res.text}")
            return None
    except Exception as e:
        log_error(f"Network error during authentication check: {e}")
        return None

def fetch_user_guilds(headers: Dict[str, str]) -> List[Dict[str, Any]]:
    """Fetches all Discord servers (guilds) joined by the user with rate limit protection."""
    guilds = []
    after = None
    
    while True:
        url = f"{DISCORD_API_BASE}/users/@me/guilds?limit=100"
        if after:
            url += f"&after={after}"
            
        try:
            res = requests.get(url, headers=headers, timeout=10)
            if res.status_code == 200:
                batch = res.json()
                if not batch:
                    break
                guilds.extend(batch)
                if len(batch) < 100:
                    break
                after = batch[-1]["id"]
                safe_sleep(1.5, 0.8)
            elif res.status_code == 429:
                retry = float(res.json().get("retry_after", 2.0))
                log_warn(f"Rate limited while fetching servers. Waiting {retry + 1.5:.2f}s...")
                safe_sleep(retry + 1.5)
            else:
                log_error(f"Failed to fetch servers. HTTP {res.status_code}: {res.text}")
                break
        except Exception as e:
            log_error(f"Error fetching servers: {e}")
            break
            
    return guilds

def select_guild_server(headers: Dict[str, str]) -> Optional[str]:
    """Interactively lists joined Discord servers and lets the user pick one."""
    log_info("Fetching your joined Discord Servers (Guilds)...")
    guilds = fetch_user_guilds(headers)
    
    print(f"\n{Fore.GREEN}Select a Discord Server:{Style.RESET_ALL}")
    print(f"  {Fore.YELLOW}[0]{Style.RESET_ALL} Enter Server (Guild) ID manually")
    
    guild_options = []
    for idx, g in enumerate(guilds, 1):
        g_id = g["id"]
        g_name = g.get("name", "Unknown Server")
        is_owner = " (Owner)" if g.get("owner") else ""
        
        guild_options.append((g_id, g_name))
        print(f"  {Fore.YELLOW}[{idx}]{Style.RESET_ALL} {g_name}{is_owner} (ID: {g_id})")

    try:
        choice = input(f"\n{Fore.GREEN}Choose option [0-{len(guild_options)}]: {Style.RESET_ALL}").strip()
        if choice == "0":
            return input(f"{Fore.YELLOW}Enter Server ID manually: {Style.RESET_ALL}").strip()
        
        val = int(choice)
        if 1 <= val <= len(guild_options):
            selected = guild_options[val - 1]
            log_info(f"Selected Server: {Fore.YELLOW}{selected[1]}{Style.RESET_ALL} (ID: {selected[0]})")
            return selected[0]
        else:
            log_error("Invalid selection!")
            return None
    except ValueError:
        log_error("Invalid input!")
        return None
    except (KeyboardInterrupt, EOFError):
        log_info("\nCancelled by user.")
        return None

def fetch_user_dms(headers: Dict[str, str]) -> List[Dict[str, Any]]:
    """Fetches user's active DM channels with rate-limit handling and retry cap."""
    for attempt in range(1, MAX_API_RETRIES + 1):
        try:
            res = requests.get(f"{DISCORD_API_BASE}/users/@me/channels", headers=headers, timeout=10)
            if res.status_code == 200:
                return res.json()
            elif res.status_code == 429:
                retry = float(res.json().get("retry_after", 2.0))
                backoff = retry + 1.5 + (attempt * 1.0)
                log_warn(f"Rate limited while fetching DMs (attempt {attempt}/{MAX_API_RETRIES}). Waiting {backoff:.2f}s...")
                safe_sleep(backoff, 1.5)
            else:
                log_error(f"Failed to fetch DMs. HTTP {res.status_code}: {res.text}")
                return []
        except Exception as e:
            log_error(f"Error fetching DMs: {e}")
            return []
    log_error(f"Exceeded max retries ({MAX_API_RETRIES}) fetching DMs.")
    return []

def fetch_user_relationships(headers: Dict[str, str]) -> List[Dict[str, Any]]:
    """Fetches user's friends and relationships with rate-limit protection and retry cap."""
    for attempt in range(1, MAX_API_RETRIES + 1):
        try:
            res = requests.get(f"{DISCORD_API_BASE}/users/@me/relationships", headers=headers, timeout=10)
            if res.status_code == 200:
                return res.json()
            elif res.status_code == 429:
                retry = float(res.json().get("retry_after", 2.0))
                backoff = retry + 2.5 + (attempt * 1.5)
                log_warn(f"Rate limited on relationships (attempt {attempt}/{MAX_API_RETRIES}). Waiting {backoff:.2f}s...")
                safe_sleep(backoff, 2.0)
            else:
                return []
        except Exception as e:
            log_warn(f"Could not fetch relationships: {e}")
            return []
    log_error(f"Exceeded max retries ({MAX_API_RETRIES}) fetching relationships.")
    return []

def discover_all_dm_chats(headers: Dict[str, str], include_hidden: bool = False) -> List[Dict[str, Any]]:
    """
    Discovers all Personal DM and Group chats.
    If include_hidden is True, slowly checks account relationships/friends with 2.5s - 4.5s delays.
    """
    all_dms: Dict[str, Dict[str, Any]] = {}
    known_recipients = set()
    
    # 1. Fetch active open DMs
    log_info("Fetching active Personal DM & Group chats...")
    active_dms = fetch_user_dms(headers)
    for dm in active_dms:
        dm_id = dm.get("id")
        if dm_id:
            all_dms[dm_id] = dm
            for r in dm.get("recipients", []):
                known_recipients.add(r.get("id"))

    log_info(f"Found {Fore.YELLOW}{len(all_dms)}{Style.RESET_ALL} active/open DM chat(s).")

    # 2. If Deep Scan is requested, safely check relationships with large delays
    if include_hidden:
        relationships = fetch_user_relationships(headers)
        if relationships:
            log_info(f"Checking {len(relationships)} friends/relationships for closed DMs with ultra-slow human delays (2.5s - 4.5s)...")
            
            for idx, rel in enumerate(relationships, 1):
                user_obj = rel.get("user", {})
                u_id = user_obj.get("id")
                u_name = user_obj.get("username", "Unknown")
                
                if u_id and u_id not in known_recipients:
                    print(f"[{idx}/{len(relationships)}] Checking friend @{u_name} (ID: {u_id}) ... ", end="", flush=True)
                    
                    # Humanized pause before checking/unhiding DM (ultra-slow: 3-6s)
                    safe_sleep(random.uniform(DEEP_SCAN_DELAY_MIN, DEEP_SCAN_DELAY_MAX), 2.0)
                    
                    dm_data = get_or_create_dm_by_user_id(headers, u_id)
                    if dm_data and dm_data.get("id"):
                        all_dms[dm_data["id"]] = dm_data
                        known_recipients.add(u_id)
                        print(f"{Fore.GREEN}DM Available{Style.RESET_ALL}")
                    else:
                        print(f"{Fore.YELLOW}Skipped{Style.RESET_ALL}")
                    
                    # Humanized pause after opening (2-4s)
                    safe_sleep(random.uniform(2.0, 4.0), 1.5)

    log_success(f"Total DM chats ready in queue: {Fore.YELLOW}{len(all_dms)}{Style.RESET_ALL}")
    return list(all_dms.values())

def select_dm_channel(headers: Dict[str, str]) -> Optional[str]:
    """Interactively lists DMs and lets the user pick one or type a Channel ID."""
    log_info("Fetching your active Direct Messages (DMs)...")
    dms = fetch_user_dms(headers)
    
    print(f"\n{Fore.GREEN}Select a DM Chat:{Style.RESET_ALL}")
    print(f"  {Fore.YELLOW}[0]{Style.RESET_ALL} Enter DM Channel ID manually")
    
    dm_options = []
    for idx, dm in enumerate(dms, 1):
        dm_id = dm["id"]
        dm_type = dm.get("type")
        recipients = dm.get("recipients", [])
        
        if dm_type == 1 and recipients:
            name = f"{recipients[0].get('username')} ({recipients[0].get('global_name') or recipients[0].get('id')})"
        elif dm_type == 3:
            name = "Group DM: " + ", ".join([r.get("username", "") for r in recipients[:3]])
        else:
            name = f"DM Channel ({dm_id})"

        dm_options.append((dm_id, name))
        print(f"  {Fore.YELLOW}[{idx}]{Style.RESET_ALL} {name} (ID: {dm_id})")

    try:
        choice = input(f"\n{Fore.GREEN}Choose option [0-{len(dm_options)}]: {Style.RESET_ALL}").strip()
        if choice == "0":
            return input(f"{Fore.YELLOW}Enter DM Channel ID: {Style.RESET_ALL}").strip()
        
        val = int(choice)
        if 1 <= val <= len(dm_options):
            selected = dm_options[val - 1]
            log_info(f"Selected DM: {Fore.YELLOW}{selected[1]}{Style.RESET_ALL}")
            return selected[0]
        else:
            log_error("Invalid selection!")
            return None
    except ValueError:
        log_error("Invalid input!")
        return None
    except (KeyboardInterrupt, EOFError):
        log_info("\nCancelled by user.")
        return None

def get_or_create_dm_by_user_id(headers: Dict[str, str], target_user_id: str) -> Optional[Dict[str, Any]]:
    """Opens or retrieves an existing DM channel with a target user by User ID with rate-limit safety and retry cap."""
    target_user_id = target_user_id.strip()
    if not target_user_id:
        log_error("User ID cannot be empty!")
        return None

    log_info(f"Resolving DM channel for User ID: {Fore.YELLOW}{target_user_id}{Style.RESET_ALL}...")

    for attempt in range(1, MAX_API_RETRIES + 1):
        try:
            payload = {"recipient_id": target_user_id}
            res = requests.post(f"{DISCORD_API_BASE}/users/@me/channels", headers=headers, json=payload, timeout=10)
            
            if res.status_code in (200, 201):
                dm_data = res.json()
                recipients = dm_data.get("recipients", [])
                recipient_name = recipients[0].get("username", "Unknown") if recipients else target_user_id
                log_success(f"Located DM channel with: {Fore.GREEN}{recipient_name}{Style.RESET_ALL} (Channel ID: {dm_data.get('id')})")
                return dm_data
            elif res.status_code == 429:
                retry = float(res.json().get("retry_after", 2.0))
                backoff = retry + 2.0 + (attempt * 1.5)
                log_warn(f"Rate limited while opening DM (attempt {attempt}/{MAX_API_RETRIES}). Waiting {backoff:.2f}s...")
                safe_sleep(backoff, 2.0)
            elif res.status_code == 400:
                log_error(f"Cannot open DM with User ID {target_user_id}. (Invalid User ID or self-DM not allowed)")
                return None
            elif res.status_code == 403:
                log_error(f"Cannot open DM with User ID {target_user_id}. (DMs closed or blocked by user)")
                return None
            else:
                log_error(f"Failed to open DM. HTTP {res.status_code}: {res.text}")
                return None
        except Exception as e:
            log_error(f"Error resolving DM channel by User ID: {e}")
            return None

    log_error(f"Exceeded max retries ({MAX_API_RETRIES}) opening DM with User ID {target_user_id}.")
    return None

def fetch_guild_channels(headers: Dict[str, str], guild_id: str) -> List[Dict[str, Any]]:
    """Fetches text channels in a guild with rate-limit protection and retry cap."""
    for attempt in range(1, MAX_API_RETRIES + 1):
        try:
            res = requests.get(f"{DISCORD_API_BASE}/guilds/{guild_id}/channels", headers=headers, timeout=10)
            if res.status_code == 200:
                channels = res.json()
                # Types: 0=Text, 2=Voice, 5=Announcement, 15=Forum
                return [c for c in channels if c.get("type") in (0, 2, 5, 15)]
            elif res.status_code == 429:
                retry = float(res.json().get("retry_after", 2.0))
                backoff = retry + 1.5 + (attempt * 1.0)
                log_warn(f"Rate limited while fetching channels (attempt {attempt}/{MAX_API_RETRIES}). Retrying in {backoff:.2f}s...")
                safe_sleep(backoff, 1.5)
            else:
                log_error(f"Failed to fetch guild channels. HTTP {res.status_code}: {res.text}")
                return []
        except Exception as e:
            log_error(f"Error fetching guild channels: {e}")
            return []
    log_error(f"Exceeded max retries ({MAX_API_RETRIES}) fetching guild channels.")
    return []

def search_guild_user_messages(headers: Dict[str, str], guild_id: str, user_id: str) -> List[Dict[str, Any]]:
    """Uses Discord Guild Search API to find messages sent by the user across the entire guild."""
    log_info(f"Searching for your messages across server (Guild ID: {guild_id})...")
    messages = []
    offset = 0
    
    while True:
        url = f"{DISCORD_API_BASE}/guilds/{guild_id}/messages/search?author_id={user_id}&offset={offset}"
        try:
            res = requests.get(url, headers=headers, timeout=10)
            if res.status_code == 200:
                data = res.json()
                total_results = data.get("total_results", 0)
                msg_groups = data.get("messages", [])
                
                if offset == 0:
                    log_info(f"Total messages found in server search index: {Fore.YELLOW}{total_results}{Style.RESET_ALL}")

                if not msg_groups:
                    break

                for group in msg_groups:
                    for msg in group:
                        if msg.get("author", {}).get("id") == user_id:
                            if not any(m["id"] == msg["id"] for m in messages):
                                messages.append({
                                    "id": msg["id"],
                                    "channel_id": msg["channel_id"],
                                    "content": msg.get("content", ""),
                                    "timestamp": msg.get("timestamp", "")
                                })

                offset += 25
                safe_sleep(BASE_SEARCH_DELAY, 1.0)
            elif res.status_code == 429:
                retry = float(res.json().get("retry_after", 2.5))
                backoff = retry + 3.0
                log_warn(f"Search API Rate limited. Waiting {backoff:.2f} seconds...")
                safe_sleep(backoff, 2.0)
            elif res.status_code == 202:
                log_warn("Discord is indexing messages for this server. Retrying in 8s...")
                safe_sleep(8.0, 2.0)
            else:
                log_warn(f"Guild Search API failed or disabled (HTTP {res.status_code}). Falling back to channel scan.")
                break
        except Exception as e:
            log_error(f"Error calling Search API: {e}")
            break
            
    return messages

def scan_channel_user_messages(headers: Dict[str, str], channel_id: str, user_id: str, label: str = "channel") -> List[Dict[str, Any]]:
    """Scans history of a single channel (Guild Channel or DM) for messages by user_id with safe pacing."""
    log_info(f"Scanning message history in {label} (ID: {channel_id})...")
    messages = []
    before = None
    scanned_count = 0
    
    while True:
        url = f"{DISCORD_API_BASE}/channels/{channel_id}/messages?limit=100"
        if before:
            url += f"&before={before}"

        try:
            res = requests.get(url, headers=headers, timeout=10)
            if res.status_code == 200:
                batch = res.json()
                if not batch:
                    break
                
                scanned_count += len(batch)
                for msg in batch:
                    if msg.get("author", {}).get("id") == user_id:
                        messages.append({
                            "id": msg["id"],
                            "channel_id": channel_id,
                            "content": msg.get("content", ""),
                            "timestamp": msg.get("timestamp", "")
                        })
                
                before = batch[-1]["id"]
                print(f"\r{Fore.CYAN}[*]{Style.RESET_ALL} Scanned {scanned_count} messages, found {len(messages)} matching...", end="", flush=True)
                safe_sleep(BASE_SCAN_DELAY, 0.8)
            elif res.status_code == 429:
                retry = float(res.json().get("retry_after", 2.0))
                backoff = retry + 2.5
                log_warn(f"\nRate limited during message scan. Waiting {backoff:.2f}s...")
                safe_sleep(backoff, 1.5)
            else:
                log_error(f"Failed to scan channel. HTTP {res.status_code}: {res.text}")
                break
        except Exception as e:
            log_error(f"Error scanning channel {channel_id}: {e}")
            break

    print()
    return messages

def delete_message(headers: Dict[str, str], channel_id: str, message_id: str) -> tuple[bool, bool]:
    """
    Sends DELETE request for a single message and handles rate limits safely with retry cap.
    Returns (success: bool, hit_rate_limit: bool)
    """
    url = f"{DISCORD_API_BASE}/channels/{channel_id}/messages/{message_id}"
    hit_rate_limit = False
    
    for attempt in range(1, MAX_API_RETRIES + 1):
        try:
            res = requests.delete(url, headers=headers, timeout=10)
            if res.status_code == 204:
                return True, hit_rate_limit
            elif res.status_code == 429:
                hit_rate_limit = True
                data = {}
                try:
                    data = res.json()
                except Exception:
                    pass
                retry = float(data.get("retry_after", 1.8))
                backoff = retry + 1.5 + (attempt * 0.5)
                log_warn(f"Rate limited by Discord (attempt {attempt}/{MAX_API_RETRIES}). Waiting {backoff:.2f}s...")
                safe_sleep(backoff, 1.5)
            elif res.status_code in (404, 200):
                return True, hit_rate_limit
            elif res.status_code == 403:
                log_error(f"Missing permissions to delete message {message_id}")
                return False, hit_rate_limit
            else:
                log_error(f"Failed to delete message {message_id}. HTTP {res.status_code}: {res.text}")
                return False, hit_rate_limit
        except Exception as e:
            log_error(f"Exception during deletion: {e}")
            return False, hit_rate_limit
    
    log_error(f"Exceeded max retries ({MAX_API_RETRIES}) deleting message {message_id}.")
    return False, hit_rate_limit

def delete_message_batch(
    headers: Dict[str, str],
    messages_to_delete: List[Dict[str, Any]],
    base_delay: float = 2.0,
    dry_run: bool = False
) -> tuple[int, int]:
    """
    Deletes a list of messages one by one with rate-limit handling, humanized jitter,
    randomized anti-ban cooldowns, and session safety limits.
    Returns (deleted_count, failed_count)
    """
    total_msgs = len(messages_to_delete)
    if total_msgs == 0:
        return 0, 0

    deleted_count = 0
    failed_count = 0
    current_delay = max(BASE_DELETE_DELAY, base_delay)
    consecutive_smooth = 0
    next_cooldown_at = random.randint(COOLDOWN_BATCH_MIN, COOLDOWN_BATCH_MAX)
    session_warned = False

    print(f"\n{Fore.CYAN}Starting deletion sequence... (Base Delay: {current_delay:.2f}s, Anti-Ban Protection Active){Style.RESET_ALL}\n")

    if total_msgs > SESSION_DELETE_LIMIT:
        log_warn(f"{Fore.YELLOW}[Safety Warning]{Style.RESET_ALL} Queued {total_msgs} messages. Deleting more than {SESSION_DELETE_LIMIT} in one session significantly increases ban risk.")

    try:
        for idx, msg in enumerate(messages_to_delete, 1):
            msg_id = msg["id"]
            ch_id = msg["channel_id"]
            content = msg["content"]
            preview = (content[:40] + "...") if len(content) > 40 else content
            preview = preview.replace("\n", " ")

            if dry_run:
                print(f"[{idx}/{total_msgs}] [DRY-RUN] Would delete Msg ID {msg_id}: '{preview}'")
                deleted_count += 1
            else:
                print(f"[{idx}/{total_msgs}] Deleting Msg ID {msg_id}: '{preview}' ... ", end="", flush=True)
                success, hit_rl = delete_message(headers, ch_id, msg_id)
                if success:
                    print(f"{Fore.GREEN}DELETED{Style.RESET_ALL}")
                    deleted_count += 1
                else:
                    print(f"{Fore.RED}FAILED{Style.RESET_ALL}")
                    failed_count += 1

                # Adaptive Delay adjustment with wider range
                if hit_rl:
                    consecutive_smooth = 0
                    current_delay = min(current_delay + random.uniform(0.5, 1.5), 8.0)
                    log_info(f"Adaptive delay increased to {current_delay:.2f}s to shield account.")
                else:
                    consecutive_smooth += 1
                    if consecutive_smooth >= 20 and current_delay > base_delay:
                        current_delay = max(current_delay - 0.1, base_delay)
                        consecutive_smooth = 0
                
                safe_sleep(current_delay, 1.0)

                # Randomized Anti-Ban Cool-Down Pause (every 12-25 messages, randomized)
                if deleted_count >= next_cooldown_at and idx < total_msgs:
                    pause_duration = random.uniform(COOLDOWN_PAUSE_MIN, COOLDOWN_PAUSE_MAX)
                    log_info(f"{Fore.YELLOW}[Anti-Ban Guard]{Style.RESET_ALL} Pausing {pause_duration:.1f}s cooldown to protect account from automated detection...")
                    safe_sleep(pause_duration, 2.0)
                    next_cooldown_at = deleted_count + random.randint(COOLDOWN_BATCH_MIN, COOLDOWN_BATCH_MAX)

                # Session safety warning and extended cooldown
                if deleted_count >= SESSION_DELETE_LIMIT and not session_warned:
                    session_warned = True
                    log_warn(f"{Fore.YELLOW}[Session Limit]{Style.RESET_ALL} Reached {SESSION_DELETE_LIMIT} deletions this session. Consider stopping and resuming later to reduce ban risk.")
                    log_info("Taking extended 15-30s safety cooldown...")
                    safe_sleep(random.uniform(15.0, 30.0), 5.0)

    except KeyboardInterrupt:
        log_warn("\nDeletion interrupted by user (Ctrl+C).")

    return deleted_count, failed_count

def process_bulk_user_queue(
    headers: Dict[str, str],
    user_ids: List[str],
    my_user_id: str,
    base_delay: float,
    dry_run: bool
):
    """Processes a queue of User IDs sequentially with safe pacing."""
    total_users = len(user_ids)
    log_info(f"Initialized Deletion Queue with {Fore.YELLOW}{total_users}{Style.RESET_ALL} User(s):")
    for i, uid in enumerate(user_ids, 1):
        print(f"  {Fore.CYAN}[{i}]{Style.RESET_ALL} User ID: {uid}")

    grand_total_found = 0
    grand_total_deleted = 0
    grand_total_failed = 0
    user_results = []

    for idx, uid in enumerate(user_ids, 1):
        print(f"\n{Fore.MAGENTA}====================================================={Style.RESET_ALL}")
        print(f"{Fore.MAGENTA}  QUEUE [{idx}/{total_users}] -> Processing User ID: {Fore.YELLOW}{uid}{Style.RESET_ALL}")
        print(f"{Fore.MAGENTA}====================================================={Style.RESET_ALL}")

        dm_data = get_or_create_dm_by_user_id(headers, uid)
        if not dm_data:
            log_error(f"Skipping User ID {uid} (Cannot open DM).")
            user_results.append((uid, "Failed to open DM", 0, 0, 0))
            continue

        ch_id = dm_data.get("id")
        recipients = dm_data.get("recipients", [])
        recipient_name = recipients[0].get("username", uid) if recipients else uid

        msgs = scan_channel_user_messages(headers, ch_id, my_user_id, label=f"DM with @{recipient_name}")
        total_msgs = len(msgs)

        if total_msgs == 0:
            log_warn(f"No messages sent by you found in chat with @{recipient_name}.")
            user_results.append((uid, f"@{recipient_name}", 0, 0, 0))
            continue

        log_success(f"Found {Fore.YELLOW}{total_msgs}{Style.RESET_ALL} sent messages in chat with @{recipient_name}. Deleting now...")

        del_cnt, fail_cnt = delete_message_batch(headers, msgs, base_delay, dry_run)
        grand_total_found += total_msgs
        grand_total_deleted += del_cnt
        grand_total_failed += fail_cnt
        user_results.append((uid, f"@{recipient_name}", total_msgs, del_cnt, fail_cnt))

        # Rest between users in queue
        if idx < total_users:
            rest_time = random.uniform(BETWEEN_USER_REST_MIN, BETWEEN_USER_REST_MAX)
            log_info(f"Resting {rest_time:.1f}s before moving to next user in queue...")
            safe_sleep(rest_time, 2.0)

    # Print Grand Queue Summary
    print(f"\n{Fore.MAGENTA}====================================================={Style.RESET_ALL}")
    print(f"{Fore.MAGENTA}              BULK QUEUE SUMMARY REPORT              {Style.RESET_ALL}")
    print(f"{Fore.MAGENTA}====================================================={Style.RESET_ALL}")
    print(f"{'User ID':<20} | {'Target':<20} | {'Found':<6} | {'Deleted':<8}")
    print(f"{'-'*65}")
    for u_id, target_label, f_cnt, d_cnt, _ in user_results:
        print(f"{u_id:<20} | {target_label:<20} | {f_cnt:<6} | {d_cnt:<8}")
    print(f"{'-'*65}")
    log_info(f"Total Users Processed : {total_users}")
    log_info(f"Total Messages Found   : {grand_total_found}")
    log_success(f"Total Messages Deleted : {grand_total_deleted}")
    if grand_total_failed > 0:
        log_error(f"Total Failed Deletions : {grand_total_failed}")
    print(f"{Fore.MAGENTA}====================================================={Style.RESET_ALL}\n")

def process_all_dms_queue(
    headers: Dict[str, str],
    my_user_id: str,
    base_delay: float,
    dry_run: bool,
    include_hidden: bool = False
):
    """Discovers Personal DMs (with optional ultra-slow hidden scan) and deletes sent messages in queue."""
    dm_list = discover_all_dm_chats(headers, include_hidden=include_hidden)
    total_chats = len(dm_list)
    
    if total_chats == 0:
        log_warn("No DM chats found on this account.")
        return

    log_info(f"Starting automatic queue deletion across {Fore.YELLOW}{total_chats}{Style.RESET_ALL} DM chat(s)... (Safe Paced)")

    grand_total_found = 0
    grand_total_deleted = 0
    grand_total_failed = 0
    chat_results = []

    for idx, dm in enumerate(dm_list, 1):
        dm_id = dm.get("id")
        dm_type = dm.get("type")
        recipients = dm.get("recipients", [])

        if dm_type == 1 and recipients:
            name = f"@{recipients[0].get('username', 'Unknown')}"
        elif dm_type == 3:
            name = "Group: " + ", ".join([r.get("username", "") for r in recipients[:3]])
        else:
            name = f"DM ({dm_id})"

        print(f"\n{Fore.MAGENTA}====================================================={Style.RESET_ALL}")
        print(f"{Fore.MAGENTA}  QUEUE [{idx}/{total_chats}] -> Chat: {Fore.YELLOW}{name}{Fore.MAGENTA} (ID: {dm_id}){Style.RESET_ALL}")
        print(f"{Fore.MAGENTA}====================================================={Style.RESET_ALL}")

        msgs = scan_channel_user_messages(headers, dm_id, my_user_id, label=name)
        total_msgs = len(msgs)

        if total_msgs == 0:
            log_info(f"No sent messages found in {name}. Continuing...")
            chat_results.append((dm_id, name, 0, 0, 0))
            continue

        log_success(f"Found {Fore.YELLOW}{total_msgs}{Style.RESET_ALL} sent messages in {name}. Deleting now...")

        del_cnt, fail_cnt = delete_message_batch(headers, msgs, base_delay, dry_run)
        grand_total_found += total_msgs
        grand_total_deleted += del_cnt
        grand_total_failed += fail_cnt
        chat_results.append((dm_id, name, total_msgs, del_cnt, fail_cnt))

        # Rest between chats in queue (3.0s - 4.5s)
        if idx < total_chats:
            rest_time = random.uniform(BETWEEN_CHAT_REST_MIN, BETWEEN_CHAT_REST_MAX)
            log_info(f"Resting {rest_time:.1f}s before moving to next DM chat in queue...")
            safe_sleep(rest_time, 2.5)

    # Print Grand Summary
    print(f"\n{Fore.MAGENTA}====================================================={Style.RESET_ALL}")
    print(f"{Fore.MAGENTA}          ALL DMs QUEUE GRAND SUMMARY REPORT         {Style.RESET_ALL}")
    print(f"{Fore.MAGENTA}====================================================={Style.RESET_ALL}")
    print(f"{'Channel ID':<20} | {'Target Chat':<20} | {'Found':<6} | {'Deleted':<8}")
    print(f"{'-'*65}")
    for ch_id, target_label, f_cnt, d_cnt, _ in chat_results:
        if f_cnt > 0:
            print(f"{ch_id:<20} | {target_label:<20} | {f_cnt:<6} | {d_cnt:<8}")
    print(f"{'-'*65}")
    log_info(f"Total DM Chats Checked : {total_chats}")
    log_info(f"Total Messages Found   : {grand_total_found}")
    log_success(f"Total Messages Deleted : {grand_total_deleted}")
    if grand_total_failed > 0:
        log_error(f"Total Failed Deletions : {grand_total_failed}")
    print(f"{Fore.MAGENTA}====================================================={Style.RESET_ALL}\n")

def prompt_next_action() -> bool:
    """Prompts user whether to return to main menu or exit. Returns True to continue, False to exit."""
    print(f"\n{Fore.CYAN}---------------------------------------------------------{Style.RESET_ALL}")
    print(f"{Fore.GREEN}What would you like to do next?{Style.RESET_ALL}")
    print(f"  {Fore.YELLOW}[1]{Style.RESET_ALL} Return to Main Menu")
    print(f"  {Fore.YELLOW}[2]{Style.RESET_ALL} Exit Tool")
    
    try:
        choice = input(f"\n{Fore.GREEN}Select option [1-2]: {Style.RESET_ALL}").strip()
        if choice == "1":
            return True
        else:
            log_info("Exiting tool. Goodbye!")
            return False
    except (KeyboardInterrupt, EOFError):
        log_info("\nExiting tool. Goodbye!")
        return False

def main():
    load_dotenv()

    parser = argparse.ArgumentParser(description="Discord Automated Message Deleter v2.0")
    parser.add_argument("token_pos", nargs="?", help="Optional Discord User Authorization Token (positional)")
    parser.add_argument("-t", "--token", help="Discord User Authorization Token")
    parser.add_argument("-g", "--guild", help="Discord Server / Guild ID")
    parser.add_argument("-c", "--channel", help="Specific Channel or DM ID")
    parser.add_argument("-u", "--user", "--users", nargs="*", help="Target User ID(s) (single or bulk queue)")
    parser.add_argument("--all-dms", action="store_true", help="Delete all sent messages across active personal DMs")
    parser.add_argument("--deep-all-dms", action="store_true", help="Deep scan: include hidden friends DMs (ultra-slow human delay)")
    parser.add_argument("-y", "--yes", action="store_true", help="Auto-confirm all deletions without confirmation prompts")
    parser.add_argument("-d", "--delay", type=float, default=2.0, help="Delay between deletions in seconds (default: 2.0s - Anti-Ban Protected)")
    parser.add_argument("--dry-run", action="store_true", help="Preview messages without deleting them")
    args = parser.parse_args()

    print_banner()

    try:
        # Get Token with getpass (Hidden prompt like Linux password entry)
        token = args.token or args.token_pos or os.getenv("DISCORD_USER_TOKEN")
        if not token:
            token = getpass.getpass(f"{Fore.YELLOW}Enter Discord User Token (hidden input): {Style.RESET_ALL}").strip()

        if not token:
            log_error("Token is required to proceed!")
            sys.exit(1)

        # Verify Token
        headers = get_headers(token)
        user_info = verify_token(headers)
        if not user_info:
            sys.exit(1)

        username = f"{user_info.get('username')} (ID: {user_info.get('id')})"
        user_id = user_info.get("id")
        log_success(f"Authenticated as: {Fore.GREEN}{username}{Style.RESET_ALL}")

        base_delay = args.delay
        env_delay = os.getenv("DELETE_DELAY")
        if env_delay and not args.delay:
            try:
                base_delay = float(env_delay)
            except ValueError:
                pass

        dry_run = args.dry_run or (os.getenv("DRY_RUN", "false").lower() == "true")
        auto_yes = args.yes or (os.getenv("AUTO_CONFIRM", "false").lower() == "true")

        if dry_run:
            log_warn(f"{Fore.YELLOW}DRY RUN MODE ENABLED: No messages will be deleted.{Style.RESET_ALL}")

        # CLI All DMs handling
        if args.deep_all_dms:
            process_all_dms_queue(headers, user_id, base_delay, dry_run, include_hidden=True)
            sys.exit(0)
        elif args.all_dms:
            process_all_dms_queue(headers, user_id, base_delay, dry_run, include_hidden=False)
            sys.exit(0)

        # CLI User IDs handling
        cli_user_ids = []
        if args.user:
            raw_cli = " ".join(args.user)
            cli_user_ids = list(dict.fromkeys(re.findall(r"\d+", raw_cli)))

        # Interactive Loop
        while True:
            target_channel_id = args.channel
            target_guild_id = args.guild

            if cli_user_ids:
                process_bulk_user_queue(headers, cli_user_ids, user_id, base_delay, dry_run)
                break

            if not target_channel_id and not target_guild_id:
                print(f"\n{Fore.GREEN}Select Deletion Scope:{Style.RESET_ALL}")
                print(f"  {Fore.YELLOW}[1]{Style.RESET_ALL} Delete ALL Sent Messages in Active Open DMs (Safe Pace: 2-3s)")
                print(f"  {Fore.YELLOW}[2]{Style.RESET_ALL} Deep Scan & Delete: Include Hidden Friends DMs (Ultra-Slow Safe Pace: 2.5s-4.5s)")
                print(f"  {Fore.YELLOW}[3]{Style.RESET_ALL} Delete messages by User ID(s) (Single or Bulk Queue)")
                print(f"  {Fore.YELLOW}[4]{Style.RESET_ALL} Delete messages from a specific Personal DM / Group Chat (Pick from list)")
                print(f"  {Fore.YELLOW}[5]{Style.RESET_ALL} Delete messages from a Discord Server (Guild)")
                print(f"  {Fore.YELLOW}[6]{Style.RESET_ALL} Exit")

                choice = input(f"\n{Fore.GREEN}Select option [1-6]: {Style.RESET_ALL}").strip()

                if choice == "1":
                    process_all_dms_queue(headers, user_id, base_delay, dry_run, include_hidden=False)
                    if not prompt_next_action():
                        break
                    continue
                elif choice == "2":
                    log_warn("Starting Deep Scan with ultra-slow human delays (2.5s - 4.5s per relationship) to prevent Discord detection...")
                    process_all_dms_queue(headers, user_id, base_delay, dry_run, include_hidden=True)
                    if not prompt_next_action():
                        break
                    continue
                elif choice == "3":
                    print(f"\n{Fore.GREEN}Enter Target User ID(s):{Style.RESET_ALL}")
                    print(f"{Fore.CYAN}Tip: Enter a single User ID, or paste multiple IDs separated by commas, spaces, or newlines.{Style.RESET_ALL}")
                    raw_input_ids = input(f"{Fore.YELLOW}Target User ID(s): {Style.RESET_ALL}").strip()
                    
                    parsed_uids = list(dict.fromkeys(re.findall(r"\d+", raw_input_ids)))
                    if not parsed_uids:
                        log_error("No valid User IDs detected!")
                        if not prompt_next_action():
                            break
                        continue
                    
                    process_bulk_user_queue(headers, parsed_uids, user_id, base_delay, dry_run)
                    if not prompt_next_action():
                        break
                    continue
                elif choice == "4":
                    target_channel_id = select_dm_channel(headers)
                    if not target_channel_id:
                        log_error("DM Channel selection failed!")
                        if not prompt_next_action():
                            break
                        continue
                elif choice == "5":
                    target_guild_id = select_guild_server(headers)
                    if not target_guild_id:
                        log_error("Server selection failed!")
                        if not prompt_next_action():
                            break
                        continue
                elif choice == "6":
                    log_info("Exiting tool. Goodbye!")
                    break
                else:
                    log_error("Invalid selection!")
                    if not prompt_next_action():
                        break
                    continue

            # Message Collection for Guild or Single DM/Channel
            messages_to_delete: List[Dict[str, Any]] = []

            if target_channel_id:
                messages_to_delete = scan_channel_user_messages(headers, target_channel_id, user_id, label="target chat")
            elif target_guild_id:
                messages_to_delete = search_guild_user_messages(headers, target_guild_id, user_id)

                if not messages_to_delete:
                    log_warn("Search index yielded 0 results. Scanning channels individually...")
                    channels = fetch_guild_channels(headers, target_guild_id)
                    log_info(f"Found {len(channels)} text channels in server.")
                    
                    for idx, ch in enumerate(channels, 1):
                        ch_name = ch.get("name", ch.get("id"))
                        log_info(f"[{idx}/{len(channels)}] Scanning #{ch_name}...")
                        ch_msgs = scan_channel_user_messages(headers, ch["id"], user_id, label=f"#{ch_name}")
                        if ch_msgs:
                            messages_to_delete.extend(ch_msgs)

            total_msgs = len(messages_to_delete)
            if total_msgs == 0:
                log_warn("No sent messages found in the selected target scope!")
                if args.channel or args.guild:
                    break
                if not prompt_next_action():
                    break
                continue

            log_success(f"Total messages queued for deletion: {Fore.YELLOW}{total_msgs}{Style.RESET_ALL}")

            if not dry_run and not auto_yes:
                confirm = input(f"\n{Fore.RED}Are you sure you want to delete all {total_msgs} messages? (y/N): {Style.RESET_ALL}").strip().lower()
                if confirm != 'y':
                    log_info("Operation cancelled by user.")
                    if args.channel or args.guild:
                        break
                    if not prompt_next_action():
                        break
                    continue

            # Execute batch deletion
            del_count, fail_count = delete_message_batch(headers, messages_to_delete, base_delay, dry_run)

            print(f"\n{Fore.MAGENTA}====================================================={Style.RESET_ALL}")
            print(f"{Fore.MAGENTA}                  SUMMARY REPORT                     {Style.RESET_ALL}")
            print(f"{Fore.MAGENTA}====================================================={Style.RESET_ALL}")
            log_info(f"Total Target Messages : {total_msgs}")
            log_success(f"Successfully Deleted   : {del_count}")
            if fail_count > 0:
                log_error(f"Failed Deletions      : {fail_count}")
            print(f"{Fore.MAGENTA}====================================================={Style.RESET_ALL}\n")

            # If CLI flags were provided, exit after one run
            if args.channel or args.guild:
                break

            # Prompt user whether to return to main menu or exit
            if not prompt_next_action():
                break

    except (KeyboardInterrupt, EOFError):
        log_info("\nExiting tool cleanly. Goodbye!")
        sys.exit(0)

if __name__ == "__main__":
    main()


