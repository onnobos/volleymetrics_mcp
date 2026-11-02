"""FastMCP server instance and tool definitions for Volleymetrics MCP.

This server exposes Model Context Protocol tools for AI clients (such as Claude Desktop,
Cursor, or Antigravity) to query Volleymetrics REST APIs for volleyball matches, athlete box
scores, rotation breakdowns (P1-P6), play-by-play touches, and official DataVolley (.dvw) exports.
"""

from __future__ import annotations

import inspect
import os
from typing import Annotated, Any, Callable, Literal, Optional, TypeVar
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from volleymetrics_mcp.auth_refresh import interactive_login, refresh_session
from volleymetrics_mcp.cache import clear_all_cache
from volleymetrics_mcp.client import (
    VolleymetricsAuthError,
    VolleymetricsClient,
    VolleymetricsConnectionError,
    VolleymetricsError,
    VolleymetricsSecurityError,
    get_volleymetrics_team_id,
)
from volleymetrics_mcp.models import (
    render_actions_output,
    render_matches_output,
    render_player_stats_output,
    render_rotation_stats_output,
    render_teams_output,
)

F = TypeVar("F", bound=Callable[..., Any])


def _clean_docstring(fn: F) -> F:
    """Normalize function docstring indentation via inspect.cleandoc before MCP registration."""
    if fn.__doc__:
        fn.__doc__ = inspect.cleandoc(fn.__doc__)
    return fn


# Initialize FastMCP Server with Coaching Workflow Routing Decision Matrix
mcp = FastMCP(
    "volleymetrics-mcp",
    instructions=(
        "Volleymetrics MCP provides read-only volleyball performance intelligence, match statistics, "
        "tactical rotation analytics (P1-P6), tagged event-by-event touches, and DataVolley (.dvw) exports.\n\n"
        "### Tool Selection & Routing Decision Matrix:\n"
        "1. Team Identification: Call `get_user_teams` first if you do not know the user's `team_id` or need to discover available accounts.\n"
        "2. Match Discovery: Call `list_volleyball_matches` to locate recent matches and acquire valid `match_id` strings (e.g. '771842').\n"
        "3. Box Scores & Player Totals: Call `get_match_player_stats` for aggregate athlete stats (Kills, Errors, Attempts, Hit%, Aces, Digs, Blocks, Passing Avg).\n"
        "4. Tactical Rotation Efficiency: Call `get_rotation_breakdown` for sideout % and point-scoring % across setter rotations P1 through P6.\n"
        "5. Touch-by-Touch / Video Play-by-Play: Call `get_game_actions` for individual tagged touches (serves, passes, sets, attacks, digs, blocks) with DataVolley codes.\n"
        "6. Official Scouting Files: Call `download_match_dvw` when the user requests an authentic .dvw file written to disk.\n"
        "7. Interactive Authentication: If any tool returns an Authentication Error (401), call `login_to_volleymetrics` to open an interactive desktop browser window.\n"
        "8. Headless Session Refresh: Call `refresh_volleymetrics_session` to refresh an existing OAuth token headlessly when `.env` credentials are configured."
    ),
)


@mcp.tool(
    title="Get User Volleymetrics Teams",
    annotations=ToolAnnotations(
        title="Get User Volleymetrics Teams",
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=True,
    ),
    structured_output=False,
)
@_clean_docstring
async def get_user_teams(
    output_format: Annotated[
        Literal["markdown", "compact"],
        Field(
            default="markdown",
            description=(
                "Response representation format: 'markdown' returns a formatted Markdown table "
                "for human display; 'compact' returns a token-minimized JSON object for downstream agent chaining."
            ),
            examples=["markdown", "compact"],
        ),
    ] = "markdown",
    force_refresh: Annotated[
        bool,
        Field(
            default=False,
            description=(
                "When True, bypasses the 15-minute local disk cache (~/.volleymetrics_mcp/cache) "
                "and forces a live HTTPS GET request to the Volleymetrics user profile endpoint."
            ),
            examples=[False, True],
        ),
    ] = False,
) -> str:
    """Retrieve all Volleymetrics volleyball team profiles and organization memberships linked to the authenticated account, unlike `list_volleyball_matches` (which lists match schedules for a single team).

    ### When to Use
    - Discover the user's accessible `team_id` values, team names, school/club organizations, conferences, and coaching roles at the start of an analysis workflow.
    - Verify which team is currently marked active before calling `list_volleyball_matches`.

    ### When NOT to Use
    - Do NOT use to search for external opponent teams or public league rosters not tied to the user's account; call `list_volleyball_matches` to inspect opponents on your match schedule.
    - Do NOT call before every match query once `team_id` is known, as `list_volleyball_matches` automatically resolves the active team when `team_id` is omitted.

    ### Behavioral Guarantees & Caching
    - **Execution Contract**: Strictly read-only, idempotent HTTPS `GET` against `https://api.volleymetrics.hudl.com`.
    - **Caching Policy**: Cached on local disk (`~/.volleymetrics_mcp/cache`) with a 15-minute TTL (`900s`). Set `force_refresh=True` only after account membership changes.
    - **Rate Limiting**: Governed by a client-side token bucket (`2 req/s`, burst capacity `4`) with exponential backoff on HTTP `429`/`5xx`.
    - **Authentication**: Reads Bearer JWT credentials from `~/.volleymetrics_mcp/auth_state.json`, OS Keychain, or `.env`.

    ### Parameter & Workflow Semantics
    - Pass the `team_id` returned by this tool into `list_volleyball_matches`, `get_match_player_stats`, or `get_rotation_breakdown` when the user coaches multiple squads and wants to switch away from their default active team.
    - Prefer `output_format='compact'` when chaining team discovery into automated multi-step tool calls to save context tokens.

    ### Returns & Error States
    - `'markdown'`: Markdown table with columns `Team ID`, `Team Name`, `School / Club`, `Conference`, `Role`, and `Active`.
    - `'compact'`: JSON object `{"active_team_id": str, "count": int, "teams": [{"team_id": str, "name": str, "school_name": str, "conference": str, "role": str, "is_current": bool}]}`.
    - On missing or expired credentials (HTTP `401`/`403`), returns an actionable `⚠️ Authentication Error` instructing the agent to invoke `login_to_volleymetrics`.
    """
    try:
        client = VolleymetricsClient()
        teams = await client.get_user_teams(force_refresh=force_refresh)
        active_tid = client.team_id or get_volleymetrics_team_id()
        return render_teams_output(teams, active_team_id=active_tid, output_format=output_format)

    except VolleymetricsAuthError as exc:
        return (
            f"⚠️ Authentication Error: {exc}\n\n"
            "Action Required: Please call the `login_to_volleymetrics` tool (or say 'Log me into Volleymetrics') to log in via a browser window."
        )
    except VolleymetricsSecurityError as exc:
        return f"🛡️ Security Error: {exc}"
    except VolleymetricsConnectionError as exc:
        return f"🌐 Connection Error: {exc}"
    except VolleymetricsError as exc:
        return f"⚠️ Error: {exc}"
    except Exception as exc:
        return f"Unexpected error while fetching user teams: {type(exc).__name__}: {exc}"


