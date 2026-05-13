---
name: zero-deploy
type: workflow
triggers: [deploy, rebuild, docker compose, zero-api, zero-ui, restart]
agent: any
---

Deployment workflow for the Zero repo (from CLAUDE.md):

- **Backend changes** require a `zero-api` rebuild — code is `COPY`'d:
  ```bash
  docker compose -f docker-compose.sprint.yml build --no-cache zero-api && \
    docker compose -f docker-compose.sprint.yml up -d zero-api
  ```

- **Frontend source changes** are live (volume-mounted `src/`). Only
  rebuild `zero-ui` when `npm install` added new packages:
  ```bash
  docker compose -f docker-compose.sprint.yml build --no-cache zero-ui && \
    docker compose -f docker-compose.sprint.yml up -d zero-ui
  ```

- Verify health after rebuild:
  ```bash
  docker ps --format "table {{.Names}}\t{{.Status}}" | grep zero
  ```

Never leave changes undeployed. Rebuild is the final step.
