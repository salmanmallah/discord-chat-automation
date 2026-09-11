import argparse
import base64
import getpass
import json
import os
import random
import re
import sys
import time
from typing import Any

import requests
from colorama import Fore, Style, init
from dotenv import load_dotenv
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

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
UNHIDE_PRE_DELAY = 5.0                # Delay in seconds BEFORE unhiding/opening a closed DM (Anti-Ban Guard)
UNHIDE_POST_DELAY = 5.0               # Delay in seconds AFTER unhiding before scanning messages (Anti-Ban Guard)
BETWEEN_UNHIDE_REST_MIN = 5.0         # Rest range between sequential unhide & delete chats
BETWEEN_UNHIDE_REST_MAX = 8.0
BETWEEN_CHAT_REST_MIN = 4.0           # Rest between different active DM chats
BETWEEN_CHAT_REST_MAX = 8.0
BETWEEN_USER_REST_MIN = 5.0           # Rest between user ID queue items
BETWEEN_USER_REST_MAX = 8.0
BETWEEN_GUILD_REST_MIN = 6.0          # Rest cooldown between sequential server (guild) deletions
BETWEEN_GUILD_REST_MAX = 10.0

# Non-blocking Keyboard Detection for Spacebar Skip (Windows standard library)
try:
    import msvcrt
    HAS_MSVCRT = True
except ImportError:
    HAS_MSVCRT = False

# Global Skip Controller
SKIP_ENABLED = False

class SkipCurrentTargetException(Exception):
    """Raised when user presses Spacebar to skip the current server or chat."""

class TokenRevokedException(Exception):
    """Raised when Discord API returns HTTP 401 (token invalidated/expired)."""

def flush_key_buffer() -> None:
    """Flushes buffered keystrokes to ensure previous keys do not cause unwanted skips."""
    if HAS_MSVCRT:
        while msvcrt.kbhit():
            ch = msvcrt.getch()
            if ch in (b'\x00', b'\xe0') and msvcrt.kbhit():
                msvcrt.getch()

def check_skip_pressed() -> bool:
    """Checks non-blocking if Spacebar (or 's'/'S') was pressed, safely ignoring extended keycodes."""
    if HAS_MSVCRT:
        while msvcrt.kbhit():
            ch = msvcrt.getch()
            if ch in (b'\x00', b'\xe0'):
                if msvcrt.kbhit():
                    msvcrt.getch()
                continue
            if ch in (b' ', b's', b'S'):
                return True
    return False

def enable_skip() -> None:
    """Enables Spacebar skip listening for the current target and clears key buffer."""
    global SKIP_ENABLED
    flush_key_buffer()
    SKIP_ENABLED = True

def disable_skip() -> None:
    """Disables Spacebar skip listening."""
    global SKIP_ENABLED
    SKIP_ENABLED = False

def safe_sleep(seconds: float, jitter: float = 1.0) -> None:
    """
    Sleeps with randomized human-like jitter while remaining responsive to Spacebar skip key.
    Checks keyboard input every 50ms so Spacebar reacts immediately.
    """
    jitter_amount = random.uniform(0.2, max(0.2, jitter))
    actual_delay = max(0.2, seconds + jitter_amount)
    if random.random() < 0.05:
        actual_delay += random.uniform(1.5, 4.0)

    end_time = time.time() + actual_delay
    while time.time() < end_time:
        if SKIP_ENABLED and check_skip_pressed():
            raise SkipCurrentTargetException("Skipped by user via Spacebar")
        remaining = end_time - time.time()
        if remaining <= 0:
            break
        time.sleep(min(0.05, max(0.01, remaining)))

def print_banner() -> None:
    print(f"\n{Fore.CYAN}+---------------------------------------------------------+{Style.RESET_ALL}")
    print(f"{Fore.CYAN}| {Fore.MAGENTA}          DISCORD AUTOMATED MESSAGE DELETER v2.2        {Fore.CYAN}|{Style.RESET_ALL}")
    print(f"{Fore.CYAN}| {Fore.YELLOW}       [ Server Guilds & Personal DMs Automation ]       {Fore.CYAN}|{Style.RESET_ALL}")
    print(f"{Fore.CYAN}| {Fore.GREEN}        (Enhanced Anti-Ban & Rate-Limit Shield)          {Fore.CYAN}|{Style.RESET_ALL}")
    print(f"{Fore.CYAN}+---------------------------------------------------------+{Style.RESET_ALL}\n")

def log_info(msg: str) -> None:
    print(f"{Fore.CYAN}[*]{Style.RESET_ALL} {msg}")

def log_success(msg: str) -> None:
    print(f"{Fore.GREEN}[+]{Style.RESET_ALL} {msg}")

def log_warn(msg: str) -> None:
    print(f"{Fore.YELLOW}[!]{Style.RESET_ALL} {msg}")

def log_error(msg: str) -> None:
    print(f"{Fore.RED}[-]{Style.RESET_ALL} {msg}")

def extract_retry_after(response: requests.Response, default: float = 2.0) -> float:
    """Safely extracts retry_after duration from a Discord rate limit response."""
    try:
        data = response.json()
        if isinstance(data, dict):
            return float(data.get("retry_after", default))
    except (ValueError, requests.RequestException, AttributeError):
        pass
    return default

def get_headers(token: str) -> dict[str, str]:
    """Returns HTTP headers mimicking a real Discord client to reduce detection risk."""
    clean_token = token.strip().strip('"').strip("'")
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
        "Authorization": clean_token,
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

def create_session(token: str) -> requests.Session:
    """Creates a persistent requests.Session with connection pooling, keep-alive, and browser headers."""
    session = requests.Session()
    headers = get_headers(token)
    session.headers.update(headers)
    retries = Retry(
        total=3,
        connect=3,
        backoff_factor=0.3,
        status_forcelist=[502, 503, 504],
        raise_on_status=False,
    )
    adapter = HTTPAdapter(pool_connections=10, pool_maxsize=25, max_retries=retries)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session

def verify_token(session: requests.Session) -> dict[str, Any] | None:
    """Verifies the authorization token and returns user details."""
    try:
        res = session.get(f"{DISCORD_API_BASE}/users/@me", timeout=12)
        if res.status_code == 200:
            return res.json()
        elif res.status_code == 401:
            log_error("Invalid or expired Discord User Token!")
            return None
        else:
            log_error(f"Authentication failed. HTTP {res.status_code}: {res.text}")
            return None
    except requests.RequestException as e:
        log_error(f"Network error during authentication check: {e}")
        return None

