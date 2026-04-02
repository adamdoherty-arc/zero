# Personal AI Ecosystem — Architecture

## 1. System Overview

```mermaid
graph TB
    subgraph Physical["Physical Layer"]
        Reachy["Reachy Mini Lite<br/>USB-C · REST :8000<br/>Camera · Mic · Speaker"]
    end

    subgraph Orchestration["Meta-Orchestration"]
        Legion["Legion :8005/3005<br/>FastAPI + React<br/>80+ Agents · Celery<br/>Autonomous Sprints"]
    end

    subgraph Core["Core Intelligence"]
        Zero["Zero :18792<br/>FastAPI + React<br/>LangGraph Engine<br/>Central AI Brain"]
        Ada["Ada :8003/5420<br/>FastAPI + React<br/>18+ Finance Agents<br/>LangGraph Workflows"]
    end

    subgraph Messaging["Messaging Channels"]
        Discord["Discord"]
        WhatsApp["WhatsApp"]
        Slack["Slack"]
    end

    subgraph LLM["LLM Providers"]
        Ollama["Ollama :11434<br/>Local Inference"]
        Gemini["Google Gemini"]
        Kimi["Kimi"]
        OpenRouter["OpenRouter"]
        HuggingFace["HuggingFace"]
    end

    subgraph Data["Data Stores"]
        PG_Zero["PostgreSQL :5433<br/>+ pgvector<br/>Zero"]
        PG_Ada["PostgreSQL :5432<br/>Ada"]
        PG_Legion["PostgreSQL :5434<br/>Legion"]
        Qdrant_Ada["Qdrant<br/>Ada Vectors"]
        Qdrant_Legion["Qdrant<br/>Legion Vectors"]
        Neo4j["Neo4j<br/>Ada Knowledge Graph"]
        Redis_Ada["Redis<br/>Ada Cache"]
        Redis_Legion["Redis<br/>Legion Queue"]
    end

    subgraph Finance["Brokerages"]
        Robinhood["Robinhood"]
        Alpaca["Alpaca"]
        Tradier["Tradier"]
    end

    subgraph Services["External Services"]
        Gmail["Gmail"]
        GCal["Google Calendar"]
        TikTok["TikTok Commerce"]
        PredMarkets["Prediction Markets"]
    end

    %% Legion orchestrates everything
    Legion -->|manages| Zero
    Legion -->|manages| Ada
    Legion -->|Kimi planning| Kimi
    Legion -->|Ollama execution| Ollama
    Legion --- PG_Legion
    Legion --- Qdrant_Legion
    Legion --- Redis_Legion

    %% Zero connections
    Zero -->|Claude Agent SDK| Discord
    Zero -->|Claude Agent SDK| WhatsApp
    Zero -->|Claude Agent SDK| Slack
    Zero -->|multi-provider| Ollama
    Zero -->|multi-provider| Gemini
    Zero -->|multi-provider| Kimi
    Zero -->|multi-provider| OpenRouter
    Zero -->|multi-provider| HuggingFace
    Zero --- PG_Zero
    Zero -->|email| Gmail
    Zero -->|calendar| GCal
    Zero -->|commerce| TikTok
    Zero -->|markets| PredMarkets

    %% Ada connections
    Ada --- PG_Ada
    Ada --- Qdrant_Ada
    Ada --- Neo4j
    Ada --- Redis_Ada
    Ada -->|trades| Robinhood
    Ada -->|trades| Alpaca
    Ada -->|trades| Tradier

    %% Reachy connects to Zero
    Reachy <-->|USB-C + REST| Zero

    %% Cross-system
    Zero <-->|data exchange| Ada

    style Zero fill:#2563eb,color:#fff,stroke:#1d4ed8
    style Ada fill:#059669,color:#fff,stroke:#047857
    style Legion fill:#7c3aed,color:#fff,stroke:#6d28d9
    style Reachy fill:#dc2626,color:#fff,stroke:#b91c1c
```

## 2. Voice Pipeline

```mermaid
sequenceDiagram
    participant Mic as Reachy Mic<br/>4x MEMS + DoA
    participant STT as faster-whisper<br/>STT Engine
    participant LG as Zero LangGraph<br/>Orchestration
    participant LLM as LLM Provider<br/>(Ollama/Gemini/etc)
    participant TTS as Piper TTS<br/>Engine
    participant Spk as Reachy Speaker<br/>5W Output

    Note over Mic,Spk: Voice Interaction Pipeline

    Mic->>STT: Raw audio stream
    Note right of Mic: Direction of Arrival<br/>selects speaker

    STT->>LG: Transcribed text + metadata
    Note right of STT: faster-whisper<br/>local inference

    LG->>LG: Intent classification<br/>& state management

    alt Simple query
        LG->>LLM: Prompt with context
        LLM->>LG: Response text
    else Tool use required
        LG->>LG: Execute tool nodes<br/>(email, calendar, etc.)
        LG->>LLM: Summarize results
        LLM->>LG: Natural language response
    end

    LG->>TTS: Response text
    Note right of TTS: Piper local TTS<br/>low latency

    TTS->>Spk: Audio stream
    Note right of Spk: Plays through<br/>Reachy speaker

    LG-->>Reachy Head: Expression cues
    Note over Reachy Head: Head movement<br/>antenna animation

    participant Reachy Head as Reachy Motors<br/>9 DOF
```

