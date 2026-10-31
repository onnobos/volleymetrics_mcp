"""Unit tests for Volleymetrics MCP models, parsers, and derived metrics."""

import pytest
from volleymetrics_mcp.models import (
    MatchSummary,
    PlayerStats,
    RotationStats,
    TeamInfo,
    VolleyballAction,
    format_actions_markdown,
    format_matches_markdown,
    format_player_stats_markdown,
    format_rotation_stats_markdown,
    format_teams_markdown,
    parse_matches_response,
    parse_player_stats_response,
    parse_rotation_stats_response,
    parse_teams_response,
    parse_video_actions,
    render_actions_output,
    render_matches_output,
    render_player_stats_output,
    render_rotation_stats_output,
    render_teams_output,
)


def test_player_stats_derived_metrics():
    """Verify automatic calculation of derived volleyball metrics."""
    player = PlayerStats(
        player_name="Kathryn Plummer",
        jersey_number="13",
        position="OH",
        sets_played=4,
        kills=18,
        attack_errors=4,
        total_attacks=35,
        assists=2,
        aces=3,
        serve_errors=2,
        digs=9,
        receptions=20,
        perfect_passes=10,
        positive_passes=6,
        medium_passes=2,
        reception_errors=2,
        block_solos=1,
        block_assists=4,
    )

    # 1. Hitting Percentage: (18 - 4) / 35 = 14 / 35 = 0.400
    assert player.hitting_percentage == 0.400

    # 2. Total Blocks: 1 solo + 0.5 * 4 assists = 3.0
    assert player.total_blocks == 3.0

    # 3. Total Points: 18 kills + 3 aces + 1 solo + 0.5 * 4 = 24.0
    assert player.points == 24.0

    # 4. Pass Rating: (3*10 + 2*6 + 1*2) / 20 = (30 + 12 + 2) / 20 = 44 / 20 = 2.20
    assert player.pass_rating == 2.20

    # Compact dict
    compact = player.to_compact_dict()
    assert compact["name"] == "Kathryn Plummer"
    assert compact["hit_pct"] == 0.400
    assert compact["pts"] == 24.0
    assert compact["blk"] == 3.0
    assert compact["pass_avg"] == 2.20


def test_player_stats_zero_division_guard():
    """Verify hitting percentage handles 0 total attacks without error."""
    player = PlayerStats(player_name="Libero", total_attacks=0, receptions=0)
    assert player.hitting_percentage == 0.000
    assert player.pass_rating is None


def test_rotation_stats_metrics():
    """Verify rotation metrics and compact dictionary formatting."""
    rot = RotationStats(
        rotation_number=1,
        rotation_name="P1",
        sideout_percentage=0.625,
        sideouts_earned=15,
        sideout_attempts=24,
        point_scoring_percentage=0.450,
        points_scored_serving=9,
        serve_attempts=20,
        first_ball_sideout_rate=0.500,
        setter_tendencies={"Zone4": "45%", "Zone2": "30%", "Pipe": "25%"},
    )
    compact = rot.to_compact_dict()
    assert compact["rotation"] == "P1"
    assert compact["sideout_pct"] == "62.5%"
    assert compact["sideouts"] == "15/24"
    assert compact["point_scoring_pct"] == "45.0%"
    assert compact["fbso_pct"] == "50.0%"


def test_volleyball_action_dvw_mapping():
    """Verify translation of touch events to DataVolley codes."""
    action = VolleyballAction(
        action_id=42,
        set_number=2,
        score="15-12",
        team="a",
        player_label="#7 Kathryn Plummer",
        jersey_number="7",
        action_type="attack",
        quality="kill",
        source_zone=4,
        dest_zone=5,
    )
    assert action.dvw_skill == "A"
    assert action.dvw_evaluation == "#"
    assert action.dvw_code == "*07AH#"

    serve_action = VolleyballAction(
        team="b",
        player_label="#12 Opponent",
        jersey_number="12",
        action_type="serve",
        quality="error",
    )
    assert serve_action.dvw_skill == "S"
    assert serve_action.dvw_evaluation == "="
    assert serve_action.dvw_code == "a12SH="


