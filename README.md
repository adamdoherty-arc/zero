# Zero - Personal AI Assistant (OpenClaw.ai)

Multi-channel AI assistant powered by Claude, built on [OpenClaw.ai](https://openclaw.ai).

## Quick Start

1. **Set your Anthropic API key** in `.env`:
   ```
   ANTHROPIC_API_KEY=sk-ant-xxxxx
   ```

2. **Start the gateway**:
   ```bash
   cd C:\code\moltbot
   docker-compose up -d
   ```

3. **Pair WhatsApp** (requires interactive terminal):
   ```bash
   docker exec -it zero-gateway node dist/index.js configure --section channels
   ```
   - Select "WhatsApp" when prompted
   - Scan the QR code with WhatsApp (Settings > Linked Devices > Link a Device)

## Commands

### Start Services
```bash
docker-compose up -d
```

### Stop Services
```bash
docker-compose down
```

### View Logs
```bash
# All logs
docker-compose logs -f

# Gateway only
docker logs -f zero-gateway
```

### Run CLI Commands
```bash
# Run doctor health check
docker exec zero-gateway node dist/index.js doctor

# Configure channels (WhatsApp)
docker exec -it zero-gateway node dist/index.js configure --section channels

# Check gateway status
docker exec zero-gateway node dist/index.js doctor
```

### Restart Services
```bash
docker-compose restart zero-gateway
```

## Configuration

- **Config file**: `./config/zero.json`
- **Workspace**: `./workspace/`
- **Environment**: `.env`

### Ports
- `18789`: Gateway WebSocket API
- `18790`: Bridge port

### Current Settings
- Model: `anthropic/claude-sonnet-4`
- Gateway mode: local
- Gateway bind: lan (network accessible)

## Troubleshooting

### WhatsApp disconnected
Re-run channel configuration:
```bash
docker exec -it zero-gateway node dist/index.js configure --section channels
```

### Gateway not responding
Check logs and restart:
```bash
docker logs zero-gateway
docker-compose restart zero-gateway
```

### API key issues
1. Edit `.env` and set your Anthropic API key
2. Restart:
   ```bash
   docker-compose down
   docker-compose up -d
   ```

### Container issues
Reset and rebuild:
```bash
docker-compose down
docker-compose pull
docker-compose up -d
```

### Run doctor to diagnose
```bash
docker exec zero-gateway node dist/index.js doctor
```

## File Structure

```
zero/
├── config/
│   └── zero.json        # Bot configuration
├── workspace/           # Bot workspace/sessions
├── docker-compose.yml   # Docker services
├── .env                 # Environment variables (API keys, tokens)
└── README.md            # This file
```

## Security Notes

- The gateway token is stored in `.env` and `config/zero.json`
- Keep your Anthropic API key secure
- The gateway is bound to LAN - ensure your network is trusted
- Run `docker exec zero-gateway node dist/index.js security audit --deep` for security checks
