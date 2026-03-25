# Multi-Agent System Implementation Details

This document describes the multi-agent architecture implementation for the Research Assistant.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         USER REQUEST                                     │
│                    "Research topic X"                                    │
└─────────────────────────────┬───────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                      ORCHESTRATOR                                        │
│  ┌────────────────────────────────────────────────────────────────┐     │
│  │ • Creates research session with unique ID                       │     │
│  │ • Manages pipeline state transitions                            │     │
│  │ • Coordinates agent execution order                             │     │
│  │ • Handles errors and saves intermediate results                 │     │
│  │ • Aggregates final output                                       │     │
│  └────────────────────────────────────────────────────────────────┘     │
└─────────────────────────────┬───────────────────────────────────────────┘
                              │
          ┌───────────────────┼───────────────────┐
          │                   │                   │
          ▼                   ▼                   ▼
┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
│   RESEARCHER    │  │    ANALYZER     │  │     WRITER      │
│                 │  │                 │  │                 │
│ Input:          │  │ Input:          │  │ Input:          │
│  ResearchTopic  │  │  ResearchResults│  │  AnalysisResult │
│                 │  │                 │  │                 │
│ Output:         │  │ Output:         │  │ Output:         │
│  ResearchResults│  │  AnalysisResult │  │  ResearchReport │
│                 │  │                 │  │                 │
│ Tasks:          │  │ Tasks:          │  │ Tasks:          │
│ • Query gen     │  │ • Synthesize    │  │ • Structure     │
│ • Web search    │  │ • Extract       │  │ • Format        │
│ • Deduplicate   │  │   insights      │  │ • Generate      │
│                 │  │ • Find patterns │  │   sections      │
└─────────────────┘  └─────────────────┘  └─────────────────┘
```

## Pattern: Supervisor/Orchestrator

This implementation uses the **Supervisor/Orchestrator** pattern from the multi-agent patterns skill.

### Why This Pattern?

| Consideration | Decision |
|---------------|----------|
| Clear task decomposition | Research naturally splits into gather → analyze → write |
| Sequential dependencies | Each stage depends on the previous stage's output |
| Need for coordination | Single orchestrator manages state and error handling |
| Human oversight | Easy to inspect intermediate results at each stage |

### Alternative Patterns Considered

- **Peer-to-Peer/Swarm**: Not suitable - tasks are sequential, not parallel exploration
- **Hierarchical**: Overkill - no need for strategy/planning/execution layers

## Context Isolation

Each agent operates in an isolated context window to prevent context degradation:

```typescript
// Each agent has its own LLM client instance
export class ResearcherAgent extends BaseAgent<ResearchTopic, ResearchResults> {
  constructor(llmConfig?: LLMConfig, verbose?: boolean) {
    super(createAgentConfig('researcher', llmConfig, verbose));
    // Fresh LLM client with clean context
  }
}
```

### Isolation Mechanism: Instruction Passing

The orchestrator passes only the necessary data between agents:

```
Orchestrator → Researcher: ResearchTopic (minimal input)
Researcher → Orchestrator: ResearchResults (findings only)
Orchestrator → Analyzer: ResearchResults (no researcher context)
Analyzer → Orchestrator: AnalysisResult (insights only)
Orchestrator → Writer: AnalysisResult (no analyzer context)
```

**Benefits:**
- Each agent starts with a clean context window
- No accumulated context from previous agents
- Prevents "lost in the middle" effect
- Each agent can use full context capacity for its task

## Pipeline Architecture

### Stage Flow

```
┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐
│ RESEARCH │ -> │ ANALYZE  │ -> │  WRITE   │ -> │ COMPLETE │
└──────────┘    └──────────┘    └──────────┘    └──────────┘
     │               │               │               │
     ▼               ▼               ▼               ▼
research.json   analysis.json   report.json    report.md
```

### File System State Machine

Following the pipeline architecture guidance, intermediate results are persisted:

```
research-output/
└── research-20241229-abc123/
    ├── research.json    # Stage 1 output
    ├── analysis.json    # Stage 2 output
    ├── report.json      # Stage 3 structured output
    └── report.md        # Final formatted report
```

**Benefits:**
- Natural idempotency (file existence gates execution)
- Easy debugging (all state is human-readable)
- Trivial caching (files persist across runs)
- Recovery from failures (resume from last completed stage)

## Agent Implementation Details

### Base Agent Pattern

All agents extend a common base class:

```typescript
export abstract class BaseAgent<TInput, TOutput> {
  protected llm: LLMClient;
  protected config: AgentConfig;
  
  async execute(input: TInput): Promise<AgentResult<TOutput>> {
    // Timing, error handling, logging
    const result = await this.process(input);
    return { success: true, data: result, executionTime };
  }
  
