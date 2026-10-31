# 🏐 Volleymetrics MCP Server (`volleymetrics-mcp`)

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Model Context Protocol](https://img.shields.io/badge/MCP-1.3+-green.svg)](https://modelcontextprotocol.io/)
[![Build System Hatchling](https://img.shields.io/badge/build-hatchling-purple.svg)](https://hatch.pypa.io/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Strict Read-Only](https://img.shields.io/badge/Security-Strict%20Read--Only-brightgreen.svg)]()
[![DataVolley Compatible](https://img.shields.io/badge/OpenVolley-DataVolley%20.dvw-orange.svg)]()

A production-grade [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) server connecting AI clients (**Claude Desktop**, **Cursor**, **Antigravity**, or custom LLM agents) to **Volleymetrics** and **Hudl** volleyball analytics.

Transform your AI into a Staff Volleyball Performance Analyst capable of scouting opponents, diagnosing rotation breakdowns (P1–P6), analyzing serve-receive stability, generating box scores, and exporting event-by-event touches directly to **DataVolley (`.dvw`)** and **Pandas**.

---

> [!IMPORTANT]
> ### ⚖️ Legal Disclaimer
> This is an **independent, open-source community project** and is **not affiliated with, maintained by, authorized by, or endorsed by Hudl, Agile Sports Technologies, Volleymetrics, or Balltime**.
>
> All product and company names are trademarks™ or registered® trademarks of their respective holders. Use of them does not imply any affiliation with or endorsement by them. This integration operates under a strict, client-side, read-only policy to access data belonging to your authenticated team account.

---

## 🌟 Why Coaches & Analysts Love This Server

- 🛡️ **Zero Password Storage**: Interactive browser login (`login_to_volleymetrics`) lets you log in via 1Password, Bitwarden, Apple/Google SSO, or 2FA. Your password is never stored or seen by the AI or environment files.
- 📦 **1-Click `.mcpb` Installation**: Distribute a single double-clickable `.mcpb` bundle that non-technical coaches can install into Claude Desktop without touching a terminal.
- ⚡ **Zero-Setup `uvx`**: Run instantly via `uvx --from git+https://github.com/onnobos/volleymetrics_mcp.git volleymetrics-mcp` without manually managing virtual environments or dependencies.
- 🪟 **Context-Window Optimized**: Strips bloated API metadata. Tools return either clean Markdown tables or token-efficient compact dictionaries (`output_format="markdown"` or `"compact"`).
- 🛡️ **Defensive Networking & Account Protection**:
  - **Strict Read-Only**: Enforces zero mutation policy; any mutating request is immediately blocked before transmission.
  - **Rate Limiting**: Built-in 2 requests/second token bucket rate limiter with jittered exponential backoff on HTTP 429/5xx.
  - **Multi-Tier Disk Caching**: 7-day persistent cache for match box scores, touches, and DVW files; 15-minute cache for schedules and team rosters.
- 🏐 **Volleyball Domain Semantics**: Native support for Rotations P1 through P6, setter distribution, First-Ball Sideout (FBSO), and **DataVolley `.dvw` skill codes** (`S`, `R`, `E`, `A`, `B`, `D`, `F`) and evaluation codes (`#`, `+`, `!`, `-`, `=`).
- 📁 **Direct DataVolley DVW Downloads**: Generate and save official `.dvw` scouting files directly from the Volleymetrics export pipeline.
- 🤖 **5 Built-In FastMCP Prompts (`@mcp.prompt`)**: Pre-packaged, professional coaching workflows for opponent scouting, rotation diagnostics, MVP evaluation, DataVolley export, and serve-receive audits.

---

## 🚀 Quick Start & Installation

### Option 1: Zero-Setup `uvx` *(Recommended for Cursor, Claude Desktop & Terminal Users)*

Requires Astral's ultra-fast [`uv`](https://github.com/astral-sh/uv). No virtual environment activation needed.

#### Claude Desktop Configuration
Add this to your `claude_desktop_config.json`:
- **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "volleymetrics": {
      "command": "uvx",
      "args": [
        "--from",
        "git+https://github.com/onnobos/volleymetrics_mcp.git",
        "volleymetrics-mcp"
      ]
    }
  }
}
```

#### Cursor IDE Configuration
In Cursor, open **Settings** > **Features** > **MCP Servers** > **Add New MCP Server** (or edit `.cursor/mcp.json`):

```json
{
  "mcpServers": {
    "volleymetrics": {
      "command": "uvx",
      "args": [
        "--from",
        "git+https://github.com/onnobos/volleymetrics_mcp.git",
        "volleymetrics-mcp"
      ]
    }
  }
}
```

#### Antigravity Configuration
In Antigravity, add to your MCP settings or use `mcp_config.antigravity.json`:

```json
{
  "mcpServers": {
    "volleymetrics": {
      "command": "python",
      "args": ["-m", "volleymetrics_mcp.server"]
    }
  }
}
```

---

## 🔑 Authentication: Interactive Pop-Up Browser

The easiest and most secure way to authenticate is saying in your AI chat:

> **"Log me into Volleymetrics"**

1. A visible browser window opens to `https://portal.volleymetrics.hudl.com`.
2. Log in using your password manager (1Password, Bitwarden, iCloud Keychain), Hudl SSO, or 2FA.
3. Once you reach the portal dashboard, session tokens are securely saved to `~/.volleymetrics_mcp/auth_state.json` and the OS Keychain.
4. The browser window closes automatically and you are authenticated!

---

## 🛠️ Available MCP Tools

| Tool | Description |
| :--- | :--- |
| `get_user_teams` | Discover and list all Volleymetrics teams and active accounts to find your Team ID. |
| `list_volleyball_matches` | Fetch recent matches and upcoming schedule fixtures for a team. |
| `get_match_player_stats` | Retrieve athlete box scores with accurate hitting %, total blocks, points, and pass ratings. |
| `get_rotation_breakdown` | Analyze tactical sideout % (SO%), point scoring % (PS%), FBSO%, and setter distribution across P1–P6. |
| `get_game_actions` | Query chronological volleyball touches with DataVolley (.dvw) skill and evaluation codes. |
| `download_match_dvw` | Generate and download the authentic `.dvw` DataVolley scouting file for an analyzed match. |
| `login_to_volleymetrics` | Launch interactive browser login window without password storage. |
| `refresh_volleymetrics_cookie` | Refresh session token or view authentication status. |

---

## 🎯 FastMCP Prompts (`@mcp.prompt`)

1. **`scout_opponent`**: 5-step tactical opponent scouting workflow analyzing offense, weak sideout rotations, and vulnerable passers.
2. **`analyze_rotation_weaknesses`**: Rotation diagnostic analyzing sideout efficiency under 50% and setter distribution predictability.
3. **`match_mvp_breakdown`**: Quantitative MVP evaluation using True Points, Hitting Efficiency, and Defensive Impact.
4. **`datavolley_export`**: Translates match touch data into standardized OpenVolley `.dvw` scouting syntax.
5. **`serve_receive_audit`**: Evaluates 3-pass percentage, reception errors, and opponent service pressure points.

---

## 🧪 Development & Testing

```bash
# 1. Clone repository
git clone https://github.com/onnobos/volleymetrics_mcp.git
cd volleymetrics_mcp

# 2. Create virtual environment and install dev dependencies
uv venv
source .venv/bin/activate
uv pip install -e ".[dev]"

# 3. Run automated tests
pytest -v tests/
```

---

## 📄 License

MIT License. See [LICENSE](file:///Users/onnobos/projects/volleymetrics_mcp/LICENSE) for details.
