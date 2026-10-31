"""FastMCP server instance and tool definitions for Volleymetrics MCP.

This server exposes Model Context Protocol tools for AI clients (such as Claude Desktop,
Cursor, or Antigravity) to query Volleymetrics REST APIs for volleyball matches, athlete box
scores, rotation breakdowns (P1-P6), play-by-play touches, and official DataVolley (.dvw) exports.
"""

from __future__ import annotations

import os
from typing import Annotated, Optional
from mcp.server.fastmcp import FastMCP

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

# Initialize FastMCP Server
mcp = FastMCP(
    "volleymetrics-mcp",
    instructions=(
        "Volleymetrics MCP Server connects to Volleymetrics and Hudl volleyball analytics APIs "
        "to retrieve match schedules, athlete box scores, rotation breakdown statistics (P1-P6), "
        "complete event-by-event volleyball touches with DataVolley (.dvw) skill and evaluation codes, "
        "and official DataVolley (.dvw) file exports. "
        "Use get_user_teams to discover your team ID automatically, list_volleyball_matches to find matches, "
        "get_match_player_stats to analyze individual player box scores, get_rotation_breakdown to analyze P1-P6 efficiencies, "
        "get_game_actions to query all tagged actions and touches (serves, passes, attacks, digs, sets, blocks), "
        "download_match_dvw to generate official DataVolley files, "
        "and login_to_volleymetrics to log in interactively via a pop-up browser window without storing passwords."
    ),
)


@mcp.tool()
async def get_user_teams(
    output_format: Annotated[
        str,
        "Desired output representation: 'markdown' for human-readable table or 'compact' for token-efficient JSON",
    ] = "markdown",
    force_refresh: Annotated[
        bool,
        "Bypass local 15-minute disk cache and force a live API fetch",
    ] = False,
) -> str:
    """Discover and list all Volleymetrics teams and accounts associated with your credentials.

    Retrieves team names, team IDs, club/school organizations, conferences, roles,
    and active status directly from your authenticated Volleymetrics account.

    Args:
        output_format: Format of the output: 'markdown' (clean table) or 'compact' (token-efficient JSON).
        force_refresh: If True, bypasses local 15-minute disk cache and forces a live fetch.

    Returns:
        A formatted Markdown table or compact JSON dictionary of your teams.
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


@mcp.tool()
async def list_volleyball_matches(
    team_id: Annotated[
        Optional[str],
        "Volleymetrics team identifier. If omitted, automatically resolves your active team ID.",
    ] = None,
    limit: Annotated[
        int,
        "Maximum number of recent matches and video recordings to retrieve (default: 10)",
    ] = 10,
    output_format: Annotated[
        str,
        "Output format: 'markdown' (table) or 'compact' (token-efficient JSON)",
    ] = "markdown",
    force_refresh: Annotated[
        bool,
        "Bypass local 15-minute disk cache and force a live API fetch",
    ] = False,
) -> str:
    """Fetch match schedule and recent games for a team from Volleymetrics.

    Returns a table or compact JSON containing match IDs, dates, opponent names, results,
    set scores, and whether DataVolley (.dvw) files are available. Call this tool first when
    analyzing team performance to discover match IDs for downstream analysis.

    Args:
        team_id: Optional Volleymetrics team ID. If omitted, uses auto-detected team ID.
        limit: Maximum number of recent matches to retrieve (default: 10).
        output_format: Output format: 'markdown' (table) or 'compact' (token-efficient JSON).
        force_refresh: If True, bypasses local 15-minute disk cache and forces a live fetch.

    Returns:
        A formatted table or compact JSON of matches or an actionable error message.
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


@mcp.tool()
async def get_match_player_stats(
    match_id: Annotated[
        str,
        "Unique Volleymetrics match identifier (obtainable via list_volleyball_matches)",
    ],
    team_id: Annotated[
        Optional[str],
        "Optional Volleymetrics team ID to filter athlete statistics to a specific squad",
    ] = None,
    output_format: Annotated[
        str,
        "Desired output representation: 'markdown' for standard box score table or 'compact' for token-efficient JSON",
    ] = "markdown",
    force_refresh: Annotated[
        bool,
        "Bypass local 7-day disk cache and force a live API fetch",
    ] = False,
) -> str:
    """Fetch individual athlete box scores and volleyball statistics for a match.

    Retrieves player stats, strips unnecessary UI metadata, ensures hitting percentage
    ((Kills - Errors) / Total Attacks) is accurately calculated, and formats the output
    into a clean, standard volleyball box score table or compact JSON including Kills (K),
    Attack Errors (E), Total Attacks (TA), Hitting % (Hit%), Assists (Ast), Service Aces (SA),
    Service Errors (SE), Digs (Dig), Block Solos (BS), Block Assists (BA), Total Blocks (TB),
    Total Points (Pts), Receptions (Rec), and Passing Average (Pass Avg).

    Args:
        match_id: The unique Volleymetrics match identifier.
        team_id: Optional team ID to filter stats to a specific squad.
        output_format: Output format: 'markdown' (standard box score table) or 'compact' (token-efficient JSON).
        force_refresh: If True, bypasses local 7-day disk cache and forces a live fetch.

    Returns:
        A formatted volleyball box score table or compact JSON.
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


@mcp.tool()
async def get_rotation_breakdown(
    match_id: Annotated[
        str,
        "Unique Volleymetrics match identifier (obtainable via list_volleyball_matches)",
    ],
    team_id: Annotated[
        Optional[str],
        "Optional Volleymetrics team ID to filter rotation analytics to a specific squad",
    ] = None,
    output_format: Annotated[
        str,
        "Desired output representation: 'markdown' for P1-P6 sideout table or 'compact' for token-efficient JSON",
    ] = "markdown",
    force_refresh: Annotated[
        bool,
        "Bypass local 7-day disk cache and force a live API fetch",
    ] = False,
) -> str:
    """Fetch tactical performance metrics broken down by volleyball rotation (P1 through P6).

    Returns sideout efficiency (earned sideout points / total receive opportunities), point
    scoring percentage while serving, first-ball sideout (FBSO) conversion rates, and
    setter distribution tendencies for each rotation (P1 through P6).

    Args:
        match_id: The unique Volleymetrics match identifier.
        team_id: Optional team ID to filter breakdown to a specific squad.
        output_format: Output format: 'markdown' (table) or 'compact' (token-efficient JSON).
        force_refresh: If True, bypasses local 7-day disk cache and forces a live fetch.

    Returns:
        A formatted table or compact JSON of rotation analytics (P1 through P6).
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


