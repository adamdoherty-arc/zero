# TikTok Shop Manager

Comprehensive TikTok Shop management skill with product research, content creation, and a persistent learning loop. Use when asked to find products, create TikTok content, manage the shop pipeline, or help sell on TikTok.

## Startup Protocol

**Every time this skill is invoked:**
1. Read `workspace/tiktok/learnings.json` to load past learnings
2. Apply relevant learnings to current recommendations
3. After any significant action (product approved, script generated, strategy chosen), update the learnings file

## Available MCP Tools

| Tool | What it does |
|------|-------------|
| `tiktok_list_products` | List/filter products (status, niche, score, search) |
| `tiktok_get_product` | Get full product details |
| `tiktok_add_product` | Add product + auto-research |
| `tiktok_import_url` | Import from Amazon/AliExpress/TikTok Shop URL |
| `tiktok_research_product` | Deep research (SearXNG + LLM scoring) |
| `tiktok_enrich_product` | Add images, supplier info, success rating |
| `tiktok_approve_products` | Approve products for content creation |
| `tiktok_reject_products` | Reject with reason |
| `tiktok_generate_script` | Generate faceless video script from template |
| `tiktok_generate_ideas` | AI-generated content ideas (hooks, scripts, captions) |
| `tiktok_get_stats` | Pipeline statistics |
| `tiktok_run_pipeline` | Run pipeline (full/research_only/content_only/performance_only) |
| `tiktok_pipeline_status` | Pipeline health + scheduler status |

## Workflow: First Product Launch

Guide the user from zero to their first TikTok Shop sale. Execute steps in order, adapting based on learnings.

### Step 1: Niche Discovery

Use WebSearch to research currently trending TikTok Shop niches:
- Search: "trending TikTok Shop products [current month] [current year]"
- Search: "best selling TikTok Shop niches [current year]"
- Search: "TikTok Shop winning products [current month]"
- Cross-reference with TikTok Creative Center trends

**Evaluate each niche using this scorecard (all 1-10):**
- **Demand signal**: Are people actively searching for and buying this?
- **Competition density**: How many sellers already exist? (lower = better)
- **Content-ability**: Can you make engaging faceless videos about it?
- **Margin health**: Is the profit margin sustainable after fees?
- **Trend trajectory**: Is it growing, peaking, or declining?

Present top 3 niches with scores. Let the user choose or recommend one.

**Record in learnings:** `niches.<niche_name> = { score, date_evaluated, reasoning }`

### Step 2: Product Selection

For the chosen niche, find 5-10 candidate products:

1. Use `tiktok_run_pipeline` with mode `research_only` to discover products
2. Use `tiktok_list_products` to see what was found
3. For top candidates, use `tiktok_research_product` for deep analysis
4. Use `tiktok_enrich_product` to get images, suppliers, success rating

**Validate each product with the Profit Calculator:**
```
Revenue per unit = Sale price
Platform fee     = Revenue x 8% (TikTok Shop commission)
Affiliate fee    = Revenue x 10-20% (if using affiliates to promote)
Product cost     = Supplier price + shipping to customer
Ad spend         = $0.50-2.00 per unit (if running TikTok ads)
---
Net profit       = Revenue - platform fee - affiliate fee - product cost - ad spend
Margin %         = Net profit / Revenue x 100
```

**Rules for product approval:**
- Minimum 30% margin after all fees (affiliate model)
- Minimum 40% margin after all fees (dropship model)
- Opportunity score >= 65 in the backend
- Must have available supplier (AliExpress, CJ, Alibaba, or TikTok Shop)
- Must be "content-able" (can you imagine 10+ video angles?)

Use `tiktok_approve_products` for winners, `tiktok_reject_products` with reason for losers.

**Record in learnings:** `products.<product_id> = { name, niche, approved, reason, margin_estimate }`

### Step 3: Content Creation

For each approved product, generate content using this protocol:

**A. Research viral hooks first:**
- WebSearch: "[product name] TikTok viral video"
- WebSearch: "[niche] TikTok hook ideas that work"
- Study what makes the top videos successful

**B. Generate content using the backend:**
1. `tiktok_generate_ideas` for the product (gets AI-generated hooks, scripts, captions)
2. `tiktok_generate_script` with the best template for the product type:

**Template selection guide:**
| Product type | Best template | Why |
|-------------|--------------|-----|
| Beauty/skincare | `before_after` | Transformation sells |
| Kitchen gadgets | `problem_solution` | Show the frustration, then the fix |
| Tech/gadgets | `voiceover_broll` | Explain features with visuals |
| Fashion | `text_overlay_showcase` | Quick, aesthetic, trend-driven |
| Any (educational) | `listicle_topn` | "5 reasons" always works |

**C. Enhance the generated script with viral patterns:**

**Hook formulas (first 3 seconds):**
1. **Curiosity gap**: "I can't believe this actually works..."
2. **Controversy**: "Everyone's buying this wrong..."
3. **POV**: "POV: you finally found the product that actually..."
4. **Social proof**: "This has 50,000+ five star reviews..."
5. **Urgency**: "This is going viral and it's about to sell out..."
6. **Challenge**: "I tried the TikTok famous [product] so you don't have to..."

