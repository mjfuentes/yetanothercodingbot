# Research Documents

Research documents for implementation tasks.

## Workflow

**1. Research Agent** (Code Analysis)
- Spawned by orchestrator for feature research
- Tools: Read, Glob, Grep (no WebSearch)
- Analyzes existing code extensively
- Compares approaches using training knowledge (up to Jan 2025)
- Returns comprehensive proposal as text

**2. General-Purpose Agent** (Online Research - Optional)
- If current web documentation needed
- Orchestrator spawns for WebSearch/WebFetch
- Finds latest docs, comparisons, tutorials
- Returns findings to orchestrator

**3. Orchestrator** (Document Creation)
- Receives research from agent(s)
- Combines code analysis + online research (if any)
- Saves to `research/{task_id}_research.md`
- Provides task ID to code agent

**4. Code Agent** (Implementation)
- Reads `research/{task_id}_research.md` first
- Follows recommendations and code templates
- References research in commits

## Structure

- Each document named: `{task_id}_research.md`
- Task ID format: `{type}-{brief-name}`
  - Examples: `feature-voice`, `library-websockets`, `api-stripe`, `refactor-routing`

## Document Template

```markdown
# Research: [Feature Name]

**Task ID**: {task_id}
**Date**: YYYY-MM-DD
**Sources**: Code Analysis + Training Knowledge [+ Online Research]

---

## Executive Summary
[2-3 sentences with clear recommendation]

## Current Implementation Analysis
### Relevant Files
- `file.py:123` - Description

### Integration Points
[Where feature connects]

## Approach Comparison
| Criteria | Option A | Option B | Option C |
|----------|----------|----------|----------|
| ... | ... | ... | ... |

**Recommendation**: ✅ Option X - [Reasoning]

## Implementation Plan
1. Step 1 (X min)
2. Step 2 (X min)
...

**Total**: ~X hours

## Code Templates
```python
# Implementation following existing patterns
```

## Security Considerations
- [ ] Checks...

## Testing Strategy
- Unit tests
- Integration tests
- Manual testing

## References
- Code: `file.py:line`
- Training knowledge: Library v[version]
- Online (if applicable): [URLs]
```

## Example

See WebSocket research from testing:
- Task ID: `feature-websocket-support`
- Analyzed: `monitoring_server.py` SSE implementation
- Compared: Flask-SocketIO vs alternatives
- Recommendation: Flask-SocketIO with reasoning
- Included: Full code templates, 9-12hr estimate

## Best Practices

**Research Agent**:
- ✅ Deep code analysis (file:line refs)
- ✅ Compare 2-3 approaches
- ✅ Code templates from existing patterns
- ✅ Realistic time estimates
- ✅ Note if online research would help

**Orchestrator**:
- ✅ Save research to this folder
- ✅ Pass task ID to code agent
- ✅ Spawn general-purpose agent for online research if needed

**Code Agent**:
- ✅ Read research FIRST
- ✅ Follow recommendations
- ✅ Use code templates
- ✅ Reference research in commits

---

**Purpose**: Separate research from implementation for better decisions and consistent patterns.
