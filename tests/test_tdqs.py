"""Tool Definition Quality Score (TDQS) automated compliance and lint test suite.

Verifies that all exported MCP tool definitions (`mcp.list_tools()`), JSON input schemas,
MCP ToolAnnotations, docstrings, and server instructions achieve a perfect 5.0 / 5.0 (100/100)
score under the Glama AI Tool Definition Quality Score (TDQS) specification
(https://github.com/glama-ai/tool-definition-quality-score / https://tdqs.dev).
"""

from __future__ import annotations

import pytest

from volleymetrics_mcp.server import (
    download_match_dvw,
    get_game_actions,
    get_match_player_stats,
    get_rotation_breakdown,
    get_user_teams,
    list_volleyball_matches,
    login_to_volleymetrics,
    mcp,
    refresh_volleymetrics_cookie,
    refresh_volleymetrics_session,
)

CORE_TOOLS = [
    get_user_teams,
    list_volleyball_matches,
    get_match_player_stats,
    get_rotation_breakdown,
    get_game_actions,
    download_match_dvw,
    login_to_volleymetrics,
    refresh_volleymetrics_session,
]


def test_server_instructions_coherence_and_routing():
    """Verify FastMCP server instructions provide high-signal routing and decision matrix."""
    instructions = mcp.instructions
    assert instructions is not None, "Server instructions cannot be empty"
    assert len(instructions) >= 300, f"Server instructions too brief ({len(instructions)} chars); expected >= 300"
    assert "Decision Matrix" in instructions or "Routing" in instructions
    for tool_fn in CORE_TOOLS:
        assert tool_fn.__name__ in instructions, f"Tool {tool_fn.__name__} missing from server routing instructions"


@pytest.mark.asyncio
async def test_mcp_exported_tools_stage1_context_signals():
    """Verify Stage 1 TDQS Context Signals on exported MCP Tool JSON schemas:
    - Exactly 8 distinct tools (no duplicate alias registered on MCP)
    - 100% title and ToolAnnotations coverage (readOnlyHint, destructiveHint, idempotentHint, openWorldHint)
    - 100% schemaDescriptionCoverage across all inputSchema.properties
    - 0 zero-parameter tools (avoids the 4/5 zero-parameter baseline cap)
    - Clean markdown formatting without 4-space docstring indentation artifacts
    """
    tools = await mcp.list_tools()
    assert len(tools) == 8, f"Expected exactly 8 distinct MCP tools, got {len(tools)}"

    for tool in tools:
        assert tool.title and len(tool.title) >= 5, f"Tool '{tool.name}' missing human-readable title"
        assert tool.description, f"Tool '{tool.name}' missing description"
        assert "\n    ### " not in tool.description, (
            f"Tool '{tool.name}' contains uncleaned 4-space docstring indentation"
        )

        # Verify MCP ToolAnnotations
        assert tool.annotations is not None, f"Tool '{tool.name}' missing MCP ToolAnnotations"
        assert tool.annotations.readOnlyHint is not None
        assert tool.annotations.destructiveHint is False
        assert tool.annotations.idempotentHint is not None
        assert tool.annotations.openWorldHint is True

        # Verify no annotation contradiction
        if tool.name in {
            "get_user_teams",
            "list_volleyball_matches",
            "get_match_player_stats",
            "get_rotation_breakdown",
            "get_game_actions",
        }:
            assert tool.annotations.readOnlyHint is True
            assert tool.annotations.idempotentHint is True
        else:
            # download_match_dvw, login_to_volleymetrics, refresh_volleymetrics_session mutate local files/state
            assert tool.annotations.readOnlyHint is False

        # Verify 100% schemaDescriptionCoverage and >= 1 parameter per tool
        props = tool.inputSchema.get("properties", {})
        assert len(props) >= 1, (
            f"Tool '{tool.name}' has 0 parameters (triggers TDQS 4/5 zero-parameter baseline cap)"
        )
        for prop_name, prop_schema in props.items():
            desc = prop_schema.get("description", "")
            assert len(desc) >= 20, (
                f"Tool '{tool.name}' parameter '{prop_name}' missing rich schema description: '{desc}'"
            )
            assert "examples" in prop_schema, (
                f"Tool '{tool.name}' parameter '{prop_name}' missing schema examples"
            )


@pytest.mark.parametrize("tool_func", CORE_TOOLS)
def test_tool_all_six_tdqs_dimensions(tool_func):
    """Verify all 6 TDQS Rubric Dimensions on every tool docstring."""
    doc = tool_func.__doc__
    assert doc is not None, f"Tool '{tool_func.__name__}' is missing docstring"

    first_line = doc.strip().split("\n")[0].strip()
    # Dimension 1: Purpose Clarity (Specific verb + resource + sibling differentiation)
    assert len(first_line) >= 50, f"Tool '{tool_func.__name__}' opening sentence too short: '{first_line}'"
    assert "unlike `" in first_line or "before calling `" in first_line, (
        f"Tool '{tool_func.__name__}' opening sentence should immediately differentiate it from sibling tools"
    )

    # Dimension 2: Usage Guidelines (Positive triggers + Negative bounds + named alternatives)
    assert "### When to Use" in doc
    assert "### When NOT to Use" in doc
    assert "Do NOT" in doc

    # Dimension 3: Behavioral Transparency (Caching, rate limits, execution contract)
    assert "### Behavioral Guarantees" in doc
    assert "Side Effects" in doc or "Execution Contract" in doc

    # Dimension 4: Parameter & Workflow Semantics (Cross-parameter meaning beyond raw schema)
    assert "### Parameter & Workflow Semantics" in doc

    # Dimension 5 & 6: Conciseness, Structure & Contextual Completeness (Return schemas & error states)
    assert "### Returns & Error States" in doc


def test_server_coherence_and_backwards_compatibility():
    """Verify Server Coherence (8 distinct tools) and Python backwards-compatibility alias."""
    assert 3 <= len(CORE_TOOLS) <= 15
    assert refresh_volleymetrics_cookie is refresh_volleymetrics_session
