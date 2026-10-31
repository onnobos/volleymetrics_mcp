"""Playwright-based interactive and automated authentication refresh for Volleymetrics.

Automates or guides logging into https://portal.volleymetrics.hudl.com using Playwright,
extracting the Bearer access token and team session, and updating both the active process
environment, OS Keychain, and persistent auth_state.json on disk.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any, Dict, Optional
import httpx
from dotenv import load_dotenv

# Ensure environment variables are loaded
load_dotenv()

AUTH_STATE_DIR = Path.home() / ".volleymetrics_mcp"
AUTH_STATE_FILE = AUTH_STATE_DIR / "auth_state.json"


def get_auth_state_path() -> Path:
    """Return the path to auth_state.json, respecting VOLLEYMETRICS_AUTH_STATE_PATH."""
    custom = os.getenv("VOLLEYMETRICS_AUTH_STATE_PATH")
    if custom:
        return Path(custom).expanduser().resolve()
    return AUTH_STATE_FILE


def get_token_from_auth_state(auth_state_path: Optional[Path] = None) -> Optional[str]:
    """Extract Bearer access token from Playwright auth_state.json file."""
    path = auth_state_path or get_auth_state_path()
    if not path.is_file():
        # Fallback to project root .volleymetrics_mcp/auth_state.json
        project_fallback = Path(__file__).resolve().parents[2] / ".volleymetrics_mcp" / "auth_state.json"
        if project_fallback.is_file():
            path = project_fallback
        else:
            return None

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # 1. Search localStorage origins for vmPortalUser
        for origin in data.get("origins", []):
            if "volleymetrics" in origin.get("origin", "").lower() or "hudl" in origin.get("origin", "").lower():
                for item in origin.get("localStorage", []):
                    if item.get("name") == "vmPortalUser":
                        try:
                            user_val = json.loads(item.get("value", "{}"))
                            token = user_val.get("access_token")
                            if token:
                                return token
                        except Exception:
                            pass

        # 2. Check cookies for Bearer token or ident session
        cookies = data.get("cookies", [])
        for c in cookies:
            if c.get("name") in ("access_token", "vm_token", "local_vm_token"):
                return c.get("value")

    except Exception:
        pass

    return None


def get_team_id_from_auth_state(auth_state_path: Optional[Path] = None) -> Optional[str]:
    """Extract active team ID from Playwright auth_state.json file."""
    path = auth_state_path or get_auth_state_path()
    if not path.is_file():
        project_fallback = Path(__file__).resolve().parents[2] / ".volleymetrics_mcp" / "auth_state.json"
        if project_fallback.is_file():
            path = project_fallback
        else:
            return None

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        fallback_acc_id = None
        for origin in data.get("origins", []):
            if "volleymetrics" in origin.get("origin", "").lower() or "hudl" in origin.get("origin", "").lower():
                for item in origin.get("localStorage", []):
                    if item.get("name") == "vmActiveAccount":
                        try:
                            acc_val = json.loads(item.get("value", "{}"))
                            tid = acc_val.get("teamId") or acc_val.get("team", {}).get("id") or acc_val.get("id")
                            if tid:
                                return str(tid)
                        except Exception:
                            pass
    except Exception:
        pass

    return None


def find_env_file() -> Path:
    """Locate the .env file in project root or current/parent directories."""
    project_root = Path(__file__).resolve().parents[2]
    project_env = project_root / ".env"
    if project_env.is_file():
        return project_env

    current = Path.cwd()
    for directory in [current, *current.parents]:
        env_file = directory / ".env"
        if env_file.is_file():
            return env_file
    return project_env


def update_env_file(key: str, value: str, env_path: Optional[Path] = None) -> Path:
    """Update or append an environment variable in the .env file preserving existing contents."""
    target_path = env_path or find_env_file()
    lines = []
    found = False

    if target_path.exists():
        with open(target_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

    new_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith(f"{key}=") or stripped.startswith(f"export {key}="):
            new_lines.append(f"{key}={value}\n")
            found = True
        else:
            new_lines.append(line)

    if not found:
        if new_lines and not new_lines[-1].endswith("\n"):
            new_lines.append("\n")
        new_lines.append(f"{key}={value}\n")

    with open(target_path, "w", encoding="utf-8") as f:
        f.writelines(new_lines)

    return target_path


async def interactive_login(
    auth_state_path: Optional[Path] = None,
    timeout_seconds: int = 300,
) -> Dict[str, Any]:
    """Open an interactive pop-up browser to portal.volleymetrics.hudl.com for user authentication.

    Opens a visible Chromium window. The user logs in via password manager, SSO, or 2FA.
    Once navigation to the Volleymetrics portal dashboard is detected, the session state is
    saved to ~/.volleymetrics_mcp/auth_state.json, the browser closes, and process memory &
    keyring are updated.

    Args:
        auth_state_path: Optional custom path to save auth_state.json.
        timeout_seconds: Maximum seconds to wait for user to complete login (default: 300).

    Returns:
        Dict with success status, storage_state_file path, masked token, and message.
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return {
            "success": False,
            "error": (
                "Playwright is not installed. Please run:\n"
                "pip install playwright && playwright install chromium"
            ),
        }

    target_path = auth_state_path or get_auth_state_path()
    try:
        target_path.parent.mkdir(parents=True, exist_ok=True)
    except PermissionError:
        target_path = Path(__file__).resolve().parents[2] / ".volleymetrics_mcp" / "auth_state.json"
        target_path.parent.mkdir(parents=True, exist_ok=True)

    user_agent = os.getenv(
        "VOLLEYMETRICS_USER_AGENT",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    )

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = await browser.new_context(
            user_agent=user_agent,
            viewport={"width": 1280, "height": 900},
        )
        page = await context.new_page()

        try:
            # 1. Navigate to portal entry point
            entry_url = os.getenv("VOLLEYMETRICS_PORTAL_URL", "https://portal.volleymetrics.hudl.com")
            await page.goto(entry_url, wait_until="domcontentloaded")

            # 2. Wait until login completes and user reaches portal dashboard or localStorage token appears
            start_time = asyncio.get_event_loop().time()
            captured_token: Optional[str] = None
            captured_team_id: Optional[str] = None

            while (asyncio.get_event_loop().time() - start_time) < timeout_seconds:
                curr_url = page.url.lower()

                # Check if we are on portal.volleymetrics.hudl.com
                if "volleymetrics" in curr_url and ("dashboard" in curr_url or "portal" in curr_url or "#/" in curr_url):
                    # Check localStorage for vmPortalUser
                    try:
                        vm_user_str = await page.evaluate("() => localStorage.getItem('vmPortalUser')")
                        if vm_user_str:
                            user_data = json.loads(vm_user_str)
                            token = user_data.get("access_token")
                            if token:
                                captured_token = token
                                # Also check active account
                                vm_acc_str = await page.evaluate("() => localStorage.getItem('vmActiveAccount')")
                                if vm_acc_str:
                                    acc_data = json.loads(vm_acc_str)
                                    captured_team_id = str(acc_data.get("teamId") or acc_data.get("id") or "")
                                break
                    except Exception:
                        pass

                # If reached home or dashboard on hudl and redirected
                if "hudl.com/home" in curr_url:
                    # User completed Hudl login, navigate back to Volleymetrics portal if not redirected automatically
                    await page.goto(entry_url, wait_until="domcontentloaded")

                await asyncio.sleep(1.0)

            # 3. Allow final tokens and storage to settle
            try:
                await page.wait_for_timeout(2000)
            except Exception:
                pass

            # 4. Save storage state to auth_state.json
            await context.storage_state(path=str(target_path))

            # 5. If token wasn't captured from localStorage yet, try extracting from auth_state or cookies
            if not captured_token:
                captured_token = get_token_from_auth_state(target_path)
            if not captured_team_id:
                captured_team_id = get_team_id_from_auth_state(target_path)

            if not captured_token:
                # Check cookies for ident or session token
                cookies = await context.cookies()
                ident_cookie = next((c for c in cookies if c.get("name") == "ident"), None)
                if ident_cookie:
                    captured_token = ident_cookie.get("value")

            if not captured_token:
                return {
                    "success": False,
                    "error": "Reached Volleymetrics portal, but no session token could be captured.",
                }

            # 6. Resolve genuine team ID from /acct/accounts if needed
            detected_team_name = None
            try:
                async with httpx.AsyncClient(timeout=10.0) as http_client:
                    resp = await http_client.get(
                        "https://api.volleymetrics.hudl.com/acct/accounts",
                        headers={
                            "Authorization": f"Bearer {captured_token}",
                            "User-Agent": user_agent,
                        },
                    )
                    if resp.status_code == 200:
                        acc_data = resp.json()
                        items = acc_data if isinstance(acc_data, list) else acc_data.get("accounts", [])
                        if items:
                            first_item = items[0]
                            team_obj = first_item.get("team") if isinstance(first_item.get("team"), dict) else first_item
                            real_tid = str(team_obj.get("id") or first_item.get("teamId") or "")
                            if real_tid:
                                captured_team_id = real_tid
                            detected_team_name = team_obj.get("name") or first_item.get("name")
            except Exception:
                pass

            # 7. Update environment and .env
            os.environ["VOLLEYMETRICS_TOKEN"] = captured_token
            if captured_team_id:
                os.environ["VOLLEYMETRICS_TEAM_ID"] = captured_team_id

            env_file = find_env_file()
            try:
                update_env_file("VOLLEYMETRICS_TOKEN", captured_token, env_path=env_file)
                if captured_team_id:
                    update_env_file("VOLLEYMETRICS_TEAM_ID", captured_team_id, env_path=env_file)
            except Exception:
                pass

            # 8. Securely cache in OS Keyring
            try:
                from volleymetrics_mcp.security import save_secure_session
                save_secure_session(captured_token, team_id=captured_team_id)
            except Exception:
                pass

            masked_token = (
                captured_token[:15] + "..." + captured_token[-8:]
                if len(captured_token) > 25
                else "***"
            )
            team_info_str = ""
            if captured_team_id:
                name_part = f" ({detected_team_name})" if detected_team_name else ""
                team_info_str = f"- **Detected Team**: `{captured_team_id}`{name_part}\n"

            return {
                "success": True,
                "storage_state_file": str(target_path),
                "token": captured_token,
                "team_id": captured_team_id,
                "masked_token": masked_token,
                "message": (
                    f"Successfully logged into Volleymetrics!\n\n"
                    f"- **Browser Window Closed**: Login completed.\n"
                    f"- **Session State Saved**: `{target_path}`\n"
                    f"{team_info_str}"
                    f"- **Active Session Token**: `{masked_token}`"
                ),
            }

        except Exception as exc:
            err_str = str(exc)
            if "Target closed" in err_str or "Page closed" in err_str or "closed" in err_str.lower():
                return {
                    "success": False,
                    "error": "The browser window was closed before login was completed.",
                }
            if "Timeout" in err_str or "timed out" in err_str.lower():
                return {
                    "success": False,
                    "error": f"Login timed out after {timeout_seconds} seconds. Please try again.",
                }
            return {
                "success": False,
                "error": f"Interactive login failed: {type(exc).__name__}: {exc}",
            }
        finally:
            try:
                await browser.close()
            except Exception:
                pass


