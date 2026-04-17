# Skill Creator

A guide for creating new Claude Code skills and iteratively improving them.

At a high level, the process of creating a skill goes like this:

- Decide what you want the skill to do and roughly how it should do it
- Write a draft of the skill
- Create a few test prompts and run them to verify the skill works
- Evaluate the results both qualitatively and quantitatively
- Rewrite the skill based on feedback
- Repeat until satisfied
- Expand the test set and try again at larger scale

Your job when using this skill is to figure out where the user is in this process and then jump in and help them progress through these stages.

## Communicating with the User

Pay attention to context cues to understand how to phrase your communication. Some users are highly technical, others are new to coding. In the default case:

- "evaluation" and "benchmark" are borderline, but OK
- For "JSON" and "assertion" you want to see cues from the user that they know what those things are before using them without explaining them

It's OK to briefly explain terms if in doubt.

## Creating a Skill

### Capture Intent

Start by understanding the user's intent. The current conversation might already contain a workflow the user wants to capture. If so, extract answers from the conversation history first -- the tools used, the sequence of steps, corrections the user made, input/output formats observed.

1. What should this skill enable Claude to do?
2. When should this skill trigger? (what user phrases/contexts)
3. What's the expected output format?
4. Should we set up test cases to verify the skill works?

### Interview and Research

Proactively ask questions about edge cases, input/output formats, example files, success criteria, and dependencies. Wait to write test prompts until you've got this part ironed out.

### Write the Skill Markdown

Based on the user interview, fill in these components:

- **Title**: Clear descriptive name
- **Description**: When to trigger, what it does. This is the primary triggering mechanism -- include both what the skill does AND specific contexts for when to use it.
- **The rest of the skill content**

### Skill Writing Guide

#### Anatomy of a Claude Code Skill

A Claude Code skill is a markdown file at `.claude/skills/` with:
- A descriptive title
- Clear description of what the skill does
- Domain knowledge and patterns
- No YAML frontmatter with metadata

#### Writing Patterns

Prefer using the imperative form in instructions.

**Defining output formats:**
```markdown
## Report structure
ALWAYS use this exact template:
# [Title]
## Executive summary
## Key findings
## Recommendations
```

**Examples pattern:**
```markdown
## Commit message format
**Example 1:**
Input: Added user authentication with JWT tokens
Output: feat(auth): implement JWT-based authentication
```

### Writing Style

Try to explain to the model why things are important in lieu of heavy-handed MUSTs. Use theory of mind and try to make the skill general and not super-narrow to specific examples. Start by writing a draft and then look at it with fresh eyes and improve it.

### Test Cases

After writing the skill draft, come up with 2-3 realistic test prompts -- the kind of thing a real user would actually say. Share them with the user for confirmation, then run them.

## Improving the Skill

### How to Think About Improvements

1. **Generalize from the feedback.** Skills are used across many different prompts. Rather than put in fiddly overfitty changes or oppressively constrictive MUSTs, if there's a stubborn issue, try branching out and using different metaphors or recommending different patterns.

2. **Keep the prompt lean.** Remove things that aren't pulling their weight. Read the transcripts, not just final outputs -- if the skill is making the model waste time doing unproductive things, get rid of those parts.

3. **Explain the why.** Try hard to explain the reasoning behind everything. Today's LLMs are smart. They have good theory of mind and when given a good harness can go beyond rote instructions. If you find yourself writing ALWAYS or NEVER in all caps, that's a yellow flag -- reframe and explain the reasoning so the model understands why the thing is important.

4. **Look for repeated work across test cases.** If all test runs independently wrote similar helper scripts or took the same multi-step approach, that's a signal the skill should bundle that script. Write it once, put it in the skill, and reference it.

### The Iteration Loop

After improving the skill:

1. Apply your improvements
2. Rerun all test cases
3. Evaluate the outputs
4. Wait for user review
5. Read feedback, improve again, repeat

Keep going until:
- The user says they're happy
- The feedback is all positive
- You're not making meaningful progress

## Core Loop Summary

1. Figure out what the skill is about
2. Draft or edit the skill
3. Run test prompts against the skill
4. Evaluate the outputs with the user
5. Repeat until satisfied
6. Finalize the skill