@mcp.tool(
    title="List Team Volleyball Matches",
    annotations=ToolAnnotations(
        title="List Team Volleyball Matches",
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=True,
    ),
    structured_output=False,
)
@_clean_docstring
async def list_volleyball_matches(
    team_id: Annotated[
        Optional[str],
        Field(
            default=None,
            description=(
                "Volleymetrics team identifier (obtainable via get_user_teams). "
                "When omitted or None, automatically resolves to the authenticated user's active team ID."
            ),
            examples=["10482", "team-city-volley-basel"],
        ),
    ] = None,
    limit: Annotated[
        int,
        Field(
            default=10,
            ge=1,
            le=50,
            description="Maximum number of recent matches to return, ordered most-recent first (1 to 50).",
            examples=[10, 25],
        ),
    ] = 10,
    output_format: Annotated[
        Literal["markdown", "compact"],
        Field(
            default="markdown",
            description=(
                "Response representation format: 'markdown' returns a match schedule table; "
                "'compact' returns a token-efficient JSON object for programmatic match_id extraction."
            ),
            examples=["markdown", "compact"],
        ),
    ] = "markdown",
    force_refresh: Annotated[
        bool,
        Field(
            default=False,
            description="When True, bypasses the 15-minute local disk cache and fetches live match schedules from Volleymetrics.",
            examples=[False, True],
        ),
    ] = False,
) -> str:
    """List recent volleyball match schedules, opponent names, set scores, and DataVolley (`.dvw`) availability for a team, serving as the primary match discovery step before calling `get_match_player_stats`, `get_rotation_breakdown`, `get_game_actions`, or `download_match_dvw`.

    ### When to Use
    - Discover valid `match_id` identifiers (e.g. `'771842'`) required by all match-level analytics and export tools.
    - Review season win/loss records, set scores, match dates, opponent names, and whether video breakdown (`.dvw`) tagging is complete.

    ### When NOT to Use
    - Do NOT use to retrieve athlete box scores or hitting percentages; pass a discovered `match_id` to `get_match_player_stats`.
    - Do NOT use to evaluate P1–P6 sideout or point-scoring percentages; pass `match_id` to `get_rotation_breakdown`.
    - Do NOT use to inspect individual rally touches; pass `match_id` to `get_game_actions`.

    ### Behavioral Guarantees & Caching
    - **Execution Contract**: Strictly read-only, idempotent HTTPS `GET` query.
    - **Auto-Resolution**: When `team_id` is `None`, resolves the active team from `~/.volleymetrics_mcp/auth_state.json`, `.env`, or the user profile endpoint.
    - **Caching Policy**: Cached on local disk for 15 minutes (`900s`). Set `force_refresh=True` when checking if a newly uploaded match has finished processing.
    - **Rate Limiting**: Client token bucket (`2 req/s`, burst `4`) with automatic retry on HTTP `429`/`5xx`.

    ### Parameter & Workflow Semantics
    - Only matches where `has_dvw` (`DVW Ready`) is `True` contain full play-by-play event tags for `get_game_actions`, `get_rotation_breakdown`, and `download_match_dvw`.
    - Increase `limit` (up to `50`) when aggregating full-season trends across all matches.

    ### Returns & Error States
    - `'markdown'`: Markdown table with columns `Match ID`, `Date`, `Opponent`, `Result`, `Set Scores`, `Season`, and `DVW Ready`.
    - `'compact'`: JSON object `{"team_id": str, "count": int, "matches": [{"match_id": str, "date": str, "opponent": str, "result": str, "sets": [str], "season": str, "has_dvw": bool}]}`.
    - Returns `⚠️ Authentication Error` on HTTP `401`/`403` (recover via `login_to_volleymetrics`).
    """
    try:
        client = VolleymetricsClient()
        active_team_id = team_id or client.team_id or await client.resolve_active_team_id(force_refresh=force_refresh)
        matches = await client.get_recent_matches(team_id=active_team_id, limit=limit, force_refresh=force_refresh)
        return render_matches_output(matches, team_id=active_team_id, output_format=output_format)

    except VolleymetricsAuthError as exc:
        return (
            f"⚠️ Authentication Error: {exc}\n\n"
            "Action Required: Your Volleymetrics session has expired or is missing. "
            "Please call the `login_to_volleymetrics` tool (or say 'Log me into Volleymetrics') to log in via a browser window."
        )
    except VolleymetricsSecurityError as exc:
        return f"🛡️ Security Error: {exc}"
    except VolleymetricsConnectionError as exc:
        return f"🌐 Connection Error: {exc}"
    except VolleymetricsError as exc:
        return f"⚠️ Error: {exc}"
    except Exception as exc:
        return f"Unexpected error while fetching matches: {type(exc).__name__}: {exc}"