@mcp.tool()
async def get_game_actions(
    match_id: Annotated[
        str,
        "Unique Volleymetrics match identifier",
    ],
    set_number: Annotated[
        Optional[int],
        "Set number (e.g. 1, 2, 3, 4, 5) to restrict events to a specific set",
    ] = None,
    action_type: Annotated[
        Optional[str],
        "Volleyball skill/action filter: 'attack' (A), 'serve' (S), 'receive'/'pass' (R), 'set' (E), 'dig' (D), 'block' (B)",
    ] = None,
    player: Annotated[
        Optional[str],
        "Athlete filter: jersey number (e.g. '17', '#7') or player name",
    ] = None,
    team: Annotated[
        Optional[str],
        "Team filter: 'a', 'b', home/away, or team name",
    ] = None,
    quality: Annotated[
        Optional[str],
        "DataVolley evaluation/quality filter: 'kill' (#), 'error' (=), 'ace' (#), 'assist', 'in_play', 'perfect_pass' (#)",
    ] = None,
    limit: Annotated[
        int,
        "Maximum number of chronological volleyball touches to return (default: 50)",
    ] = 50,
    offset: Annotated[
        int,
        "Pagination offset for scrolling through match events (default: 0)",
    ] = 0,
    output_format: Annotated[
        str,
        "Desired output representation: 'markdown' for action table or 'compact' for token-efficient JSON",
    ] = "markdown",
    force_refresh: Annotated[
        bool,
        "Bypass local 7-day disk cache and force a live API fetch",
    ] = False,
) -> str:
    """Retrieve detailed tagged volleyball actions and touch events from match video analysis.

    Returns an event-by-event timeline including set number, score, video timestamp,
    player jersey/name, action type (serve, receive, set, attack, dig, block), result/quality,
    tactical details (start/end zones, routes, FBSO), and DataVolley (.dvw) codes.

    Args:
        match_id: The unique Volleymetrics match identifier.
        set_number: Optional set number (e.g. 1, 2, 3) to filter events to a specific set.
        action_type: Optional action filter: 'attack', 'serve', 'receive', 'set', 'dig', 'block'.
        player: Optional player filter: jersey number or player name.
        team: Optional team filter: 'a', 'b', or team name.
        quality: Optional quality/result filter: 'kill', 'error', 'ace', 'assist', 'in_play'.
        limit: Maximum number of events to return (default: 50).
        offset: Offset for paging through match events (default: 0).
        output_format: Output format: 'markdown' (table) or 'compact' (token-efficient JSON).
        force_refresh: If True, bypasses local 7-day disk cache and forces a live fetch.

    Returns:
        A formatted table or compact JSON of tagged match actions and event statistics.
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


@mcp.tool()
async def download_match_dvw(
    match_id: Annotated[
        str,
        "Unique Volleymetrics match identifier (obtainable via list_volleyball_matches)",
    ],
    output_dir: Annotated[
        Optional[str],
        "Optional directory to save the downloaded .dvw file (defaults to current directory)",
    ] = None,
) -> str:
    """Download or generate the official DataVolley (.dvw) scouting file for a match.

    Calls Volleymetrics DVW export service, generates the .dvw scouting file containing
    all official codes, court coordinates, and rosters, and saves it locally.

    Args:
        match_id: The unique Volleymetrics match identifier.
        output_dir: Optional directory path to save the .dvw file.

    Returns:
        Confirmation of download including local file path and byte size.
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


@mcp.tool()
async def login_to_volleymetrics(timeout_seconds: int = 300) -> str:
    """Open an interactive pop-up browser window to log into Volleymetrics and save session state.

    Opens a visible browser to https://portal.volleymetrics.hudl.com where you can log in normally
    using your password manager (1Password, Bitwarden, iCloud Keychain), Hudl SSO,
    or two-factor authentication (2FA).

    The moment login completes and the dashboard is detected, session tokens and active team
    information are saved to ~/.volleymetrics_mcp/auth_state.json and the OS Keychain,
    the browser closes automatically, and your session is active without ever storing your password.

    Args:
        timeout_seconds: Maximum time in seconds to wait for login completion (default: 300 = 5 minutes).

    Returns:
        A confirmation status message when login completes or details on any error.
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


@mcp.tool()
async def refresh_volleymetrics_cookie() -> str:
    """Refresh the Volleymetrics session authentication token.

    If credentials are configured in .env, attempts automated OAuth password grant refresh.
    Otherwise, recommends interactive pop-up browser login via login_to_volleymetrics.

    Returns:
        A confirmation status message indicating success or details on how to log in.
    """
    if os.getenv("VOLLEYMETRICS_EMAIL") and os.getenv("VOLLEYMETRICS_PASSWORD"):
        res = await refresh_session()
        if res.get("success"):
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
