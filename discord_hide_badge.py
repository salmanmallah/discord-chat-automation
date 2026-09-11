#!/usr/bin/env python3
"""
Discord Legacy Username Badge Manager / Visibility Automator (v2.2)
Uses Discord's PreloadedUserSettings Protocol Buffer Engine to accurately
hide or show the "Legacy Username Badge" ("Originally Known As") across accounts.
"""

import argparse
import base64
import binascii
import getpass
import json
import os
import random
import sys
import time
from typing import Any

import requests
from colorama import Fore, Style, init
from dotenv import load_dotenv
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Try importing discord_protos if available
try:
    from discord_protos import PreloadedUserSettings
    HAS_DISCORD_PROTOS = True
except ImportError:
    HAS_DISCORD_PROTOS = False

# Initialize colorama
init(autoreset=True)

# Load environment variables
load_dotenv()

# Discord API Base URLs
DISCORD_API_BASE = "https://discord.com/api/v9"

# Raw pre-compiled Protobuf byte sequences for PreloadedUserSettings.privacy.hide_legacy_username
# HIDE (hide_legacy_username = True): 42 05 b2 01 02 08 01
PROTO_HIDE_B64 = "QgWyAQIIAQ=="
# SHOW (hide_legacy_username = False): 42 03 b2 01 00
PROTO_SHOW_B64 = "QgOyAQA="

# User Badge Flags Mapping (Public user flags & profile badges)
DISCORD_FLAGS: dict[int, str] = {
    1 << 0: "Discord Employee",
    1 << 1: "Partnered Server Owner",
    1 << 2: "HypeSquad Events Member",
    1 << 3: "Bug Hunter Level 1",
    1 << 6: "House Bravery (HypeSquad)",
    1 << 7: "House Brilliance (HypeSquad)",
    1 << 8: "House Balance (HypeSquad)",
    1 << 9: "Early Nitro Supporter",
    1 << 14: "Bug Hunter Level 2",
    1 << 17: "Early Verified Bot Developer",
    1 << 18: "Discord Certified Moderator",
    1 << 22: "Active Developer",
}


def print_banner():
    print(f"\n{Fore.CYAN}+---------------------------------------------------------+{Style.RESET_ALL}")
    print(f"{Fore.CYAN}| {Fore.MAGENTA}      DISCORD LEGACY USERNAME BADGE MANAGER v2.2         {Fore.CYAN}|{Style.RESET_ALL}")
    print(f"{Fore.CYAN}| {Fore.YELLOW}     [ Protocol Buffer Settings Engine Enabled ]         {Fore.CYAN}|{Style.RESET_ALL}")
    print(f"{Fore.CYAN}| {Fore.GREEN}        (Multi-Token Support & Live Verification)        {Fore.CYAN}|{Style.RESET_ALL}")
    print(f"{Fore.CYAN}+---------------------------------------------------------+{Style.RESET_ALL}\n")


def log_info(msg: str):
    print(f"{Fore.CYAN}[*]{Style.RESET_ALL} {msg}")


def log_success(msg: str):
    print(f"{Fore.GREEN}[+]{Style.RESET_ALL} {msg}")


def log_warn(msg: str):
    print(f"{Fore.YELLOW}[!]{Style.RESET_ALL} {msg}")


def log_error(msg: str):
    print(f"{Fore.RED}[-]{Style.RESET_ALL} {msg}")


def safe_sleep(seconds: float, jitter: float = 0.5):
    """Sleeps with randomized jitter to prevent bot-detection patterns."""
    actual_delay = max(0.2, seconds + random.uniform(0.1, jitter))
    time.sleep(actual_delay)


def is_bot_token(token: str) -> bool:
    """Detects whether the provided token is a Discord Bot token."""
    stripped = token.strip().strip('"').strip("'")
    if stripped.startswith("Bot "):
        return True
    parts = stripped.split(".")
    if len(parts) == 3:
        try:
            padded = parts[0] + "=" * (-len(parts[0]) % 4)
            decoded_id = base64.b64decode(padded).decode("utf-8")
            if (
                decoded_id.isdigit()
                and len(decoded_id) in (17, 18, 19, 20)
                and len(parts[1]) > 5
                and len(parts[2]) > 20
                and parts[1].isalnum()
            ):
                return False
        except (binascii.Error, UnicodeDecodeError, ValueError):
            return False
    return False