def test_markdown_and_compact_renderers():
    """Verify dual rendering support for markdown tables and compact JSON."""
    teams = [
        TeamInfo(
            team_id="101",
            name="Stanford Women's Volleyball",
            school_name="Stanford",
            conference="ACC",
            role="Head Coach",
            is_current=True,
        )
    ]
    md = render_teams_output(teams, active_team_id="101", output_format="markdown")
    assert "Stanford Women's Volleyball" in md
    assert "✅ Active" in md

    compact = render_teams_output(teams, active_team_id="101", output_format="compact")
    assert '"active_team_id": "101"' in compact
    assert '"Stanford"' in compact

    matches = [
        MatchSummary(
            match_id="m-500",
            date="2026-10-15",
            opponent_name="Texas",
            result="W 3-1",
            score="3-1",
            set_scores=["25-22", "20-25", "25-19", "25-21"],
            status="Final",
            has_dvw=True,
        )
    ]
    m_md = render_matches_output(matches, team_id="101", output_format="markdown")
    assert "Texas" in m_md
    assert "W 3-1" in m_md
    assert "✅ Yes" in m_md

    m_json = render_matches_output(matches, team_id="101", output_format="compact")
    assert '"m-500"' in m_json
    assert '"dvw_available": true' in m_json


def test_parsers():
    """Verify parsing of raw API responses into structured models."""
    # Teams parser
    raw_accounts = {
        "accounts": [
            {
                "id": "1",
                "role": "COACH",
                "team": {
                    "id": "555",
                    "name": "Bruins",
                    "school": "UCLA",
                    "conference": "Big Ten",
                },
            }
        ]
    }
    teams = parse_teams_response(raw_accounts, active_team_id="555")
    assert len(teams) == 1
    assert teams[0].team_id == "555"
    assert teams[0].name == "Bruins"
    assert teams[0].is_current is True

    # Matches parser
    raw_matches = [
        {
            "id": "match-77",
            "date": "2026-09-20",
            "opponentName": "USC",
            "result": "W 3-0",
            "hasDvw": True,
        }
    ]
    matches = parse_matches_response(raw_matches)
    assert len(matches) == 1
    assert matches[0].match_id == "match-77"
    assert matches[0].opponent_name == "USC"
    assert matches[0].has_dvw is True

    # Video actions parser
    raw_touches = [
        {
            "id": 1,
            "setNumber": 1,
            "skill": "serve",
            "quality": "ace",
            "jerseyNumber": "10",
            "team": "a",
        },
        {
            "id": 2,
            "setNumber": 2,
            "skill": "attack",
            "quality": "kill",
            "jerseyNumber": "15",
            "team": "b",
        },
    ]
    # Filter by set_number=1
    set1_actions = parse_video_actions(raw_touches, set_number=1)
    assert len(set1_actions) == 1
    assert set1_actions[0].action_type == "serve"

    # Filter by action_type='attack'
    attack_actions = parse_video_actions(raw_touches, action_type="attack")
    assert len(attack_actions) == 1
    assert attack_actions[0].action_type == "attack"