@mcp.tool(
    title="Get Match Player Box Score",
    annotations=ToolAnnotations(
        title="Get Match Player Box Score",
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=True,
    ),
    structured_output=False,
)
@_clean_docstring
async def get_match_player_stats(
    match_id: Annotated[
        str,
        Field(
            description="Unique Volleymetrics match identifier obtained from list_volleyball_matches.",
            examples=["771842", "m-100"],
        ),
    ],
    team_id: Annotated[
        Optional[str],
        Field(
            default=None,
            description=(
                "Optional Volleymetrics team ID (from get_user_teams) to restrict athlete box scores to one squad. "
                "When omitted, returns athlete statistics for all participating players in the match."
            ),
            examples=["10482"],
        ),
    ] = None,
    output_format: Annotated[
        Literal["markdown", "compact"],
        Field(
            default="markdown",
            description=(
                "Response representation format: 'markdown' renders a standard volleyball box score table; "
                "'compact' returns a token-efficient JSON array of athlete stat objects."
            ),
            examples=["markdown", "compact"],
        ),
    ] = "markdown",
    force_refresh: Annotated[
        bool,
        Field(
            default=False,
            description="When True, bypasses the 7-day local disk cache for historical match box scores and forces a live API fetch.",
            examples=[False, True],
        ),
    ] = False,
) -> str:
    """Fetch aggregated athlete box scores and individual volleyball statistics (attacking, serving, passing, blocking, and digging totals) for a single match, unlike `get_rotation_breakdown` (team P1–P6 rotation efficiencies) or `get_game_actions` (chronological touch-by-touch events).

    ### When to Use
    - Evaluate individual player performance in a match: Kills (`K`), Attack Errors (`E`), Total Attacks (`TA`), Hitting Percentage (`(K - E) / TA`), Assists (`Ast`), Service Aces (`SA`), Service Errors (`SE`), Receptions (`Rec`), Reception Errors (`RE`), Passing Average (`0.00`–`3.00` scale), Digs (`Dig`), Block Solos (`BS`), Block Assists (`BA`), Total Blocks (`TB`), and Total Points (`Pts`).
    - Identify top scorers, pin/middle offensive efficiency, and primary serve-receive passers.

    ### When NOT to Use
    - Do NOT use to analyze team sideout or point-scoring rates by setter rotation (P1–P6); call `get_rotation_breakdown` instead.
    - Do NOT use to inspect individual rally touches, court zones, or set-by-set play sequences; call `get_game_actions` instead.
    - Do NOT call with an unknown `match_id`; call `list_volleyball_matches` first.

    ### Behavioral Guarantees & Caching
    - **Execution Contract**: Strictly read-only, idempotent query.
    - **Derived Metric Integrity**: Automatically computes zero-division-safe Hitting Percentage (`0.000` when `TA == 0`), Total Blocks (`BS + 0.5 * BA`), and Total Points (`K + SA + BS + 0.5 * BA`).
    - **Caching Policy**: Historical match stats are cached on local disk for 7 days (`604800s`).
    - **Rate Limiting**: Client token bucket (`2 req/s`, burst `4`) with exponential backoff.

    ### Parameter & Workflow Semantics
    - Combine `match_id` (from `list_volleyball_matches`) with `team_id` (from `get_user_teams`) when you want to isolate a single team's roster; leave `team_id=None` when comparing both teams head-to-head.

    ### Returns & Error States
    - `'markdown'`: Box score table with columns `#`, `Player`, `Pos`, `SP`, `K`, `E`, `TA`, `Hit%`, `Ast`, `SA`, `SE`, `Rec`, `RE`, `Pass Avg`, `Dig`, `BS`, `BA`, `TB`, and `Pts`.
    - `'compact'`: JSON object `{"match_id": str, "player_count": int, "players": [{"name": str, "no": str, "pos": str, "sp": int, "k": int, "e": int, "ta": int, "hit_pct": float, "ast": int, "sa": int, "se": int, "rec": int, "re": int, "pass_avg": float, "dig": int, "bs": int, "ba": int, "tb": float, "pts": float}]}`.
    - Returns validation error if `match_id` is empty, or `⚠️ Authentication Error` on HTTP `401`/`403`.
    """
    if not match_id or not match_id.strip():
        return "Error: 'match_id' parameter is required. Use 'list_volleyball_matches' to find match IDs."

    try:
        client = VolleymetricsClient()
        players = await client.get_match_player_stats(
            match_id=match_id.strip(), team_id=team_id, force_refresh=force_refresh
        )
        return render_player_stats_output(players, match_id=match_id.strip(), output_format=output_format)

    except VolleymetricsAuthError as exc:
        return (
            f"⚠️ Authentication Error: {exc}\n\n"
            "Action Required: Please call the `login_to_volleymetrics` tool (or say 'Log me into Volleymetrics') to log in via a browser window."
        )
    except VolleymetricsSecurityError as exc:
        return f"🛡️ Security Error: {exc}"
    except VolleymetricsConnectionError as exc:
        return f"🌐 Connection Error: {exc}"
    except VolleymetricsError as exc:
        return f"⚠️ Error: {exc}"
    except Exception as exc:
        return f"Unexpected error while fetching player statistics: {type(exc).__name__}: {exc}"


