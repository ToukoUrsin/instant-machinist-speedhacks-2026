# Alike: coordinating the agents that built Instant Machinist

[Alike](https://alike.dev) gives coding agents a shared memory. Every Claude Code and Codex session on the build box is briefed with the team's decisions and live work, and Alike shows which other agents are on the same work item.
We used it to run many agents at once in one workspace: the CAM build thread, a Codex simulator swarm, the demo threads and five parallel sponsor agents.

## Setup (done 2026-10-11)
- Account: the team's Alike workspace. Credentials come from environment variables.
- Machine `the build server` paired at 13:34 PDT with `npx @alikeai/setup --doctor`, which resumed pairing and approved it in a headless browser. The Claude Code and Codex hooks were already wired; nothing was rewired.
- Codex MCP OAuth: `codex mcp login alike`, approved headlessly. `codex mcp list` shows `alike … OAuth`.
- Capture scope: `~/.alike/ignore` lists `path:` rules that keep other `~/work` projects local. The `credentials.json` history floor is `2026-10-11T15:00Z`, so only today's hackathon sessions go to Alike.
- Alike's opt-in local injection tee (`~/.alike/injections/.enabled`) records what Alike puts into each agent's context. It stays on this box and is never uploaded.

## Files
- `alike_mcp.py`: small read client for the Alike MCP server. It uses the OAuth token Codex stored and never prints it. `python3 alike_mcp.py tools | call NAME '{json}'`.
- `record_decisions.py`: recorded 7 of the team's real decisions from `../../DECISIONS.md` and `../README.md` as Alike decisions, anchored to the project work item and its folders. Already run; URNs are in `evidence/recorded_decisions.json`.
- `stats.py`: the numbers. It writes `evidence/stats.json`, `evidence/stats.md` and `evidence/served_moments.jsonl`.
- `sample_live.py`: asks Alike which agent sessions are live once a minute and writes `evidence/alike_live_samples.jsonl`.

## Run
```bash
cd integrations/alike
python3 stats.py                      # refresh numbers -> evidence/stats.md
python3 alike_mcp.py call list_agent_sessions
nohup python3 sample_live.py --until 2026-10-11T23:15:00Z &   # if the sampler is not running
```

## Data sources (kept separate)
- **Alike (MCP):** live sessions by harness, ingested sessions, decisions, work items with more than one agent session, analytics (context injected/followed), and load-bearing records.
- **Alike (local tee):** the exact pointer blocks Alike injected into each agent, with timestamp, tool and file path. Titles only.
- **Box logs (not Alike):** T3 Code thread turns (`~/.t3/userdata/state.sqlite`, read-only), Claude sub-agent transcripts, and Codex swarm `run.json` files. Use these for the total agent count and for anything before 13:34 PDT, when Alike wasn't connected yet.
