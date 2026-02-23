# TikTok Shop 24/7 Automation Engine — Setup Guide

## Overview

Zero's TikTok Shop automation engine continuously:
1. **Researches** trending products via SearXNG (4x daily)
2. **Scores** products using heuristic + LLM analysis
3. **Auto-approves** high-confidence products (score >= 85)
4. **Generates** faceless video scripts using 5 template types
5. **Queues** video generation via AIContentTools
6. **Tracks** performance and runs improvement cycles

## Prerequisites

### 1. TikTok Seller Account
- Create a TikTok Shop seller account at [seller-us.tiktok.com](https://seller-us.tiktok.com)
- Choose your business model:
  - **Affiliate**: Promote others' products for commission (lowest barrier)
  - **Dropship**: List products, supplier handles fulfillment
  - **Own products**: Full control over inventory and shipping

### 2. TikTok for Business
- Create a TikTok Business account linked to your seller account
- Enable TikTok Shopping features
- Set up your product catalog in TikTok Seller Center

### 3. AIContentTools (Video Generation)
- AIContentTools runs at `C:\code\AIContentTools` on port 8085
- Handles actual video rendering using AI models
- Zero generates scripts/prompts and sends requests to AIContentTools
- Ensure AIContentTools Docker container is running

### 4. Zero Configuration

Add to your `.env` or environment:
```
# Already configured in Zero's config.py
AICONTENTTOOLS_API_URL=http://localhost:8085
```

## Architecture

```
Zero (Research + Orchestration)
  |
  |-- SearXNG (Product Discovery)
  |-- Ollama/LangChain (LLM Scoring + Script Generation)
  |-- PostgreSQL (Product DB, Scripts, Queue)
  |
  +--> AIContentTools (Video Generation)
         |-- Text-to-Video
         |-- Image Generation
         |-- Audio/Voiceover
```

## How It Works

### Research Pipeline
Zero searches for trending products every 4 hours:
- Queries SearXNG for: trending TikTok products, viral items, high-commission affiliates
- Scores each product on: trend momentum, competition level, margin potential
- Products scoring >= 85 are auto-approved; others go to your approval queue

### Approval Workflow
1. Check the **Approval Queue** tab in TikTok Shop page
2. Review product details, LLM analysis, and scores
3. Batch approve or reject with optional reason
4. Approved products enter the content pipeline

### Faceless Video Templates
5 templates designed for TikTok without showing your face:

| Template | Duration | Style |
|----------|----------|-------|
| Voiceover + B-Roll | 30s | AI narration over product footage |
| Text Overlay Showcase | 15s | Captions + product images, no voice |
| Before/After | 20s | Problem vs solution split screen |
| Listicle Top-N | 30s | "Top 5 reasons..." countdown |
| Problem/Solution | 25s | Hook with pain point, product solution |

### Content Generation Flow
1. Script generated via LangChain (hook, body, CTA, overlays, voiceover)
2. Script sent to AIContentTools for video rendering
3. Zero polls for completion every 15 minutes
4. Completed videos ready for TikTok upload

## Scheduled Jobs

| Job | Frequency | What It Does |
|-----|-----------|--------------|
| Continuous Research | Every 4 hours | Product discovery pipeline |
| Niche Deep Dive | Daily 2 PM | Deep research into top niches |
| Approval Reminder | 9 AM & 5 PM | Discord notification for pending reviews |
| Auto Content Pipeline | Every 6 hours | Generate scripts for approved products |
| Generation Check | Every 15 min | Poll AIContentTools for completed videos |
| Performance Sync | Every 3 hours | Sync metrics + improvement cycle |
| Pipeline Health | Every 2 hours | Alert on failures, retry stuck jobs |
| Weekly Report | Sunday 10 AM | Full performance report to Discord |

## Dashboard Pages

- **TikTok Shop** (`/tiktok-shop`): Research, approval queue, pipeline controls
- **TikTok Catalog** (`/tiktok-catalog`): Product catalog with content status

## Running the Pipeline Manually

### Via API
```bash
# Full pipeline (research -> score -> approve -> content -> generate -> track)
curl -X POST http://localhost:18792/api/tiktok-shop/pipeline/run?mode=full

# Research only
curl -X POST http://localhost:18792/api/tiktok-shop/pipeline/run?mode=research_only

# Content only (for already approved products)
curl -X POST http://localhost:18792/api/tiktok-shop/pipeline/run?mode=content_only
```

### Via Dashboard
Go to TikTok Shop > Pipeline tab > click "Full Pipeline"

### Via Chat
Tell Zero: "run the tiktok pipeline" or "research tiktok products"

## Troubleshooting

- **No products discovered**: Check SearXNG is running (`docker ps | grep searxng`)
- **LLM analysis empty**: Verify Ollama is running with a model loaded
- **Scripts not generating**: Check LangChain adapter config in settings
- **Videos stuck in queue**: Verify AIContentTools is running on port 8085
- **Pipeline errors**: Check `docker logs zero-api` for tracebacks
