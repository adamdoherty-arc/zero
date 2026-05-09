# Centralize Qwen3.6-35B-A3B Q4_K_M Abliterated Model in Shared Infrastructure

## Context

The user removed a model from the "zero" project but discovered it should not have been project-specific. The Qwen3.6-35B-A3B Q4_K_M abliterated model needs to be properly centralized in the shared infrastructure folder so all projects (ADA, Zero, Legion) can access it. Currently, the shared-infra setup is configured correctly but the model file itself is missing, causing the `llama-cpp-chat` container to fail.

## Current Situation Analysis

### ✅ Properly Configured (No Changes Needed)
- **Shared Infrastructure**: `c:\code\shared-infra\docker-compose.vllm.yml` correctly configured
- **Model Mount**: Maps `../zero/workspace/llm-models:/models:ro` to llama.cpp container
- **LiteLLM Router**: `c:\code\shared-infra\litellm\config.yaml` has correct model aliases (`qwen3-chat`)
- **Project References**: All projects (ADA, Zero, Legion) correctly reference shared endpoints
- **No Duplicates**: Clean setup with no conflicting model references

### ❌ Critical Issue Found
- **Missing Model File**: `c:\code\zero\workspace\llm-models\Huihui-Qwen3.6-35B-A3B-abliterated-Q4_K_M.gguf` does not exist
- **Container Status**: `llama-cpp-chat` in restart loop (exit code 1) due to missing model
- **Health Check Failing**: Cannot load model, preventing full shared-infra operation

## Implementation Plan

### Phase 1: Download Missing Model to Shared Location
1. **Download Model**: Fetch `Huihui-Qwen3.6-35B-A3B-abliterated-Q4_K_M.gguf` to `c:\code\zero\workspace\llm-models\`
   - Model source: HuggingFace (Huihui/Qwen3.6-35B-A3B-abliterated)
   - Expected size: ~21-22 GB
   - Location rationale: This directory is mounted as shared volume in docker-compose

2. **Verify Download**: Confirm file exists and has correct size/checksum

### Phase 2: Restart Shared Infrastructure
1. **Stop Current Services**: `docker-compose -f c:\code\shared-infra\docker-compose.vllm.yml down`
2. **Start Services**: `docker-compose -f c:\code\shared-infra\docker-compose.vllm.yml up -d`
3. **Monitor Startup**: Watch container logs for successful model loading

### Phase 3: Test Multi-Project Access
1. **Test ADA Integration**: Verify `backend/infrastructure/llm_router.py` can access model
   - Check endpoint: `http://localhost:18800/v1/models`
   - Test chat completion via ADA's router

2. **Test Zero Integration**: Verify zero-api can access shared model
   - Check `.env` configuration points to shared endpoint
   - Test chat completion via zero's backend

3. **Test Legion Integration**: Verify Legion can access shared model
   - Check VLLMClient connection to `http://host.docker.internal:18800/v1`

### Phase 4: Verify Logs and Health
1. **Check vLLM Logs**: 
   - `docker logs llama-cpp-chat --tail 50`
   - `docker logs vllm-embed --tail 20`
   - `docker logs shared-litellm --tail 20`

2. **Health Check Endpoints**:
   - Chat model: `curl http://localhost:18800/health`
   - Embeddings: `curl http://localhost:8001/health`
   - LiteLLM router: `curl http://localhost:4444/health`

3. **GPU Memory Verification**:
   - Check VRAM usage: ~22GB for chat + ~1.5GB for embeddings
   - Confirm headroom: ~8.5GB remaining on RTX 5090

## Critical Files to Monitor

| File/Location | Purpose |
|---------------|---------|
| `c:\code\shared-infra\docker-compose.vllm.yml` | Container orchestration |
| `c:\code\shared-infra\litellm\config.yaml` | Model routing configuration |
| `c:\code\zero\workspace\llm-models\` | Shared model storage directory |
| `c:\code\ADA\backend\infrastructure\llm_router.py` | ADA's LLM client |
| `c:\code\zero\.env` | Zero's endpoint configuration |
| `c:\code\Legion\.env` | Legion's endpoint configuration |

## Success Criteria

1. **Model Download**: `Huihui-Qwen3.6-35B-A3B-abliterated-Q4_K_M.gguf` exists in shared location
2. **Container Health**: `llama-cpp-chat` container running without restart loops
3. **Multi-Project Access**: All three projects can successfully make chat completions
4. **Log Verification**: Clean startup logs with no errors
5. **VRAM Efficiency**: Single model instance serving all projects (no duplication)

## Post-Completion Verification

Run these commands to confirm success:

```bash
# Check container status
docker-compose -f c:\code\shared-infra\docker-compose.vllm.yml ps

# Test model access
curl http://localhost:18800/v1/models

# Verify chat completion
curl -X POST http://localhost:18800/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model": "qwen3-chat", "messages": [{"role": "user", "content": "Hello"}], "max_tokens": 50}'

# Check VRAM usage
nvidia-smi
```