def fetch_user_guilds(session: requests.Session) -> list[dict[str, Any]]:
    """Fetches all Discord servers (guilds) joined by the user with rate limit protection."""
    guilds: list[dict[str, Any]] = []
    after = None
    consecutive_rate_limits = 0
    
    while True:
        url = f"{DISCORD_API_BASE}/users/@me/guilds?limit=100"
        if after:
            url += f"&after={after}"
            
        try:
            res = session.get(url, timeout=12)
            if res.status_code == 200:
                consecutive_rate_limits = 0
                batch = res.json()
                if not batch:
                    break
                guilds.extend(batch)
                if len(batch) < 100:
                    break
                after = batch[-1]["id"]
                safe_sleep(1.5, 0.8)
            elif res.status_code == 429:
                consecutive_rate_limits += 1
                if consecutive_rate_limits > MAX_API_RETRIES:
                    log_error(f"Exceeded max retries ({MAX_API_RETRIES}) fetching servers.")
                    break
                retry = extract_retry_after(res, 2.0)
                backoff = retry + 1.5 + (consecutive_rate_limits * 1.0)
                log_warn(f"Rate limited while fetching servers (attempt {consecutive_rate_limits}/{MAX_API_RETRIES}). Waiting {backoff:.2f}s...")
                safe_sleep(backoff, 1.5)
            elif res.status_code == 401:
                raise TokenRevokedException("Discord token expired or revoked.")
            else:
                log_error(f"Failed to fetch servers. HTTP {res.status_code}: {res.text}")
                break
        except (SkipCurrentTargetException, TokenRevokedException):
            raise
        except requests.RequestException as e:
            log_error(f"Error fetching servers: {e}")
            break
            
    return guilds

def select_guild_server(session: requests.Session) -> str | None:
    """Interactively lists joined Discord servers and lets the user pick one, enter an ID, or select ALL servers."""
    log_info("Fetching your joined Discord Servers (Guilds)...")
    guilds = fetch_user_guilds(session)
    
    print(f"\n{Fore.GREEN}Select a Discord Server:{Style.RESET_ALL}")
    print(f"  {Fore.YELLOW}[0]{Style.RESET_ALL} Enter Server (Guild) ID manually")
    if guilds:
        print(f"  {Fore.CYAN}[A]{Style.RESET_ALL} Delete sent messages across {Fore.GREEN}ALL {len(guilds)} Servers / Groups{Style.RESET_ALL} (Queue with Cooldown)")
    
    guild_options = []
    for idx, g in enumerate(guilds, 1):
        g_id = g["id"]
        g_name = g.get("name", "Unknown Server")
        is_owner = " (Owner)" if g.get("owner") else ""
        
        guild_options.append((g_id, g_name))
        print(f"  {Fore.YELLOW}[{idx}]{Style.RESET_ALL} {g_name}{is_owner} (ID: {g_id})")

    try:
        choice = input(f"\n{Fore.GREEN}Choose option [0-{len(guild_options)}, or 'A' for all groups]: {Style.RESET_ALL}").strip()
        if choice.lower() in ("a", "all"):
            return "ALL"
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

def fetch_user_dms(session: requests.Session) -> list[dict[str, Any]]:
    """Fetches user's active DM channels with rate-limit handling and retry cap."""
    for attempt in range(1, MAX_API_RETRIES + 1):
        try:
            res = session.get(f"{DISCORD_API_BASE}/users/@me/channels", timeout=12)
            if res.status_code == 200:
                return res.json()
            elif res.status_code == 429:
                retry = extract_retry_after(res, 2.0)
                backoff = retry + 1.5 + (attempt * 1.0)
                log_warn(f"Rate limited while fetching DMs (attempt {attempt}/{MAX_API_RETRIES}). Waiting {backoff:.2f}s...")
                safe_sleep(backoff, 1.5)
            elif res.status_code == 401:
                raise TokenRevokedException("Discord token expired or revoked.")
            else:
                log_error(f"Failed to fetch DMs. HTTP {res.status_code}: {res.text}")
                return []
        except (SkipCurrentTargetException, TokenRevokedException):
            raise
        except requests.RequestException as e:
            log_error(f"Error fetching DMs: {e}")
            return []
    log_error(f"Exceeded max retries ({MAX_API_RETRIES}) fetching DMs.")
    return []

def fetch_user_relationships(session: requests.Session) -> list[dict[str, Any]]:
    """Fetches user's friends and relationships with rate-limit protection and retry cap."""
    for attempt in range(1, MAX_API_RETRIES + 1):
        try:
            res = session.get(f"{DISCORD_API_BASE}/users/@me/relationships", timeout=12)
            if res.status_code == 200:
                return res.json()
            elif res.status_code == 429:
                retry = extract_retry_after(res, 2.0)
                backoff = retry + 2.5 + (attempt * 1.5)
                log_warn(f"Rate limited on relationships (attempt {attempt}/{MAX_API_RETRIES}). Waiting {backoff:.2f}s...")
                safe_sleep(backoff, 2.0)
            elif res.status_code == 401:
                raise TokenRevokedException("Discord token expired or revoked.")
            else:
                return []
        except (SkipCurrentTargetException, TokenRevokedException):
            raise
        except requests.RequestException as e:
            log_warn(f"Could not fetch relationships: {e}")
            return []
    log_error(f"Exceeded max retries ({MAX_API_RETRIES}) fetching relationships.")
    return []

def discover_all_dm_chats(session: requests.Session) -> list[dict[str, Any]]:
    """Discovers all currently active Personal DM and Group chats safely without opening closed DMs."""
    all_dms: dict[str, dict[str, Any]] = {}
    
    log_info("Fetching active Personal DM & Group chats...")
    active_dms = fetch_user_dms(session)
    for dm in active_dms:
        dm_id = dm.get("id")
        if dm_id:
            all_dms[dm_id] = dm

    log_info(f"Found {Fore.YELLOW}{len(all_dms)}{Style.RESET_ALL} active/open DM chat(s).")
    return list(all_dms.values())

def select_dm_channel(session: requests.Session) -> str | None:
    """Interactively lists DMs and lets the user pick one or type a Channel ID."""
    log_info("Fetching your active Direct Messages (DMs)...")
    dms = fetch_user_dms(session)
    
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

