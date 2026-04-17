# Intelligence and Research

Comprehensive intelligence gathering skill combining AI news tracking, tech news monitoring, and Hacker News browsing for strategic briefings and research.

## When to Use

Activate this skill when:
- The user wants a tech news summary or briefing
- Scanning AI news from major labs (OpenAI, DeepMind, Anthropic, etc.)
- Monitoring global news from sources like Reuters, RTHK, SCMP
- Browsing Hacker News stories, comments, or search results
- Fetching top stories from TechMeme
- Compiling a strategic intelligence briefing

## Components

### 1. AI News Monitor

Tracks developments from major AI labs and research organizations:
- OpenAI, DeepMind, Anthropic, Meta AI, Mistral, xAI
- Key conferences (NeurIPS, ICML, ICLR)
- Policy and regulation developments

Use web search to scan for recent announcements, papers, and product launches.

### 2. Tech News (TechMeme)

Fetches top stories from TechMeme and summarizes linked articles with social media reactions.

**Workflow:**
1. Fetch TechMeme homepage for top stories
2. For each story, retrieve the linked article
3. Generate a concise summary (2-3 sentences)
4. Check for notable social media reactions
5. Present results in a clean, readable format

**Output includes:**
- Story title and original link
- AI-generated summary
- Social media highlights
- Relevance score based on topic preferences

### 3. Hacker News

Browse Hacker News feeds and story details.

**Available feeds:**
- `top` -- Top stories (default 10, configurable)
- `new` -- Newest stories
- `best` -- Best stories
- `ask` -- Ask HN threads
- `show` -- Show HN projects
- `jobs` -- Job postings

**Story details:**
- Fetch individual story with top comments
- Search stories by keyword

**API:** Uses the official [Hacker News API](https://github.com/HackerNews/API) (no auth required). Base URL: `https://hacker-news.firebaseio.com/v0/`

Key endpoints:
- Top stories: `/v0/topstories.json`
- New stories: `/v0/newstories.json`
- Best stories: `/v0/beststories.json`
- Ask HN: `/v0/askstories.json`
- Show HN: `/v0/showstories.json`
- Jobs: `/v0/jobstories.json`
- Item details: `/v0/item/{id}.json`

### 4. Global News Hub

Monitors geopolitical and global news from:
- Reuters
- RTHK (Radio Television Hong Kong)
- SCMP (South China Morning Post)

## Briefing Format

When compiling a full intelligence briefing, use this structure:

```
# Intelligence Briefing - [Date]

## AI & Technology
- [Top 3-5 developments with brief analysis]

## Tech Industry
- [Top stories from TechMeme/HN with context]

## Global News
- [Key geopolitical developments]

## Analysis & Implications
- [Cross-cutting themes and strategic implications]
```

## Tools Available

- **WebSearch**: For real-time news scanning
- **WebFetch**: For fetching specific article content
- **Zero API briefing**: `get_briefing` for system-integrated briefings
- **Zero API search**: `search_knowledge` for past research notes
