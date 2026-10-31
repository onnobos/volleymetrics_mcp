"""Async HTTPX REST client and authentication wrapper for Volleymetrics.

This module handles:
1. Loading configuration and credentials from .env, OS Keyring, and auth_state.json
2. Realistic browser header injection and Bearer token formatting
3. Sending async REST requests to https://api.volleymetrics.hudl.com
4. Robust error handling for 401/403 with actionable AI guidance
5. High-level domain methods for volleyball matches, box scores, rotations, and DVW downloads.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
import httpx
from dotenv import load_dotenv

from volleymetrics_mcp.cache import (
    TTL_HISTORICAL_MATCH,
    TTL_SCHEDULE_TEAM,
    clear_all_cache,
    compute_cache_key,
    get_cached_response,
    set_cached_response,
)
from volleymetrics_mcp.models import (
    MatchSummary,
    PlayerStats,
    RotationStats,
    TeamInfo,
    VolleyballAction,
    parse_matches_response,
    parse_player_stats_response,
    parse_rotation_stats_response,
    parse_teams_response,
    parse_video_actions,
)
from volleymetrics_mcp.rate_limiter import DEFAULT_RATE_LIMITER, execute_with_retry
from volleymetrics_mcp.security import (
    VolleymetricsSecurityError,
    assert_read_only,
    get_secure_team_id,
    get_secure_token,
)

logger = logging.getLogger(__name__)

_ENV_LOADED = False


def load_project_env(force: bool = False) -> None:
    """Find and load .env regardless of working directory."""
    global _ENV_LOADED
    if not force and _ENV_LOADED:
        return
    _ENV_LOADED = True

    project_root = Path(__file__).resolve().parents[2]
    project_env = project_root / ".env"
    if project_env.is_file():
        load_dotenv(project_env, override=force)
        return

    curr = Path.cwd()
    for d in [curr, *curr.parents]:
        p = d / ".env"
        if p.is_file():
            load_dotenv(p, override=force)
            return

    load_dotenv(override=force)


load_project_env()

DEFAULT_API_URL = "https://api.volleymetrics.hudl.com"
DEFAULT_TIMEOUT = 20.0
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/128.0.0.0 Safari/537.36"
)


class VolleymetricsError(Exception):
    """Base exception for Volleymetrics MCP errors."""


class VolleymetricsAuthError(VolleymetricsError):
    """Authentication failed due to missing, expired, or invalid session tokens."""


class VolleymetricsConnectionError(VolleymetricsError):
    """Network connection, DNS, or timeout communicating with Volleymetrics."""


def get_volleymetrics_token() -> Optional[str]:
    """Retrieve and format the active VOLLEYMETRICS_TOKEN."""
    # 1. Environment variable
    raw = os.getenv("VOLLEYMETRICS_TOKEN")
    if raw and raw.strip():
        tok = raw.strip().strip('"').strip("'")
        if tok.lower().startswith("bearer "):
            tok = tok[7:].strip()
        return tok

    # 2. Secure OS Keyring
    keyring_tok = get_secure_token()
    if keyring_tok:
        os.environ["VOLLEYMETRICS_TOKEN"] = keyring_tok
        return keyring_tok

    # 3. Playwright auth_state.json
    from volleymetrics_mcp.auth_refresh import get_token_from_auth_state
    state_tok = get_token_from_auth_state()
    if state_tok:
        os.environ["VOLLEYMETRICS_TOKEN"] = state_tok
        return state_tok

    # 4. Fallback to .env file
    load_project_env()
    raw = os.getenv("VOLLEYMETRICS_TOKEN")
    if raw and raw.strip():
        tok = raw.strip().strip('"').strip("'")
        if tok.lower().startswith("bearer "):
            tok = tok[7:].strip()
        return tok

    return None


def get_volleymetrics_team_id() -> Optional[str]:
    """Retrieve default VOLLEYMETRICS_TEAM_ID."""
    load_project_env()
    raw = os.getenv("VOLLEYMETRICS_TEAM_ID")
    if raw and raw.strip():
        return raw.strip().strip('"').strip("'")

    keyring_tid = get_secure_team_id()
    if keyring_tid and keyring_tid.strip():
        return keyring_tid.strip()

    from volleymetrics_mcp.auth_refresh import get_team_id_from_auth_state
    state_tid = get_team_id_from_auth_state()
    if state_tid:
        return state_tid

    return None


def get_api_url() -> str:
    """Retrieve base API URL."""
    load_project_env()
    return os.getenv("VOLLEYMETRICS_API_URL", DEFAULT_API_URL).rstrip("/")


def get_api_timeout() -> float:
    """Retrieve timeout setting in seconds."""
    raw = os.getenv("VOLLEYMETRICS_TIMEOUT")
    if raw:
        try:
            return float(raw)
        except ValueError:
            pass
    return DEFAULT_TIMEOUT


def get_api_headers() -> Dict[str, str]:
    """Construct realistic HTTP headers with Bearer token authentication."""
    token = get_volleymetrics_token()
    user_agent = os.getenv("VOLLEYMETRICS_USER_AGENT", DEFAULT_USER_AGENT).strip()

    headers = {
        "User-Agent": user_agent,
        "Origin": "https://portal.volleymetrics.hudl.com",
        "Referer": "https://portal.volleymetrics.hudl.com/",
        "Content-Type": "application/json",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
    }
    if token:
        # Check if cookie or Bearer JWT token
        if "=" in token and ";" in token:
            headers["Cookie"] = token
        else:
            headers["Authorization"] = f"Bearer {token}"
    return headers


class VolleymetricsClient:
    """High-level client for Volleymetrics volleyball statistics, matches, and DVW files."""

    def __init__(
        self,
        api_url: Optional[str] = None,
        team_id: Optional[str] = None,
        timeout: Optional[float] = None,
    ):
        self.api_url = api_url or get_api_url()
        self.team_id = team_id or get_volleymetrics_team_id()
        self.timeout = timeout or get_api_timeout()

    async def _send_request(
        self,
        method: str,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Any] = None,
        client: Optional[httpx.AsyncClient] = None,
        _retried: bool = False,
    ) -> httpx.Response:
        """Execute HTTP request with strict read-only enforcement and rate limiting."""
        # Enforce strict Read-Only Policy
        assert_read_only(method, path)

        token = get_volleymetrics_token()
        if not token:
            raise VolleymetricsAuthError(
                "No Volleymetrics session token found. Please call the 'login_to_volleymetrics' tool "
                "(or say 'Log me into Volleymetrics') to authenticate via an interactive pop-up browser window."
            )

        headers = get_api_headers()
        full_url = f"{self.api_url}/{path.lstrip('/')}"

        async def _do_req(c: httpx.AsyncClient) -> httpx.Response:
            return await c.request(
                method=method.upper(),
                url=full_url,
                params=params,
                json=json_body,
                headers=headers,
                timeout=self.timeout,
            )

        try:
            if client is not None:
                resp = await execute_with_retry(lambda: _do_req(client), rate_limiter=DEFAULT_RATE_LIMITER)
            else:
                async with httpx.AsyncClient() as new_client:
                    resp = await execute_with_retry(lambda: _do_req(new_client), rate_limiter=DEFAULT_RATE_LIMITER)
        except httpx.TimeoutException as exc:
            raise VolleymetricsConnectionError(
                f"Connection to Volleymetrics API timed out after {self.timeout}s: {exc}"
            ) from exc
        except httpx.RequestError as exc:
            raise VolleymetricsConnectionError(
                f"Failed to connect to Volleymetrics API ({full_url}): {exc}"
            ) from exc

        # Handle 401 / 403 Unauthorized
        if resp.status_code in (401, 403):
            if not _retried and os.getenv("VOLLEYMETRICS_EMAIL") and os.getenv("VOLLEYMETRICS_PASSWORD"):
                try:
                    from volleymetrics_mcp.auth_refresh import refresh_session
                    refresh_res = await refresh_session(api_url=self.api_url)
                    if refresh_res.get("success"):
                        clear_all_cache()
                        return await self._send_request(
                            method=method,
                            path=path,
                            params=params,
                            json_body=json_body,
                            client=client,
                            _retried=True,
                        )
                except Exception:
                    pass

            raise VolleymetricsAuthError(
                f"Volleymetrics authentication failed (HTTP {resp.status_code}). "
                "Your session token has expired or is invalid. "
                "Please call the 'login_to_volleymetrics' tool (or say 'Log me into Volleymetrics') to re-authenticate."
            )

        return resp

    async def get_user_teams(
        self, force_refresh: bool = False, client: Optional[httpx.AsyncClient] = None
    ) -> List[TeamInfo]:
        """Fetch all Volleymetrics teams and accounts for the authenticated user (cached 15m)."""
        active_tid = self.team_id or get_volleymetrics_team_id()
        cache_key = compute_cache_key("user_teams", get_volleymetrics_token() or "anon")

        if not force_refresh:
            cached = get_cached_response(cache_key)
            if cached and isinstance(cached, list):
                return [TeamInfo.model_validate(t) for t in cached]

        teams: List[TeamInfo] = []

        # 1. Try /acct/accounts endpoint
        try:
            resp = await self._send_request("GET", "acct/accounts", client=client)
            if resp.status_code == 200:
                teams = parse_teams_response(resp.json(), active_team_id=active_tid)
        except VolleymetricsAuthError:
            raise
        except Exception:
            pass

        # 2. If empty, try /portal/teams endpoint
        if not teams:
            try:
                resp = await self._send_request("GET", "portal/teams", client=client)
                if resp.status_code == 200:
                    teams = parse_teams_response(resp.json(), active_team_id=active_tid)
            except VolleymetricsAuthError:
                raise
            except Exception:
                pass

        if teams:
            if not active_tid:
                first_tid = teams[0].team_id
                os.environ["VOLLEYMETRICS_TEAM_ID"] = first_tid
                self.team_id = first_tid
            set_cached_response(cache_key, [t.model_dump() for t in teams], TTL_SCHEDULE_TEAM)

        return teams

    async def resolve_active_team_id(
        self, force_refresh: bool = False, client: Optional[httpx.AsyncClient] = None
    ) -> Optional[str]:
        """Resolve active team ID from environment or auto-detected teams."""
        tid = self.team_id or get_volleymetrics_team_id()
        if tid:
            return tid

        teams = await self.get_user_teams(force_refresh=force_refresh, client=client)
        if teams:
            first_tid = teams[0].team_id
            os.environ["VOLLEYMETRICS_TEAM_ID"] = first_tid
            self.team_id = first_tid
            return first_tid

        return None

    async def get_recent_matches(
        self,
        team_id: Optional[str] = None,
        limit: int = 10,
        force_refresh: bool = False,
        client: Optional[httpx.AsyncClient] = None,
    ) -> List[MatchSummary]:
        """Fetch schedule and recent matches for a team from Volleymetrics (cached 15m)."""
        resolved_tid = team_id or self.team_id or await self.resolve_active_team_id(force_refresh=force_refresh, client=client)
        if not resolved_tid:
            raise VolleymetricsError(
                "No team_id provided and could not resolve an active team. "
                "Please specify team_id or call get_user_teams first."
            )

        cache_key = compute_cache_key("recent_matches", {"team_id": resolved_tid, "limit": limit})
        if not force_refresh:
            cached = get_cached_response(cache_key)
            if cached and isinstance(cached, list):
                return [MatchSummary.model_validate(m) for m in cached]

        matches: List[MatchSummary] = []

        # Try /portal/matches/team/{teamId}/matches
        try:
            path = f"portal/matches/team/{resolved_tid}/matches"
            resp = await self._send_request("GET", path, client=client)
            if resp.status_code == 200:
                matches = parse_matches_response(resp.json())
        except VolleymetricsAuthError:
            raise
        except Exception:
            pass

        # Fallback to /portal/matches
        if not matches:
            try:
                resp = await self._send_request("GET", "portal/matches", params={"teamId": resolved_tid}, client=client)
                if resp.status_code == 200:
                    matches = parse_matches_response(resp.json())
            except VolleymetricsAuthError:
                raise
            except Exception:
                pass

        matches = matches[:limit]
        if matches:
            set_cached_response(cache_key, [m.model_dump() for m in matches], TTL_SCHEDULE_TEAM)

        return matches

    async def get_match_player_stats(
        self,
        match_id: str,
        team_id: Optional[str] = None,
        force_refresh: bool = False,
        client: Optional[httpx.AsyncClient] = None,
    ) -> List[PlayerStats]:
        """Fetch individual athlete box score statistics for a match (cached 7 days)."""
        if not match_id or not match_id.strip():
            raise VolleymetricsError("match_id is required to fetch box score statistics.")

        clean_mid = match_id.strip()
        cache_key = compute_cache_key("player_stats", {"match_id": clean_mid, "team_id": team_id})
        if not force_refresh:
            cached = get_cached_response(cache_key)
            if cached and isinstance(cached, list):
                return [PlayerStats.model_validate(p) for p in cached]

        players: List[PlayerStats] = []

        # 1. Try /stats/matchStats/{teamId}
        target_tid = team_id or self.team_id or await self.resolve_active_team_id(client=client)
        if target_tid:
            try:
                path = f"stats/matchStats/{target_tid}"
                resp = await self._send_request("POST", path, json_body={"matchId": clean_mid}, client=client)
                if resp.status_code == 200:
                    players = parse_player_stats_response(resp.json(), team=target_tid)
            except VolleymetricsAuthError:
                raise
            except Exception:
                pass

        # 2. Try /analysis/matches/{matchId}
        if not players:
            try:
                path = f"analysis/matches/{clean_mid}"
                resp = await self._send_request("GET", path, client=client)
                if resp.status_code == 200:
                    players = parse_player_stats_response(resp.json(), team=target_tid)
            except VolleymetricsAuthError:
                raise
            except Exception:
                pass

        if players:
            set_cached_response(cache_key, [p.model_dump() for p in players], TTL_HISTORICAL_MATCH)
            return players

        raise VolleymetricsError(
            f"No player box score statistics found for match '{clean_mid}'. "
            "Ensure the match has completed and stats have been verified in Volleymetrics."
        )

    async def get_rotation_stats(
        self,
        match_id: str,
        team_id: Optional[str] = None,
        force_refresh: bool = False,
        client: Optional[httpx.AsyncClient] = None,
    ) -> List[RotationStats]:
        """Fetch rotation breakdown (P1 through P6) metrics for a match (cached 7 days)."""
        if not match_id or not match_id.strip():
            raise VolleymetricsError("match_id is required to fetch rotation statistics.")

        clean_mid = match_id.strip()
        cache_key = compute_cache_key("rotation_stats", {"match_id": clean_mid, "team_id": team_id})
        if not force_refresh:
            cached = get_cached_response(cache_key)
            if cached and isinstance(cached, list):
                return [RotationStats.model_validate(r) for r in cached]

        rotations: List[RotationStats] = []
        target_tid = team_id or self.team_id or await self.resolve_active_team_id(client=client)

        # 1. Try analysis endpoint /analysis/matches/{matchId}
        try:
            path = f"analysis/matches/{clean_mid}"
            resp = await self._send_request("GET", path, client=client)
            if resp.status_code == 200:
                rotations = parse_rotation_stats_response(resp.json(), team=target_tid)
        except VolleymetricsAuthError:
            raise
        except Exception:
            pass

        # 2. Try /stats/matchStats/{teamId}
        if not rotations and target_tid:
            try:
                path = f"stats/matchStats/{target_tid}"
                resp = await self._send_request("POST", path, json_body={"matchId": clean_mid}, client=client)
                if resp.status_code == 200:
                    rotations = parse_rotation_stats_response(resp.json(), team=target_tid)
            except VolleymetricsAuthError:
                raise
            except Exception:
                pass

        if rotations:
            set_cached_response(cache_key, [r.model_dump() for r in rotations], TTL_HISTORICAL_MATCH)
            return rotations

        raise VolleymetricsError(
            f"No rotation breakdown statistics found for match '{clean_mid}'. "
            "Ensure the match has completed video breakdown in Volleymetrics."
        )

    async def get_game_actions(
        self,
        match_id: str,
        set_number: Optional[int] = None,
        action_type: Optional[str] = None,
        player: Optional[str] = None,
        team: Optional[str] = None,
        quality: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
        force_refresh: bool = False,
        client: Optional[httpx.AsyncClient] = None,
    ) -> List[VolleyballAction]:
        """Retrieve tagged actions and touch events from match video analysis (cached 7 days)."""
        if not match_id or not match_id.strip():
            raise VolleymetricsError("match_id is required to fetch game actions.")

        clean_mid = match_id.strip()
        cache_key = compute_cache_key(
            "game_actions",
            {
                "match_id": clean_mid,
                "set": set_number,
                "action": action_type,
                "player": player,
                "team": team,
                "quality": quality,
                "limit": limit,
                "offset": offset,
            },
        )
        if not force_refresh:
            cached = get_cached_response(cache_key)
            if cached and isinstance(cached, list):
                return [VolleyballAction.model_validate(a) for a in cached]

        actions: List[VolleyballAction] = []

        try:
            path = f"analysis/matches/{clean_mid}"
            resp = await self._send_request("GET", path, client=client)
            if resp.status_code == 200:
                actions = parse_video_actions(
                    resp.json(),
                    set_number=set_number,
                    action_type=action_type,
                    player=player,
                    team=team,
                    quality=quality,
                    limit=limit,
                    offset=offset,
                )
        except VolleymetricsAuthError:
            raise
        except Exception as exc:
            raise VolleymetricsError(f"Failed to fetch actions for match '{clean_mid}': {exc}") from exc

        if actions:
            set_cached_response(cache_key, [a.model_dump() for a in actions], TTL_HISTORICAL_MATCH)
        return actions

    async def download_dvw(
        self,
        match_id: str,
        output_dir: Optional[str] = None,
        client: Optional[httpx.AsyncClient] = None,
    ) -> Dict[str, Any]:
        """Generate and download the official DataVolley (.dvw) scouting file for a match.

        Calls POST /dvw/dvws/generate?portalMatchId={matchId} and writes the resulting .dvw file to disk.
        """
        if not match_id or not match_id.strip():
            raise VolleymetricsError("match_id is required to download DVW file.")

        clean_mid = match_id.strip()
        target_dir = Path(output_dir).expanduser().resolve() if output_dir else Path.cwd()
        target_dir.mkdir(parents=True, exist_ok=True)
        target_file = target_dir / f"match_{clean_mid}.dvw"

        path = f"dvw/dvws/generate?portalMatchId={clean_mid}"
        resp = await self._send_request("POST", path, client=client)

        if resp.status_code == 200:
            content = resp.content
            target_file.write_bytes(content)
            return {
                "success": True,
                "match_id": clean_mid,
                "file_path": str(target_file),
                "file_size_bytes": len(content),
                "message": f"Successfully generated and downloaded DataVolley file to `{target_file}` ({len(content):,} bytes).",
            }
        else:
            raise VolleymetricsError(
                f"DVW export endpoint returned HTTP {resp.status_code}. "
                "Ensure your subscription tier includes DataVolley exports for this match."
            )