def get_headers(token: str) -> dict[str, str]:
    """Builds browser-mimicking headers with realistic X-Super-Properties."""
    token_clean = token.strip().strip('"').strip("'")
    super_properties = base64.b64encode(json.dumps({
        "os": "Windows",
        "browser": "Chrome",
        "device": "",
        "system_locale": "en-US",
        "browser_user_agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
        "browser_version": "124.0.0.0",
        "os_version": "10",
        "referrer": "",
        "referring_domain": "",
        "referrer_current": "",
        "referring_domain_current": "",
        "release_channel": "stable",
        "client_build_number": 291963,
        "client_event_source": None,
    }, separators=(",", ":")).encode()).decode()

    return {
        "Authorization": token_clean,
        "Content-Type": "application/json",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
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
    """
    Creates a requests.Session with connection pooling and default browser headers.
    Reusing sessions avoids per-request TLS handshake overhead and fingerprinting flags.
    """
    session = requests.Session()
    session.headers.update(get_headers(token))
    retries = Retry(
        total=3,
        backoff_factor=0.5,
        status_forcelist=[500, 502, 503, 504],
        raise_on_status=False,
    )
    adapter = HTTPAdapter(pool_connections=5, pool_maxsize=10, max_retries=retries)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def extract_retry_after(response: requests.Response, default: float = 2.0) -> float:
    """Extracts rate limit retry duration from Discord API response with fallback."""
    try:
        data = response.json()
        if isinstance(data, dict) and "retry_after" in data:
            return float(data["retry_after"])
    except (ValueError, KeyError):
        pass

    header_retry = response.headers.get("Retry-After")
    if header_retry:
        try:
            return float(header_retry)
        except ValueError:
            pass
    return default


def verify_token(session: requests.Session) -> dict[str, Any] | None:
    """Verifies token and fetches basic user account information with rate limit retries."""
    for attempt in range(1, 4):
        try:
            res = session.get(f"{DISCORD_API_BASE}/users/@me", timeout=12)
            if res.status_code == 200:
                return res.json()
            elif res.status_code == 401:
                return None
            elif res.status_code == 429:
                retry_after = extract_retry_after(res, 2.0)
                log_warn(f"Rate limited during verify (attempt {attempt}/3). Waiting {retry_after:.1f}s...")
                safe_sleep(retry_after + 0.5)
            else:
                return None
        except requests.RequestException as e:
            log_error(f"Network error during authentication check: {e}")
            return None
    return None


def get_account_badges(user_data: dict[str, Any], profile_data: dict[str, Any] | None) -> list[str]:
    """Parses and formats all badges associated with the account."""
    badges = []
    flags = user_data.get("flags", 0) or user_data.get("public_flags", 0)
    for flag_val, flag_name in DISCORD_FLAGS.items():
        if flags & flag_val:
            badges.append(flag_name)

    if profile_data:
        profile_badges = profile_data.get("badges", [])
        for b in profile_badges:
            b_id = b.get("id") if isinstance(b, dict) else str(b)
            if b_id and b_id not in badges:
                badges.append(b_id)

    return badges


def get_current_proto_status(session: requests.Session) -> bool | None:
    """
    Fetches settings-proto/1 and decodes whether hide_legacy_username is True or False.
    Returns: True if hidden, False if visible, None if unable to fetch/parse.
    """
    try:
        res = session.get(f"{DISCORD_API_BASE}/users/@me/settings-proto/1", timeout=12)
        if res.status_code == 200:
            data = res.json()
            settings_b64 = data.get("settings")
            if settings_b64:
                if HAS_DISCORD_PROTOS:
                    raw = base64.b64decode(settings_b64)
                    proto = PreloadedUserSettings()
                    proto.ParseFromString(raw)
                    if proto.HasField("privacy") and proto.privacy.HasField("hide_legacy_username"):
                        return proto.privacy.hide_legacy_username.value
                else:
                    raw_bytes = base64.b64decode(settings_b64)
                    # Search for field tag: privacy (0x42) -> hide_legacy_username (0xb2 0x01)
                    idx = raw_bytes.find(b"\xb2\x01")
                    if idx != -1 and idx + 3 < len(raw_bytes):
                        val_len = raw_bytes[idx + 2]
                        if val_len == 0:
                            return False
                        elif val_len == 2 and raw_bytes[idx + 3] == 0x08:
                            return bool(raw_bytes[idx + 4])
    except (requests.RequestException, ValueError, KeyError):
        pass
    return None


def encode_proto_payload(hide: bool) -> str:
    """Encodes the PreloadedUserSettings protobuf payload for hide_legacy_username."""
    if HAS_DISCORD_PROTOS:
        proto = PreloadedUserSettings()
        proto.privacy.hide_legacy_username.value = hide
        return base64.b64encode(proto.SerializeToString()).decode("utf-8")
    else:
        return PROTO_HIDE_B64 if hide else PROTO_SHOW_B64


def update_legacy_badge_proto(session: requests.Session, hide: bool = True) -> tuple[bool, str]:
    """
    Updates the Discord User Settings Protobuf (settings-proto/1) to toggle hide_legacy_username.
    This corresponds directly to the 'Legacy Username Badge' switch in Discord client profile settings.
    """
    encoded_proto = encode_proto_payload(hide)
    payload = {"settings": encoded_proto}

    for attempt in range(1, 4):
        try:
            res = session.patch(
                f"{DISCORD_API_BASE}/users/@me/settings-proto/1",
                json=payload,
                timeout=12,
            )
            if res.status_code == 200:
                # Also send standard profile touch to synchronize CDN cache
                try:
                    session.patch(
                        f"{DISCORD_API_BASE}/users/@me/profile",
                        json={"legacy_username": None if hide else True},
                        timeout=6,
                    )
                except requests.RequestException:
                    pass
                return True, "HTTP 200 via PreloadedUserSettings (settings-proto/1)"
            elif res.status_code == 429:
                retry_after = extract_retry_after(res, 2.0)
                log_warn(f"Rate limited (attempt {attempt}/3). Waiting {retry_after:.1f}s...")
                safe_sleep(retry_after + 0.5)
                continue

            return False, f"HTTP {res.status_code}: {res.text[:80]}"
        except requests.RequestException as e:
            return False, f"Network error: {e}"

    return False, "Exceeded maximum rate limit retries (3/3)"


def parse_tokens(token_args: list[str] | None, file_arg: str | None) -> list[str]:
    """Gathers tokens from arguments, token files, .env, or interactive prompt."""
    tokens = []

    if token_args:
        for t in token_args:
            for sub_t in t.split(","):
                sub_clean = sub_t.strip().strip('"').strip("'")
                if sub_clean:
                    tokens.append(sub_clean)

    if file_arg and os.path.exists(file_arg):
        try:
            with open(file_arg, "r", encoding="utf-8") as f:
                for line in f:
                    clean = line.strip().strip('"').strip("'")
                    if clean and not clean.startswith("#"):
                        tokens.append(clean)
            log_info(f"Loaded {len(tokens)} token(s) from file: {file_arg}")
        except OSError as e:
            log_error(f"Failed to read token file: {e}")

    if not tokens:
        env_token = os.getenv("DISCORD_USER_TOKEN") or os.getenv("DISCORD_USER_TOKENS")
        if env_token:
            for item in env_token.split(","):
                item_clean = item.strip().strip('"').strip("'")
                if item_clean:
                    tokens.append(item_clean)
            if tokens:
                log_info(f"Loaded {len(tokens)} token(s) from .env configuration.")

    if not tokens:
        print(f"{Fore.YELLOW}No tokens specified via arguments, file, or .env!{Style.RESET_ALL}")
        print("You can provide:")
        print("  - A single token (hidden input)")
        print("  - Multiple tokens separated by commas or spaces")
        print("  - Path to a text file containing tokens (e.g. tokens.txt)\n")
        user_input = getpass.getpass(f"{Fore.CYAN}Enter token(s) or file path (hidden input): {Style.RESET_ALL}").strip()

        if os.path.isfile(user_input):
            try:
                with open(user_input, "r", encoding="utf-8") as f:
                    for line in f:
                        clean = line.strip().strip('"').strip("'")
                        if clean and not clean.startswith("#"):
                            tokens.append(clean)
            except OSError as e:
                log_error(f"Failed to read file {user_input}: {e}")
        elif user_input:
            for item in user_input.replace(",", " ").split():
                clean = item.strip().strip('"').strip("'")
                if clean:
                    tokens.append(clean)

    # Remove duplicates preserving order
    seen = set()
    unique_tokens = []
    for t in tokens:
        if t not in seen:
            seen.add(t)
            unique_tokens.append(t)

    return unique_tokens


def process_token(token: str, index: int, total: int, hide: bool = True) -> dict[str, Any]:
    """Processes a single token: validates, inspects proto, updates proto setting, verifies."""
    masked_token = token[:10] + "..." + token[-6:] if len(token) > 16 else token[:6] + "..."
    action_str = "HIDING" if hide else "SHOWING"

    print(f"\n{Fore.BLUE}==========================================================={Style.RESET_ALL}")
    print(f"{Fore.CYAN}[{index}/{total}] Processing Account: {Fore.YELLOW}{masked_token}{Style.RESET_ALL}")
    print(f"{Fore.BLUE}==========================================================={Style.RESET_ALL}")

    if is_bot_token(token):
        log_error("Bot token detected! PreloadedUserSettings Protobuf endpoints only support User accounts.")
        return {
            "token": masked_token,
            "status": "SKIPPED_BOT_TOKEN",
            "username": "Bot Account",
            "id": "N/A",
            "result": "Bot tokens not supported by Discord user settings",
        }

    session = create_session(token)
    try:
        user_data = verify_token(session)

        if not user_data:
            log_error("Token is invalid, expired, or failed authentication check.")
            return {
                "token": masked_token,
                "status": "INVALID_TOKEN",
                "username": "N/A",
                "id": "N/A",
                "result": "Authentication Failed",
            }

        user_id = user_data.get("id", "Unknown")
        username = user_data.get("username", "Unknown")
        global_name = user_data.get("global_name") or username
        discriminator = user_data.get("discriminator", "0")
        legacy_tag = user_data.get("legacy_username") or (f"#{discriminator}" if discriminator != "0" else "Migrated")

        # Initial check on proto status
        initial_hidden = get_current_proto_status(session)
        status_label = "HIDDEN" if initial_hidden is True else ("VISIBLE" if initial_hidden is False else "DEFAULT")

        print(f"  {Fore.WHITE}* User:{Style.RESET_ALL} {Fore.GREEN}{global_name}{Style.RESET_ALL} (@{username})")
        print(f"  {Fore.WHITE}* User ID:{Style.RESET_ALL} {user_id}")
        print(f"  {Fore.WHITE}* Legacy Tag:{Style.RESET_ALL} {Fore.MAGENTA}{legacy_tag}{Style.RESET_ALL}")
        print(f"  {Fore.WHITE}* Current Badge Visibility:{Style.RESET_ALL} {Fore.YELLOW}{status_label}{Style.RESET_ALL}")

        log_info(f"Applying Protobuf User Settings update to {action_str} Legacy Username Badge...")
        success, detail = update_legacy_badge_proto(session, hide=hide)

        safe_sleep(1.2, 0.5)

        # Verification: Re-query proto status
        verified_hidden = get_current_proto_status(session)

        if success:
            log_success(f"Protobuf update accepted by Discord! ({detail})")
            if verified_hidden is True:
                log_success(
                    f"{Fore.GREEN}Verified:{Style.RESET_ALL} Legacy Username Badge is now permanently "
                    f"{Fore.GREEN}HIDDEN{Style.RESET_ALL} on Discord servers & for friends!"
                )
                final_status = "SUCCESS (HIDDEN)"
            elif verified_hidden is False:
                log_success(f"{Fore.GREEN}Verified:{Style.RESET_ALL} Legacy Username Badge is now {Fore.GREEN}VISIBLE{Style.RESET_ALL}!")
                final_status = "SUCCESS (VISIBLE)"
            else:
                log_success("Settings update sent successfully!")
                final_status = "SUCCESS"
        else:
            log_error(f"Failed to apply settings update: {detail}")
            final_status = "FAILED"

        return {
            "token": masked_token,
            "status": final_status,
            "username": f"{global_name} (@{username})",
            "id": user_id,
            "result": detail,
        }
    finally:
        session.close()


def main():
    print_banner()

    parser = argparse.ArgumentParser(
        description="Hide or show the Discord Legacy Username Badge ('Originally Known As') on one or more accounts."
    )
    parser.add_argument(
        "-t", "--tokens", "--token",
        nargs="+",
        help="One or more Discord user tokens (space-separated or comma-separated).",
    )
    parser.add_argument(
        "-f", "--file",
        help="Path to a text file containing Discord user tokens (one per line).",
    )
    parser.add_argument(
        "--hide",
        action="store_true",
        default=True,
        help="Hide the Legacy Username Badge (default behavior).",
    )
    parser.add_argument(
        "--show",
        action="store_true",
        help="Show / restore the Legacy Username Badge.",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=2.5,
        help="Delay in seconds between processing each account token (default: 2.5s).",
    )

    args = parser.parse_args()

    hide_badge = not args.show

    tokens = parse_tokens(args.tokens, args.file)

    if not tokens:
        log_error("No tokens provided. Exiting.")
        sys.exit(1)

    mode_name = "SHOW / RESTORE" if args.show else "HIDE"
    engine_name = (
        f"{Fore.GREEN}discord-protos (Google Protobuf Engine){Style.RESET_ALL}"
        if HAS_DISCORD_PROTOS
        else f"{Fore.YELLOW}Direct Binary Byte Stream Engine (Zero-dependency){Style.RESET_ALL}"
    )

    print(f"{Fore.GREEN}Action Mode:{Style.RESET_ALL} {Fore.YELLOW}{mode_name} Legacy Username Badge{Style.RESET_ALL}")
    print(f"{Fore.GREEN}Protobuf Engine:{Style.RESET_ALL} {engine_name}")
    print(f"{Fore.GREEN}Total Accounts Loaded:{Style.RESET_ALL} {Fore.CYAN}{len(tokens)}{Style.RESET_ALL}\n")

    results = []
    for idx, token in enumerate(tokens, 1):
        res = process_token(token, idx, len(tokens), hide=hide_badge)
        results.append(res)
        if idx < len(tokens):
            log_info(f"Pausing {args.delay:.1f}s before next account to prevent rate limits...")
            safe_sleep(args.delay, 0.8)

    # Print Summary Table
    print(f"\n{Fore.CYAN}==========================================================={Style.RESET_ALL}")
    print(f"{Fore.CYAN}                   SUMMARY EXECUTION REPORT                {Style.RESET_ALL}")
    print(f"{Fore.CYAN}==========================================================={Style.RESET_ALL}")

    success_count = sum(1 for r in results if "SUCCESS" in r["status"])
    failed_count = sum(1 for r in results if "SUCCESS" not in r["status"])

    print(f"{'#':<4} {'Username':<26} {'Status':<20} {'Details':<20}")
    print("-" * 72)
    for idx, r in enumerate(results, 1):
        status_color = Fore.GREEN if "SUCCESS" in r["status"] else Fore.RED
        print(f"{idx:<4} {r['username'][:24]:<26} {status_color}{r['status']:<20}{Style.RESET_ALL} {r['result'][:20]}")

    print("-" * 72)
    print(
        f"Total: {len(results)} | {Fore.GREEN}Success: {success_count}{Style.RESET_ALL} | "
        f"{Fore.RED}Failed/Skipped: {failed_count}{Style.RESET_ALL}\n"
    )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n{Fore.YELLOW}[!] Process cancelled by user. Exiting safely.{Style.RESET_ALL}")
        sys.exit(0)
