"""
Story Template Service.

Manages reusable carousel templates for character content.
10 pre-built templates covering different storytelling approaches.
"""

import secrets
from functools import lru_cache
from typing import List, Optional, Dict, Any

import structlog
from sqlalchemy import select, update

from app.db.models import StoryTemplateModel
from app.infrastructure.database import get_session
from app.models.character_content import StoryTemplate, StoryTemplateCreate

logger = structlog.get_logger()


# 10 pre-built story templates
SEED_TEMPLATES = [
    {
        "name": "Secrets Revealed",
        "template_type": "secrets_revealed",
        "description": "Numbered list of shocking facts about a character that most people don't know",
        "slide_structure": [
            {"slide": 1, "role": "hook", "format": "X Things They Don't Tell You About {name}..."},
            {"slide": 2, "role": "fact", "format": "1. [Surprising fact with context]"},
            {"slide": 3, "role": "fact", "format": "2. [Escalating reveal]"},
            {"slide": 4, "role": "fact", "format": "3. [Deeper secret]"},
            {"slide": 5, "role": "fact", "format": "4. [Mind-blowing fact]"},
            {"slide": 6, "role": "cta", "format": "Follow for more [universe] secrets 🔥"},
        ],
        "prompt_template": """Create a 6-slide carousel about {name} from {universe} using the "Secrets Revealed" format.

Character facts: {facts}
Research data: {research_summary}

Rules:
- Slide 1: Hook that creates curiosity gap. Start with a number (e.g., "5 Things They Don't Tell You About {name}...")
- Slides 2-5: Numbered facts that ESCALATE in shock value. Each fact should be 1-2 sentences max.
- Slide 6: Call-to-action encouraging follows
- Use short, punchy sentences. Max 20 words per fact.
- Each fact must be verifiable and sourced from the research data.
- Write in second person ("You probably didn't know...")
- NEVER use em dashes, markdown asterisks (*text* or **text**), or formatting markup. Plain text only.

Return JSON:
{{"hook_text": "...", "slides": [{{"slide_num": 1, "text": "...", "image_query": "..."}}], "caption": "...", "hashtags": ["..."], "music_mood": "mysterious"}}""",
        "example_hook": "5 Things They Don't Tell You About Loki...",
        "suitable_angles": ["hidden_truths", "dark_facts", "power_secrets", "easter_eggs"],
        "suitable_universes": ["marvel", "dc", "star_wars", "lotr", "harry_potter", "anime", "gaming", "tv", "film"],
    },
    {
        "name": "Hidden Connection",
        "template_type": "hidden_connection",
        "description": "Reveals a surprising connection between two characters that most people missed",
        "slide_structure": [
            {"slide": 1, "role": "hook", "format": "{name} and {name2} are connected in a way nobody noticed..."},
            {"slide": 2, "role": "setup", "format": "[Establish Character A's situation]"},
            {"slide": 3, "role": "connection", "format": "[The hidden link between them]"},
            {"slide": 4, "role": "evidence", "format": "[Proof/evidence from canon]"},
            {"slide": 5, "role": "reveal", "format": "[The mind-blowing implication]"},
            {"slide": 6, "role": "cta", "format": "Did you catch this? Follow for more 🤯"},
        ],
        "prompt_template": """Create a 6-slide carousel about the hidden connection between {name} and {secondary_names}.

Character A facts: {facts}
Character B facts: {secondary_facts}
Relationships: {relationships}

Rules:
- Slide 1: Hook that teases the connection without revealing it
- Slide 2: Set up Character A's relevant backstory
- Slide 3: Reveal the connection point
- Slide 4: Provide evidence from the source material
- Slide 5: Explain why this changes everything
- Slide 6: CTA with engagement question
- Each slide max 25 words. Punchy and dramatic.
- NEVER use em dashes, markdown asterisks (*text* or **text**), or formatting markup. Plain text only.

Return JSON:
{{"hook_text": "...", "slides": [{{"slide_num": 1, "text": "...", "image_query": "..."}}], "caption": "...", "hashtags": ["..."], "music_mood": "mysterious"}}""",
        "example_hook": "Tony Stark and Black Panther are connected in a way nobody noticed...",
        "suitable_angles": ["crossover_connections", "hidden_truths", "fan_theories"],
        "suitable_universes": ["marvel", "dc", "star_wars", "lotr", "harry_potter"],
    },
    {
        "name": "Dark Origin",
        "template_type": "dark_origin",
        "description": "The darker, untold origin story that goes beyond the surface narrative",
        "slide_structure": [
            {"slide": 1, "role": "hook", "format": "The REAL origin of {name} is darker than you think..."},
            {"slide": 2, "role": "surface", "format": "[The commonly known version]"},
            {"slide": 3, "role": "twist", "format": "But here's what they don't show you..."},
            {"slide": 4, "role": "dark_truth", "format": "[The dark reality]"},
            {"slide": 5, "role": "evidence", "format": "[Supporting evidence]"},
            {"slide": 6, "role": "impact", "format": "[Why this changes how you see them]"},
        ],
        "prompt_template": """Create a 6-slide carousel about the dark origin of {name} from {universe}.

Character facts: {facts}
Research: {research_summary}

Rules:
- Slide 1: Dramatic hook promising dark revelations
- Slide 2: Briefly state what everyone thinks they know
- Slide 3: Transition. "But here's what they don't show you..."
- Slide 4-5: The darker truth with evidence
- Slide 6: Emotional impact statement
- Tone: Dark, dramatic, revelatory. Short sentences.
- NEVER use em dashes, markdown asterisks (*text* or **text**), or formatting markup. Plain text only.

Return JSON:
{{"hook_text": "...", "slides": [{{"slide_num": 1, "text": "...", "image_query": "..."}}], "caption": "...", "hashtags": ["..."], "music_mood": "dark"}}""",
        "example_hook": "The REAL origin of Batman is darker than you think...",
        "suitable_angles": ["dark_facts", "origin_story", "hidden_truths"],
        "suitable_universes": ["marvel", "dc", "star_wars", "lotr", "harry_potter", "anime", "gaming"],
    },
    {
        "name": "Fan Theory Deep Dive",
        "template_type": "fan_theory_deep_dive",
        "description": "Explores a compelling fan theory with evidence for and against",
        "slide_structure": [
            {"slide": 1, "role": "hook", "format": "This fan theory about {name} changes EVERYTHING..."},
            {"slide": 2, "role": "theory", "format": "[State the theory clearly]"},
            {"slide": 3, "role": "evidence1", "format": "Evidence #1: [Strong supporting point]"},
            {"slide": 4, "role": "evidence2", "format": "Evidence #2: [Another supporting point]"},
            {"slide": 5, "role": "implication", "format": "If true, this means... [mind-blowing consequence]"},
            {"slide": 6, "role": "cta", "format": "Do you believe it? Comment below 👇"},
        ],
        "prompt_template": """Create a 6-slide carousel exploring a fan theory about {name} from {universe}.

Character facts: {facts}
Fan theories from research: {fan_theories}

Rules:
- Slide 1: Hook that promises a paradigm shift
- Slide 2: State the theory in one clear sentence
- Slides 3-4: Two pieces of evidence (from canon, interviews, or patterns)
- Slide 5: The implication if the theory is true
- Slide 6: Engagement CTA asking for opinions
- Tone: Excited, conspiratorial, "connecting the dots"
- NEVER use em dashes, markdown asterisks (*text* or **text**), or formatting markup. Plain text only.

Return JSON:
{{"hook_text": "...", "slides": [{{"slide_num": 1, "text": "...", "image_query": "..."}}], "caption": "...", "hashtags": ["..."], "music_mood": "mysterious"}}""",
        "example_hook": "This fan theory about Doctor Strange changes EVERYTHING...",
        "suitable_angles": ["fan_theories", "hidden_truths", "what_if"],
        "suitable_universes": ["marvel", "dc", "star_wars", "lotr", "harry_potter", "anime"],
    },
    {
        "name": "Actor Behind the Role",
        "template_type": "actor_behind_role",
        "description": "Behind-the-scenes facts about the actor who plays the character",
        "slide_structure": [
            {"slide": 1, "role": "hook", "format": "{actor} almost WASN'T {name}..."},
            {"slide": 2, "role": "casting", "format": "[Casting fact or near-miss]"},
            {"slide": 3, "role": "preparation", "format": "[How they prepared for the role]"},
            {"slide": 4, "role": "onset", "format": "[On-set story or improvisation]"},
            {"slide": 5, "role": "personal", "format": "[Personal connection to the character]"},
            {"slide": 6, "role": "legacy", "format": "[Impact on their career/legacy]"},
        ],
        "prompt_template": """Create a 6-slide carousel about the actor behind {name} from {universe}.

Character facts: {facts}
Behind-the-scenes research: {behind_scenes}

Rules:
- Slide 1: Hook with casting surprise or near-miss
- Slide 2: How they got/almost lost the role
- Slide 3: Their dedication to the role
- Slide 4: A memorable on-set moment
- Slide 5: Their personal relationship with the character
- Slide 6: Career impact
- Keep factual. Reference real events and interviews.
- NEVER use em dashes, markdown asterisks (*text* or **text**), or formatting markup. Plain text only.

Return JSON:
{{"hook_text": "...", "slides": [{{"slide_num": 1, "text": "...", "image_query": "..."}}], "caption": "...", "hashtags": ["..."], "music_mood": "emotional"}}""",
        "example_hook": "Robert Downey Jr. almost WASN'T Iron Man...",
        "suitable_angles": ["behind_scenes", "actor_secrets"],
        "suitable_universes": ["marvel", "dc", "star_wars", "lotr", "harry_potter", "tv", "film"],
    },
    {
        "name": "Versus Breakdown",
        "template_type": "versus_breakdown",
        "description": "Side-by-side comparison of two characters with a definitive verdict",
        "slide_structure": [
            {"slide": 1, "role": "hook", "format": "{name} vs {name2}: Here's who ACTUALLY wins..."},
            {"slide": 2, "role": "fighter1", "format": "[Character A's key strengths]"},
            {"slide": 3, "role": "fighter2", "format": "[Character B's key strengths]"},
            {"slide": 4, "role": "analysis", "format": "[Key advantage that tips the scale]"},
            {"slide": 5, "role": "verdict", "format": "Winner: [character] because..."},
            {"slide": 6, "role": "cta", "format": "Agree or disagree? Comment below 🔥"},
        ],
        "prompt_template": """Create a 6-slide versus breakdown carousel: {name} vs {secondary_names}.

Character A facts: {facts}
Character B facts: {secondary_facts}

Rules:
- Slide 1: Hook with the matchup
- Slide 2: Character A's 3 biggest strengths (bullet points)
- Slide 3: Character B's 3 biggest strengths (bullet points)
- Slide 4: The decisive factor
- Slide 5: Clear winner with reasoning
- Slide 6: Engagement question
- Be definitive. Don't say "it depends." Pick a winner.
- NEVER use em dashes, markdown asterisks (*text* or **text**), or formatting markup. Plain text only.

Return JSON:
{{"hook_text": "...", "slides": [{{"slide_num": 1, "text": "...", "image_query": "..."}}], "caption": "...", "hashtags": ["..."], "music_mood": "epic"}}""",
        "example_hook": "Thor vs Superman: Here's who ACTUALLY wins...",
        "suitable_angles": ["vs_comparison", "power_secrets"],
        "suitable_universes": ["marvel", "dc", "star_wars", "lotr", "harry_potter", "anime", "gaming"],
    },
    {
        "name": "Timeline Tragedy",
        "template_type": "timeline_tragedy",
        "description": "Chronological look at a character's suffering and hardships",
        "slide_structure": [
            {"slide": 1, "role": "hook", "format": "The complete timeline of {name}'s suffering..."},
            {"slide": 2, "role": "event1", "format": "[First major tragedy]"},
            {"slide": 3, "role": "event2", "format": "[Second tragedy that made it worse]"},
            {"slide": 4, "role": "event3", "format": "[The breaking point]"},
            {"slide": 5, "role": "event4", "format": "[The most devastating moment]"},
            {"slide": 6, "role": "aftermath", "format": "[Where they ended up / emotional reflection]"},
        ],
        "prompt_template": """Create a 6-slide timeline of tragedy for {name} from {universe}.

Character facts: {facts}
Research: {research_summary}

Rules:
- Slide 1: Hook promising an emotional journey
- Slides 2-5: Chronological tragic events, ESCALATING in impact
- Slide 6: Emotional reflection or where they ended up
- Each event should be 1-2 sentences, hitting hard emotionally
- Tone: Empathetic, dramatic, building tension
- NEVER use em dashes, markdown asterisks (*text* or **text**), or formatting markup. Plain text only.

Return JSON:
{{"hook_text": "...", "slides": [{{"slide_num": 1, "text": "...", "image_query": "..."}}], "caption": "...", "hashtags": ["..."], "music_mood": "emotional"}}""",
        "example_hook": "The complete timeline of Wanda's suffering...",
        "suitable_angles": ["character_evolution", "dark_facts", "origin_story"],
        "suitable_universes": ["marvel", "dc", "star_wars", "lotr", "harry_potter", "anime"],
    },
    {
        "name": "What They Changed",
        "template_type": "what_they_changed",
        "description": "Comics/books vs movie/show adaptation differences",
        "slide_structure": [
            {"slide": 1, "role": "hook", "format": "The comics version of {name} is COMPLETELY different..."},
            {"slide": 2, "role": "original", "format": "[Original version key traits]"},
            {"slide": 3, "role": "adaptation", "format": "[Adapted version changes]"},
            {"slide": 4, "role": "difference", "format": "[The biggest change they made]"},
            {"slide": 5, "role": "why", "format": "[Why they changed it]"},
            {"slide": 6, "role": "opinion", "format": "Which version do you prefer? 🤔"},
        ],
        "prompt_template": """Create a 6-slide carousel about how {name} was changed from {universe} source material to screen.

Character facts: {facts}
Research: {research_summary}

Rules:
- Slide 1: Hook about the drastic differences
- Slide 2: Original comics/book version (key traits, powers, personality)
- Slide 3: Movie/show adaptation (what changed)
- Slide 4: The BIGGEST single change
- Slide 5: Why producers made that change
- Slide 6: Poll-style CTA asking preference
- Reference specific storylines and issues when possible
- NEVER use em dashes, markdown asterisks (*text* or **text**), or formatting markup. Plain text only.

Return JSON:
{{"hook_text": "...", "slides": [{{"slide_num": 1, "text": "...", "image_query": "..."}}], "caption": "...", "hashtags": ["..."], "music_mood": "dramatic"}}""",
        "example_hook": "The comics version of Thanos is COMPLETELY different...",
        "suitable_angles": ["hidden_truths", "behind_scenes", "character_evolution"],
        "suitable_universes": ["marvel", "dc", "star_wars", "lotr", "harry_potter"],
    },
    {
        "name": "Real Life Inspiration",
        "template_type": "real_life_inspiration",
        "description": "The real-world person or event that inspired a fictional character",
        "slide_structure": [
            {"slide": 1, "role": "hook", "format": "{name} was based on a REAL person..."},
            {"slide": 2, "role": "character", "format": "[The fictional character everyone knows]"},
            {"slide": 3, "role": "real_person", "format": "[The real person/event]"},
            {"slide": 4, "role": "parallels", "format": "[Key similarities]"},
            {"slide": 5, "role": "differences", "format": "[What fiction added or changed]"},
            {"slide": 6, "role": "reflection", "format": "[Why this makes the character more meaningful]"},
        ],
        "prompt_template": """Create a 6-slide carousel about the real-life inspiration behind {name} from {universe}.

Character facts: {facts}
Research: {research_summary}

Rules:
- Slide 1: Hook revealing real-world inspiration
- Slide 2: Brief character intro (for context)
- Slide 3: The real person, event, or concept
- Slide 4: Striking parallels
- Slide 5: What was fictionalized
- Slide 6: Why this adds depth
- Must be factual. Cite creator interviews or documented sources.
- NEVER use em dashes, markdown asterisks (*text* or **text**), or formatting markup. Plain text only.

Return JSON:
{{"hook_text": "...", "slides": [{{"slide_num": 1, "text": "...", "image_query": "..."}}], "caption": "...", "hashtags": ["..."], "music_mood": "emotional"}}""",
        "example_hook": "Iron Man was based on a REAL person...",
        "suitable_angles": ["behind_scenes", "hidden_truths", "actor_secrets"],
        "suitable_universes": ["marvel", "dc", "star_wars", "lotr", "harry_potter", "tv", "film"],
    },
    {
        "name": "Deleted Scenes",
        "template_type": "deleted_scenes",
        "description": "Cut content that would have changed the story completely",
        "slide_structure": [
            {"slide": 1, "role": "hook", "format": "These deleted scenes of {name} would have changed EVERYTHING..."},
            {"slide": 2, "role": "scene1", "format": "[Deleted scene #1 description]"},
            {"slide": 3, "role": "impact1", "format": "[How it would have changed the story]"},
            {"slide": 4, "role": "scene2", "format": "[Deleted scene #2 description]"},
            {"slide": 5, "role": "impact2", "format": "[The alternate timeline this creates]"},
            {"slide": 6, "role": "cta", "format": "Should they have kept these scenes? 🎬"},
        ],
        "prompt_template": """Create a 6-slide carousel about deleted scenes involving {name} from {universe}.

Character facts: {facts}
Behind-the-scenes research: {behind_scenes}

Rules:
- Slide 1: Hook about cut content
- Slide 2: First deleted scene or cut storyline
- Slide 3: How including it would have changed the story
- Slide 4: Second deleted scene
- Slide 5: The alternate version this creates
- Slide 6: CTA asking if they should have kept the scenes
- Reference real deleted scenes, director's cuts, or confirmed cut content
- NEVER use em dashes, markdown asterisks (*text* or **text**), or formatting markup. Plain text only.

Return JSON:
{{"hook_text": "...", "slides": [{{"slide_num": 1, "text": "...", "image_query": "..."}}], "caption": "...", "hashtags": ["..."], "music_mood": "dramatic"}}""",
        "example_hook": "These deleted scenes of Spider-Man would have changed EVERYTHING...",
        "suitable_angles": ["behind_scenes", "hidden_truths", "what_if"],
        "suitable_universes": ["marvel", "dc", "star_wars", "lotr", "harry_potter", "tv", "film"],
    },
    # --- Templates 11-15: Content Variety Expansion ---
    {
        "name": "Storyline Recap",
        "template_type": "storyline_recap",
        "description": "Narrates a specific comic/show storyline as a dramatic story, not fact lists",
        "slide_structure": [
            {"slide": 1, "role": "hook", "format": "When {name} [dramatic event]..."},
            {"slide": 2, "role": "setup", "format": "[Set the scene: what led to this moment]"},
            {"slide": 3, "role": "escalation", "format": "[The situation gets worse]"},
            {"slide": 4, "role": "climax", "format": "[The defining moment / battle / decision]"},
            {"slide": 5, "role": "aftermath", "format": "[The consequences nobody expected]"},
            {"slide": 6, "role": "cta", "format": "[Emotional reflection + follow CTA]"},
        ],
        "prompt_template": """Create a 6-slide carousel that tells a specific STORYLINE about {name} from {universe}.

Character facts: {facts}
Research data: {research_summary}

IMPORTANT: This is NOT a fact list. Tell a STORY. Each slide should advance the PLOT like chapters in a book.

Rules:
- Slide 1: Hook that drops you into the action. Start with "When [name] [dramatic verb]..." or "[name] [dramatic past tense verb]..."
- Slide 2: Set the scene. What was happening before? What pushed the character to this point?
- Slide 3: Escalation. Things get worse, stakes get higher, the conflict intensifies.
- Slide 4: Climax. The defining battle, decision, or revelation. This is the peak tension moment.
- Slide 5: Aftermath. What happened next? What were the consequences? How did it change things?
- Slide 6: Emotional reflection or cliffhanger CTA.
- Each slide max 25 words. Punchy, dramatic, present tense where possible.
- Pick ONE specific storyline from comics, shows, or films. Do not mix multiple storylines.
- NEVER use em dashes, markdown asterisks (*text* or **text**), or formatting markup. Plain text only.

Return JSON:
{{"hook_text": "...", "slides": [{{"slide_num": 1, "text": "...", "image_query": "..."}}], "caption": "...", "hashtags": ["..."], "music_mood": "epic"}}""",
        "example_hook": "When Peter Parker became the Hulk and killed Captain America...",
        "suitable_angles": ["storyline_recap", "what_if", "origin_story", "character_evolution", "dark_facts"],
        "suitable_universes": ["marvel", "dc", "star_wars", "lotr", "harry_potter", "anime", "gaming", "tv", "film"],
    },
    {
        "name": "Power Ranking",
        "template_type": "power_ranking",
        "description": "Multi-character countdown ranking (Top 5) with one character per slide",
        "slide_structure": [
            {"slide": 1, "role": "hook", "format": "Top 5 [category] in [universe]..."},
            {"slide": 2, "role": "rank5", "format": "#5: [Character name + why they rank here]"},
            {"slide": 3, "role": "rank4", "format": "#4: [Character name + why they rank here]"},
            {"slide": 4, "role": "rank3", "format": "#3: [Character name + why they rank here]"},
            {"slide": 5, "role": "rank2", "format": "#2: [Character name + why they rank here]"},
            {"slide": 6, "role": "rank1", "format": "#1: [Character name + the big reveal]"},
        ],
        "prompt_template": """Create a 6-slide "Top 5" ranking carousel about {ranking_theme} in the {universe} universe.

Characters to consider: {character_names}
Character facts: {facts}

Rules:
- Slide 1: Hook announcing the ranking. Make it bold and opinionated.
- Slides 2-6: Count DOWN from #5 to #1. Each slide features ONE different character.
- Each ranking entry: Character name + 1-2 sentences explaining WHY they rank here.
- #1 should be the most surprising or controversial pick to drive comments.
- Use image_query to find each ranked character specifically.
- NEVER use em dashes, markdown asterisks (*text* or **text**), or formatting markup. Plain text only.

Return JSON:
{{"hook_text": "...", "slides": [{{"slide_num": 1, "text": "...", "image_query": "..."}}], "caption": "...", "hashtags": ["..."], "music_mood": "epic"}}""",
        "example_hook": "Top 5 Heroes Who Became Villains...",
        "suitable_angles": ["power_ranking", "power_secrets", "vs_comparison", "controversial_takes"],
        "suitable_universes": ["marvel", "dc", "star_wars", "lotr", "harry_potter", "anime", "gaming"],
    },
    {
        "name": "Versus Battle",
        "template_type": "versus_battle",
        "description": "Argumentative fight analysis that picks a definitive winner with scenario",
        "slide_structure": [
            {"slide": 1, "role": "hook", "format": "[Character A] vs [Character B]: Only one walks away."},
            {"slide": 2, "role": "fighter_a", "format": "[Character A's arsenal, feats, and biggest advantage]"},
            {"slide": 3, "role": "fighter_b", "format": "[Character B's arsenal, feats, and biggest advantage]"},
            {"slide": 4, "role": "key_factor", "format": "[The ONE factor that decides this fight]"},
            {"slide": 5, "role": "fight_scenario", "format": "[How the actual fight plays out, blow by blow]"},
            {"slide": 6, "role": "verdict", "format": "Winner: [Name]. Here's why it's not even close."},
        ],
        "prompt_template": """Create a 6-slide versus battle carousel: {name} vs {secondary_names}.

Character A facts: {facts}
Character B facts: {secondary_facts}

Rules:
- Slide 1: Bold hook with both names. Make it sound like a fight promo.
- Slide 2: Character A's best feats, powers, and strategic advantage. Be specific (cite storylines).
- Slide 3: Character B's best feats, powers, and strategic advantage. Be specific.
- Slide 4: The ONE deciding factor. What tips the scale?
- Slide 5: Write the fight. 3-4 sentences describing how it plays out, like sports commentary.
- Slide 6: Declare a winner definitively. No "it depends." Be controversial if needed.
- Take a STRONG stance. The more opinionated, the more comments.
- NEVER use em dashes, markdown asterisks (*text* or **text**), or formatting markup. Plain text only.

Return JSON:
{{"hook_text": "...", "slides": [{{"slide_num": 1, "text": "...", "image_query": "..."}}], "caption": "...", "hashtags": ["..."], "music_mood": "epic"}}""",
        "example_hook": "Punisher vs Batman: Only one walks away.",
        "suitable_angles": ["vs_comparison", "power_secrets", "controversial_takes"],
        "suitable_universes": ["marvel", "dc", "star_wars", "lotr", "harry_potter", "anime", "gaming"],
    },
    {
        "name": "Timeline Story",
        "template_type": "timeline_story",
        "description": "Chronological transformation arc showing how a character changed over time",
        "slide_structure": [
            {"slide": 1, "role": "hook", "format": "{name}: From [origin] to [current state]"},
            {"slide": 2, "role": "early_era", "format": "[Who they were at the beginning]"},
            {"slide": 3, "role": "turning_point", "format": "[The event that changed everything]"},
            {"slide": 4, "role": "transformation", "format": "[How they changed as a result]"},
            {"slide": 5, "role": "current_state", "format": "[Who they became / where they are now]"},
            {"slide": 6, "role": "whats_next", "format": "[What's coming next / speculation + CTA]"},
        ],
        "prompt_template": """Create a 6-slide timeline story showing {name}'s transformation across {universe}.

Character facts: {facts}
Research: {research_summary}

Rules:
- Slide 1: Hook that frames the transformation. Use "From [A] to [B]" format.
- Slide 2: Early era. Who were they before everything changed? Paint the picture.
- Slide 3: The turning point. ONE specific event, issue, or episode that changed their trajectory.
- Slide 4: The transformation. How did they change? Powers, personality, allegiance, goals.
- Slide 5: Current state. Where are they now? What did they become?
- Slide 6: What's next + engagement CTA.
- Each slide is a TIME PERIOD, not a random fact. Show the PROGRESSION.
- NEVER use em dashes, markdown asterisks (*text* or **text**), or formatting markup. Plain text only.

Return JSON:
{{"hook_text": "...", "slides": [{{"slide_num": 1, "text": "...", "image_query": "..."}}], "caption": "...", "hashtags": ["..."], "music_mood": "dramatic"}}""",
        "example_hook": "Scarlet Witch: From background Avenger to the most dangerous being in the multiverse",
        "suitable_angles": ["character_evolution", "timeline_deep_dive", "origin_story", "storyline_recap"],
        "suitable_universes": ["marvel", "dc", "star_wars", "lotr", "harry_potter", "anime", "gaming", "tv", "film"],
    },
    {
        "name": "Hot Take",
        "template_type": "hot_take",
        "description": "Opinion-driven argumentative content designed to drive comments and debate",
        "slide_structure": [
            {"slide": 1, "role": "hook", "format": "[Bold controversial claim about character]."},
            {"slide": 2, "role": "common_belief", "format": "[What most people think / the popular opinion]"},
            {"slide": 3, "role": "counter", "format": "[Why the popular opinion is wrong]"},
            {"slide": 4, "role": "evidence", "format": "[Specific evidence supporting the hot take]"},
            {"slide": 5, "role": "objection", "format": "[Addressing the biggest counter-argument]"},
            {"slide": 6, "role": "stance", "format": "[Final stance + engagement bait]"},
        ],
        "prompt_template": """Create a 6-slide "hot take" carousel with a controversial opinion about {name} from {universe}.

Character facts: {facts}
Research: {research_summary}

Rules:
- Slide 1: The hot take. A bold, one-sentence claim that will make fans argue. No question marks. State it as fact.
- Slide 2: The popular opinion you're going against. "Most people think..."
- Slide 3: Why the popular opinion is wrong. Be specific, cite evidence.
- Slide 4: Your strongest piece of evidence. Reference a specific comic issue, episode, or movie scene.
- Slide 5: Acknowledge the biggest counter-argument, then dismiss it.
- Slide 6: Double down on your stance. End with "Change my mind" or "Fight me in the comments."
- The take should be defensible but controversial. Not trolling, but genuinely debatable.
- NEVER use em dashes, markdown asterisks (*text* or **text**), or formatting markup. Plain text only.

Return JSON:
{{"hook_text": "...", "slides": [{{"slide_num": 1, "text": "...", "image_query": "..."}}], "caption": "...", "hashtags": ["..."], "music_mood": "hype"}}""",
        "example_hook": "Batman is the most overrated superhero in DC. And it's not even close.",
        "suitable_angles": ["controversial_takes", "fan_theories", "vs_comparison", "power_secrets"],
        "suitable_universes": ["marvel", "dc", "star_wars", "lotr", "harry_potter", "anime", "gaming", "tv", "film"],
    },
]


