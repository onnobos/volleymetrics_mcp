"""Pydantic models and data parsing for Volleymetrics MCP.

Strips unnecessary UI metadata from raw Volleymetrics API payloads, cleanses
and normalizes stats, calculates missing derived volleyball metrics (e.g. Hitting
Percentage = (Kills - Errors) / Attacks), and outputs compact analytical representations
(Markdown tables and token-efficient JSON).
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, Field, model_validator


class MatchSummary(BaseModel):
    """Cleaned representation of a Volleymetrics volleyball match summary."""

    match_id: str = Field(..., description="Unique match identifier")
    date: Optional[str] = Field(None, description="Date or timestamp of the match")
    opponent_name: str = Field("Unknown Opponent", description="Opponent team name")
    result: Optional[str] = Field(None, description="Match result, e.g. 'W 3-1', 'L 0-3'")
    home_away: Optional[str] = Field(None, description="'Home', 'Away', or 'Neutral'")
    score: Optional[str] = Field(None, description="Overall match set score, e.g. '3-1'")
    set_scores: Optional[List[str]] = Field(default_factory=list, description="Scores per set")
    status: Optional[str] = Field(None, description="Match status, e.g. 'Final', 'Complete'")
    season: Optional[str] = Field(None, description="Season name or year")
    has_dvw: bool = Field(False, description="Whether DataVolley (.dvw) file is available")
    has_analysis: bool = Field(False, description="Whether full video touch analysis is available")

    model_config = {"populate_by_name": True}

    def to_compact_dict(self) -> Dict[str, Any]:
        """Convert to compact high-signal dictionary stripping UI bloat."""
        res: Dict[str, Any] = {
            "id": self.match_id,
            "opponent": self.opponent_name,
            "date": self.date,
            "result": self.result or self.score,
            "status": self.status,
            "dvw_available": self.has_dvw,
        }
        if self.set_scores:
            res["set_scores"] = self.set_scores
        return res


class TeamInfo(BaseModel):
    """Cleaned representation of a Volleymetrics Team or Account."""

    team_id: str = Field(..., description="Volleymetrics Team ID")
    name: str = Field(..., description="Team Name")
    school_name: Optional[str] = Field(None, description="Club, University or Organization name")
    conference: Optional[str] = Field(None, description="Conference or League name")
    role: Optional[str] = Field(None, description="User role on the team (e.g. Coach, Admin, Analyst)")
    current_season: Optional[str] = Field(None, description="Active season name or year")
    gender: Optional[str] = Field(None, description="Gender / Category (e.g. Women, Men)")
    is_current: bool = Field(False, description="Whether this is the currently active/selected team")

    model_config = {"populate_by_name": True}

    def to_compact_dict(self) -> Dict[str, Any]:
        """Convert to compact high-signal dictionary stripping UI bloat."""
        return {
            "team_id": self.team_id,
            "name": self.name,
            "school": self.school_name,
            "conference": self.conference,
            "role": self.role,
            "is_current": self.is_current,
        }


class PlayerStats(BaseModel):
    """Cleaned individual athlete volleyball statistics with derived metrics."""

    player_id: Optional[str] = Field(None, description="Athlete ID")
    jersey_number: str = Field("", description="Jersey number")
    player_name: str = Field(..., description="Athlete full name")
    position: str = Field("", description="Position (OH, MB, RS, S, L, DS)")
    sets_played: int = Field(0, description="Sets played in the match")

    # Attacking
    kills: int = Field(0, description="Total kills (winning attacks)")
    attack_errors: int = Field(0, description="Attack errors")
    total_attacks: int = Field(0, description="Total attack attempts")
    hitting_percentage: Optional[float] = Field(
        None, description="Hitting %: (Kills - Errors) / Total Attacks"
    )

    # Setting
    assists: int = Field(0, description="Setting assists")
    ball_handling_errors: int = Field(0, description="Ball handling errors (BHE)")

    # Serving
    aces: int = Field(0, description="Service aces")
    serve_errors: int = Field(0, description="Service errors")
    total_serves: int = Field(0, description="Total serves")

    # Defense & Passing
    digs: int = Field(0, description="Digs")
    receptions: int = Field(0, description="Total serve receptions")
    perfect_passes: int = Field(0, description="Quality 3 (perfect) passes")
    positive_passes: int = Field(0, description="Quality 2 (positive) passes")
    medium_passes: int = Field(0, description="Quality 1 (medium) passes")
    reception_errors: int = Field(0, description="Serve reception errors (0s)")
    pass_rating: Optional[float] = Field(
        None, description="Serve receive passing rating (0-3 scale)"
    )

    # Blocking
    block_solos: int = Field(0, description="Solo blocks (BS)")
    block_assists: int = Field(0, description="Block assists (BA)")
    total_blocks: Optional[float] = Field(
        None, description="Total blocks (BS + 0.5 * BA)"
    )
    block_errors: int = Field(0, description="Blocking errors (BE)")

    # Overall Scoring
    points: Optional[float] = Field(
        None, description="Total points scored (Kills + Aces + BS + 0.5 * BA)"
    )

    model_config = {"populate_by_name": True}

    @model_validator(mode="after")
    def calculate_derived_metrics(self) -> PlayerStats:
        """Calculate missing derived volleyball statistics."""
        # 1. Hitting Percentage: (Kills - Errors) / Total Attacks
        if self.hitting_percentage is None:
            if self.total_attacks > 0:
                self.hitting_percentage = round(
                    (self.kills - self.attack_errors) / self.total_attacks, 3
                )
            else:
                self.hitting_percentage = 0.000

        # 2. Total Blocks: Solos + 0.5 * Assists
        if self.total_blocks is None:
            self.total_blocks = round(self.block_solos + (0.5 * self.block_assists), 1)

        # 3. Total Points: Kills + Aces + Solo Blocks + (0.5 * Block Assists)
        if self.points is None:
            self.points = round(
                self.kills + self.aces + self.block_solos + (0.5 * self.block_assists), 1
            )

        # 4. Pass Rating: (3 * Perfect + 2 * Positive + 1 * Medium) / Total Receptions
        if self.pass_rating is None and self.receptions > 0:
            total_points = (
                (3 * self.perfect_passes)
                + (2 * self.positive_passes)
                + (1 * self.medium_passes)
            )
            self.pass_rating = round(total_points / self.receptions, 2)

        return self

    def to_compact_dict(self) -> Dict[str, Any]:
        """Convert to compact high-signal box score dictionary stripping UI bloat."""
        return {
            "num": self.jersey_number,
            "name": self.player_name,
            "pos": self.position or None,
            "sets": self.sets_played,
            "k": self.kills,
            "e": self.attack_errors,
            "ta": self.total_attacks,
            "hit_pct": self.hitting_percentage,
            "ast": self.assists,
            "ace": self.aces,
            "se": self.serve_errors,
            "dig": self.digs,
            "blk": self.total_blocks,
            "pts": self.points,
            "rec": self.receptions,
            "pass_avg": self.pass_rating,
        }


class RotationStats(BaseModel):
    """Cleaned rotation performance metrics for P1 through P6."""

    rotation_number: int = Field(..., ge=1, le=6, description="Rotation number (1-6)")
    rotation_name: str = Field("P1", description="Rotation label, e.g. 'P1', 'P2', etc.")
    sideout_percentage: Optional[float] = Field(
        None, description="Sideout % when receiving serve in this rotation"
    )
    sideouts_earned: Optional[int] = Field(None, description="Successful sideouts")
    sideout_attempts: Optional[int] = Field(None, description="Receiving opportunities")
    point_scoring_percentage: Optional[float] = Field(
        None, description="Point scoring % when serving in this rotation"
    )
    points_scored_serving: Optional[int] = Field(None, description="Points scored on serve")
    serve_attempts: Optional[int] = Field(None, description="Serving opportunities")
    first_ball_sideout_rate: Optional[float] = Field(
        None, description="First-Ball Sideout (FBSO) % on in-system / first pass"
    )
    setter_tendencies: Optional[Dict[str, Any]] = Field(
        default_factory=dict, description="Setter set distribution (Left, Middle, Right, Pipe)"
    )
    notes: Optional[str] = Field(None, description="Tactical notes or observations")

    model_config = {"populate_by_name": True}

    def to_compact_dict(self) -> Dict[str, Any]:
        """Convert to compact high-signal rotation dictionary stripping UI bloat."""
        return {
            "rotation": f"P{self.rotation_number}" if self.rotation_number else self.rotation_name,
            "sideout_pct": (
                f"{round(self.sideout_percentage * 100, 1)}%"
                if self.sideout_percentage is not None
                else None
            ),
            "sideouts": f"{self.sideouts_earned or 0}/{self.sideout_attempts or 0}",
            "point_scoring_pct": (
                f"{round(self.point_scoring_percentage * 100, 1)}%"
                if self.point_scoring_percentage is not None
                else None
            ),
            "points_served": f"{self.points_scored_serving or 0}/{self.serve_attempts or 0}",
            "fbso_pct": (
                f"{round(self.first_ball_sideout_rate * 100, 1)}%"
                if self.first_ball_sideout_rate is not None
                else None
            ),
            "setter_distribution": self.setter_tendencies or {},
        }


class VolleyballAction(BaseModel):
    """Detailed volleyball action / touch event from video breakdown."""

    action_id: Optional[Union[int, str]] = Field(None, description="Action or touch event ID")
    rally_id: Optional[Union[int, str]] = Field(None, description="Rally ID")
    set_number: int = Field(1, description="Set number (1-5)")
    score: Optional[str] = Field(None, description="Score at time of action, e.g. '12-7'")
    timestamp_seconds: Optional[float] = Field(None, description="Timestamp in seconds from video start")
    timestamp_formatted: Optional[str] = Field(None, description="Formatted video timestamp (MM:SS)")
    team: str = Field(..., description="Team code ('a', 'b') or team name")
    team_name: Optional[str] = Field(None, description="Full team name")
    player_id: Optional[str] = Field(None, description="Player ID")
    jersey_number: Optional[str] = Field(None, description="Jersey number, e.g. '17'")
    player_label: str = Field(..., description="Display label, e.g. '#17 (Stanford)'")
    action_type: str = Field(..., description="Action skill (serve, receive, set, attack, dig, block, free_ball)")
    touch_type: Optional[str] = Field(None, description="Touch type (e.g. hand, bump)")
    quality: Optional[str] = Field(None, description="Result/quality (kill, error, ace, assist, in_play, rating 1-3)")
    attack_type: Optional[str] = Field(None, description="Attack set route / type (e.g. quick, pipe, high)")
    first_ball_side_out: bool = Field(False, description="Whether this action was during a first-ball sideout")
    source_zone: Optional[Union[int, float]] = Field(None, description="Origin court coordinate or zone")
    dest_zone: Optional[Union[int, float]] = Field(None, description="Destination court coordinate or zone")
    speed_kmh: Optional[float] = Field(None, description="Ball speed in km/h")
    details: Optional[str] = Field(None, description="Extra tactical details")

    model_config = {"populate_by_name": True}

    @property
    def dvw_skill(self) -> str:
        """Map action type to standard DataVolley skill code (S, R, E, A, B, D, F)."""
        act = (self.action_type or "").lower().strip()
        if "serve" in act:
            return "S"
        elif "receive" in act or "pass" in act:
            return "R"
        elif "set" in act:
            return "E"
        elif "attack" in act or "spike" in act:
            return "A"
        elif "block" in act:
            return "B"
        elif "dig" in act or "cover" in act:
            return "D"
        elif "free" in act or "down" in act:
            return "F"
        return "A"

    @property
    def dvw_evaluation(self) -> str:
        """Map quality to standard DataVolley evaluation code (#, +, !, -, =)."""
        qual = (self.quality or "").lower().strip()
        if qual in ("kill", "ace", "perfect", "3", "point"):
            return "#"
        elif qual in ("positive", "2", "good"):
            return "+"
        elif qual in ("medium", "1", "in_play", "in-play", "assist"):
            return "!"
        elif qual in ("poor", "negative", "slash"):
            return "-"
        elif qual in ("error", "0", "blocked"):
            return "="
        return "+"

    @property
    def dvw_code(self) -> str:
        """Generate standardized DataVolley scouting string code."""
        team_char = "*" if self.team.lower() in ("a", "home") else "a"
        jersey_clean = (self.jersey_number or "00").replace("#", "").strip()
        if len(jersey_clean) == 1:
            jersey_clean = f"0{jersey_clean}"
        elif len(jersey_clean) > 2:
            jersey_clean = jersey_clean[-2:]
        return f"{team_char}{jersey_clean}{self.dvw_skill}H{self.dvw_evaluation}"

    def to_compact_dict(self) -> Dict[str, Any]:
        """Convert to compact high-signal action dictionary."""
        return {
            "id": self.action_id,
            "set": self.set_number,
            "score": self.score,
            "time": self.timestamp_formatted,
            "player": self.player_label,
            "skill": self.action_type,
            "quality": self.quality,
            "dvw": self.dvw_code,
            "zone": f"{self.source_zone}->{self.dest_zone}" if self.source_zone and self.dest_zone else None,
            "route": self.attack_type,
        }


# ---------------------------------------------------------------------------
# Markdown Formatting Functions
# ---------------------------------------------------------------------------

def format_teams_markdown(teams: List[TeamInfo], active_team_id: Optional[str] = None) -> str:
    """Format team records into a clean Markdown table."""
    if not teams:
        return "No Volleymetrics teams found for this account."

    lines = [
        "### 🏐 Volleymetrics Teams",
        "",
        "| Team ID | Team Name | School / Org | Conference | Role | Status |",
        "| :--- | :--- | :--- | :--- | :--- | :--- |",
    ]

    for t in teams:
        is_active = (
            "✅ Active"
            if (active_team_id and str(t.team_id) == str(active_team_id)) or t.is_current
            else ""
        )
        lines.append(
            f"| `{t.team_id}` | **{t.name}** | {t.school_name or '-'} | {t.conference or '-'} | {t.role or '-'} | {is_active} |"
        )

    return "\n".join(lines)


def render_teams_output(
    teams: List[TeamInfo], active_team_id: Optional[str] = None, output_format: str = "markdown"
) -> str:
    """Render teams list in Markdown or compact JSON."""
    if output_format.lower() == "compact":
        return json.dumps(
            {"active_team_id": active_team_id, "teams": [t.to_compact_dict() for t in teams]},
            indent=2,
        )
    return format_teams_markdown(teams, active_team_id=active_team_id)


def format_matches_markdown(matches: List[MatchSummary], team_id: Optional[str] = None) -> str:
    """Format match summaries into a clean Markdown table."""
    if not matches:
        team_str = f" for team '{team_id}'" if team_id else ""
        return f"No matches found{team_str}."

    lines = [
        f"### 🏐 Volleymetrics Matches{f' (Team: {team_id})' if team_id else ''}",
        "",
        "| Match ID | Date | Opponent | Result | Sets | DVW Available | Status |",
        "| :--- | :--- | :--- | :--- | :--- | :---: | :--- |",
    ]

    for m in matches:
        date_str = m.date[:10] if m.date and len(m.date) >= 10 else (m.date or "-")
        sets_str = ", ".join(m.set_scores) if m.set_scores else (m.score or "-")
        dvw_badge = "✅ Yes" if m.has_dvw else "⏳ Processing"
        lines.append(
            f"| `{m.match_id}` | {date_str} | **{m.opponent_name}** | {m.result or '-'} | {sets_str} | {dvw_badge} | {m.status or '-'} |"
        )

    return "\n".join(lines)


def render_matches_output(
    matches: List[MatchSummary], team_id: Optional[str] = None, output_format: str = "markdown"
) -> str:
    """Render matches in Markdown or compact JSON."""
    if output_format.lower() == "compact":
        return json.dumps(
            {"team_id": team_id, "matches": [m.to_compact_dict() for m in matches]},
            indent=2,
        )
    return format_matches_markdown(matches, team_id=team_id)


def format_player_stats_markdown(players: List[PlayerStats], match_id: str) -> str:
    """Format player box score statistics into a volleyball box score table."""
    if not players:
        return f"No player box score statistics available for match `{match_id}`."

    lines = [
        f"### 🏐 Match Box Score (ID: `{match_id}`)",
        "",
        "| # | Player | Pos | Sets | K | E | TA | Hit% | Ast | SA | SE | Dig | BS | BA | TB | Pts | Rec | Pass Avg |",
        "| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |",
    ]

    for p in players:
        hit_pct_str = f"{p.hitting_percentage:.3f}" if p.hitting_percentage is not None else ".000"
        tb_str = f"{p.total_blocks:.1f}" if p.total_blocks is not None else "0.0"
        pts_str = f"{p.points:.1f}" if p.points is not None else "0.0"
        pass_str = f"{p.pass_rating:.2f}" if p.pass_rating is not None else "-"

        lines.append(
            f"| {p.jersey_number or '-'} | **{p.player_name}** | {p.position or '-'} | {p.sets_played} | "
            f"{p.kills} | {p.attack_errors} | {p.total_attacks} | {hit_pct_str} | {p.assists} | "
            f"{p.aces} | {p.serve_errors} | {p.digs} | {p.block_solos} | {p.block_assists} | "
            f"{tb_str} | {pts_str} | {p.receptions} | {pass_str} |"
        )

    return "\n".join(lines)


def render_player_stats_output(
    players: List[PlayerStats], match_id: str, output_format: str = "markdown"
) -> str:
    """Render player stats in Markdown or compact JSON."""
    if output_format.lower() == "compact":
        return json.dumps(
            {"match_id": match_id, "box_score": [p.to_compact_dict() for p in players]},
            indent=2,
        )
    return format_player_stats_markdown(players, match_id=match_id)


def format_rotation_stats_markdown(rotations: List[RotationStats], match_id: str) -> str:
    """Format rotation statistics into a tactical P1-P6 analytics table."""
    if not rotations:
        return f"No rotation breakdown statistics available for match `{match_id}`."

    lines = [
        f"### 🏐 Rotation Breakdown (P1-P6) - Match `{match_id}`",
        "",
        "| Rotation | Sideout % | Sideouts Earned | Point Scoring % | Points Served | FBSO % | Setter Distribution |",
        "| :--- | :---: | :---: | :---: | :---: | :---: | :--- |",
    ]

    for r in rotations:
        so_pct_str = (
            f"{round(r.sideout_percentage * 100, 1)}%"
            if r.sideout_percentage is not None
            else "-"
        )
        so_counts = (
            f"{r.sideouts_earned or 0}/{r.sideout_attempts or 0}"
            if r.sideout_attempts is not None
            else "-"
        )
        ps_pct_str = (
            f"{round(r.point_scoring_percentage * 100, 1)}%"
            if r.point_scoring_percentage is not None
            else "-"
        )
        ps_counts = (
            f"{r.points_scored_serving or 0}/{r.serve_attempts or 0}"
            if r.serve_attempts is not None
            else "-"
        )
        fbso_str = (
            f"{round(r.first_ball_sideout_rate * 100, 1)}%"
            if r.first_ball_sideout_rate is not None
            else "-"
        )

        dist_parts = []
        if r.setter_tendencies:
            for k, v in r.setter_tendencies.items():
                dist_parts.append(f"{k}: {v}")
        dist_str = ", ".join(dist_parts) if dist_parts else "-"

        rot_label = f"**P{r.rotation_number}**" if r.rotation_number else f"**{r.rotation_name}**"
        lines.append(
            f"| {rot_label} | {so_pct_str} | {so_counts} | {ps_pct_str} | {ps_counts} | {fbso_str} | {dist_str} |"
        )

    return "\n".join(lines)


def render_rotation_stats_output(
    rotations: List[RotationStats], match_id: str, output_format: str = "markdown"
) -> str:
    """Render rotation stats in Markdown or compact JSON."""
    if output_format.lower() == "compact":
        return json.dumps(
            {"match_id": match_id, "rotations": [r.to_compact_dict() for r in rotations]},
            indent=2,
        )
    return format_rotation_stats_markdown(rotations, match_id=match_id)


def format_actions_markdown(actions: List[VolleyballAction], match_name: str) -> str:
    """Format touch events into a chronological volleyball play-by-play table."""
    if not actions:
        return f"No tagged volleyball touches match the requested filters for match `{match_name}`."

    lines = [
        f"### 🏐 Tagged Volleyball Touches: {match_name} ({len(actions)} events)",
        "",
        "| Set | Score | Time | Player | Skill | Result | DataVolley Code | Route / Zone |",
        "| :---: | :---: | :---: | :--- | :--- | :--- | :---: | :--- |",
    ]

    for a in actions:
        time_str = a.timestamp_formatted or "-"
        sz = f"{a.source_zone:.1f}" if isinstance(a.source_zone, float) else f"{a.source_zone}"
        dz = f"{a.dest_zone:.1f}" if isinstance(a.dest_zone, float) else f"{a.dest_zone}"
        zone_str = f"({sz}->{dz})" if a.source_zone is not None and a.dest_zone is not None else "-"
        route_str = f"{a.attack_type} ({zone_str})" if a.attack_type else zone_str

        lines.append(
            f"| {a.set_number} | {a.score or '-'} | {time_str} | {a.player_label} | "
            f"**{a.action_type.capitalize()}** | {a.quality or '-'} | `{a.dvw_code}` | {route_str} |"
        )

    return "\n".join(lines)


def render_actions_output(
    actions: List[VolleyballAction],
    match_name: Optional[str] = None,
    match_id: Optional[str] = None,
    output_format: str = "markdown",
) -> str:
    """Render game actions in Markdown or compact JSON."""
    name = match_name or match_id or "Match"
    if output_format.lower() == "compact":
        return json.dumps(
            {"match": name, "total_events": len(actions), "actions": [a.to_compact_dict() for a in actions]},
            indent=2,
        )
    return format_actions_markdown(actions, match_name=name)


# ---------------------------------------------------------------------------
# API Response Parsing Helpers
# ---------------------------------------------------------------------------

def parse_teams_response(
    data: Any, active_team_id: Optional[str] = None
) -> List[TeamInfo]:
    """Parse raw Volleymetrics accounts/teams payload into TeamInfo objects."""
    teams: List[TeamInfo] = []
    if not data:
        return teams

    # Check if accounts list from /acct/accounts
    items = []
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        items = data.get("accounts") or data.get("content") or data.get("teams") or [data]

    seen_ids = set()
    for item in items:
        if not isinstance(item, dict):
            continue

        # Handle nested team object in accounts payload
        team_obj = item.get("team") if isinstance(item.get("team"), dict) else item
        tid = str(team_obj.get("id") or item.get("teamId") or item.get("id") or "")
        if not tid or tid in seen_ids:
            continue
        seen_ids.add(tid)

        name = team_obj.get("name") or item.get("name") or f"Team {tid}"
        
        school = team_obj.get("school") or team_obj.get("organization") or item.get("schoolName")
        if isinstance(school, dict):
            school = school.get("name") or school.get("schoolName")
        elif school is not None:
            school = str(school)

        conf = team_obj.get("conference") or item.get("conference")
        if isinstance(conf, dict):
            conf = conf.get("name") or conf.get("conferenceName")
        elif conf is not None:
            conf = str(conf)

        role = item.get("role") or item.get("userRole")
        if isinstance(role, dict):
            role = role.get("name") or role.get("role")
        elif not role and isinstance(item.get("accountType"), dict):
            role = item["accountType"].get("accountClass")
        elif role is not None:
            role = str(role)

        season = item.get("season") or team_obj.get("season")
        if not season and isinstance(team_obj.get("conference"), dict):
            seasons = team_obj["conference"].get("conferenceSeasons", [])
            active_s = next((s for s in seasons if s.get("status") == "ACTIVE"), None)
            if active_s:
                season = active_s.get("season", {}).get("name")
        if isinstance(season, dict):
            season = season.get("name") or season.get("year")
        elif season is not None:
            season = str(season)

        gender = team_obj.get("gender")
        if not gender and isinstance(team_obj.get("conference"), dict):
            gender = team_obj["conference"].get("gender")
        if gender is not None:
            gender = str(gender)

        is_current = (
            (active_team_id and str(tid) == str(active_team_id))
            or bool(item.get("isDefault"))
            or (len(items) == 1)
        )

        teams.append(
            TeamInfo(
                team_id=tid,
                name=name,
                school_name=school,
                conference=conf,
                role=role,
                current_season=str(season) if season else None,
                gender=gender,
                is_current=bool(is_current),
            )
        )

    return teams


def parse_matches_response(
    data: Any, active_team_id: Optional[str] = None
) -> List[MatchSummary]:
    """Parse raw Volleymetrics matches payload into MatchSummary objects."""
    matches: List[MatchSummary] = []
    if not data:
        return matches

    items = []
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        items = data.get("content") or data.get("matches") or [data]

    for item in items:
        if not isinstance(item, dict):
            continue

        mid = str(item.get("id") or item.get("matchId") or "")
        if not mid:
            continue

        date_val = item.get("date") or item.get("matchDate") or item.get("startTime")

        # Resolve Home and Away teams
        home_obj = item.get("homeTeam") if isinstance(item.get("homeTeam"), dict) else {}
        away_obj = item.get("awayTeam") if isinstance(item.get("awayTeam"), dict) else {}
        home_name = home_obj.get("name") or item.get("homeTeamName") or "Home Team"
        away_name = away_obj.get("name") or item.get("awayTeamName") or "Away Team"
        home_id = str(home_obj.get("id") or "")
        away_id = str(away_obj.get("id") or "")

        home_away = None
        opponent = None

        if active_team_id:
            tid_str = str(active_team_id).strip()
            if home_id == tid_str:
                opponent = away_name
                home_away = "Home"
            elif away_id == tid_str:
                opponent = home_name
                home_away = "Away"

        if not opponent:
            if home_obj and away_obj:
                opponent = f"{home_name} vs {away_name}"
            else:
                opponent = (
                    item.get("opponentName")
                    or item.get("opponent")
                    or item.get("awayTeamName")
                    or item.get("homeTeamName")
                    or "Unknown Opponent"
                )
                if isinstance(opponent, dict):
                    opponent = opponent.get("name", "Unknown Opponent")

        result = item.get("result") or item.get("matchResult")
        score = item.get("score") or item.get("setScore")
        if not score and item.get("scores"):
            score = str(item.get("scores"))

        # Set scores
        set_scores_raw = item.get("setScores") or item.get("scores") or []
        set_scores = [str(s) for s in set_scores_raw] if isinstance(set_scores_raw, list) else []

        status = item.get("status") or item.get("analysisStatus")
        extra_data = item.get("extraData", {}) if isinstance(item.get("extraData"), dict) else {}
        video_status = extra_data.get("videoStatus", {}) if isinstance(extra_data.get("videoStatus"), dict) else {}
        if not status and video_status.get("status"):
            status = video_status.get("status")

        has_dvw = bool(
            item.get("hasDvw")
            or item.get("dvwFileId")
            or item.get("dvwAvailable")
            or item.get("scoresheetId")
            or (video_status.get("status") == "COMPLETE")
            or "dvw" in str(item).lower()
        )
        has_analysis = bool(
            item.get("hasAnalysis")
            or item.get("analyzed")
            or (status and str(status).lower() in ("complete", "analyzed", "verified"))
        )

        matches.append(
            MatchSummary(
                match_id=mid,
                date=str(date_val) if date_val else None,
                opponent_name=str(opponent),
                result=str(result) if result else None,
                home_away=home_away,
                score=str(score) if score else None,
                set_scores=set_scores,
                status=str(status) if status else None,
                has_dvw=has_dvw,
                has_analysis=has_analysis,
            )
        )

    return matches


def parse_player_stats_response(data: Any, team: Optional[str] = None) -> List[PlayerStats]:
    """Parse Volleymetrics box score / athlete statistics payload."""
    players: List[PlayerStats] = []
    if not data:
        return players

    # 1. If data is full analysis payload containing 'sets', aggregate touches into athlete box scores
    if isinstance(data, dict) and "sets" in data and isinstance(data["sets"], list):
        home_tid = str(data.get("homeTeamId") or "")
        away_tid = str(data.get("awayTeamId") or "")
        agg: Dict[str, Dict[str, Any]] = {}
        sets_played_per_player: Dict[str, set] = {}

        for s_idx, s in enumerate(data["sets"], start=1):
            set_num = s.get("setNum") or s_idx
            for r in s.get("rallies", []):
                for e in r.get("events", []):
                    if not isinstance(e, dict):
                        continue

                    e_tid = str(e.get("teamId") or "")
                    if team:
                        target_t = str(team).lower().strip()
                        if target_t in ("a", "home") and e_tid != home_tid:
                            continue
                        elif target_t in ("b", "away") and e_tid != away_tid:
                            continue
                        elif target_t in (home_tid.lower(), away_tid.lower()) and target_t != e_tid.lower():
                            continue

                    p = e.get("player") or {}
                    p_num = str(p.get("number") or "")
                    p_first = p.get("firstName") or ""
                    p_last = p.get("lastName") or ""
                    p_name = f"{p_first} {p_last}".strip() or p.get("name") or "Unknown"
                    p_id = str(p.get("portalPlayerId") or p.get("id") or p_num or p_name)

                    if p_id not in agg:
                        agg[p_id] = {
                            "id": p_id,
                            "number": p_num,
                            "name": p_name,
                            "position": str(p.get("position") or ""),
                            "kills": 0,
                            "errors": 0,
                            "attacks": 0,
                            "assists": 0,
                            "aces": 0,
                            "serve_errors": 0,
                            "total_serves": 0,
                            "digs": 0,
                            "receptions": 0,
                            "perfect_passes": 0,
                            "positive_passes": 0,
                            "medium_passes": 0,
                            "reception_errors": 0,
                            "block_solos": 0,
                            "block_assists": 0,
                        }
                        sets_played_per_player[p_id] = set()

                    sets_played_per_player[p_id].add(set_num)

                    act = (e.get("type", {}).get("description") if isinstance(e.get("type"), dict) else str(e.get("type") or "")).lower()
                    grade = str(e.get("grade") or "").lower().strip()

                    if "attack" in act or "spike" in act:
                        agg[p_id]["attacks"] += 1
                        if grade in ("#", "kill", "point"):
                            agg[p_id]["kills"] += 1
                        elif grade in ("=", "error", "blocked"):
                            agg[p_id]["errors"] += 1
                    elif "serve" in act:
                        agg[p_id]["total_serves"] += 1
                        if grade in ("#", "ace", "point"):
                            agg[p_id]["aces"] += 1
                        elif grade in ("=", "error"):
                            agg[p_id]["serve_errors"] += 1
                    elif "receive" in act or "pass" in act:
                        agg[p_id]["receptions"] += 1
                        if grade in ("#", "perfect", "3"):
                            agg[p_id]["perfect_passes"] += 1
                        elif grade in ("+", "positive", "2"):
                            agg[p_id]["positive_passes"] += 1
                        elif grade in ("!", "medium", "1", "in_play", "in-play"):
                            agg[p_id]["medium_passes"] += 1
                        elif grade in ("=", "error", "0"):
                            agg[p_id]["reception_errors"] += 1
                    elif "dig" in act or "cover" in act:
                        agg[p_id]["digs"] += 1
                    elif "block" in act:
                        if grade in ("#", "point", "kill"):
                            agg[p_id]["block_solos"] += 1
                        elif grade in ("+", "positive", "touch"):
                            agg[p_id]["block_assists"] += 1
                    elif "set" in act:
                        if grade in ("#", "assist", "+"):
                            agg[p_id]["assists"] += 1

        for p_id, stat in agg.items():
            if stat["attacks"] == 0 and stat["total_serves"] == 0 and stat["receptions"] == 0 and stat["digs"] == 0 and stat["block_solos"] == 0:
                continue

            players.append(
                PlayerStats(
                    player_id=stat["id"],
                    jersey_number=stat["number"],
                    player_name=stat["name"],
                    position=stat["position"],
                    sets_played=len(sets_played_per_player.get(p_id, set())),
                    kills=stat["kills"],
                    attack_errors=stat["errors"],
                    total_attacks=stat["attacks"],
                    assists=stat["assists"],
                    aces=stat["aces"],
                    serve_errors=stat["serve_errors"],
                    total_serves=stat["total_serves"],
                    digs=stat["digs"],
                    receptions=stat["receptions"],
                    perfect_passes=stat["perfect_passes"],
                    positive_passes=stat["positive_passes"],
                    medium_passes=stat["medium_passes"],
                    reception_errors=stat["reception_errors"],
                    block_solos=stat["block_solos"],
                    block_assists=stat["block_assists"],
                )
            )

        # Sort by points descending
        players.sort(key=lambda p: p.points or 0, reverse=True)
        return players

    # 2. Can be a list of players or a dict containing player arrays
    raw_players = []
    if isinstance(data, list):
        raw_players = data
    elif isinstance(data, dict):
        if "players" in data:
            raw_players = data["players"]
        elif "boxScore" in data:
            raw_players = data["boxScore"]
        elif "athleteStats" in data:
            raw_players = data["athleteStats"]
        elif "teams" in data and isinstance(data["teams"], list):
            for t in data["teams"]:
                if not team or str(t.get("id")) == str(team) or str(t.get("name")).lower() == str(team).lower():
                    raw_players.extend(t.get("players", []))
        else:
            raw_players = [data]

    for p in raw_players:
        if not isinstance(p, dict):
            continue

        name = p.get("playerName") or p.get("name") or p.get("athleteName") or "Unknown Player"
        jersey = str(p.get("jerseyNumber") or p.get("jersey") or p.get("number") or "")
        pos = str(p.get("position") or p.get("pos") or "")
        sets = int(p.get("setsPlayed") or p.get("sets") or 0)

        kills = int(p.get("kills") or p.get("k") or 0)
        errors = int(p.get("attackErrors") or p.get("errors") or p.get("e") or 0)
        attacks = int(p.get("totalAttacks") or p.get("attacks") or p.get("ta") or 0)
        assists = int(p.get("assists") or p.get("ast") or p.get("a") or 0)
        bhe = int(p.get("ballHandlingErrors") or p.get("bhe") or 0)
        aces = int(p.get("serviceAces") or p.get("aces") or p.get("sa") or 0)
        se = int(p.get("serviceErrors") or p.get("serveErrors") or p.get("se") or 0)
        serves = int(p.get("totalServes") or p.get("serves") or 0)
        digs = int(p.get("digs") or p.get("d") or 0)
        receptions = int(p.get("receptions") or p.get("rec") or p.get("receptionAttempts") or 0)
        perf_pass = int(p.get("perfectPasses") or p.get("quality3Passes") or 0)
        pos_pass = int(p.get("positivePasses") or p.get("quality2Passes") or 0)
        med_pass = int(p.get("mediumPasses") or p.get("quality1Passes") or 0)
        rec_err = int(p.get("receptionErrors") or p.get("re") or 0)
        bs = int(p.get("blockSolos") or p.get("bs") or 0)
        ba = int(p.get("blockAssists") or p.get("ba") or 0)
        be = int(p.get("blockErrors") or p.get("be") or 0)

        players.append(
            PlayerStats(
                player_id=str(p.get("id") or p.get("playerId") or ""),
                jersey_number=jersey,
                player_name=name,
                position=pos,
                sets_played=sets,
                kills=kills,
                attack_errors=errors,
                total_attacks=attacks,
                assists=assists,
                ball_handling_errors=bhe,
                aces=aces,
                serve_errors=se,
                total_serves=serves,
                digs=digs,
                receptions=receptions,
                perfect_passes=perf_pass,
                positive_passes=pos_pass,
                medium_passes=med_pass,
                reception_errors=rec_err,
                block_solos=bs,
                block_assists=ba,
                block_errors=be,
            )
        )

    return players


def parse_rotation_stats_response(data: Any, team: Optional[str] = None) -> List[RotationStats]:
    """Parse Volleymetrics rotation analytics into RotationStats objects."""
    rotations: List[RotationStats] = []
    if not data:
        return rotations

    # 1. If data is full analysis payload containing 'sets', compute P1-P6 sideout & scoring stats
    if isinstance(data, dict) and "sets" in data and isinstance(data["sets"], list):
        home_tid = str(data.get("homeTeamId") or "")
        away_tid = str(data.get("awayTeamId") or "")

        target_is_home = True
        if team:
            t_str = str(team).lower().strip()
            if t_str in ("b", "away") or (away_tid and t_str == away_tid):
                target_is_home = False
            elif t_str in ("a", "home") or (home_tid and t_str == home_tid):
                target_is_home = True

        target_team_id = home_tid if target_is_home else away_tid

        # Initialize P1..P6 accumulators
        p_stats: Dict[int, Dict[str, Any]] = {
            rot: {
                "sideouts_earned": 0,
                "sideout_attempts": 0,
                "points_scored_serving": 0,
                "serve_attempts": 0,
                "first_ball_sideouts": 0,
                "setter_tendencies": {},
            }
            for rot in range(1, 7)
        }

        for s in data["sets"]:
            rallies = s.get("rallies", [])
            for r_idx, r in enumerate(rallies):
                events = r.get("events", [])
                if not events:
                    continue

                rot_val = r.get("homeSetterRotation" if target_is_home else "awaySetterRotation")
                try:
                    rot_num = int(rot_val) if rot_val is not None else 1
                except (ValueError, TypeError):
                    rot_num = 1
                rot_num = max(1, min(6, rot_num))

                # Identify serving team from first serve event or first touch
                serving_tid = None
                for e in events:
                    act_desc = (e.get("type", {}).get("description") if isinstance(e.get("type"), dict) else str(e.get("type") or "")).lower()
                    if "serve" in act_desc:
                        serving_tid = str(e.get("teamId") or "")
                        break
                if not serving_tid and events:
                    serving_tid = str(events[0].get("teamId") or "")

                is_serving = (serving_tid == target_team_id)

                # Determine winning team of rally
                winning_tid = None
                if r_idx + 1 < len(rallies):
                    next_r = rallies[r_idx + 1]
                    h_curr, a_curr = r.get("homeScore", 0) or 0, r.get("awayScore", 0) or 0
                    h_next, a_next = next_r.get("homeScore", 0) or 0, next_r.get("awayScore", 0) or 0
                    if h_next > h_curr:
                        winning_tid = home_tid
                    elif a_next > a_curr:
                        winning_tid = away_tid

                if not winning_tid:
                    last_e = events[-1]
                    last_act = (last_e.get("type", {}).get("description") if isinstance(last_e.get("type"), dict) else str(last_e.get("type") or "")).lower()
                    last_grade = str(last_e.get("grade") or "").lower().strip()
                    last_tid = str(last_e.get("teamId") or "")
                    opp_tid = away_tid if last_tid == home_tid else home_tid

                    if last_grade in ("#", "kill", "point", "ace") or "block" in last_act:
                        winning_tid = last_tid
                    elif last_grade in ("=", "error") or "error" in last_act:
                        winning_tid = opp_tid
                    else:
                        winning_tid = last_tid

                won_rally = (winning_tid == target_team_id)

                if is_serving:
                    p_stats[rot_num]["serve_attempts"] += 1
                    if won_rally:
                        p_stats[rot_num]["points_scored_serving"] += 1
                else:
                    p_stats[rot_num]["sideout_attempts"] += 1
                    if won_rally:
                        p_stats[rot_num]["sideouts_earned"] += 1
                        if len(events) <= 3:
                            p_stats[rot_num]["first_ball_sideouts"] += 1

                # Track setter distribution in rotation
                for e in events:
                    if str(e.get("teamId") or "") == target_team_id:
                        act_desc = (e.get("type", {}).get("description") if isinstance(e.get("type"), dict) else str(e.get("type") or "")).lower()
                        if "attack" in act_desc or "spike" in act_desc:
                            p_obj = e.get("player") or {}
                            p_name = p_obj.get("lastName") or p_obj.get("name") or str(p_obj.get("number") or "Hitter")
                            p_stats[rot_num]["setter_tendencies"][p_name] = p_stats[rot_num]["setter_tendencies"].get(p_name, 0) + 1

        for rot_num in range(1, 7):
            st = p_stats[rot_num]
            so_att = st["sideout_attempts"]
            so_pct = round(st["sideouts_earned"] / so_att, 4) if so_att > 0 else 0.0
            srv_att = st["serve_attempts"]
            ps_pct = round(st["points_scored_serving"] / srv_att, 4) if srv_att > 0 else 0.0
            fbso_rate = round(st["first_ball_sideouts"] / so_att, 4) if so_att > 0 else 0.0

            rotations.append(
                RotationStats(
                    rotation_number=rot_num,
                    rotation_name=f"P{rot_num}",
                    sideout_percentage=so_pct,
                    sideouts_earned=st["sideouts_earned"],
                    sideout_attempts=so_att,
                    point_scoring_percentage=ps_pct,
                    points_scored_serving=st["points_scored_serving"],
                    serve_attempts=srv_att,
                    first_ball_sideout_rate=fbso_rate,
                    setter_tendencies=st["setter_tendencies"],
                )
            )

        return rotations

    # 2. Existing raw rotation array parsing
    raw_rotations = []
    if isinstance(data, list):
        raw_rotations = data
    elif isinstance(data, dict):
        raw_rotations = data.get("rotations") or data.get("rotationStats") or []

    for idx, r in enumerate(raw_rotations, start=1):
        if not isinstance(r, dict):
            continue

        rot_num = int(r.get("rotationNumber") or r.get("rotation") or r.get("p") or idx)
        rot_num = max(1, min(6, rot_num))

        so_pct = r.get("sideoutPercentage") or r.get("sideoutPct") or r.get("soPct")
        if so_pct is not None:
            so_pct = float(so_pct)
            if so_pct > 1.0:
                so_pct = round(so_pct / 100.0, 4)

        ps_pct = r.get("pointScoringPercentage") or r.get("pointScoringPct") or r.get("psPct")
        if ps_pct is not None:
            ps_pct = float(ps_pct)
            if ps_pct > 1.0:
                ps_pct = round(ps_pct / 100.0, 4)

        fbso = r.get("firstBallSideoutRate") or r.get("fbsoPct") or r.get("fbso")
        if fbso is not None:
            fbso = float(fbso)
            if fbso > 1.0:
                fbso = round(fbso / 100.0, 4)

        rotations.append(
            RotationStats(
                rotation_number=rot_num,
                rotation_name=f"P{rot_num}",
                sideout_percentage=so_pct,
                sideouts_earned=r.get("sideoutsEarned") or r.get("sideouts"),
                sideout_attempts=r.get("sideoutAttempts") or r.get("receptions"),
                point_scoring_percentage=ps_pct,
                points_scored_serving=r.get("pointsScoredServing") or r.get("pointsServed"),
                serve_attempts=r.get("serveAttempts") or r.get("serves"),
                first_ball_sideout_rate=fbso,
                setter_tendencies=r.get("setterTendencies") or r.get("setterDistribution") or {},
                notes=r.get("notes"),
            )
        )

    # Sort rotations by rotation_number P1 through P6
    rotations.sort(key=lambda x: x.rotation_number)
    return rotations


def parse_video_actions(
    data: Any,
    set_number: Optional[int] = None,
    action_type: Optional[str] = None,
    player: Optional[str] = None,
    team: Optional[str] = None,
    quality: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> List[VolleyballAction]:
    """Parse Volleymetrics play-by-play / touches payload with filtering."""
    actions: List[VolleyballAction] = []
    if not data:
        return actions

    raw_events = []
    if isinstance(data, list):
        raw_events = data
    elif isinstance(data, dict):
        if "sets" in data and isinstance(data["sets"], list):
            home_tid = str(data.get("homeTeamId") or "")
            away_tid = str(data.get("awayTeamId") or "")
            home_name = data.get("homeTeam", {}).get("name") if isinstance(data.get("homeTeam"), dict) else "Home"
            away_name = data.get("awayTeam", {}).get("name") if isinstance(data.get("awayTeam"), dict) else "Away"

            for s_idx, s in enumerate(data["sets"], start=1):
                set_num = int(s.get("setNum") or s_idx)
                for r in s.get("rallies", []):
                    rally_id = r.get("id") or r.get("rallyId")
                    score_str = f"{r.get('homeScore', 0)}-{r.get('awayScore', 0)}"
                    h_rot = r.get("homeSetterRotation")
                    a_rot = r.get("awaySetterRotation")

                    for e in r.get("events", []):
                        if not isinstance(e, dict):
                            continue
                        e_tid = str(e.get("teamId") or "")
                        t_code = "a" if e_tid == home_tid else ("b" if e_tid == away_tid else "a")
                        t_name = home_name if t_code == "a" else away_name

                        p = e.get("player") or {}
                        p_first = p.get("firstName") or ""
                        p_last = p.get("lastName") or ""
                        p_name = f"{p_first} {p_last}".strip() or p.get("name") or ""
                        p_num = str(p.get("number") or "")

                        act_desc = e.get("type", {}).get("description") if isinstance(e.get("type"), dict) else str(e.get("type") or "")
                        grade = str(e.get("grade") or "")

                        raw_events.append({
                            "id": e.get("id"),
                            "rallyId": rally_id,
                            "setNumber": set_num,
                            "score": score_str,
                            "team": t_code,
                            "teamName": t_name,
                            "playerId": str(p.get("portalPlayerId") or p.get("id") or ""),
                            "playerName": p_name,
                            "jerseyNumber": p_num,
                            "actionType": act_desc,
                            "quality": grade,
                            "timestampSeconds": e.get("videoStartTime") or e.get("timestamp"),
                            "sourceZone": e.get("xCoordinate"),
                            "destZone": e.get("destXCoordinate"),
                            "details": f"Rotation H:P{h_rot} A:P{a_rot}" if (h_rot or a_rot) else None,
                        })
        else:
            raw_events = data.get("actions") or data.get("touches") or data.get("events") or []

    for idx, e in enumerate(raw_events):
        if not isinstance(e, dict):
            continue

        evt_set = int(e.get("setNumber") or e.get("set") or 1)
        if set_number is not None and evt_set != set_number:
            continue

        act_type = str(e.get("actionType") or e.get("skill") or e.get("event") or "").lower()
        if action_type:
            at_clean = action_type.lower().strip()
            if at_clean not in act_type and act_type not in at_clean:
                continue

        p_name = str(e.get("playerName") or e.get("player") or "")
        p_jersey = str(e.get("jerseyNumber") or e.get("jersey") or "")
        if player:
            target_p = player.lower().replace("#", "").strip()
            if target_p not in p_name.lower() and target_p != p_jersey.replace("#", "").strip():
                continue

        t_code = str(e.get("team") or e.get("teamCode") or "a").lower()
        t_name = str(e.get("teamName") or "")
        if team:
            target_t = team.lower().strip()
            if target_t != t_code and target_t not in t_name.lower():
                continue

        res_qual = str(e.get("quality") or e.get("result") or e.get("evaluation") or "").lower()
        if quality:
            target_q = quality.lower().strip()
            if target_q not in res_qual and res_qual not in target_q:
                continue

        ts_sec = e.get("timestampSeconds") or e.get("time") or e.get("timestamp")
        ts_sec_val = float(ts_sec) if ts_sec is not None else None
        ts_fmt = None
        if ts_sec_val is not None:
            m = int(ts_sec_val // 60)
            s = int(ts_sec_val % 60)
            ts_fmt = f"{m:02d}:{s:02d}"

        p_label = f"#{p_jersey} {p_name}".strip() if p_jersey or p_name else f"Player {idx + 1}"

        actions.append(
            VolleyballAction(
                action_id=e.get("id") or idx + 1,
                rally_id=e.get("rallyId"),
                set_number=evt_set,
                score=e.get("score"),
                timestamp_seconds=ts_sec_val,
                timestamp_formatted=ts_fmt,
                team=t_code,
                team_name=t_name or None,
                player_id=str(e.get("playerId") or ""),
                jersey_number=p_jersey,
                player_label=p_label,
                action_type=act_type or "touch",
                touch_type=e.get("touchType"),
                quality=res_qual or None,
                attack_type=e.get("attackType") or e.get("route"),
                first_ball_side_out=bool(e.get("fbso") or e.get("firstBallSideOut")),
                source_zone=e.get("sourceZone") or e.get("startZone"),
                dest_zone=e.get("destZone") or e.get("endZone"),
                speed_kmh=e.get("speedKmh") or e.get("speed"),
                details=e.get("details"),
            )
        )

    # Apply pagination offset and limit
    return actions[offset : offset + limit]