def test_full_analysis_sets_parser():
    """Verify parsing sets, rallies, and events into player stats, rotation stats, and touches."""
    analysis_payload = {
        "homeTeamId": "100",
        "awayTeamId": "200",
        "homeTeam": {"id": "100", "name": "Stanford"},
        "awayTeam": {"id": "200", "name": "Texas"},
        "sets": [
            {
                "setNum": 1,
                "homeScore": 25,
                "awayScore": 20,
                "rallies": [
                    {
                        "id": "r1",
                        "homeScore": 0,
                        "awayScore": 0,
                        "homeSetterRotation": 1,
                        "awaySetterRotation": 4,
                        "events": [
                            {
                                "id": "e1",
                                "teamId": "100",
                                "type": {"description": "serve"},
                                "grade": "+",
                                "player": {"portalPlayerId": "p1", "number": "7", "firstName": "Kathryn", "lastName": "Plummer"},
                                "videoStartTime": 12.5,
                            },
                            {
                                "id": "e2",
                                "teamId": "200",
                                "type": {"description": "receive"},
                                "grade": "!",
                                "player": {"portalPlayerId": "p2", "number": "2", "firstName": "Logan", "lastName": "Eggleston"},
                                "videoStartTime": 14.0,
                            },
                            {
                                "id": "e3",
                                "teamId": "200",
                                "type": {"description": "attack"},
                                "grade": "=",  # Attack error -> Stanford (home) wins rally
                                "player": {"portalPlayerId": "p2", "number": "2", "firstName": "Logan", "lastName": "Eggleston"},
                                "videoStartTime": 16.2,
                            },
                        ],
                    },
                    {
                        "id": "r2",
                        "homeScore": 1,
                        "awayScore": 0,
                        "homeSetterRotation": 1,
                        "awaySetterRotation": 4,
                        "events": [
                            {
                                "id": "e4",
                                "teamId": "100",
                                "type": {"description": "serve"},
                                "grade": "#",  # Ace -> Stanford scores serving point
                                "player": {"portalPlayerId": "p1", "number": "7", "firstName": "Kathryn", "lastName": "Plummer"},
                                "videoStartTime": 25.0,
                            },
                        ],
                    },
                    {
                        "id": "r3",
                        "homeScore": 2,
                        "awayScore": 0,
                        "homeSetterRotation": 2,
                        "awaySetterRotation": 4,
                        "events": [
                            {
                                "id": "e5",
                                "teamId": "200",
                                "type": {"description": "serve"},
                                "grade": "+",
                                "player": {"portalPlayerId": "p2", "number": "2", "firstName": "Logan", "lastName": "Eggleston"},
                                "videoStartTime": 40.0,
                            },
                            {
                                "id": "e6",
                                "teamId": "100",
                                "type": {"description": "receive"},
                                "grade": "#",  # Perfect pass
                                "player": {"portalPlayerId": "p3", "number": "1", "firstName": "Morgan", "lastName": "Hentz"},
                                "videoStartTime": 41.5,
                            },
                            {
                                "id": "e7",
                                "teamId": "100",
                                "type": {"description": "attack"},
                                "grade": "#",  # Kill -> Stanford earns sideout
                                "player": {"portalPlayerId": "p1", "number": "7", "firstName": "Kathryn", "lastName": "Plummer"},
                                "videoStartTime": 43.0,
                            },
                        ],
                    },
                ],
            }
        ],
    }

    # 1. Test Player Stats aggregation
    players = parse_player_stats_response(analysis_payload, team="100")
    assert len(players) >= 1
    plummer = next(p for p in players if "Plummer" in p.player_name)
    assert plummer.kills == 1
    assert plummer.aces == 1
    assert plummer.total_serves == 2

    # 2. Test Rotation Stats aggregation
    rotations = parse_rotation_stats_response(analysis_payload, team="100")
    assert len(rotations) == 6
    p1 = next(r for r in rotations if r.rotation_number == 1)
    assert p1.serve_attempts == 2
    assert p1.points_scored_serving == 2
    assert p1.point_scoring_percentage == 1.0

    p2 = next(r for r in rotations if r.rotation_number == 2)
    assert p2.sideout_attempts == 1
    assert p2.sideouts_earned == 1
    assert p2.sideout_percentage == 1.0
    assert p2.first_ball_sideout_rate == 1.0

    # 3. Test Video Actions parsing
    actions = parse_video_actions(analysis_payload, limit=10)
    assert len(actions) == 7
    assert actions[0].action_type == "serve"
    assert actions[0].player_label == "#7 Kathryn Plummer"
    assert actions[0].score == "0-0"
    assert actions[0].team == "a"