def get_or_create_dm_by_user_id(session: requests.Session, target_user_id: str) -> dict[str, Any] | None:
    """Opens or retrieves an existing DM channel with a target user by User ID with rate-limit safety and retry cap."""
    target_user_id = target_user_id.strip()
    if not target_user_id:
        log_error("User ID cannot be empty!")
        return None

    log_info(f"Resolving DM channel for User ID: {Fore.YELLOW}{target_user_id}{Style.RESET_ALL}...")

    for attempt in range(1, MAX_API_RETRIES + 1):
        try:
            payload = {"recipient_id": target_user_id}
            res = session.post(f"{DISCORD_API_BASE}/users/@me/channels", json=payload, timeout=12)
            
            if res.status_code in (200, 201):
                dm_data = res.json()
                recipients = dm_data.get("recipients", [])
                recipient_name = recipients[0].get("username", "Unknown") if recipients else target_user_id
                log_success(f"Located DM channel with: {Fore.GREEN}{recipient_name}{Style.RESET_ALL} (Channel ID: {dm_data.get('id')})")
                return dm_data
            elif res.status_code == 429:
                retry = extract_retry_after(res, 2.0)
                backoff = retry + 2.0 + (attempt * 1.5)
                log_warn(f"Rate limited while opening DM (attempt {attempt}/{MAX_API_RETRIES}). Waiting {backoff:.2f}s...")
                safe_sleep(backoff, 2.0)
            elif res.status_code == 400:
                log_error(f"Cannot open DM with User ID {target_user_id}. (Invalid User ID or self-DM not allowed)")
                return None
            elif res.status_code == 401:
                raise TokenRevokedException("Discord token expired or revoked.")
            elif res.status_code == 403:
                log_error(f"Cannot open DM with User ID {target_user_id}. (DMs closed or blocked by user)")
                return None
            else:
                log_error(f"Failed to open DM. HTTP {res.status_code}: {res.text}")
                return None
        except (SkipCurrentTargetException, TokenRevokedException):
            raise
        except requests.RequestException as e:
            log_error(f"Error resolving DM channel by User ID: {e}")
            return None

    log_error(f"Exceeded max retries ({MAX_API_RETRIES}) opening DM with User ID {target_user_id}.")
    return None

def close_dm_channel(session: requests.Session, channel_id: str) -> bool:
    """Closes / re-hides an open DM channel so it does not clutter the user's Discord client sidebar."""
    try:
        res = session.delete(f"{DISCORD_API_BASE}/channels/{channel_id}", timeout=10)
        return res.status_code in (200, 204)
    except requests.RequestException:
        return False

def fetch_guild_channels(session: requests.Session, guild_id: str) -> list[dict[str, Any]]:
    """Fetches text channels in a guild with rate-limit protection and retry cap."""
    for attempt in range(1, MAX_API_RETRIES + 1):
        try:
            res = session.get(f"{DISCORD_API_BASE}/guilds/{guild_id}/channels", timeout=12)
            if res.status_code == 200:
                channels = res.json()
                # Types: 0=Text, 2=Voice (with text chat), 5=Announcement
                return [c for c in channels if c.get("type") in (0, 2, 5)]
            elif res.status_code == 429:
                retry = extract_retry_after(res, 2.0)
                backoff = retry + 1.5 + (attempt * 1.0)
                log_warn(f"Rate limited while fetching channels (attempt {attempt}/{MAX_API_RETRIES}). Retrying in {backoff:.2f}s...")
                safe_sleep(backoff, 1.5)
            elif res.status_code == 401:
                raise TokenRevokedException("Discord token expired or revoked.")
            else:
                log_error(f"Failed to fetch guild channels. HTTP {res.status_code}: {res.text}")
                return []
        except (SkipCurrentTargetException, TokenRevokedException):
            raise
        except requests.RequestException as e:
            log_error(f"Error fetching guild channels: {e}")
            return []
    log_error(f"Exceeded max retries ({MAX_API_RETRIES}) fetching guild channels.")
    return []

def search_guild_user_messages(session: requests.Session, guild_id: str, user_id: str) -> list[dict[str, Any]]:
    """Uses Discord Guild Search API to find messages sent by the user across the entire guild."""
    log_info(f"Searching for your messages across server (Guild ID: {guild_id})...")
    messages: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    offset = 0
    consecutive_rate_limits = 0
    
    while True:
        if offset >= 5000:
            log_warn(f"Reached Discord Search API maximum indexing limit (5000 messages). Continuing with {len(messages)} collected messages.")
            break

        url = f"{DISCORD_API_BASE}/guilds/{guild_id}/messages/search?author_id={user_id}&offset={offset}"
        try:
            res = session.get(url, timeout=12)
            if res.status_code == 200:
                consecutive_rate_limits = 0
                data = res.json()
                total_results = data.get("total_results", 0)
                msg_groups = data.get("messages", [])
                
                if offset == 0:
                    log_info(f"Total messages found in server search index: {Fore.YELLOW}{total_results}{Style.RESET_ALL}")
                    if total_results > 5000:
                        log_warn(f"Note: Server has {total_results} indexed messages. Discord API allows searching up to 5,000 per query.")

                if not msg_groups:
                    break

                for group in msg_groups:
                    for msg in group:
                        msg_id = msg.get("id")
                        if msg_id and msg.get("author", {}).get("id") == user_id and msg_id not in seen_ids:
                            seen_ids.add(msg_id)
                            messages.append({
                                "id": msg_id,
                                "channel_id": msg["channel_id"],
                                "content": msg.get("content", ""),
                                "timestamp": msg.get("timestamp", "")
                            })

                offset += 25
                safe_sleep(BASE_SEARCH_DELAY, 1.0)
            elif res.status_code == 429:
                consecutive_rate_limits += 1
                if consecutive_rate_limits > MAX_API_RETRIES:
                    log_error(f"Exceeded max consecutive rate limits ({MAX_API_RETRIES}) on Search API. Halting search.")
                    break
                retry = extract_retry_after(res, 2.5)
                backoff = retry + 3.0 + (consecutive_rate_limits * 1.0)
                log_warn(f"Search API Rate limited (attempt {consecutive_rate_limits}/{MAX_API_RETRIES}). Waiting {backoff:.2f} seconds...")
                safe_sleep(backoff, 2.0)
            elif res.status_code == 202:
                log_warn("Discord is indexing messages for this server. Retrying in 8s...")
                safe_sleep(8.0, 2.0)
            elif res.status_code == 400 and offset >= 5000:
                log_warn(f"Search API maximum offset limit reached. Processed {len(messages)} messages.")
                break
            elif res.status_code == 401:
                raise TokenRevokedException("Discord token expired or revoked.")
            else:
                log_warn(f"Guild Search API failed or disabled (HTTP {res.status_code}). Falling back to channel scan.")
                break
        except (SkipCurrentTargetException, TokenRevokedException):
            raise
        except requests.RequestException as e:
            log_error(f"Error calling Search API: {e}")
            break
            
    return messages