@mcp.tool(
    title="Get Match Rotation Breakdown (P1-P6)",
    annotations=ToolAnnotations(
        title="Get Match Rotation Breakdown (P1-P6)",
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=True,
    ),
    structured_output=False,
)
@_clean_docstring
async def get_rotation_breakdown(
    match_id: Annotated[
        str,
        Field(
            description="Unique Volleymetrics match identifier obtained from list_volleyball_matches.",
            examples=["771842", "m-100"],
        ),
    ],
    team_id: Annotated[
        Optional[str],
        Field(
            default=None,
            description=(
                "Optional Volleymetrics team ID (from get_user_teams) to filter P1-P6 rotation analytics to a specific squad. "
                "When omitted, analyzes the default primary team in the match."
            ),
            examples=["10482"],
        ),
    ] = None,
    output_format: Annotated[
        Literal["markdown", "compact"],
        Field(
            default="markdown",
            description=(
                "Response representation format: 'markdown' renders a P1-P6 tactical efficiency table; "
                "'compact' returns a token-efficient JSON object."
            ),
            examples=["markdown", "compact"],
        ),
    ] = "markdown",
    force_refresh: Annotated[
        bool,
        Field(
            default=False,
            description="When True, bypasses the 7-day local disk cache and recalculates rotation metrics from live Volleymetrics data.",
            examples=[False, True],
        ),
    ] = False,
) -> str:
    """Fetch team tactical sideout, point-scoring, and first-ball sideout (FBSO) efficiencies broken down across setter rotations P1 through P6 for a match, unlike `get_match_player_stats` (individual player box scores) or `get_game_actions` (event-level rally touches).

    ### When to Use
    - Diagnose which setter rotation (`P1` through `P6`) is leaking sideout points or generating service scoring runs.
    - Compare Sideout Percentage (`Sideout%`), First-Ball Sideout Percentage (`FBSO%`), Point Scoring Percentage (`Point Score%`), and Setter Distribution tendencies (`Left/OH`, `Middle`, `Right/Opp`, `Pipe/Backrow`) by rotation.

    ### When NOT to Use
    - Do NOT use for individual athlete kill/dig/pass totals; call `get_match_player_stats` instead.
    - Do NOT use to inspect which specific player committed reception or attack errors inside a weak rotation; call `get_game_actions` after identifying the rotation here.

    ### Behavioral Guarantees & Caching
    - **Execution Contract**: Strictly read-only, idempotent query.
    - **Domain Conventions**: `P1`–`P6` denote the setter's starting court zone (`P1` = Zone 1 right-back, `P6` = Zone 6 middle-back, `P5` = Zone 5 left-back, `P4` = Zone 4 front-left, `P3` = Zone 3 front-center, `P2` = Zone 2 front-right).
    - **Caching Policy**: Cached on local disk for 7 days (`604800s`).
    - **Rate Limiting**: Client token bucket (`2 req/s`, burst `4`) with automatic retry.

    ### Parameter & Workflow Semantics
    - Typical coaching workflow: call `get_rotation_breakdown` first to find any rotation with `Sideout% < 50%`, then call `get_game_actions(match_id=..., action_type='receive', quality='error')` to pinpoint the exact breakdown cause.

    ### Returns & Error States
    - `'markdown'`: Table with columns `Rotation`, `SO Opp`, `SO Pts`, `Sideout%`, `FBSO%`, `Srv Opp`, `Srv Pts`, `Point Score%`, and `Setter Distribution`.
    - `'compact'`: JSON object `{"match_id": str, "rotations": [{"rot": str, "so_opp": int, "so_pts": int, "so_pct": float, "fbso_pct": float, "ps_opp": int, "ps_pts": int, "ps_pct": float, "dist": dict}]}`.
    - Returns validation error if `match_id` is empty, or `⚠️ Authentication Error` on HTTP `401`/`403`.
    """
    if not match_id or not match_id.strip():
        return "Error: 'match_id' parameter is required. Use 'list_volleyball_matches' to find match IDs."

    try:
        client = VolleymetricsClient()
        rotations = await client.get_rotation_stats(
            match_id=match_id.strip(), team_id=team_id, force_refresh=force_refresh
        )
        return render_rotation_stats_output(rotations, match_id=match_id.strip(), output_format=output_format)

    except VolleymetricsAuthError as exc:
        return (
            f"⚠️ Authentication Error: {exc}\n\n"
            "Action Required: Please call the `login_to_volleymetrics` tool (or say 'Log me into Volleymetrics') to log in via a browser window."
        )
    except VolleymetricsSecurityError as exc:
        return f"🛡️ Security Error: {exc}"
    except VolleymetricsConnectionError as exc:
        return f"🌐 Connection Error: {exc}"
    except VolleymetricsError as exc:
        return f"⚠️ Error: {exc}"
    except Exception as exc:
        return f"Unexpected error while fetching rotation breakdown: {type(exc).__name__}: {exc}"