class StoryTemplateService:
    """Manages carousel story templates."""

    async def seed_templates(self) -> List[StoryTemplate]:
        """Pre-populate the 15 story templates."""
        seeded = []
        async with get_session() as session:
            for tmpl in SEED_TEMPLATES:
                # Check if already exists
                result = await session.execute(
                    select(StoryTemplateModel).where(
                        StoryTemplateModel.template_type == tmpl["template_type"]
                    )
                )
                if result.scalar_one_or_none():
                    continue

                row = StoryTemplateModel(
                    id=f"st-{secrets.token_hex(12)}",
                    name=tmpl["name"],
                    template_type=tmpl["template_type"],
                    description=tmpl["description"],
                    slide_structure=tmpl["slide_structure"],
                    prompt_template=tmpl["prompt_template"],
                    example_hook=tmpl["example_hook"],
                    suitable_angles=tmpl["suitable_angles"],
                    suitable_universes=tmpl["suitable_universes"],
                )
                session.add(row)
                seeded.append(self._row_to_model(row))

        logger.info("story_templates_seeded", count=len(seeded))
        return seeded

    async def list_templates(
        self, active_only: bool = True
    ) -> List[StoryTemplate]:
        """List all story templates."""
        async with get_session() as session:
            q = select(StoryTemplateModel).order_by(StoryTemplateModel.times_used.desc())
            if active_only:
                q = q.where(StoryTemplateModel.is_active == True)
            result = await session.execute(q)
            rows = result.scalars().all()
        return [self._row_to_model(r) for r in rows]

    async def get_template(self, template_type: str) -> Optional[StoryTemplate]:
        """Get a specific template by type."""
        async with get_session() as session:
            result = await session.execute(
                select(StoryTemplateModel).where(
                    StoryTemplateModel.template_type == template_type
                )
            )
            row = result.scalar_one_or_none()
        return self._row_to_model(row) if row else None

    async def get_template_for_angle(
        self, angle: str, universe: str
    ) -> Optional[StoryTemplate]:
        """Find the best template for a given angle and universe."""
        templates = await self.list_templates()
        best = None
        best_score = -1

        for tmpl in templates:
            score = 0
            if angle in tmpl.suitable_angles:
                score += 10
            if universe in tmpl.suitable_universes:
                score += 5
            # Prefer less-used templates for variety
            score -= tmpl.times_used * 0.1
            if score > best_score:
                best_score = score
                best = tmpl

        return best

    async def increment_usage(self, template_type: str) -> None:
        """Increment usage counter for a template."""
        async with get_session() as session:
            await session.execute(
                update(StoryTemplateModel)
                .where(StoryTemplateModel.template_type == template_type)
                .values(times_used=StoryTemplateModel.times_used + 1)
            )

    async def update_score(self, template_type: str, score: float) -> None:
        """Update the average score for a template."""
        async with get_session() as session:
            result = await session.execute(
                select(StoryTemplateModel).where(
                    StoryTemplateModel.template_type == template_type
                )
            )
            row = result.scalar_one_or_none()
            if row:
                # Exponential moving average
                if row.avg_score == 0.0:
                    row.avg_score = score
                else:
                    row.avg_score = row.avg_score * 0.7 + score * 0.3

    async def create_template(self, data: StoryTemplateCreate) -> StoryTemplate:
        """Create a custom template."""
        row = StoryTemplateModel(
            id=f"st-{secrets.token_hex(12)}",
            name=data.name,
            template_type=data.template_type,
            description=data.description,
            slide_structure=data.slide_structure,
            prompt_template=data.prompt_template,
            example_hook=data.example_hook,
            suitable_angles=data.suitable_angles,
            suitable_universes=data.suitable_universes,
        )
        async with get_session() as session:
            session.add(row)
            await session.flush()
        return self._row_to_model(row)

    async def get_template_leaderboard(self) -> Dict[str, Any]:
        """Get template performance leaderboard."""
        templates = await self.list_templates()
        ranked = sorted(templates, key=lambda t: (t.times_used, t.avg_score), reverse=True)
        return {
            "templates": [
                {
                    "name": t.name,
                    "template_type": t.template_type,
                    "times_used": t.times_used,
                    "avg_score": t.avg_score,
                }
                for t in ranked
            ]
        }

    def _row_to_model(self, row: StoryTemplateModel) -> StoryTemplate:
        """Convert ORM row to Pydantic model."""
        return StoryTemplate(
            id=row.id,
            name=row.name,
            template_type=row.template_type,
            description=row.description,
            slide_structure=row.slide_structure or [],
            prompt_template=row.prompt_template,
            example_hook=row.example_hook,
            suitable_angles=row.suitable_angles or [],
            suitable_universes=row.suitable_universes or [],
            times_used=row.times_used or 0,
            avg_score=row.avg_score or 0.0,
            is_active=row.is_active if row.is_active is not None else True,
            created_at=row.created_at,
        )


@lru_cache()
def get_story_template_service() -> StoryTemplateService:
    """Get cached story template service instance."""
    return StoryTemplateService()