def scan_channel_user_messages(session: requests.Session, channel_id: str, user_id: str, label: str = "channel") -> list[dict[str, Any]]:
    """Scans history of a single channel (Guild Channel or DM) for messages by user_id with safe pacing."""
    log_info(f"Scanning message history in {label} (ID: {channel_id})...")
    messages: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    before = None
    scanned_count = 0
    consecutive_rate_limits = 0
    
    while True:
        if SKIP_ENABLED and check_skip_pressed():
            raise SkipCurrentTargetException("Skipped by user via Spacebar")

        url = f"{DISCORD_API_BASE}/channels/{channel_id}/messages?limit=100"
        if before:
            url += f"&before={before}"

        try:
            res = session.get(url, timeout=12)
            if res.status_code == 200:
                consecutive_rate_limits = 0
                batch = res.json()
                if not batch:
                    break
                
                scanned_count += len(batch)
                for msg in batch:
                    msg_id = msg.get("id")
                    if msg_id and msg.get("author", {}).get("id") == user_id and msg_id not in seen_ids:
                        seen_ids.add(msg_id)
                        messages.append({
                            "id": msg_id,
                            "channel_id": channel_id,
                            "content": msg.get("content", ""),
                            "timestamp": msg.get("timestamp", "")
                        })
                
                before = batch[-1]["id"]
                print(f"\r{Fore.CYAN}[*]{Style.RESET_ALL} Scanned {scanned_count} messages, found {len(messages)} matching...", end="", flush=True)
                safe_sleep(BASE_SCAN_DELAY, 0.8)
            elif res.status_code == 429:
                consecutive_rate_limits += 1
                if consecutive_rate_limits > MAX_API_RETRIES:
                    log_error(f"\nExceeded max consecutive rate limits ({MAX_API_RETRIES}) scanning channel. Halting channel scan.")
                    break
                retry = extract_retry_after(res, 2.0)
                backoff = retry + 2.5 + (consecutive_rate_limits * 1.0)
                log_warn(f"\nRate limited during message scan (attempt {consecutive_rate_limits}/{MAX_API_RETRIES}). Waiting {backoff:.2f}s...")
                safe_sleep(backoff, 1.5)
            elif res.status_code == 401:
                log_error("Discord User Token was revoked, expired, or logged out! (HTTP 401 Unauthorized)")
                raise TokenRevokedException("Discord token expired or revoked.")
            elif res.status_code == 403:
                log_error(f"Cannot access channel {channel_id} (Missing Permissions).")
                break
            else:
                log_error(f"Failed to scan channel. HTTP {res.status_code}: {res.text}")
                break
        except (SkipCurrentTargetException, TokenRevokedException):
            raise
        except requests.RequestException as e:
            log_error(f"Error scanning channel {channel_id}: {e}")
            break

    print()
    return messages

def delete_message(session: requests.Session, channel_id: str, message_id: str) -> tuple[bool, bool]:
    """
    Sends DELETE request for a single message and handles rate limits safely with retry cap.
    Returns (success: bool, hit_rate_limit: bool)
    """
    url = f"{DISCORD_API_BASE}/channels/{channel_id}/messages/{message_id}"
    hit_rate_limit = False
    
    for attempt in range(1, MAX_API_RETRIES + 1):
        try:
            res = session.delete(url, timeout=12)
            if res.status_code == 204:
                return True, hit_rate_limit
            elif res.status_code == 429:
                hit_rate_limit = True
                retry = extract_retry_after(res, 1.8)
                backoff = retry + 1.5 + (attempt * 0.5)
                log_warn(f"Rate limited by Discord (attempt {attempt}/{MAX_API_RETRIES}). Waiting {backoff:.2f}s...")
                safe_sleep(backoff, 1.5)
            elif res.status_code in (404, 200):
                return True, hit_rate_limit
            elif res.status_code == 401:
                log_error("Discord User Token was revoked, expired, or logged out! (HTTP 401 Unauthorized)")
                raise TokenRevokedException("Discord token expired or revoked.")
            elif res.status_code == 403:
                log_error(f"Missing permissions to delete message {message_id}")
                return False, hit_rate_limit
            else:
                log_error(f"Failed to delete message {message_id}. HTTP {res.status_code}: {res.text}")
                return False, hit_rate_limit
        except (SkipCurrentTargetException, TokenRevokedException):
            raise
        except requests.RequestException as e:
            log_error(f"Network error during deletion: {e}")
            return False, hit_rate_limit
    
    log_error(f"Exceeded max retries ({MAX_API_RETRIES}) deleting message {message_id}.")
    return False, hit_rate_limit