@mcp.tool(
    title="Get Match Tagged Game Actions",
    annotations=ToolAnnotations(
        title="Get Match Tagged Game Actions",
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=True,
    ),
    structured_output=False,
)
@_clean_docstring
async def get_game_actions(
    match_id: Annotated[
        str,
        Field(
            description="Unique Volleymetrics match identifier obtained from list_volleyball_matches.",
            examples=["771842", "m-100"],
        ),
    ],
    set_number: Annotated[
        Optional[int],
        Field(
            default=None,
            ge=1,
            le=5,
            description="Optional set number (1 to 5) to restrict play-by-play touches to a single set. When None, searches across all sets.",
            examples=[1, 3],
        ),
    ] = None,
    action_type: Annotated[
        Optional[Literal["serve", "receive", "set", "attack", "block", "dig", "free_ball"]],
        Field(
            default=None,
            description=(
                "Optional volleyball skill filter mapping to DataVolley skill codes: "
                "'serve' (S), 'receive' (R), 'set' (E), 'attack' (A), 'block' (B), 'dig' (D), or 'free_ball' (F)."
            ),
            examples=["attack", "receive", "serve"],
        ),
    ] = None,
    player: Annotated[
        Optional[str],
        Field(
            default=None,
            description="Optional athlete filter matching jersey number (e.g. '17' or '#7') or case-insensitive player name substring.",
            examples=["17", "Plummer"],
        ),
    ] = None,
    team: Annotated[
        Optional[str],
        Field(
            default=None,
            description="Optional team filter: 'a' (home/primary team), 'b' (away/opponent team), or team name substring.",
            examples=["a", "b"],
        ),
    ] = None,
    quality: Annotated[
        Optional[Literal["kill", "error", "ace", "assist", "in_play", "perfect_pass"]],
        Field(
            default=None,
            description=(
                "Optional outcome/evaluation filter mapping to DataVolley evaluation codes: "
                "'kill' (# on attack/block), 'error' (=), 'ace' (# on serve), 'perfect_pass' (# on receive), 'assist', or 'in_play'."
            ),
            examples=["kill", "error", "perfect_pass"],
        ),
    ] = None,
    limit: Annotated[
        int,
        Field(
            default=50,
            ge=1,
            le=200,
            description="Maximum number of chronological touch events to return per page (1 to 200).",
            examples=[50, 100],
        ),
    ] = 50,
    offset: Annotated[
        int,
        Field(
            default=0,
            ge=0,
            description="Zero-based pagination offset for stepping through chronological match touches.",
            examples=[0, 50, 100],
        ),
    ] = 0,
    output_format: Annotated[
        Literal["markdown", "compact"],
        Field(
            default="markdown",
            description=(
                "Response representation format: 'markdown' renders a chronological play-by-play table; "
                "'compact' returns a token-efficient JSON object with total count and filtered breakdown."
            ),
            examples=["markdown", "compact"],
        ),
    ] = "markdown",
    force_refresh: Annotated[
        bool,
        Field(
            default=False,
            description="When True, bypasses the 7-day local disk cache and fetches raw match events directly from Volleymetrics.",
            examples=[False, True],
        ),
    ] = False,
) -> str:
    """Query chronologically ordered, event-by-event volleyball touches and DataVolley (`.dvw`) scout tags from a match with optional set, skill, player, team, and quality filters, unlike `get_match_player_stats` (aggregate player totals) or `download_match_dvw` (raw `.dvw` file export to disk).

    ### When to Use
    - Inspect granular play-by-play contacts, video timestamps, start/end court zones (`1`–`9`), attack combinations, and DataVolley codes (e.g. `*17AT#`, `a07SM=`).
    - Filter specific tactical subsets, such as all reception errors (`action_type='receive', quality='error'`), clutch kills in Set 5 (`set_number=5, action_type='attack', quality='kill'`), or an individual hitter's shot tendencies (`player='17', action_type='attack'`).

    ### When NOT to Use
    - Do NOT page through all match touches just to compute a player's kill or dig totals; call `get_match_player_stats` in a single request instead.
    - Do NOT use for P1–P6 sideout summary tables; call `get_rotation_breakdown` instead.
    - Do NOT use when the user wants a `.dvw` file saved to disk for external software; call `download_match_dvw` instead.

    ### Behavioral Guarantees & Caching
    - **Execution Contract**: Strictly read-only, idempotent query.
    - **Caching Policy**: Raw match touch timelines are cached on local disk for 7 days (`604800s`); all filtering and pagination execute locally in memory after the initial fetch.
    - **Rate Limiting**: Client token bucket (`2 req/s`, burst `4`) with automatic retry.

    ### Parameter & Workflow Semantics
    - All provided filter parameters (`set_number`, `action_type`, `player`, `team`, `quality`) combine via logical `AND` before `offset` and `limit` pagination are applied.
    - The response header always reports `total_matching` alongside `returned_count` so you know whether to advance `offset` (`offset + limit`) for additional pages.

    ### Returns & Error States
    - `'markdown'`: Summary counts by action type followed by a table with columns `#`, `Set`, `Score`, `Time`, `Team`, `Player`, `Action`, `Quality`, `DVW Code`, and `Tactical Details`.
    - `'compact'`: JSON object `{"match": str, "total_matching": int, "returned_count": int, "by_type": dict, "events": [{"idx": int, "set": int, "score": str, "time": float, "team": str, "no": str, "player": str, "type": str, "quality": str, "dvw": str, "zone": str, "fbso": bool}]}`.
    - Returns validation error if `match_id` is empty, or `⚠️ Authentication Error` on HTTP `401`/`403`.
    """
    if not match_id or not match_id.strip():
        return "Error: 'match_id' parameter is required. Use 'list_volleyball_matches' to find match IDs."

    try:
        client = VolleymetricsClient()
        actions = await client.get_game_actions(
            match_id=match_id.strip(),
            set_number=set_number,
            action_type=action_type,
            player=player,
            team=team,
            quality=quality,
            limit=limit,
            offset=offset,
            force_refresh=force_refresh,
        )
        return render_actions_output(actions, match_name=match_id.strip(), output_format=output_format)

    except VolleymetricsAuthError as exc:
        return (
            f"⚠️ Authentication Error: {exc}\n\n"
            "Action Required: Please call the `login_to_volleymetrics` tool (or say 'Log me into Volleymetrics') to log in via a browser window."
        )
    except VolleymetricsSecurityError as exc:
        return f"🛡️ Security Error: {exc}"
    except VolleymetricsConnectionError as exc:
        return f"🌐 Connection Error: {exc}"
    except VolleymetricsError as exc:
        return f"⚠️ Error: {exc}"
    except Exception as exc:
        return f"Unexpected error while fetching game actions: {type(exc).__name__}: {exc}"


