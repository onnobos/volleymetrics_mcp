"""CLI utility to test Volleymetrics connection and credentials."""

from __future__ import annotations

import asyncio
import os
import sys

from volleymetrics_mcp.client import (
    VolleymetricsAuthError,
    VolleymetricsClient,
    get_api_url,
    get_volleymetrics_team_id,
    get_volleymetrics_token,
)
from volleymetrics_mcp.models import format_teams_markdown


async def test_connection() -> int:
    """Test connection to Volleymetrics API and verify authentication."""
    print("=" * 60)
    print("🏐 Volleymetrics MCP Connection Diagnostic")
    print("=" * 60)

    api_url = get_api_url()
    print(f"API Endpoint: {api_url}")

    token = get_volleymetrics_token()
    if token:
        masked = token[:15] + "..." + token[-8:] if len(token) > 25 else "***"
        print(f"Session Token: {masked} (Found)")
    else:
        print("Session Token: None")
        print("\n⚠️ No session token found.")
        print("Run `volleymetrics-auth-refresh` or call `login_to_volleymetrics` in AI chat.")
        return 1

    team_id = get_volleymetrics_team_id()
    print(f"Active Team ID: {team_id or '(Not specified - will auto-discover)'}")

    print("\nConnecting to Volleymetrics API...")
    try:
        client = VolleymetricsClient()
        teams = await client.get_user_teams(force_refresh=True)

        if teams:
            print(f"✅ Success! Connected and found {len(teams)} team(s):\n")
            print(format_teams_markdown(teams, active_team_id=client.team_id))
            return 0
        else:
            print("⚠️ Connected to API successfully, but no teams were returned for this account.")
            return 0

    except VolleymetricsAuthError as exc:
        print(f"\n❌ Authentication Error: {exc}")
        print("Please refresh your session by running `volleymetrics-auth-refresh`.")
        return 1
    except Exception as exc:
        print(f"\n❌ Connection Error: {type(exc).__name__}: {exc}")
        return 1


def main() -> None:
    """Main CLI entrypoint."""
    code = asyncio.run(test_connection())
    sys.exit(code)


if __name__ == "__main__":
    main()