def delete_message_batch(
    session: requests.Session,
    messages_to_delete: list[dict[str, Any]],
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
            if SKIP_ENABLED and check_skip_pressed():
                raise SkipCurrentTargetException("Skipped by user via Spacebar")

            msg_id = msg["id"]
            ch_id = msg["channel_id"]
            content = msg.get("content", "")
            preview = (content[:40] + "...") if len(content) > 40 else content
            preview = preview.replace("\n", " ")

            if dry_run:
                print(f"[{idx}/{total_msgs}] [DRY-RUN] Would delete Msg ID {msg_id}: '{preview}'")
                deleted_count += 1
            else:
                print(f"[{idx}/{total_msgs}] Deleting Msg ID {msg_id}: '{preview}' ... ", end="", flush=True)
                success, hit_rl = delete_message(session, ch_id, msg_id)
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

    except (SkipCurrentTargetException, TokenRevokedException):
        raise
    except KeyboardInterrupt:
        log_warn("\nDeletion interrupted by user (Ctrl+C).")

    return deleted_count, failed_count

def process_bulk_user_queue(
    session: requests.Session,
    user_ids: list[str],
    my_user_id: str,
    base_delay: float,
    dry_run: bool
) -> None:
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
        print(f"{Fore.CYAN}  Tip: Press [SPACE] at any time to skip this user and move to next!{Style.RESET_ALL}")
        print(f"{Fore.MAGENTA}====================================================={Style.RESET_ALL}")

        enable_skip()
        try:
            # Anti-Ban Guard: 5-second delay BEFORE unhiding/resolving DM
            log_info(f"Pausing {UNHIDE_PRE_DELAY:.1f}s before resolving/unhiding DM with User ID {uid}...")
            safe_sleep(UNHIDE_PRE_DELAY, 1.5)

            dm_data = get_or_create_dm_by_user_id(session, uid)
            if not dm_data:
                log_error(f"Skipping User ID {uid} (Cannot open DM).")
                user_results.append((uid, "Failed to open DM", 0, 0, 0))
                continue

            # Anti-Ban Guard: 5-second delay AFTER unhiding before scanning messages
            log_info(f"Pausing {UNHIDE_POST_DELAY:.1f}s after unhide before scanning message history...")
            safe_sleep(UNHIDE_POST_DELAY, 1.5)

            ch_id = dm_data.get("id")
            recipients = dm_data.get("recipients", [])
            recipient_name = recipients[0].get("username", uid) if recipients else uid

            msgs = scan_channel_user_messages(session, ch_id, my_user_id, label=f"DM with @{recipient_name}")
            total_msgs = len(msgs)

            if total_msgs == 0:
                log_warn(f"No messages sent by you found in chat with @{recipient_name}.")
                user_results.append((uid, f"@{recipient_name}", 0, 0, 0))
            else:
                log_success(f"Found {Fore.YELLOW}{total_msgs}{Style.RESET_ALL} sent messages in chat with @{recipient_name}. Deleting now...")
                del_cnt, fail_cnt = delete_message_batch(session, msgs, base_delay, dry_run)
                grand_total_found += total_msgs
                grand_total_deleted += del_cnt
                grand_total_failed += fail_cnt
                user_results.append((uid, f"@{recipient_name}", total_msgs, del_cnt, fail_cnt))

        except SkipCurrentTargetException:
            print(f"\n{Fore.YELLOW}[>>] [SPACE] pressed! Skipped user ID: {Fore.CYAN}{uid}{Fore.YELLOW} -> Moving to next user...{Style.RESET_ALL}")
            user_results.append((uid, f"User {uid} (Skipped)", 0, 0, 0))
        finally:
            disable_skip()

        # Rest between users in queue (5s - 8s)
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
    session: requests.Session,
    my_user_id: str,
    base_delay: float,
    dry_run: bool,
    include_hidden: bool = False
) -> None:
    """
    Processes Personal DMs with anti-ban sequential workflow:
    - Phase 1: Cleans currently active open DMs (safe, no unhiding needed).
    - Phase 2 (Optional Deep Scan): Unhides 1 closed friend DM -> 5s delay -> Deletes its messages -> 5s rest -> Next friend.
    """
    # ── PHASE 1: Active Open DMs ──
    dm_list = discover_all_dm_chats(session)
    total_chats = len(dm_list)
    known_recipients = set()

    grand_total_found = 0
    grand_total_deleted = 0
    grand_total_failed = 0
    chat_results = []

    if total_chats > 0:
        log_info(f"Starting automatic queue deletion across {Fore.YELLOW}{total_chats}{Style.RESET_ALL} Active Open DM chat(s)... (Safe Paced)")

        for idx, dm in enumerate(dm_list, 1):
            dm_id = dm.get("id")
            dm_type = dm.get("type")
            recipients = dm.get("recipients", [])
            for r in recipients:
                if r.get("id"):
                    known_recipients.add(r["id"])

            if dm_type == 1 and recipients:
                name = f"@{recipients[0].get('username', 'Unknown')}"
            elif dm_type == 3:
                name = "Group: " + ", ".join([r.get("username", "") for r in recipients[:3]])
            else:
                name = f"DM ({dm_id})"

            print(f"\n{Fore.MAGENTA}====================================================={Style.RESET_ALL}")
            print(f"{Fore.MAGENTA}  ACTIVE DM [{idx}/{total_chats}] -> Chat: {Fore.YELLOW}{name}{Fore.MAGENTA} (ID: {dm_id}){Style.RESET_ALL}")
            print(f"{Fore.CYAN}  Tip: Press [SPACE] at any time to skip this chat and move to next!{Style.RESET_ALL}")
            print(f"{Fore.MAGENTA}====================================================={Style.RESET_ALL}")

            enable_skip()
            try:
                msgs = scan_channel_user_messages(session, dm_id, my_user_id, label=name)
                total_msgs = len(msgs)

                if total_msgs == 0:
                    log_info(f"No sent messages found in {name}. Continuing...")
                    chat_results.append((dm_id, name, 0, 0, 0))
                else:
                    log_success(f"Found {Fore.YELLOW}{total_msgs}{Style.RESET_ALL} sent messages in {name}. Deleting now...")
                    del_cnt, fail_cnt = delete_message_batch(session, msgs, base_delay, dry_run)
                    grand_total_found += total_msgs
                    grand_total_deleted += del_cnt
                    grand_total_failed += fail_cnt
                    chat_results.append((dm_id, name, total_msgs, del_cnt, fail_cnt))
            except SkipCurrentTargetException:
                print(f"\n{Fore.YELLOW}[>>] [SPACE] pressed! Skipped chat: {Fore.CYAN}{name}{Fore.YELLOW} -> Moving to next chat...{Style.RESET_ALL}")
                chat_results.append((dm_id, f"{name} (Skipped)", 0, 0, 0))
            finally:
                disable_skip()

            # Rest between active chats in queue (4s - 8s)
            if idx < total_chats:
                rest_time = random.uniform(BETWEEN_CHAT_REST_MIN, BETWEEN_CHAT_REST_MAX)
                log_info(f"Resting {rest_time:.1f}s before moving to next DM chat in queue...")
                safe_sleep(rest_time, 2.0)
    else:
        log_warn("No currently active/open DM chats found.")

    # ── PHASE 2: Safe Sequential Unhide for Hidden Friends DMs ──
    if include_hidden:
        print(f"\n{Fore.CYAN}====================================================={Style.RESET_ALL}")
        print(f"{Fore.CYAN}    PHASE 2: SAFE 1-BY-1 HIDDEN FRIENDS DM CLEANUP   {Style.RESET_ALL}")
        print(f"{Fore.CYAN}====================================================={Style.RESET_ALL}")
        log_info("Fetching friends/relationships to check for closed DMs...")
        relationships = fetch_user_relationships(session)

        friends_to_check = []
        if relationships:
            for rel in relationships:
                u_obj = rel.get("user", {})
                f_id = u_obj.get("id")
                f_name = u_obj.get("username", "Unknown")
                if f_id and f_id not in known_recipients:
                    friends_to_check.append((f_id, f_name))

        if not friends_to_check:
            log_info("No additional closed friend chats to process.")
        else:
            total_friends = len(friends_to_check)
            log_info(f"Identified {Fore.YELLOW}{total_friends}{Style.RESET_ALL} closed friend chat(s) to process sequentially.")
            log_info(f"{Fore.GREEN}[Safe Protocol Enforced]{Style.RESET_ALL} 5s Delay -> Unhide 1 Chat -> 5s Delay -> Delete Messages -> Re-Close Chat -> 5s Rest -> Next Chat")

            for idx, (f_id, f_name) in enumerate(friends_to_check, 1):
                print(f"\n{Fore.CYAN}-----------------------------------------------------{Style.RESET_ALL}")
                print(f"{Fore.CYAN}  HIDDEN CHAT [{idx}/{total_friends}] -> Friend: {Fore.YELLOW}@{f_name}{Fore.CYAN} (ID: {f_id}){Style.RESET_ALL}")
                print(f"{Fore.CYAN}  Tip: Press [SPACE] at any time to skip this friend chat and move to next!{Style.RESET_ALL}")
                print(f"{Fore.CYAN}-----------------------------------------------------{Style.RESET_ALL}")

                ch_id = None
                enable_skip()
                try:
                    # 1. Mandatory 5s delay BEFORE unhiding this single chat
                    log_info(f"Pausing {UNHIDE_PRE_DELAY:.1f}s before unhiding chat with @{f_name}...")
                    safe_sleep(UNHIDE_PRE_DELAY, 1.5)

                    # 2. Unhide/open this single chat
                    dm_data = get_or_create_dm_by_user_id(session, f_id)
                    if not dm_data or not dm_data.get("id"):
                        log_warn(f"Could not open/unhide DM with @{f_name}. Skipping to next friend...")
                        chat_results.append((f_id, f"@{f_name} (Unhide Failed)", 0, 0, 0))
                        safe_sleep(2.0, 1.0)
                        continue

                    ch_id = dm_data["id"]

                    # 3. Mandatory 5s delay AFTER unhiding before scanning messages
                    log_info(f"Pausing {UNHIDE_POST_DELAY:.1f}s after unhide before scanning messages...")
                    safe_sleep(UNHIDE_POST_DELAY, 1.5)

                    # 4. Scan & Delete messages inside this 1 chat
                    msgs = scan_channel_user_messages(session, ch_id, my_user_id, label=f"DM with @{f_name}")
                    total_msgs = len(msgs)

                    if total_msgs == 0:
                        log_info(f"No sent messages found in chat with @{f_name}.")
                        chat_results.append((ch_id, f"@{f_name}", 0, 0, 0))
                    else:
                        log_success(f"Found {Fore.YELLOW}{total_msgs}{Style.RESET_ALL} sent messages in chat with @{f_name}. Deleting now...")
                        del_cnt, fail_cnt = delete_message_batch(session, msgs, base_delay, dry_run)
                        grand_total_found += total_msgs
                        grand_total_deleted += del_cnt
                        grand_total_failed += fail_cnt
                        chat_results.append((ch_id, f"@{f_name}", total_msgs, del_cnt, fail_cnt))

                    # 5. Clean up: Re-hide/close this DM channel so client sidebar stays tidy
                    close_dm_channel(session, ch_id)

                except SkipCurrentTargetException:
                    print(f"\n{Fore.YELLOW}[>>] [SPACE] pressed! Skipped friend: {Fore.CYAN}@{f_name}{Fore.YELLOW} -> Moving to next friend...{Style.RESET_ALL}")
                    if ch_id:
                        close_dm_channel(session, ch_id)
                    chat_results.append((f_id, f"@{f_name} (Skipped)", 0, 0, 0))
                finally:
                    disable_skip()

                # 6. Rest 5s-8s after finishing this chat before moving to the next
                if idx < total_friends:
                    rest_time = random.uniform(BETWEEN_UNHIDE_REST_MIN, BETWEEN_UNHIDE_REST_MAX)
                    log_info(f"Resting {rest_time:.1f}s before proceeding to next friend chat...")
                    safe_sleep(rest_time, 2.0)

    # Print Grand Summary
    print(f"\n{Fore.MAGENTA}====================================================={Style.RESET_ALL}")
    print(f"{Fore.MAGENTA}          ALL DMs QUEUE GRAND SUMMARY REPORT         {Style.RESET_ALL}")
    print(f"{Fore.MAGENTA}====================================================={Style.RESET_ALL}")
    print(f"{'Channel ID':<20} | {'Target Chat':<20} | {'Found':<6} | {'Deleted':<8}")
    print(f"{'-'*65}")
    for ch_id, target_label, f_cnt, d_cnt, _ in chat_results:
        print(f"{ch_id:<20} | {target_label:<20} | {f_cnt:<6} | {d_cnt:<8}")
    print(f"{'-'*65}")
    log_info(f"Total DM Chats Checked : {len(chat_results)}")
    log_info(f"Total Messages Found   : {grand_total_found}")
    log_success(f"Total Messages Deleted : {grand_total_deleted}")
    if grand_total_failed > 0:
        log_error(f"Total Failed Deletions : {grand_total_failed}")
    print(f"{Fore.MAGENTA}====================================================={Style.RESET_ALL}\n")

