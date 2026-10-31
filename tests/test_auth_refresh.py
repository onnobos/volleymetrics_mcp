"""Unit tests for Volleymetrics authentication refresh and token storage."""

import json
from unittest.mock import AsyncMock, patch
import httpx
import pytest

from volleymetrics_mcp.auth_refresh import (
    find_env_file,
    get_team_id_from_auth_state,
    get_token_from_auth_state,
    refresh_session,
    update_env_file,
)


def test_get_token_and_team_from_auth_state(tmp_path):
    """Verify extracting access_token and active team ID from Playwright auth_state.json."""
    auth_state_data = {
        "cookies": [],
        "origins": [
            {
                "origin": "https://portal.volleymetrics.hudl.com",
                "localStorage": [
                    {
                        "name": "vmPortalUser",
                        "value": json.dumps({
                            "access_token": "mock-jwt-bearer-xyz",
                            "activeAccountId": 8888,
                            "auth0_token": "mock-auth0",
                        }),
                    },
                    {
                        "name": "vmActiveAccount",
                        "value": json.dumps({
                            "id": 8888,
                            "teamId": "team-456",
                            "name": "Stanford",
                        }),
                    },
                ],
            }
        ],
    }

    state_file = tmp_path / "auth_state.json"
    state_file.write_text(json.dumps(auth_state_data), encoding="utf-8")

    token = get_token_from_auth_state(state_file)
    assert token == "mock-jwt-bearer-xyz"

    team_id = get_team_id_from_auth_state(state_file)
    assert team_id == "team-456"


def test_update_env_file(tmp_path):
    """Verify updating and appending environment variables in .env."""
    env_file = tmp_path / ".env"
    env_file.write_text("SOME_VAR=hello\nVOLLEYMETRICS_TOKEN=old_token\n", encoding="utf-8")

    update_env_file("VOLLEYMETRICS_TOKEN", "new_token_123", env_path=env_file)
    content = env_file.read_text(encoding="utf-8")

    assert "VOLLEYMETRICS_TOKEN=new_token_123" in content
    assert "SOME_VAR=hello" in content


@pytest.mark.asyncio
async def test_refresh_session_oauth_success():
    """Verify automated refresh_session calls OAuth password grant endpoint."""
    mock_resp = httpx.Response(
        200,
        json={
            "access_token": "new-oauth-token-99999",
            "identity": {
                "activeAccount": {
                    "id": 1234,
                    "teamId": "team-777",
                }
            },
        },
        request=httpx.Request("POST", "https://api.volleymetrics.hudl.com/acct/oauth/token"),
    )

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp
        res = await refresh_session(email="coach@example.com", password="secure_password")

        assert res["success"] is True
        assert res["token"] == "new-oauth-token-99999"
        assert res["team_id"] == "team-777"