## 3. Data Flow

```mermaid
flowchart LR
    subgraph Inputs["Input Sources"]
        Email["Email / Gmail"]
        Cal["Google Calendar"]
        Chat["Discord / WhatsApp / Slack"]
        Voice["Reachy Microphone"]
        Broker["Brokerage APIs"]
        TikTok["TikTok Shop"]
        Web["Web Research"]
    end

    subgraph Zero["Zero — Central Brain"]
        ZRouter["LangGraph Router"]
        ZKnow["Knowledge Store<br/>pgvector"]
        ZTrans["Transcription<br/>faster-whisper"]
        ZTools["Tool Executor"]
    end

    subgraph Ada["Ada — Finance"]
        AAgents["18+ Specialist Agents"]
        ALearn["Learning Loop"]
        ARAG["RAG Pipeline<br/>Qdrant"]
        AGraph["Knowledge Graph<br/>Neo4j"]
    end

    subgraph Legion["Legion — Orchestrator"]
        LSprint["Sprint Engine"]
        LAgents["80+ Agents"]
        LLearn["Cross-Sprint Learning"]
        LQA["QA Gates"]
    end

    subgraph Outputs["Outputs"]
        Reply["Chat Replies"]
        Trade["Trade Execution"]
        Speak["Voice Response"]
        Move["Robot Movement"]
        Report["Reports & Alerts"]
    end

    %% Inputs to Zero
    Email --> ZRouter
    Cal --> ZRouter
    Chat --> ZRouter
    Voice --> ZTrans --> ZRouter
    TikTok --> ZRouter
    Web --> ZRouter

    %% Zero internal
    ZRouter --> ZTools
    ZRouter <--> ZKnow

    %% Zero to Ada (financial queries)
    ZRouter -->|financial queries| AAgents
    AAgents <--> ARAG
    AAgents <--> AGraph
    AAgents --> ALearn
    ALearn -->|improved strategies| ARAG
    Broker --> AAgents

    %% Legion orchestrates
    LSprint -->|task assignment| ZRouter
    LSprint -->|task assignment| AAgents
    LAgents --> LSprint
    LSprint --> LQA
    LQA -->|pass| LLearn
    LQA -->|fail| LSprint

    %% Outputs
    ZTools --> Reply
    ZTools --> Speak
    ZTools --> Move
    ZTools --> Report
    AAgents --> Trade
    AAgents --> Report

    style Zero fill:#2563eb,color:#fff
    style Ada fill:#059669,color:#fff
    style Legion fill:#7c3aed,color:#fff
```

## 4. Service Dependency Map

```mermaid
graph BT
    subgraph Infrastructure["Shared Infrastructure"]
        Docker["Docker Compose"]
        Ollama["Ollama :11434"]
        PG5432["PostgreSQL :5432"]
        PG5433["PostgreSQL :5433<br/>+ pgvector"]
        PG5434["PostgreSQL :5434"]
        Redis1["Redis (Ada)"]
        Redis2["Redis (Legion)"]
        Qdrant1["Qdrant (Ada)"]
        Qdrant2["Qdrant (Legion)"]
        Neo4j["Neo4j"]
    end

    subgraph External["External APIs"]
        Gemini["Gemini API"]
        KimiAPI["Kimi API"]
        OR["OpenRouter API"]
        HF["HuggingFace API"]
        RH["Robinhood API"]
        ALP["Alpaca API"]
        TRD["Tradier API"]
        GAPI["Google APIs"]
        TTAPI["TikTok API"]
    end

    subgraph Apps["Applications"]
        Zero["Zero :18792"]
        Ada["Ada :8003"]
        Legion["Legion :8005"]
        Reachy["Reachy :8000"]
    end

    %% Zero dependencies
    Zero --> PG5433
    Zero --> Ollama
    Zero --> Gemini
    Zero --> KimiAPI
    Zero --> OR
    Zero --> HF
    Zero --> GAPI
    Zero --> TTAPI
    Zero --> Docker

    %% Ada dependencies
    Ada --> PG5432
    Ada --> Qdrant1
    Ada --> Neo4j
    Ada --> Redis1
    Ada --> Ollama
    Ada --> RH
    Ada --> ALP
    Ada --> TRD
    Ada --> Docker

    %% Legion dependencies
    Legion --> PG5434
    Legion --> Qdrant2
    Legion --> Redis2
    Legion --> Ollama
    Legion --> KimiAPI
    Legion --> Docker

    %% Reachy depends on Zero
    Reachy --> Zero

    %% Cross-app
    Legion -.->|orchestrates| Zero
    Legion -.->|orchestrates| Ada
    Zero -.->|queries| Ada

    style Infrastructure fill:#f59e0b,color:#000
    style Apps fill:#3b82f6,color:#fff
    style External fill:#6b7280,color:#fff
```

