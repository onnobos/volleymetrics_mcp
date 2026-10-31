"""Unit tests for FastMCP server tool handlers, error handling, and prompt generation."""

from unittest.mock import AsyncMock, patch
import pytest

from volleymetrics_mcp.client import VolleymetricsAuthError, VolleymetricsSecurityError
from volleymetrics_mcp.models import MatchSummary, PlayerStats, RotationStats, TeamInfo, VolleyballAction
from volleymetrics_mcp.server import (
    analyze_rotation_weaknesses,
    datavolley_export,
    download_match_dvw,
    get_game_actions,
    get_match_player_stats,
    get_rotation_breakdown,
    get_user_teams,
    list_volleyball_matches,
    login_to_volleymetrics,
    match_mvp_breakdown,
    refresh_volleymetrics_cookie,
    scout_opponent,
    serve_receive_audit,
)


@pytest.mark.asyncio
async def test_get_user_teams_tool_success():
    """Verify get_user_teams tool outputs formatted markdown."""
    mock_teams = [
        TeamInfo(
            team_id="team-1",
            name="Stanford Cardinal",
            school_name="Stanford",
            conference="ACC",
            role="Coach",
            is_current=True,
        )
    ]
    with patch("volleymetrics_mcp.client.VolleymetricsClient.get_user_teams", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_teams
        result = await get_user_teams()
        assert "Volleymetrics Teams" in result
        assert "Stanford Cardinal" in result
        assert "team-1" in result


@pytest.mark.asyncio
async def test_get_user_teams_auth_error():
    """Verify get_user_teams provides clear guidance on authentication error."""
    with patch("volleymetrics_mcp.client.VolleymetricsClient.get_user_teams", new_callable=AsyncMock) as mock_get:
        mock_get.side_effect = VolleymetricsAuthError("Session expired")
        result = await get_user_teams()
        assert "⚠️ Authentication Error" in result
        assert "login_to_volleymetrics" in result


@pytest.mark.asyncio
async def test_list_volleyball_matches_tool():
    """Verify list_volleyball_matches tool outputs formatted table."""
    mock_matches = [
        MatchSummary(
            match_id="m-100",
            date="2026-10-10",
            opponent_name="Minnesota Gophers",
            result="W 3-1",
            set_scores=["25-18", "25-22", "23-25", "25-20"],
            has_dvw=True,
        )
    ]
    with patch("volleymetrics_mcp.client.VolleymetricsClient.get_recent_matches", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_matches
        result = await list_volleyball_matches(team_id="team-1", limit=5)
        assert "Volleymetrics Matches" in result
        assert "Minnesota Gophers" in result
        assert "m-100" in result
        assert "✅ Yes" in result


@pytest.mark.asyncio
async def test_get_match_player_stats_tool():
    """Verify get_match_player_stats tool handles parameters and formatting."""
    # Test missing match_id
    err = await get_match_player_stats(match_id="")
    assert "required" in err

    mock_players = [
        PlayerStats(
            player_name="Dana Rettke",
            jersey_number="16",
            position="MB",
            sets_played=3,
            kills=14,
            attack_errors=1,
            total_attacks=22,
            block_solos=2,
            block_assists=6,
        )
    ]
    with patch("volleymetrics_mcp.client.VolleymetricsClient.get_match_player_stats", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_players
        result = await get_match_player_stats(match_id="m-100")
        assert "Match Box Score" in result
        assert "Dana Rettke" in result
        assert "0.591" in result  # (14-1)/22 = 13/22 = 0.591


@pytest.mark.asyncio
async def test_get_rotation_breakdown_tool():
    """Verify get_rotation_breakdown tool outputs tactical P1-P6 sideout table."""
    mock_rotations = [
        RotationStats(
            rotation_number=1,
            rotation_name="P1",
            sideout_percentage=0.700,
            sideouts_earned=14,
            sideout_attempts=20,
            point_scoring_percentage=0.550,
            points_scored_serving=11,
            serve_attempts=20,
            first_ball_sideout_rate=0.600,
        )
    ]
    with patch("volleymetrics_mcp.client.VolleymetricsClient.get_rotation_stats", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_rotations
        result = await get_rotation_breakdown(match_id="m-100")
        assert "Rotation Breakdown (P1-P6)" in result
        assert "70.0%" in result
        assert "14/20" in result


@pytest.mark.asyncio
async def test_get_game_actions_tool():
    """Verify get_game_actions tool formats touch events with DataVolley codes."""
    mock_actions = [
        VolleyballAction(
            action_id=1,
            set_number=1,
            score="10-8",
            team="a",
            player_label="#7 Player",
            jersey_number="7",
            action_type="attack",
            quality="kill",
        )
    ]
    with patch("volleymetrics_mcp.client.VolleymetricsClient.get_game_actions", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_actions
        result = await get_game_actions(match_id="m-100", action_type="attack")
        assert "Tagged Volleyball Touches" in result
        assert "*07AH#" in result
        assert "Kill" in result or "kill" in result


@pytest.mark.asyncio
async def test_download_match_dvw_tool():
    """Verify download_match_dvw tool formats confirmation."""
    mock_res = {
        "success": True,
        "match_id": "m-100",
        "file_path": "/tmp/match_m-100.dvw",
        "file_size_bytes": 1024,
    }
    with patch("volleymetrics_mcp.client.VolleymetricsClient.download_dvw", new_callable=AsyncMock) as mock_dl:
        mock_dl.return_value = mock_res
        result = await download_match_dvw(match_id="m-100")
        assert "DataVolley Export Successful" in result
        assert "match_m-100.dvw" in result


@pytest.mark.asyncio
async def test_login_to_volleymetrics_tool():
    """Verify login_to_volleymetrics handles success and failure responses."""
    with patch("volleymetrics_mcp.server.interactive_login", new_callable=AsyncMock) as mock_login:
        mock_login.return_value = {
            "success": True,
            "storage_state_file": "/tmp/auth_state.json",
            "masked_token": "eyJhbGciOi...abcd",
        }
        res = await login_to_volleymetrics()
        assert "✅ **Volleymetrics Login Successful!**" in res
        assert "eyJhbGciOi...abcd" in res


def test_prompts_generation():
    """Verify built-in FastMCP coaching and scouting prompts."""
    scout = scout_opponent("Penn State")
    assert "Penn State" in scout
    assert "list_volleyball_matches" in scout
    assert "get_rotation_breakdown" in scout

    rot = analyze_rotation_weaknesses("m-999")
    assert "m-999" in rot
    assert "get_rotation_breakdown" in rot

    mvp = match_mvp_breakdown("m-999")
    assert "True Points" in mvp

    dvw = datavolley_export("m-999", set_number=2)
    assert "m-999" in dvw
    assert "set_number=2" in dvw

    audit = serve_receive_audit("m-999")
    assert "Passing & Receiving Specialist" in audit
