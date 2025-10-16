# Multi-Agent Orchestrator Project Plan

## Project Overview
Build an orchestrator agent using Claude Agent SDK that manages worker agents asynchronously, with real-time status monitoring and non-blocking user interaction.

## Core Architecture

### Components
1. **Orchestrator Agent** (Claude Opus 4)
   - Main interface for user interaction
   - Task delegation and coordination
   - Status aggregation and reporting
   - Job queue management

2. **Worker Agents** (Claude Sonnet 4)
   - Specialized subagents for specific tasks
   - Independent execution contexts
   - Artifact-based output generation

3. **State Management System**
   - Job database (SQLite)
   - Artifact storage (file system + metadata)
   - Status tracking and history

4. **Status Monitor**
   - Background polling service
   - Desktop notifications
   - Progress reporting

## Implementation Phases

### Phase 1: Foundation (Week 1)
**Goal:** Basic orchestrator + single worker agent

**Tasks:**
- [ ] Set up Claude Agent SDK project structure
- [ ] Implement orchestrator agent with basic prompt
- [ ] Create simple worker agent template
- [ ] Build artifact storage system (JSON files + manifest)
- [ ] Implement basic job queue (in-memory)

**Deliverables:**
- Working orchestrator that spawns 1 worker
- Worker writes results to artifact files
- Orchestrator reads and reports results

### Phase 2: State Management (Week 2)
**Goal:** Persistent job tracking and status

**Tasks:**
- [ ] Design job database schema
- [ ] Implement SQLite database layer
- [ ] Add job states: pending, in_progress, completed, failed
- [ ] Build status query system
- [ ] Create job history and logging

**Database Schema:**
```sql
jobs:
  - id (uuid)
  - type (string)
  - status (enum)
  - created_at (timestamp)
  - updated_at (timestamp)
  - input_artifact_id (uuid)
  - output_artifact_id (uuid)
  - worker_agent_id (string)
  - error_message (text)

artifacts:
  - id (uuid)
  - job_id (uuid)
  - type (string: input|output)
  - content_path (string)
  - metadata (json)
  - created_at (timestamp)
```

**Deliverables:**
- Persistent job tracking
- Query status by job ID or filter
- Job history retrieval

### Phase 3: Async Monitoring (Week 3)
**Goal:** Non-blocking status updates

**Tasks:**
- [ ] Build background polling service
- [ ] Implement status change detection
- [ ] Add desktop notification system (via terminal-notifier/notify-send)
- [ ] Create status dashboard (CLI or web)
- [ ] Add "watch" command for live updates

**Monitoring Features:**
- Check job status every 5-10 seconds
- Notify on: completion, failure, stuck >5min
- Display: running count, completed count, failed count
- Show recent logs for each job

**Deliverables:**
- Background monitor process
- Real-time notifications
- Status dashboard

### Phase 4: Multi-Agent Coordination (Week 4)
**Goal:** Multiple parallel workers

**Tasks:**
- [ ] Implement worker agent registry
- [ ] Create specialized agent types (code, research, test, review)
- [ ] Build intelligent task routing
- [ ] Add worker pool management (max 10 concurrent)
- [ ] Implement dependency resolution (job chains)

**Agent Types:**
- **CodeAgent**: Write/modify code
- **ResearchAgent**: Web search, documentation reading
- **TestAgent**: Write and run tests
- **ReviewAgent**: Code review, quality checks

**Deliverables:**
- 4+ specialized worker types
- Parallel execution (up to 10 workers)
- Task routing logic

### Phase 5: Communication & UX (Week 5)
**Goal:** Seamless user interaction

**Tasks:**
- [ ] Design conversational interface
- [ ] Implement natural language task parsing
- [ ] Add status query via natural language ("how's the API work going?")
- [ ] Build result summarization
- [ ] Create interactive prompts for user decisions

**Interaction Patterns:**
```
User: "Build a REST API for user management and write tests"
Orchestrator:
  - Creating 2 jobs: API implementation, test suite
  - Job #1 (CodeAgent): Building REST API...
  - Job #2 (TestAgent): Waiting for Job #1...

User: "What's the status?"
Orchestrator:
  - Job #1: 60% complete, added 3 endpoints
  - Job #2: Queued, starts when Job #1 finishes

[Notification] Job #1 completed! REST API ready.
```

**Deliverables:**
- Natural language interface
- Status queries
- Summarized reporting

## Technical Stack

### Core Dependencies
```json
{
  "claude-agent-sdk": "^1.0.0",
  "sqlite3": "^5.1.0",
  "node-notifier": "^10.0.0",
  "uuid": "^9.0.0",
  "typescript": "^5.0.0"
}
```

### Project Structure
```
agentlab/
├── src/
│   ├── orchestrator/
│   │   ├── agent.ts           # Main orchestrator agent
│   │   ├── parser.ts          # Task parsing logic
│   │   └── router.ts          # Task routing
│   ├── workers/
│   │   ├── base.ts            # Worker agent base class
│   │   ├── code-agent.ts
│   │   ├── research-agent.ts
│   │   ├── test-agent.ts
│   │   └── review-agent.ts
│   ├── state/
│   │   ├── database.ts        # SQLite operations
│   │   ├── artifacts.ts       # Artifact management
│   │   └── queue.ts           # Job queue
│   ├── monitor/
│   │   ├── polling.ts         # Background status checks
│   │   └── notifier.ts        # Desktop notifications
│   └── cli/
│       ├── index.ts           # CLI entry point
│       └── dashboard.ts       # Status dashboard
├── artifacts/                 # Generated artifacts
├── logs/                      # Agent logs
├── agentlab.db               # SQLite database
└── package.json
```

## Success Criteria

### MVP (End of Phase 3)
- [x] Orchestrator spawns workers
- [x] Workers execute tasks independently
- [x] Status persisted and queryable
- [x] Background monitoring with notifications
- [x] User can submit new tasks while workers run

### Full Release (End of Phase 5)
- [x] 4+ specialized agent types
- [x] 10 parallel workers supported
- [x] Natural language task input
- [x] Conversational status queries
- [x] Dependency chains (job A → job B)
- [x] Desktop notifications
- [x] Web/CLI dashboard

## Future Enhancements (Post-Launch)

### Phase 6: Remote Deployment
- Deploy workers on remote machines via MCP
- Distributed job queue (Redis)
- Load balancing across machines

### Phase 7: Advanced Features
- Agent learning from past jobs
- Auto-retry failed jobs
- Cost tracking and optimization
- Agent performance metrics
- Job templates and presets

## Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Context window limits | High | Use artifact references, not full content |
| Worker crashes | Medium | Add health checks, auto-restart |
| Job queue overflow | Medium | Implement max queue size, prioritization |
| Notification spam | Low | Smart batching, user preferences |

## Timeline
- **Phase 1**: Days 1-7
- **Phase 2**: Days 8-14
- **Phase 3**: Days 15-21
- **Phase 4**: Days 22-28
- **Phase 5**: Days 29-35

**Total**: ~5 weeks to full release

## Next Steps
1. Review and approve plan
2. Set up project repository
3. Install Claude Agent SDK
4. Begin Phase 1 implementation
