---
inclusion: always
---

# Documentation Sync Rules

When making changes to the codebase, always keep documentation in sync:

## Files to update when architecture changes

- `docs/architecture.md` — High-level diagrams, stacks, agent layer, data layer, deployment pipeline
- `docs/local-testing.md` — Local dev setup, ports, how pieces fit together, troubleshooting
- `README.md` — Repo layout, prerequisites, local development, deploy commands, agent descriptions
- `local/README.md` — Scripts table, ports table, quick start commands

## What triggers a doc update

- Adding, removing, or renaming a service/component (agent, MCP server, API, etc.)
- Changing ports, URLs, or environment variables
- Modifying startup scripts (`up.sh`, `down.sh`, `status.sh`)
- Changing dependencies in `requirements.txt` or `package.json`
- Modifying CDK stacks (adding/removing resources)
- Changing the deployment pipeline or CI workflow

## Port registry

Keep the ports table in `local/README.md` current. All local ports:

| Port | Service |
|------|---------|
| 8001 | DynamoDB Local (Docker) |
| 8000 | API shim (Docker) |
| 8083 | MCP Server (Host) |
| 8081 | LangGraph agent (Host) |
| 8082 | Strands agent (Host) |
| 3000 | Chatbot UI - Next.js (Host) |
| 5174 | Device Simulator UI (Vite) |
| 5175 | Admin Console UI (Vite) |

## Spec files

Spec files under `.kiro/specs/` do NOT need to be updated when code changes — they are point-in-time design documents.