def process_all_guilds_queue(
    session: requests.Session,
    my_user_id: str,
    base_delay: float,
    dry_run: bool,
    auto_yes: bool = False
) -> None:
    """Processes ALL joined Discord servers (guilds) sequentially with safe pacing and cooldowns."""
    log_info("Fetching your joined Discord Servers (Guilds)...")
    guilds = fetch_user_guilds(session)
    total_guilds = len(guilds)

    if total_guilds == 0:
        log_warn("No joined Discord servers found on this account.")
        return

    print(f"\n{Fore.CYAN}====================================================={Style.RESET_ALL}")
    print(f"{Fore.CYAN}   BULK ALL SERVERS QUEUE DELETION INITIALIZED       {Style.RESET_ALL}")
    print(f"{Fore.CYAN}====================================================={Style.RESET_ALL}")
    log_info(f"Loaded {Fore.YELLOW}{total_guilds}{Style.RESET_ALL} server(s) in queue.")
    log_info(f"{Fore.GREEN}[Safe Protocol Enforced]{Style.RESET_ALL} Scan 1 Server -> Delete Messages -> Rest Cooldown ({BETWEEN_GUILD_REST_MIN:.0f}s-{BETWEEN_GUILD_REST_MAX:.0f}s) -> Next Server")

    if not dry_run and not auto_yes:
        confirm = input(f"\n{Fore.RED}Are you sure you want to process and delete your messages across ALL {total_guilds} servers? (y/N): {Style.RESET_ALL}").strip().lower()
        if confirm != 'y':
            log_info("Operation cancelled by user.")
            return

    grand_total_found = 0
    grand_total_deleted = 0
    grand_total_failed = 0
    guild_results = []

    for idx, g in enumerate(guilds, 1):
        g_id = g["id"]
        g_name = g.get("name", "Unknown Server")

        print(f"\n{Fore.MAGENTA}====================================================={Style.RESET_ALL}")
        print(f"{Fore.MAGENTA}  SERVER [{idx}/{total_guilds}] -> {Fore.YELLOW}{g_name}{Fore.MAGENTA} (ID: {g_id}){Style.RESET_ALL}")
        print(f"{Fore.CYAN}  Tip: Press [SPACE] at any time to skip this server and move to next!{Style.RESET_ALL}")
        print(f"{Fore.MAGENTA}====================================================={Style.RESET_ALL}")

        messages_to_delete = []
        enable_skip()
        try:
            messages_to_delete = search_guild_user_messages(session, g_id, my_user_id)
            if not messages_to_delete:
                channels = fetch_guild_channels(session, g_id)
                if channels:
                    log_info(f"Checking {len(channels)} text channels in {g_name}...")
                    for ch in channels:
                        if SKIP_ENABLED and check_skip_pressed():
                            raise SkipCurrentTargetException("Skipped by user via Spacebar")
                        ch_msgs = scan_channel_user_messages(session, ch["id"], my_user_id, label=f"#{ch.get('name', ch['id'])}")
                        if ch_msgs:
                            messages_to_delete.extend(ch_msgs)

            total_msgs = len(messages_to_delete)
            if total_msgs == 0:
                log_info(f"No messages sent by you found in {g_name}. Moving forward...")
                guild_results.append((g_id, g_name, 0, 0, 0, "Clean (0 msgs)"))
            else:
                log_success(f"Found {Fore.YELLOW}{total_msgs}{Style.RESET_ALL} sent message(s) in {g_name}. Deleting now...")
                del_cnt, fail_cnt = delete_message_batch(session, messages_to_delete, base_delay, dry_run)
                grand_total_found += total_msgs
                grand_total_deleted += del_cnt
                grand_total_failed += fail_cnt
                guild_results.append((g_id, g_name, total_msgs, del_cnt, fail_cnt, "Completed"))

        except SkipCurrentTargetException:
            print(f"\n{Fore.YELLOW}[>>] [SPACE] pressed! Skipped server: {Fore.CYAN}{g_name}{Fore.YELLOW} -> Moving to next server...{Style.RESET_ALL}")
            guild_results.append((g_id, g_name, len(messages_to_delete), 0, 0, "Skipped by User"))
        finally:
            disable_skip()

        # Cooldown rest between servers
        if idx < total_guilds:
            rest_time = random.uniform(BETWEEN_GUILD_REST_MIN, BETWEEN_GUILD_REST_MAX)
            log_info(f"Resting {rest_time:.1f}s cooldown before moving to next server...")
            safe_sleep(rest_time, 2.0)

    # Print Grand Summary Report
    print(f"\n{Fore.MAGENTA}====================================================={Style.RESET_ALL}")
    print(f"{Fore.MAGENTA}        ALL SERVERS QUEUE GRAND SUMMARY REPORT       {Style.RESET_ALL}")
    print(f"{Fore.MAGENTA}====================================================={Style.RESET_ALL}")
    print(f"{'Server ID':<20} | {'Server Name':<22} | {'Found':<6} | {'Deleted':<8} | {'Status':<15}")
    print(f"{'-'*84}")
    for g_id, g_label, f_cnt, d_cnt, _, status_txt in guild_results:
        print(f"{g_id:<20} | {g_label[:20]:<22} | {f_cnt:<6} | {d_cnt:<8} | {status_txt:<15}")
    print(f"{'-'*84}")
    log_info(f"Total Servers Checked  : {total_guilds}")
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