@mcp.tool(
    title="Download Match DataVolley (.dvw) File",
    annotations=ToolAnnotations(
        title="Download Match DataVolley (.dvw) File",
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=True,
    ),
    structured_output=False,
)
@_clean_docstring
async def download_match_dvw(
    match_id: Annotated[
        str,
        Field(
            description="Unique Volleymetrics match identifier obtained from list_volleyball_matches.",
            examples=["771842", "m-100"],
        ),
    ],
    output_dir: Annotated[
        Optional[str],
        Field(
            default=None,
            description=(
                "Optional local directory path where the exported match_<match_id>.dvw file will be saved. "
                "When omitted or None, writes to the current working directory."
            ),
            examples=["./exports", "/tmp/dvw"],
        ),
    ] = None,
) -> str:
    """Export and save the official raw DataVolley (`.dvw`) scouting file for a match to the local filesystem for external analysis software, unlike `get_game_actions` (which returns parsed touch events directly in the conversation).

    ### When to Use
    - Save an authentic `.dvw` file (`[3DATAVOLLEYSCOUT]` format) to disk for import into DataVolley 4, VolleyStation, Click&Scout, or OpenVolley / R / Python (`datavolley`) pipelines.
    - Archive raw match scouting files locally.

    ### When NOT to Use
    - Do NOT use when you only need to analyze player stats, rotations, or touches inside the chat; call `get_match_player_stats`, `get_rotation_breakdown`, or `get_game_actions` instead to avoid unnecessary filesystem writes.
    - Do NOT call if `has_dvw` is `False` in `list_volleyball_matches`.

    ### Behavioral Guarantees & Filesystem Policy
    - **Side Effects**: Remote Volleymetrics interaction is strictly read-only (`GET`), but this tool writes a local file named `match_<match_id>.dvw` inside `output_dir` (hence `readOnlyHint=False`, `destructiveHint=False`, `idempotentHint=True`).
    - **Path Sanitization**: Strips unsafe characters from `match_id` and resolves `output_dir` via `Path.expanduser().resolve()` to prevent path traversal.
    - **Fallback Generation**: If the native `.dvw` endpoint returns plain JSON events, automatically synthesizes a standards-compliant `.dvw` file containing match metadata and `[3SCOUT]` codes.
    - **Rate Limiting**: Client token bucket (`2 req/s`, burst `4`) with automatic retry.

    ### Parameter & Workflow Semantics
    - Acquire `match_id` from `list_volleyball_matches` first; pass an explicit `output_dir` when organizing exports for a specific opponent or tournament folder.

    ### Returns & Error States
    - Returns a Markdown confirmation containing `Match ID`, resolved absolute `Local File` path, and `File Size` in bytes.
    - Returns validation error if `match_id` is empty, or `⚠️ Authentication Error` on HTTP `401`/`403`.
    """
    if not match_id or not match_id.strip():
        return "Error: 'match_id' parameter is required. Use 'list_volleyball_matches' to find match IDs."

    try:
        client = VolleymetricsClient()
        res = await client.download_dvw(match_id=match_id.strip(), output_dir=output_dir)
        return (
            f"✅ **DataVolley Export Successful!**\n\n"
            f"- **Match ID**: `{res.get('match_id')}`\n"
            f"- **Local File**: `{res.get('file_path')}`\n"
            f"- **File Size**: `{res.get('file_size_bytes'):,} bytes`\n\n"
            "The `.dvw` file is ready for import into DataVolley, VolleyStation, or OpenVolley analysis libraries."
        )

    except VolleymetricsAuthError as exc:
        return (
            f"⚠️ Authentication Error: {exc}\n\n"
            "Action Required: Please call the `login_to_volleymetrics` tool (or say 'Log me into Volleymetrics') to log in via a browser window."
        )
    except VolleymetricsSecurityError as exc:
        return f"🛡️ Security Error: {exc}"
    except VolleymetricsConnectionError as exc:
        return f"🌐 Connection Error: {exc}"
    except VolleymetricsError as exc:
        return f"⚠️ Error: {exc}"
    except Exception as exc:
        return f"Unexpected error while generating DVW file: {type(exc).__name__}: {exc}"


@mcp.tool(
    title="Interactive Browser Login to Volleymetrics",
    annotations=ToolAnnotations(
        title="Interactive Browser Login to Volleymetrics",
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=False,
        openWorldHint=True,
    ),
    structured_output=False,
)
@_clean_docstring
async def login_to_volleymetrics(
    timeout_seconds: Annotated[
        int,
        Field(
            default=300,
            ge=30,
            le=900,
            description=(
                "Maximum time in seconds (30 to 900) to keep the interactive Chromium browser window open "
                "waiting for the user to complete Volleymetrics / Hudl login before aborting."
            ),
            examples=[300, 180],
        ),
    ] = 300,
) -> str:
    """Launch an interactive desktop Chromium browser window to authenticate with the Volleymetrics / Hudl portal (supporting password managers, SSO, and 2FA) and persist the OAuth Bearer session locally, unlike `refresh_volleymetrics_session` (which performs a headless OAuth token refresh using environment variables).

    ### When to Use
    - Recover from `⚠️ Authentication Error (401)` returned by any Volleymetrics query tool.
    - Perform initial setup without storing plaintext passwords in `.env` (supports 1Password, Bitwarden, Apple Passwords / iCloud Keychain, Hudl SSO, and two-factor authentication).

    ### When NOT to Use
    - Do NOT call proactively before every query; persisted sessions in `~/.volleymetrics_mcp/auth_state.json` remain valid across conversations until token expiry.
    - Do NOT call in headless CI/server environments without a local display; use `refresh_volleymetrics_session` with `.env` credentials instead.

    ### Behavioral Guarantees & Security
    - **Side Effects**: Launches a visible Playwright Chromium window to `https://portal.volleymetrics.hudl.com`, writes captured Bearer tokens and active team metadata to `~/.volleymetrics_mcp/auth_state.json` (permissions `0600`) and OS Keychain, and clears the local disk query cache (`clear_all_cache()`).
    - **Zero Password Exposure**: Credentials and 2FA codes are entered directly in the browser by the user and are never read or logged by the MCP server.
    - **Auto-Close & Timeout**: Automatically closes the browser the instant a valid JWT session is detected on the dashboard, or aborts after `timeout_seconds`.

    ### Parameter & Workflow Semantics
    - Keep the default `timeout_seconds=300` (5 minutes) when the user needs time to approve mobile 2FA prompts; reduce to `60`–`120` for quick password-manager autofill.

    ### Returns & Error States
    - On success: Markdown summary reporting `Storage State Saved` path and `Masked Session Token` (`eyJhbGci...`).
    - On failure/timeout: Actionable error describing whether Playwright Chromium is missing (`playwright install chromium`) or the login window timed out.
    """
    res = await interactive_login(timeout_seconds=timeout_seconds)
    if res.get("success"):
        clear_all_cache()
        return (
            f"✅ **Volleymetrics Login Successful!**\n\n"
            f"- **Browser Window Closed**: Login completed.\n"
            f"- **Session State Saved**: `{res.get('storage_state_file')}`\n"
            f"- **Active Session Token**: `{res.get('masked_token')}`\n\n"
            "You are authenticated! You can now run any Volleymetrics queries (box scores, matches, rotations, actions, DVW)."
        )
    else:
        err = res.get("error", "Unknown error")
        return f"❌ **Volleymetrics Login Failed**: {err}"