**Caption formula:**
```
[Hook line that creates curiosity] + [1-2 benefit sentences] + [CTA]

CTA options:
- "Link in bio" (for TikTok Shop link)
- "Comment LINK and I'll send it to you"
- "Follow for more [niche] finds"
- "Save this for later"
```

**Hashtag strategy (8-12 total):**
- 2-3 trending hashtags (#tiktokmademebuyit, #tiktokshopfinds, #viralproducts)
- 2-3 niche hashtags (#skincareroutine, #kitchengadgets, #techfinds)
- 2-3 product-specific (#ledmask, #portableblender)
- 1-2 engagement hashtags (#fyp, #foryou)

**Record in learnings:** `hooks.<hook_type> = { used_count, product, template }`

### Step 4: Setup Guidance

Guide the user through what they need to start selling:

**For Affiliate Model:**
1. Apply for TikTok Shop affiliate program (shop.tiktok.com)
2. Browse marketplace for products to promote
3. Generate affiliate links for chosen products
4. Create content and post with links

**For Dropship Model:**
1. Register as TikTok Shop seller (seller-us.tiktok.com for US)
2. Complete identity verification
3. Set up shipping templates (sourcing from CJ/AliExpress)
4. List products with optimized titles and images
5. Connect payment method

**Content posting schedule (optimal times for US audience):**
- Post 1-3x daily minimum
- Best times: 7-9 AM, 12-1 PM, 7-10 PM EST
- Consistency matters more than perfection
- First 30 days: post daily, test different hooks/templates

### Step 5: Launch & Iterate

After the first product is set up:
1. Post first 3 videos using different templates/hooks
2. Wait 48-72 hours for initial data
3. Check which hook style got the most views
4. Double down on what works, drop what doesn't
5. Use `tiktok_run_pipeline` with `performance_only` to sync metrics

## Feedback Loop Protocol

The learning system persists across sessions. **Always follow this protocol.**

### On Every Invocation
```
1. Read workspace/tiktok/learnings.json
2. Check lessons[] for relevant past learnings
3. Check niches{} for previously evaluated niches
4. Check products{} for past product decisions
5. Apply relevant context to current recommendations
```

### After Significant Actions
Update the learnings file with:

**After product research:**
```json
{
  "products": {
    "<product_id>": {
      "name": "...",
      "niche": "...",
      "approved": true/false,
      "reason": "...",
      "margin_estimate": 0.35,
      "date": "2026-03-21"
    }
  }
}
```

**After content creation:**
```json
{
  "hooks": {
    "<hook_type>": {
      "used_count": 1,
      "products": ["product_name"],
      "template": "before_after"
    }
  },
  "templates": {
    "<template_type>": {
      "used_count": 1,
      "niches": ["beauty"],
      "effectiveness_notes": "..."
    }
  }
}
```

**After learning something new:**
```json
{
  "lessons": [
    {
      "date": "2026-03-21",
      "category": "research|content|strategy|mistake",
      "lesson": "Short description of what was learned",
      "context": "What triggered this learning"
    }
  ]
}
```

**After tracking metrics:**
```json
{
  "metrics": {
    "products_researched": 5,
    "products_approved": 2,
    "scripts_generated": 4,
    "content_published": 1
  }
}
```

### Learning Application Rules
- If a niche was previously evaluated with score < 5, skip it unless user specifically asks
- If a hook type has been used 3+ times without success, suggest alternatives
- If a template has effectiveness_notes indicating poor performance, de-prioritize it
- Always reference past lessons when they're relevant to the current decision
- Track what margin estimates were vs actual — calibrate over time

## Decision Framework

### When to Approve a Product
- Opportunity score >= 65
- Clear margin >= 30% (affiliate) or 40% (dropship)
- At least 3 content angles come to mind
- Supplier is verified and in stock
- No learnings flag it as a bad category

### When to Reject a Product
- Opportunity score < 50
- Margin below minimum thresholds
- Saturated market (too many sellers with same product)
- Hard to make content about (boring, no visual appeal)
- Past learnings show this category/type fails

### When to Pivot
- First 5 videos get < 500 views each
- No sales after 2 weeks of consistent posting
- Supplier issues (out of stock, shipping delays)
- Better opportunity found in learnings or new research

## Common Mistakes to Avoid

1. **Picking products based on personal preference** instead of data — always validate with scores
2. **Too many products at once** — start with 1-2, master them, then expand
3. **Generic hooks** like "Check this out" — use the hook formulas above
4. **Ignoring trends** — TikTok moves fast, what works this week may not next week
5. **No CTA** — every video needs a clear call to action
6. **Wrong hashtags** — don't use only viral hashtags, mix in niche-specific ones
7. **Inconsistent posting** — the algorithm rewards consistency over quality
8. **Not testing templates** — try all 5 templates for your first product to find what resonates
9. **Skipping enrichment** — always run `tiktok_enrich_product` to get images and supplier data
10. **Not recording learnings** — the feedback loop only works if you feed it data