def main() -> None:
    load_dotenv()

    parser = argparse.ArgumentParser(description="Discord Automated Message Deleter v2.2")
    parser.add_argument("token_pos", nargs="?", help="Optional Discord User Authorization Token (positional)")
    parser.add_argument("-t", "--token", help="Discord User Authorization Token")
    parser.add_argument("-g", "--guild", help="Discord Server / Guild ID")
    parser.add_argument("-c", "--channel", help="Specific Channel or DM ID")
    parser.add_argument("-u", "--user", "--users", nargs="*", help="Target User ID(s) (single or bulk queue)")
    parser.add_argument("--all-dms", action="store_true", help="Delete all sent messages across active personal DMs")
    parser.add_argument("--deep-all-dms", action="store_true", help="Deep scan: include hidden friends DMs (ultra-slow human delay)")
    parser.add_argument("--all-guilds", "--all-servers", action="store_true", help="Delete all sent messages across all joined Discord servers (guilds)")
    parser.add_argument("-y", "--yes", action="store_true", help="Auto-confirm all deletions without confirmation prompts")
    parser.add_argument("-d", "--delay", type=float, default=None, help="Delay between deletions in seconds (default: 2.0s - Anti-Ban Protected)")
    parser.add_argument("--dry-run", action="store_true", help="Preview messages without deleting them")
    args = parser.parse_args()

    print_banner()

    session: requests.Session | None = None
    try:
        # Get Token with getpass (Hidden prompt like Linux password entry)
        token = args.token or args.token_pos or os.getenv("DISCORD_USER_TOKEN")
        if not token:
            token = getpass.getpass(f"{Fore.YELLOW}Enter Discord User Token (hidden input): {Style.RESET_ALL}").strip()

        if not token:
            log_error("Token is required to proceed!")
            sys.exit(1)

        token = token.strip().strip('"').strip("'")
        if token.lower().startswith("bot "):
            log_error("A Bot token was provided! This tool is designed for Discord User Accounts to delete personal messages.")
            log_warn("Please provide your personal Discord User Authorization Token.")
            sys.exit(1)

        # Create persistent session with keep-alive & connection pooling
        session = create_session(token)

        # Verify Token
        user_info = verify_token(session)
        if not user_info:
            sys.exit(1)

        username = f"{user_info.get('username')} (ID: {user_info.get('id')})"
        user_id = user_info.get("id")
        log_success(f"Authenticated as: {Fore.GREEN}{username}{Style.RESET_ALL}")

        env_delay = os.getenv("DELETE_DELAY")
        if args.delay is not None:
            base_delay = args.delay
        elif env_delay:
            try:
                base_delay = float(env_delay)
            except ValueError:
                base_delay = 2.0
        else:
            base_delay = 2.0

        dry_run = args.dry_run or (os.getenv("DRY_RUN", "false").lower() == "true")
        auto_yes = args.yes or (os.getenv("AUTO_CONFIRM", "false").lower() == "true")

        if dry_run:
            log_warn(f"{Fore.YELLOW}DRY RUN MODE ENABLED: No messages will be deleted.{Style.RESET_ALL}")

        # CLI All Servers / Guilds handling
        if args.all_guilds:
            process_all_guilds_queue(session, user_id, base_delay, dry_run, auto_yes)
            sys.exit(0)

        # CLI All DMs handling
        if args.deep_all_dms:
            process_all_dms_queue(session, user_id, base_delay, dry_run, include_hidden=True)
            sys.exit(0)
        elif args.all_dms:
            process_all_dms_queue(session, user_id, base_delay, dry_run, include_hidden=False)
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
                process_bulk_user_queue(session, cli_user_ids, user_id, base_delay, dry_run)
                break

            if not target_channel_id and not target_guild_id:
                print(f"\n{Fore.GREEN}Select Deletion Scope:{Style.RESET_ALL}")
                print(f"  {Fore.YELLOW}[1]{Style.RESET_ALL} Delete ALL Sent Messages in Active Open DMs (Safe Pace: 2-3s)")
                print(f"  {Fore.YELLOW}[2]{Style.RESET_ALL} Deep Scan & Delete: Include Hidden Friends DMs (Safe 1-by-1 Unhide with 5s Delays & Auto Re-Close)")
                print(f"  {Fore.YELLOW}[3]{Style.RESET_ALL} Delete messages by User ID(s) (Single or Bulk Queue)")
                print(f"  {Fore.YELLOW}[4]{Style.RESET_ALL} Delete messages from a specific Personal DM / Group Chat (Pick from list)")
                print(f"  {Fore.YELLOW}[5]{Style.RESET_ALL} Delete messages from a specific Discord Server (Guild)")
                print(f"  {Fore.YELLOW}[6]{Style.RESET_ALL} Delete messages across ALL Joined Servers / Groups (Queue with Cooldown)")
                print(f"  {Fore.YELLOW}[7]{Style.RESET_ALL} Exit")

                choice = input(f"\n{Fore.GREEN}Select option [1-7]: {Style.RESET_ALL}").strip()

                if choice == "1":
                    process_all_dms_queue(session, user_id, base_delay, dry_run, include_hidden=False)
                    if not prompt_next_action():
                        break
                    continue
                elif choice == "2":
                    log_warn("Starting Deep Scan with sequential 1-by-1 unhide, 5s delays, and auto re-close...")
                    process_all_dms_queue(session, user_id, base_delay, dry_run, include_hidden=True)
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
                    
                    process_bulk_user_queue(session, parsed_uids, user_id, base_delay, dry_run)
                    if not prompt_next_action():
                        break
                    continue
                elif choice == "4":
                    target_channel_id = select_dm_channel(session)
                    if not target_channel_id:
                        log_error("DM Channel selection failed!")
                        if not prompt_next_action():
                            break
                        continue
                elif choice == "5":
                    target_guild_id = select_guild_server(session)
                    if not target_guild_id:
                        log_error("Server selection failed!")
                        if not prompt_next_action():
                            break
                        continue
                    if target_guild_id == "ALL":
                        process_all_guilds_queue(session, user_id, base_delay, dry_run, auto_yes)
                        if not prompt_next_action():
                            break
                        continue
                elif choice == "6":
                    process_all_guilds_queue(session, user_id, base_delay, dry_run, auto_yes)
                    if not prompt_next_action():
                        break
                    continue
                elif choice == "7":
                    log_info("Exiting tool. Goodbye!")
                    break
                else:
                    log_error("Invalid selection!")
                    if not prompt_next_action():
                        break
                    continue

            # Message Collection for Guild or Single DM/Channel
            messages_to_delete: list[dict[str, Any]] = []

            enable_skip()
            try:
                if target_channel_id:
                    messages_to_delete = scan_channel_user_messages(session, target_channel_id, user_id, label="target chat")
                elif target_guild_id:
                    print(f"{Fore.CYAN}Tip: Press [SPACE] at any time during scanning to skip and return to menu.{Style.RESET_ALL}")
                    messages_to_delete = search_guild_user_messages(session, target_guild_id, user_id)

                    if not messages_to_delete:
                        log_warn("Search index yielded 0 results. Scanning channels individually...")
                        channels = fetch_guild_channels(session, target_guild_id)
                        log_info(f"Found {len(channels)} text channels in server.")
                        
                        for idx, ch in enumerate(channels, 1):
                            if SKIP_ENABLED and check_skip_pressed():
                                raise SkipCurrentTargetException("Skipped by user via Spacebar")
                            ch_name = ch.get("name", ch.get("id"))
                            log_info(f"[{idx}/{len(channels)}] Scanning #{ch_name}...")
                            ch_msgs = scan_channel_user_messages(session, ch["id"], user_id, label=f"#{ch_name}")
                            if ch_msgs:
                                messages_to_delete.extend(ch_msgs)
            except SkipCurrentTargetException:
                print(f"\n{Fore.YELLOW}[>>] [SPACE] pressed! Scanning skipped by user.{Style.RESET_ALL}")
                disable_skip()
                if not prompt_next_action():
                    break
                continue
            finally:
                disable_skip()

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

            # Execute batch deletion with Spacebar skip support
            print(f"{Fore.CYAN}Tip: Press [SPACE] at any time during deletion to stop and return to menu.{Style.RESET_ALL}")
            enable_skip()
            del_count = 0
            fail_count = 0
            try:
                del_count, fail_count = delete_message_batch(session, messages_to_delete, base_delay, dry_run)
            except SkipCurrentTargetException:
                print(f"\n{Fore.YELLOW}[>>] [SPACE] pressed! Deletion stopped by user.{Style.RESET_ALL}")
            finally:
                disable_skip()

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

    except TokenRevokedException as e:
        log_error(f"Execution halted: {e}")
        log_error("Please check your Discord User Token and log back in.")
        sys.exit(1)
    except (KeyboardInterrupt, EOFError):
        log_info("\nExiting tool cleanly. Goodbye!")
        sys.exit(0)
    finally:
        if session is not None:
            session.close()

if __name__ == "__main__":
    main()