@mcp.tool(
    title="Refresh Volleymetrics OAuth Session",
    annotations=ToolAnnotations(
        title="Refresh Volleymetrics OAuth Session",
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=False,
        openWorldHint=True,
    ),
    structured_output=False,
)
@_clean_docstring
async def refresh_volleymetrics_session(
    clear_cache: Annotated[
        bool,
        Field(
            default=True,
            description=(
                "When True (default), clears the local disk query cache (~/.volleymetrics_mcp/cache) "
                "after minting a new OAuth Bearer token so subsequent queries fetch fresh data."
            ),
            examples=[True, False],
        ),
    ] = True,
    timeout_seconds: Annotated[
        int,
        Field(
            default=30,
            ge=5,
            le=120,
            description=(
                "Maximum timeout in seconds (5 to 120) for the headless OAuth token refresh "
                "request against https://auth.volleymetrics.hudl.com."
            ),
            examples=[30, 60],
        ),
    ] = 30,
) -> str:
    """Perform a headless OAuth 2.0 token refresh for the Volleymetrics session using `.env` credentials (`VOLLEYMETRICS_EMAIL` and `VOLLEYMETRICS_PASSWORD`), unlike `login_to_volleymetrics` (which opens an interactive desktop browser window for manual/SSO/2FA login).

    ### When to Use
    - Refresh an expired Volleymetrics Bearer token in headless or automated environments where `VOLLEYMETRICS_EMAIL` and `VOLLEYMETRICS_PASSWORD` are configured in `.env`.
    - Test whether stored `.env` credentials can mint a fresh token without user interaction.

    ### When NOT to Use
    - Do NOT use when the user authenticates via password manager, Hudl SSO, or 2FA without storing plaintext credentials in `.env`; call `login_to_volleymetrics` instead.
    - Do NOT call in a loop if this tool returns `Interactive Login Recommended`, as that indicates `.env` credentials are not configured.

    ### Behavioral Guarantees & Security
    - **Side Effects**: Executes an OAuth password-grant token request (or headless Playwright fallback), persists the new JWT to OS Keychain and `.env` (`chmod 0600`), and optionally clears the local response cache when `clear_cache=True`.
    - **Fallback Guidance**: If `.env` credentials are absent, performs zero network calls and immediately directs the agent to call `login_to_volleymetrics`.

    ### Parameter & Workflow Semantics
    - Leave `clear_cache=True` when recovering from an authentication error or switching accounts; set `clear_cache=False` to retain cached 7-day historical match data across token renewals.

    ### Returns & Error States
    - On success: Confirmation message with masked JWT (`eyJhbGci...`).
    - When `.env` credentials are missing or rejected: Actionable instructions to invoke `login_to_volleymetrics`.
    """
    _ = timeout_seconds
    if os.getenv("VOLLEYMETRICS_EMAIL") and os.getenv("VOLLEYMETRICS_PASSWORD"):
        res = await refresh_session()
        if res.get("success"):
            if clear_cache:
                clear_all_cache()
            return (
                f"✅ Volleymetrics Session Refreshed Successfully!\n\n"
                f"- Masked Token: `{res.get('masked_token')}`\n\n"
                "The active session has been updated. You can now re-run your volleyball queries."
            )
        else:
            err = res.get("error", "Unknown error")
            return (
                f"❌ Failed to refresh Volleymetrics session: {err}\n\n"
                "Recommended Action: Call the `login_to_volleymetrics` tool (or say 'Log me into Volleymetrics') to log in "
                "interactively via a browser window using your password manager, Hudl SSO, or 2FA."
            )

    return (
        "ℹ️ **Interactive Login Recommended**\n\n"
        "Username and password are not stored in `.env`. Please call the `login_to_volleymetrics` tool "
        "(or say **'Log me into Volleymetrics'**).\n\n"
        "This will open a visible pop-up browser window to https://portal.volleymetrics.hudl.com where you can log in "
        "using your password manager, Hudl SSO, or 2FA. Once you reach the dashboard, the session is "
        "automatically saved to `~/.volleymetrics_mcp/auth_state.json` and the window closes."
    )


# Backwards-compatible Python function alias for legacy callers/tests without registering a duplicate MCP tool
refresh_volleymetrics_cookie = refresh_volleymetrics_session


# ---------------------------------------------------------------------------
# FastMCP Prompts for Volleyball Coaching and Scouting Workflows
# ---------------------------------------------------------------------------

@mcp.prompt()
def scout_opponent(
    opponent_name: Annotated[
        str,
        "Name of the opponent volleyball team or school/club to scout",
    ],
) -> str:
    """Generate a comprehensive tactical scouting report on an opponent team."""
    return (
        f"You are an expert Volleyball Performance Analyst and Head Coach preparing a match scouting report on '{opponent_name}'.\n\n"
        "Follow these analytical steps:\n"
        f"1. **Locate Match Data**: Call `list_volleyball_matches(limit=10)` to find recent matches involving '{opponent_name}'.\n"
        "2. **Analyze Opponent Offense**: For the identified match, call `get_match_player_stats(match_id=...)` to inspect the box score. "
        "Identify their primary point producers, high-volume pin hitters, and their hitting percentage ((K - E) / TA).\n"
        "3. **Audit Opponent Rotations**: Call `get_rotation_breakdown(match_id=...)` to examine their sideout efficiencies across rotations P1 through P6. "
        "Highlight their weakest sideout rotation (lowest sideout %) where our team should look to score multi-point service runs.\n"
        "4. **Analyze Serve-Receive Vulnerabilities**: Call `get_game_actions(match_id=..., action_type='receive')` to evaluate their passers. "
        "Find which passer has the highest error rate or lowest passing average.\n"
        "5. **Synthesize Game Plan**: Produce a structured coaching report containing:\n"
        "   - **Key Players to Neutralize**: Attack tendencies and favored hitting zones.\n"
        "   - **Serving Strategy**: Recommended serving targets and specific passers to isolate.\n"
        "   - **Defensive & Blocking Scheme**: Perimeter vs middle-up defense, commit vs read blocking.\n"
        "   - **Rotational Exploit Targets**: Specific rotations (P1-P6) where we must apply maximum pressure."
    )


