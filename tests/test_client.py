"""Unit tests for VolleymetricsClient, security enforcement, and HTTP mock responses."""

from unittest.mock import AsyncMock, MagicMock, patch
import httpx
import pytest

from volleymetrics_mcp.client import (
    VolleymetricsAuthError,
    VolleymetricsClient,
    VolleymetricsConnectionError,
    VolleymetricsError,
    VolleymetricsSecurityError,
    get_api_headers,
)
from volleymetrics_mcp.security import assert_read_only


def test_security_assert_read_only():
    """Verify strict read-only policy blocks mutating requests."""
    # GET and HEAD should pass
    assert_read_only("GET", "portal/teams")
    assert_read_only("GET", "analysis/matches/123")

    # Authorized POST queries should pass
    assert_read_only("POST", "acct/oauth/token")
    assert_read_only("POST", "stats/matchStats/555")
    assert_read_only("POST", "dvw/dvws/generate?portalMatchId=123")

    # Mutating requests must raise VolleymetricsSecurityError
    with pytest.raises(VolleymetricsSecurityError):
        assert_read_only("PUT", "portal/teams/555")

    with pytest.raises(VolleymetricsSecurityError):
        assert_read_only("DELETE", "portal/matches/123")

    with pytest.raises(VolleymetricsSecurityError):
        assert_read_only("POST", "portal/teams/create")


def test_api_headers_bearer_token():
    """Verify Bearer token is properly attached to headers."""
    with patch("volleymetrics_mcp.client.get_volleymetrics_token", return_value="jwt-test-token-123"):
        headers = get_api_headers()
        assert headers["Authorization"] == "Bearer jwt-test-token-123"
        assert "application/json" in headers["Accept"]


@pytest.mark.asyncio
async def test_client_missing_token_raises_auth_error():
    """Verify client raises VolleymetricsAuthError if no token is configured."""
    with patch("volleymetrics_mcp.client.get_volleymetrics_token", return_value=None):
        client = VolleymetricsClient()
        with pytest.raises(VolleymetricsAuthError) as exc_info:
            await client.get_user_teams()
        assert "login_to_volleymetrics" in str(exc_info.value)


@pytest.mark.asyncio
async def test_client_get_user_teams_success():
    """Verify get_user_teams retrieves and parses team list."""
    mock_response = httpx.Response(
        200,
        json={
            "accounts": [
                {
                    "id": "acc-1",
                    "role": "HEAD_COACH",
                    "team": {
                        "id": "team-99",
                        "name": "Badgers",
                        "school": "Wisconsin",
                        "conference": "Big Ten",
                    },
                }
            ]
        },
        request=httpx.Request("GET", "https://api.volleymetrics.hudl.com/acct/accounts"),
    )

    with patch("volleymetrics_mcp.client.get_volleymetrics_token", return_value="mock-token"), \
         patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = mock_response

        client = VolleymetricsClient(team_id="team-99")
        teams = await client.get_user_teams(force_refresh=True)

        assert len(teams) == 1
        assert teams[0].team_id == "team-99"
        assert teams[0].name == "Badgers"
        assert teams[0].school_name == "Wisconsin"


@pytest.mark.asyncio
async def test_client_401_triggers_auth_error():
    """Verify HTTP 401 returns clear authentication error."""
    mock_response = httpx.Response(
        401,
        json={"error": "Unauthorized"},
        request=httpx.Request("GET", "https://api.volleymetrics.hudl.com/portal/teams"),
    )

    with patch("volleymetrics_mcp.client.get_volleymetrics_token", return_value="expired-token"), \
         patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = mock_response

        client = VolleymetricsClient()
        with pytest.raises(VolleymetricsAuthError) as exc:
            await client.get_user_teams(force_refresh=True)
        assert "authentication failed (HTTP 401)" in str(exc.value)


@pytest.mark.asyncio
async def test_client_download_dvw(tmp_path):
    """Verify download_dvw calls generation endpoint and saves file to disk."""
    fake_dvw_content = b"[3MATCH]\nDate=2026.10.15\n[3TEAMS]\nStanford\nTexas\n"
    mock_response = httpx.Response(
        200,
        content=fake_dvw_content,
        request=httpx.Request("POST", "https://api.volleymetrics.hudl.com/dvw/dvws/generate?portalMatchId=101"),
    )

    with patch("volleymetrics_mcp.client.get_volleymetrics_token", return_value="mock-token"), \
         patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = mock_response

        client = VolleymetricsClient()
        res = await client.download_dvw(match_id="101", output_dir=str(tmp_path))

        assert res["success"] is True
        assert res["match_id"] == "101"
        assert res["file_size_bytes"] == len(fake_dvw_content)

        saved_file = tmp_path / "match_101.dvw"
        assert saved_file.is_file()
        assert saved_file.read_bytes() == fake_dvw_content
