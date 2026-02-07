# Microsoft Agent Framework Evaluation

**Date**: 2026-02-07
**Evaluator**: Zero Sprint Intelligence
**Sprint**: S69 - Research Discoveries

## Executive Summary

This evaluation compares Microsoft's AI agent ecosystem (AutoGen, Semantic Kernel, and the newer Agent Framework) against Zero's current LangGraph-based orchestration approach. The goal is to determine if any Microsoft tooling would benefit Zero's architecture.

## Microsoft Agent Ecosystem Overview

### 1. AutoGen (Multi-Agent Conversations)
- **Purpose**: Framework for building multi-agent systems where AI agents converse to solve tasks
- **Architecture**: Agent-to-agent messaging with configurable conversation patterns
- **Key Features**:
  - GroupChat for multi-agent collaboration
  - Code execution agents (sandboxed)
  - Human-in-the-loop patterns
  - Tool/function calling integration
- **Language**: Python (primary), .NET
- **License**: MIT

### 2. Semantic Kernel (AI Orchestration SDK)
- **Purpose**: Lightweight SDK for integrating AI models into applications
- **Architecture**: Plugin-based with planners for multi-step task decomposition
- **Key Features**:
  - Native function/plugin system
  - Handlebars and Stepwise planners
  - Memory connectors (vector stores)
  - Multi-model support (OpenAI, Azure, Hugging Face, Ollama)
- **Language**: C# (primary), Python, Java
- **License**: MIT

### 3. Azure AI Agent Service (Cloud-Managed)
- **Purpose**: Managed agent hosting on Azure
- **Architecture**: Cloud-native, integrates with Azure AI services
- **Key Features**:
  - Managed agent lifecycle
  - Built-in tools (Code Interpreter, File Search, Azure Functions)
  - Enterprise security and compliance
- **Dependency**: Requires Azure subscription
- **Relevance to Zero**: Low (Zero runs locally, no cloud dependency desired)

## Comparison with Current LangGraph Approach

| Dimension | LangGraph (Current) | AutoGen | Semantic Kernel |
|-----------|---------------------|---------|-----------------|
| **Graph-based orchestration** | Native StateGraph | No (conversation-based) | No (planner-based) |
| **State persistence** | Built-in checkpointing (Postgres/Memory) | Manual | Memory connectors |
| **Multi-agent routing** | Conditional edges, supervisor pattern | GroupChat, agent-to-agent | Planner chains |
| **Ollama/local LLM support** | Via langchain-community | Via OpenAI-compatible API | Via connectors |
| **Python-first** | Yes | Yes | C# primary, Python secondary |
| **Streaming** | Native async streaming | Callback-based | Async streaming |
| **Crash recovery** | Checkpoint + replay | No built-in | No built-in |
| **Complexity** | Medium | Medium-High | Low-Medium |
| **Community size** | Large (LangChain ecosystem) | Growing | Large (.NET ecosystem) |
| **Maturity** | Production-ready (1.0+) | v0.4+ (evolving rapidly) | Production-ready |

## Integration Potential with Zero

### What AutoGen Could Add
1. **Multi-agent debate patterns**: Useful if Zero needed agents to critique each other's work (e.g., code review agent vs. implementation agent)
2. **Code execution sandbox**: AutoGen's Docker-based code execution could supplement Zero's sprint task execution
3. **Limitation**: AutoGen's conversation-centric model doesn't map well to Zero's graph-based routing architecture

### What Semantic Kernel Could Add
1. **Plugin ecosystem**: SK's plugin model could provide a cleaner abstraction for Zero's tool functions
2. **Planner**: SK's Stepwise Planner could replace or augment LangGraph for simple sequential workflows
3. **Limitation**: Python support lags behind C#; adding SK would introduce a second orchestration layer alongside LangGraph

### What Neither Adds Over LangGraph
- Zero already has: state persistence (checkpointing), conditional routing, async execution, Ollama integration, tool calling
- LangGraph's graph model is a better fit for Zero's supervisor/router architecture than conversation or planner patterns

## Pros & Cons

### Adopting AutoGen
| Pros | Cons |
|------|------|
| Multi-agent conversations out of the box | Different paradigm from Zero's graph model |
| Active Microsoft investment | API still evolving (breaking changes) |
| Good for code generation tasks | Adds complexity without clear benefit |

### Adopting Semantic Kernel
| Pros | Cons |
|------|------|
| Clean plugin abstraction | Python SDK is secondary to C# |
| Enterprise-grade | Overlaps heavily with LangGraph |
| Good Azure integration | Zero doesn't use Azure |

### Staying with LangGraph
| Pros | Cons |
|------|------|
| Already integrated and working | Single-vendor dependency (LangChain) |
| Best fit for graph-based routing | Less multi-agent conversation support |
| Crash recovery via checkpointing | Steeper learning curve for new patterns |
| Active development, 1.0 stable | |

## Recommendation

**Stay with LangGraph.** The current architecture is well-suited to Zero's needs:

1. **No migration cost**: Zero's orchestration graph, checkpointing, and tool integration already work
2. **Better paradigm fit**: Graph-based routing with conditional edges matches Zero's supervisor pattern better than conversation-based (AutoGen) or planner-based (Semantic Kernel) approaches
3. **Local-first**: LangGraph works natively with Ollama without cloud dependencies
4. **Checkpoint persistence**: Neither AutoGen nor Semantic Kernel offers equivalent crash-recovery capabilities

**Future consideration**: If Zero ever needs multi-agent debate/critique patterns (e.g., separate "planner" and "reviewer" agents that argue), AutoGen's GroupChat could be evaluated as a subcomponent within specific LangGraph nodes, rather than replacing the entire orchestration layer.

## References
- [AutoGen GitHub](https://github.com/microsoft/autogen)
- [Semantic Kernel GitHub](https://github.com/microsoft/semantic-kernel)
- [LangGraph Documentation](https://langchain-ai.github.io/langgraph/)
- [Azure AI Agent Service](https://learn.microsoft.com/en-us/azure/ai-services/agents/)