@mcp.prompt()
def analyze_rotation_weaknesses(
    match_id: Annotated[
        str,
        "Unique Volleymetrics match ID to diagnose",
    ],
) -> str:
    """Diagnose sideout and point scoring vulnerabilities across rotations P1 through P6."""
    return (
        f"You are a Volleyball Tactical Analyst conducting a deep-dive rotation analysis for match '{match_id}'.\n\n"
        "Execute the following steps:\n"
        f"1. **Fetch Rotation Analytics**: Call `get_rotation_breakdown(match_id='{match_id}')` to retrieve sideout percentage, "
        "point-scoring percentage, and first-ball sideout (FBSO) rates for rotations P1 through P6.\n"
        f"2. **Investigate Trouble Rotations**: For any rotation with sideout efficiency below 50%:\n"
        f"   - Call `get_game_actions(match_id='{match_id}', action_type='receive', quality='error')` to check for direct reception errors.\n"
        f"   - Call `get_game_actions(match_id='{match_id}', action_type='attack', quality='error')` to check if errors were unforced attack errors or blocked attacks.\n"
        "3. **Setter Distribution**: Evaluate whether the setter became predictable in out-of-system plays.\n"
        "4. **Actionable Coaching Recommendations**: Provide concrete adjustments:\n"
        "   - Serve-receive pattern adjustment (e.g. dropping an OH deeper, switching to a 2-person receive line).\n"
        "   - Route adjustments (e.g. running middle slide behind setter in P1/P2 or back-row pipe to open the net).\n"
        "   - Sideout tempo modifications to relieve pressure."
    )


@mcp.prompt()
def match_mvp_breakdown(
    match_id: Annotated[
        str,
        "Unique Volleymetrics match ID to evaluate",
    ],
) -> str:
    """Determine the Most Valuable Player (MVP) of a match using advanced volleyball metrics."""
    return (
        f"You are an Elite Volleyball Analyst selecting the official Match MVP for match '{match_id}'.\n\n"
        "Follow these steps:\n"
        f"1. **Retrieve Box Score**: Call `get_match_player_stats(match_id='{match_id}')`.\n"
        "2. **Calculate Advanced Value Metrics**:\n"
        "   - **True Points**: Kills + Aces + Solo Blocks + 0.5 * Block Assists.\n"
        "   - **Hitting Efficiency**: (Kills - Attack Errors) / Total Attacks.\n"
        "   - **Point Differential**: Total Points scored minus Total Errors committed.\n"
        f"3. **Inspect Clutch Touches**: Call `get_game_actions(match_id='{match_id}', quality='kill', limit=50)` to evaluate late-set kills.\n"
        "4. **Award Categories**:\n"
        "   - 🏆 **Match MVP**: The athlete with the highest net impact on match outcome.\n"
        "   - ⚡ **Offensive Player of the Match**: Highest kill efficiency and terminal attack rate.\n"
        "   - 🛡️ **Defensive Anchor**: Best performance in digs, serve receive stability, and block touches.\n"
        "   - ⭐ **Unsung Hero**: A role player whose contributions changed match momentum."
    )


@mcp.prompt()
def datavolley_export(
    match_id: Annotated[
        str,
        "Unique Volleymetrics match ID",
    ],
    set_number: Annotated[
        Optional[int],
        "Optional set number to export (1-5). If omitted, exports all available touches.",
    ] = None,
) -> str:
    """Generate standardized DataVolley (.dvw) scouting codes for match touches."""
    set_clause = f", set_number={set_number}" if set_number is not None else ""
    return (
        f"You are an accredited DataVolley Scout transforming touch data for match '{match_id}' into standard .dvw code format.\n\n"
        "Follow these steps:\n"
        f"1. **Optionally Download Official DVW File**: Call `download_match_dvw(match_id='{match_id}')` to retrieve the authentic .dvw file directly.\n"
        f"2. **Retrieve Match Touches**: Call `get_game_actions(match_id='{match_id}'{set_clause}, output_format='compact', limit=100)`.\n"
        "3. **Format DataVolley Codes** using standard OpenVolley conventions:\n"
        "   - **Team**: `*` for Home team / Team A, `a` for Away team / Team B.\n"
        "   - **Jersey**: 2 digits (e.g., `07`, `17`, `20`). If unknown, use `00`.\n"
        "   - **Skill Codes**: `S` (Serve), `R` (Receive), `E` (Set), `A` (Attack), `B` (Block), `D` (Dig), `F` (Freeball).\n"
        "   - **Evaluation Codes**: `#` (Perfect / Kill / Ace), `+` (Positive), `!` (Medium), `-` (Poor / Negative), `=` (Error).\n"
        "4. **Present Output**: Provide a clean DataVolley event table and a raw text block of `.dvw` scouting strings ready for copy-pasting."
    )


@mcp.prompt()
def serve_receive_audit(
    match_id: Annotated[
        str,
        "Unique Volleymetrics match ID to audit",
    ],
) -> str:
    """Conduct a comprehensive serve-receive and passing performance audit."""
    return (
        f"You are a Volleyball Passing & Receiving Specialist auditing serve-receive performance for match '{match_id}'.\n\n"
        "Follow these steps:\n"
        f"1. **Fetch Receptions & Serves**: Call `get_game_actions(match_id='{match_id}', action_type='receive', limit=100)` and "
        f"`get_game_actions(match_id='{match_id}', action_type='serve', limit=100)`.\n"
        "2. **Calculate Passer Efficiency Ratings**:\n"
        "   - Perfect Pass (# / 3-pass): In-system ball enabling middle quick or slide.\n"
        "   - Positive Pass (+ / 2-pass): Good pass enabling pin attack options.\n"
        "   - Medium Pass (! / 1-pass): Out-of-system emergency set.\n"
        "   - Reception Error (= / 0-pass): Direct ace conceded.\n"
        "   - Overall Rating Formula: `(3 * perfect + 2 * positive + 1 * medium) / total_receptions` (Target: > 2.00).\n"
        "3. **Diagnose Opponent Service Pressure**:\n"
        "   - Identify which opponent servers caused the most reception errors or poor passes.\n"
        "   - Analyze target areas (Zone 1, Zone 5, Zone 6, or seam between passers).\n"
        "4. **Deliver Coaching Adjustments**:\n"
        "   - Specific passing lineup adjustments (e.g. shift receive seam left/right, pinch libero).\n"
        "   - First-contact focus areas for next practice session."
    )


def main() -> None:
    """Run the FastMCP server via standard IO transport."""
    mcp.run()


if __name__ == "__main__":
    main()
