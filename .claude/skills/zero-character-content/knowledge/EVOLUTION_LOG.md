# Prompt Evolution Log

Tracks prompt mutations, hook performance, and template effectiveness over time.
Inspired by PromptBreeder (Google DeepMind) and OpenAI Self-Evolving Agents.

## Hook Style Performance

| Style | Avg AI Score | Times Used | Trend |
|-------|-------------|------------|-------|
| numbered_list | -- | 0 | baseline |
| story_opener | -- | 0 | baseline |
| hot_take | -- | 0 | baseline |
| question | -- | 0 | baseline |
| comparison | -- | 0 | baseline |
| reveal | -- | 0 | baseline |
| superlative | -- | 0 | baseline |

## Template Performance

| Template | Avg Score | Times Used | Best Hook Style |
|----------|-----------|------------|-----------------|
| secrets_revealed | -- | 6 | -- |
| dark_origin | -- | 3 | -- |
| storyline_recap | -- | 0 | -- |
| power_ranking | -- | 0 | -- |
| versus_battle | -- | 0 | -- |
| timeline_story | -- | 0 | -- |
| hot_take | -- | 0 | -- |

## Prompt Mutations

*No mutations yet. After first batch with scoring, underperforming prompts will be mutated here.*

## Evolution Rules

1. Score threshold for promotion: 75% of graders passing OR avg score >= 7.5
2. Max retry attempts per mutation: 3
3. Always keep rollback version
4. Log reason for each mutation