async def refresh_session(
    email: Optional[str] = None,
    password: Optional[str] = None,
    api_url: str = "https://api.volleymetrics.hudl.com",
) -> Dict[str, Any]:
    """Automated token retrieval using OAuth password grant.

    Calls POST /acct/oauth/token with basic auth 'Basic cG9ydGFsOg=='.
    """
    usr = email or os.getenv("VOLLEYMETRICS_EMAIL")
    pwd = password or os.getenv("VOLLEYMETRICS_PASSWORD")

    if not usr or not pwd:
        return {
            "success": False,
            "error": "VOLLEYMETRICS_EMAIL and VOLLEYMETRICS_PASSWORD must be configured in .env for automated token refresh.",
        }

    token_url = f"{api_url.rstrip('/')}/acct/oauth/token"
    headers = {
        "Authorization": "Basic cG9ydGFsOg==",  # Base64("portal:")
        "Content-Type": "application/x-www-form-urlencoded",
        "User-Agent": os.getenv("VOLLEYMETRICS_USER_AGENT", "Mozilla/5.0"),
    }
    payload = {
        "grant_type": "password",
        "username": usr,
        "password": pwd,
    }

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(token_url, data=payload, headers=headers)

        if resp.status_code == 200:
            data = resp.json()
            token = data.get("access_token")
            if not token:
                return {"success": False, "error": "Token endpoint succeeded but returned no access_token."}

            tid = None
            ident = data.get("identity", {})
            act = ident.get("activeAccount", {})
            if act:
                tid = str(act.get("teamId") or act.get("id") or "")

            os.environ["VOLLEYMETRICS_TOKEN"] = token
            if tid:
                os.environ["VOLLEYMETRICS_TEAM_ID"] = tid

            # Securely save to keyring
            try:
                from volleymetrics_mcp.security import save_secure_session
                save_secure_session(token, team_id=tid)
            except Exception:
                pass

            masked = token[:15] + "..." + token[-8:] if len(token) > 25 else "***"
            return {
                "success": True,
                "token": token,
                "team_id": tid,
                "masked_token": masked,
                "message": f"Successfully refreshed Volleymetrics session token: {masked}",
            }
        elif resp.status_code in (401, 403):
            return {
                "success": False,
                "error": "Invalid email or password. Please verify credentials or use interactive login.",
            }
        else:
            return {
                "success": False,
                "error": f"Token endpoint returned HTTP {resp.status_code}: {resp.text[:200]}",
            }
    except Exception as exc:
        return {"success": False, "error": f"OAuth token refresh request failed: {exc}"}


def main() -> None:
    """CLI entrypoint for volleymetrics-auth-refresh."""
    import argparse
    parser = argparse.ArgumentParser(description="Volleymetrics Authentication Refresh CLI")
    parser.add_argument("--timeout", type=int, default=300, help="Interactive login timeout in seconds")
    parser.add_argument("--direct", action="store_true", help="Attempt direct OAuth password login with .env credentials")
    args = parser.parse_args()

    if args.direct:
        print("Attempting automated OAuth login with .env credentials...")
        res = asyncio.run(refresh_session())
    else:
        print("Opening interactive browser window to log into Volleymetrics...")
        res = asyncio.run(interactive_login(timeout_seconds=args.timeout))

    if res.get("success"):
        print(f"\n✅ {res.get('message')}")
    else:
        print(f"\n❌ {res.get('error')}")
        exit(1)


if __name__ == "__main__":
    main()