## 5. Reachy Integration Architecture

```mermaid
flowchart TB
    subgraph Reachy["Reachy Mini Lite Hardware"]
        Camera["Camera<br/>12MP Wide"]
        Mics["4x MEMS Mics<br/>Direction of Arrival"]
        Speaker["Speaker 5W"]
        Head["6-DOF Head<br/>Pan · Tilt · Roll"]
        Base["1-DOF Base<br/>Rotation"]
        Antennas["2x Antennas<br/>Expressive"]
        SDK["Reachy Python SDK"]
        REST["REST API :8000"]
    end

    subgraph USB["Connection"]
        USBC["USB-C to PC"]
    end

    subgraph Zero["Zero Brain :18792"]
        subgraph Perception["Perception Layer"]
            STT["faster-whisper STT"]
            Vision["Camera Processing"]
            DoA["Speaker Localization"]
        end

        subgraph Cognition["Cognition Layer"]
            LG["LangGraph Engine"]
            LLM["LLM Router"]
            Ctx["Context Manager"]
            KB["Knowledge Base<br/>pgvector"]
        end

        subgraph Action["Action Layer"]
            TTS["Piper TTS"]
            Motion["Motion Planner"]
            Express["Expression Engine"]
        end

        subgraph Integration["Integration Layer"]
            ReachyClient["Reachy Client<br/>SDK Wrapper"]
        end
    end

    %% Hardware to SDK
    Camera --> SDK
    Mics --> SDK
    Speaker --> SDK
    Head --> SDK
    Base --> SDK
    Antennas --> SDK
    SDK <--> REST

    %% USB connection
    REST <-->|USB-C| USBC
    USBC <--> ReachyClient

    %% Perception
    ReachyClient -->|audio stream| STT
    ReachyClient -->|video frames| Vision
    ReachyClient -->|DoA data| DoA

    %% Perception to Cognition
    STT -->|text| LG
    Vision -->|descriptions| LG
    DoA -->|direction| Ctx
    Ctx --> LG
    LG <--> LLM
    LG <--> KB

    %% Cognition to Action
    LG -->|response text| TTS
    LG -->|movement cues| Motion
    LG -->|emotion cues| Express

    %% Action to Hardware
    TTS -->|audio| ReachyClient
    Motion -->|joint targets| ReachyClient
    Express -->|antenna patterns| ReachyClient

    style Reachy fill:#dc2626,color:#fff
    style Zero fill:#2563eb,color:#fff
    style Perception fill:#0891b2,color:#fff
    style Cognition fill:#4f46e5,color:#fff
    style Action fill:#7c3aed,color:#fff
```

## 6. Legion Orchestration Flow

```mermaid
flowchart TB
    Start([New Task / Sprint Trigger])

    subgraph Planning["Planning Phase (Kimi)"]
        Analyze["Analyze Requirements"]
        Decompose["Decompose into Subtasks"]
        Assign["Assign to Target System<br/>Zero · Ada · Legion · FortressOS · AIContentTools"]
        Plan["Generate Sprint Plan"]
    end

    subgraph Execution["Execution Phase (Ollama)"]
        Queue["Task Queue<br/>Celery + Redis"]
        subgraph Agents["Agent Pool (80+)"]
            A1["Code Agents"]
            A2["Test Agents"]
            A3["Research Agents"]
            A4["Review Agents"]
        end
        Execute["Execute Subtasks"]
        Monitor["Progress Monitor"]
    end

    subgraph QA["Quality Assurance"]
        Gate["QA Gate Check"]
        Tests["Automated Tests"]
        Review["Code Review"]
        Decision{Pass?}
    end

    subgraph Learning["Cross-Sprint Learning"]
        Eval["Outcome Evaluation"]
        Store["Store in Qdrant"]
        Update["Update Strategies"]
    end

    subgraph Targets["Managed Systems"]
        Zero["Zero<br/>:18792"]
        Ada["Ada<br/>:8003"]
        Fortress["FortressOS"]
        AICT["AIContentTools"]
        Self["Legion Self"]
    end

    Start --> Analyze
    Analyze --> Decompose
    Decompose --> Assign
    Assign --> Plan

    Plan --> Queue
    Queue --> Agents
    Agents --> Execute
    Execute --> Monitor
    Monitor -->|in progress| Execute

    Monitor -->|complete| Gate
    Gate --> Tests
    Gate --> Review
    Tests --> Decision
    Review --> Decision

    Decision -->|Yes| Eval
    Decision -->|No, retry| Queue

    Eval --> Store
    Store --> Update
    Update -->|improved planning| Analyze

    %% Targets
    Execute -->|deploy / modify| Zero
    Execute -->|deploy / modify| Ada
    Execute -->|deploy / modify| Fortress
    Execute -->|deploy / modify| AICT
    Execute -->|deploy / modify| Self

    style Planning fill:#7c3aed,color:#fff
    style Execution fill:#2563eb,color:#fff
    style QA fill:#f59e0b,color:#000
    style Learning fill:#059669,color:#fff
```