  protected abstract process(input: TInput): Promise<TOutput>;
  protected abstract getSystemPrompt(): string;
}
```

### Researcher Agent

**Role:** Gather information from multiple sources

**Process:**
1. Generate 5-8 targeted search queries from the topic
2. Execute searches and collect results
3. Deduplicate and score by relevance

**Key Prompts:**
- `SEARCH_QUERY_PROMPT`: Generates search queries
- `SEARCH_RESULTS_PROMPT`: Simulates web search results

**Output Schema:**
```typescript
interface ResearchResults {
  topic: string;
  searchQueries: string[];
  findings: SearchResult[];
  rawContent: string[];
  timestamp: string;
}
```

### Analyzer Agent

**Role:** Synthesize and extract insights from research

**Process:**
1. Format findings for analysis
2. Extract key insights with confidence levels
3. Identify themes, gaps, and contradictions
4. Generate recommendations

**Output Schema:**
```typescript
interface AnalysisResult {
  topic: string;
  summary: string;
  keyInsights: Insight[];
  themes: string[];
  gaps: string[];
  contradictions?: string[];
  recommendations: string[];
  timestamp: string;
}
```

### Writer Agent

**Role:** Generate comprehensive reports

**Process:**
1. Build structured prompt from analysis
2. Generate report sections
3. Format as markdown

**Output Schema:**
```typescript
interface ResearchReport {
  title: string;
  topic: string;
  executiveSummary: string;
  sections: ReportSection[];
  conclusion: string;
  references: string[];
  generatedAt: string;
  format: ReportFormat;
}
```

## Orchestrator Implementation

### Session Management

```typescript
interface ResearchSession {
  id: string;                    // Unique session ID
  topic: ResearchTopic;          // Original request
  status: PipelineStatus;        // Current pipeline state
  research?: ResearchResults;    // Stage 1 output
  analysis?: AnalysisResult;     // Stage 2 output
  report?: ResearchReport;       // Stage 3 output
  startedAt: string;
  completedAt?: string;
}
```

### Pipeline Execution

```typescript
async research(topic: ResearchTopic): Promise<ResearchSession> {
  // Stage 1: Research
  this.updateStatus(session, 'research');
  const researchResult = await this.researcher.execute(topic);
  session.research = researchResult.data;
  
  // Stage 2: Analysis  
  this.updateStatus(session, 'analyze');
  const analysisResult = await this.analyzer.execute(session.research);
  session.analysis = analysisResult.data;
  
  // Stage 3: Writing
  this.updateStatus(session, 'write');
  const reportResult = await this.writer.execute({
    analysis: session.analysis,
    format,
  });
  session.report = reportResult.data;
  
  return session;
}
```

### Error Handling

Each stage wraps execution in try/catch:
- Logs errors with context
- Preserves partial results
- Allows debugging of failed stages

## Token Economics

Based on the multi-agent patterns guidance, this system has higher token usage than single-agent:

| Component | Est. Tokens per Research |
|-----------|-------------------------|
| Researcher (query gen) | ~500 |
| Researcher (5 searches) | ~2,500 |
| Analyzer | ~3,000 |
| Writer | ~4,000 |
| **Total** | **~10,000** |

**Mitigation Strategies:**
- Configurable research depth (quick/standard/deep)
- Caching intermediate results
- Option to skip stages with cached data

## Failure Modes & Mitigations

### 1. Orchestrator Bottleneck
**Risk:** Orchestrator context fills with agent outputs
**Mitigation:** Only pass structured data objects, not raw responses

### 2. Error Propagation
**Risk:** Researcher failure cascades to Analyzer and Writer
**Mitigation:** Validate each stage output before proceeding

### 3. Coordination Overhead
**Risk:** Multiple LLM calls increase latency
**Mitigation:** Sequential execution is appropriate here; parallel would risk inconsistent results

## Extension Points

### Adding New Agents

1. Extend `BaseAgent<TInput, TOutput>`
2. Implement `process()` and `getSystemPrompt()`
3. Add to orchestrator pipeline

### Adding New Report Formats

1. Add format to `ReportFormat` type
2. Update `REPORT_PROMPT` with format instructions
3. Add formatter method to `WriterAgent`

### Integrating Real Search APIs

Replace simulated search in `ResearcherAgent.executeSearch()`:

```typescript
private async executeSearch(query: string): Promise<SearchResult[]> {
  // Replace with actual API call:
  // - Brave Search API
  // - Google Custom Search
  // - Bing Web Search API
  const response = await fetch(`https://api.search.brave.com/...`);
  return this.parseResults(response);
}
```

## References

- [Multi-Agent Patterns Skill](.cursor/rules/multiagent-patterns-skill.mdc)
- [Project Development Skill](.cursor/rules/project-development-skill.mdc)
- [LangGraph Multi-Agent Patterns](https://langchain-ai.github.io/langgraph/)
