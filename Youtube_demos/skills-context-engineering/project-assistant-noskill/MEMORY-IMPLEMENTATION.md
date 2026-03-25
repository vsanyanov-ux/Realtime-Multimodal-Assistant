# Memory Implementation Summary

## Overview

The Project Assistant Memory System v2 implements an advanced **multi-tier memory architecture** designed specifically for **long-running conversations (200+ turns)** and **large projects**. The system provides intelligent context management, automatic summarization, and relevance-based retrieval while maintaining a configurable token budget.

---

## Architecture Layers

### Layer 1: Working Memory (Volatile)

The working memory represents the current context window for LLM interaction.

```typescript
interface WorkingMemory {
  systemPrompt: string;
  recentMessages: ConversationMessage[];
  retrievedMemories: RetrievedMemory[];
  activeContext: ContextItem[];
  tokenUsage: TokenBudget;
}
```

**Characteristics:**
- Rebuilt on each turn
- Subject to token budget constraints
- Contains prioritized, most relevant information
- Lost when conversation ends

**Token Budget Management:**
```typescript
interface TokenBudget {
  total: number;           // e.g., 128000 for GPT-4
  systemPrompt: number;    // Reserved for system prompt
  workingMemory: number;   // Reserved for current turn
  retrievedContext: number; // For retrieved memories
  recentMessages: number;   // For conversation history
  used: number;
  available: number;
}
```

---

### Layer 2: Short-Term Memory (Session-Scoped)

Manages recent conversation history with automatic chunking and summarization.

```typescript
interface Conversation {
  id: string;
  projectId: string;
  startedAt: string;
  endedAt?: string;
  status: 'active' | 'paused' | 'ended';
  totalTurns: number;
  chunks: ConversationChunk[];
  recentMessages: ConversationMessage[];  // Last N messages verbatim
  activeFacts: string[];
  milestones: EpisodeMilestone[];
}
```

**Chunking Strategy:**
1. Messages are added to `recentMessages`
2. When `recentMessages` exceeds `maxRecentMessages` (default: 20)
3. Oldest messages are moved to a new `ConversationChunk`
4. Chunk is summarized with key topics extracted
5. Original messages in chunk are preserved but not sent to LLM

```typescript
interface ConversationChunk {
  id: string;
  conversationId: string;
  chunkNumber: number;
  messages: ConversationMessage[];
  summary: string;           // Compressed representation
  keyTopics: string[];       // Extracted keywords
  tokenCount: number;
  createdAt: string;
}
```

**Chunk Compression:**
When chunks exceed `maxChunks`, oldest chunks are merged:
- Original messages are dropped
- Summaries are combined: `"Earlier: {summary1}\n\nThen: {summary2}"`
- Topics are deduplicated

---

### Layer 3: Long-Term Memory (Persistent)

Stores extracted facts, decisions, and knowledge that persists across sessions.

```typescript
interface LongTermMemory extends StoredItem {
  type: LongTermMemoryType;  // fact, decision, preference, entity, procedure, constraint, goal
  content: string;
  category: string;
  tags: string[];
  relationships: MemoryRelationship[];
  validFrom: string;
  validUntil?: string;       // Temporal validity
}
```

**Memory Types:**
| Type | Purpose | Default Importance |
|------|---------|-------------------|
| `fact` | Factual information | 0.5 |
| `decision` | Choices made | 0.7 |
| `preference` | User/system preferences | 0.6 |
| `entity` | People, technologies, components | 0.5 |
| `procedure` | How-to knowledge | 0.5 |
| `constraint` | Limitations, requirements | 0.6 |
| `goal` | Objectives and targets | 0.8 |

**Metadata Tracking:**
```typescript
interface ItemMetadata {
  source: MemorySource;
  importance: number;        // 0-1 scale
  accessCount: number;       // Times retrieved
  lastAccessedAt: string;
  decayFactor: number;       // Current relevance (1.0 = full, 0 = forgotten)
  tokens: number;
  embedding?: number[];      // Optional semantic embedding
}
```

**Decay Function:**
```typescript
function calculateDecay(metadata, halfLifeDays = 30) {
  const daysSinceAccess = (now - lastAccess) / (1000 * 60 * 60 * 24);
  const accessBoost = Math.min(metadata.accessCount * 0.1, 0.5);
  const baseDecay = Math.pow(0.5, daysSinceAccess / halfLifeDays);
  return Math.min(1, baseDecay + accessBoost);
}
```

---

### Layer 4: Episodic Memory (Narrative)

Records key conversation moments and milestones.

```typescript
interface EpisodicMemory extends StoredItem {
  type: 'episode';
  title: string;
  summary: string;
  context: string;
  participants: string[];
  outcome?: string;
  emotionalValence: number;    // -1 to 1
  significance: number;        // 0-1
  linkedMemories: string[];
  conversationRef: {
    conversationId: string;
    turnRange: { start: number; end: number };
  };
}
```

**Episode Types:**
- **Decision Made**: Important choices with rationale
- **Problem Solved**: Issues that were resolved
- **Breakthrough**: Significant progress or insights
- **Issue Identified**: Problems discovered
- **Task Completed**: Milestones achieved
- **Pivot**: Direction changes

**Narrative Arc Tracking:**
```typescript
getNarrativeArc(conversationId): {
  beginning: EpisodicMemory[];  // First third
  middle: EpisodicMemory[];     // Middle third
  end: EpisodicMemory[];        // Final third
  keyMoments: EpisodicMemory[]; // Significance >= 0.7
}
```

---

## Context Window Management

### Budget Allocation

The `ContextManager` allocates tokens across different context sections:

```
Total Budget (e.g., 128K tokens)
├── System Prompt Reserve (2K)
├── Working Memory Reserve (8K)
└── Available for Context (118K)
    ├── Recent Messages (60% = ~70K)
    └── Retrieved Memories (40% = ~47K)
```

### Context Building Process

```typescript
buildContext(userQuery?: string): ContextBuildResult {
  // 1. Create token budget
  const budget = createBudget();
  
  // 2. Build retrieval query from user input + recent context
  const query = buildRetrievalQuery(userQuery, recentMessages);
  
  // 3. Retrieve relevant memories
  const retrievedMemories = retrievalEngine.retrieve(query);
  
  // 4. Get chunk summaries for conversation history
  const chunkSummaries = getChunks(conversationId);
  
  // 5. Allocate context items by priority
  const allocation = allocateContext(
    systemPrompt,
    recentMessages,
    retrievedMemories,
    chunkSummaries,
    budget
  );
  
  // 6. Return with warnings if over budget
  return { allocation, budget, retrievalResults, warnings };
}
```

### Priority-based Allocation

Items are allocated by priority until budget is exhausted:

| Component | Priority | Budget Share |
|-----------|----------|--------------|
| System prompt | 1.0 | Fixed reserve |
| Recent messages | 0.9 (decreasing) | 60% of available |
| Retrieved memories | By relevance score | 40% of available |
| Chunk summaries | 0.5 (decreasing) | Remaining |

---

## Retrieval System

### Multi-Strategy Scoring

Each candidate memory is scored using multiple strategies:

```typescript
interface RetrievalWeights {
  semantic: number;   // 0.4 - TF-IDF similarity
  keyword: number;    // 0.3 - Exact term matching
  recency: number;    // 0.2 - Time-based decay
  importance: number; // 0.1 - Stored importance
  access: number;     // 0.0 - Access frequency
}
```

**Final Score:**
```
relevanceScore = Σ(weight_i × score_i) / Σ(weight_i)
```

### TF-IDF Index

The system maintains a TF-IDF index for semantic search:

```typescript
// Term frequency (normalized)
tf(term, document) = count(term) / max_count(any_term)

// Inverse document frequency
idf(term) = log(total_documents / documents_containing_term)

// TF-IDF score
tfidf(term, document) = tf(term, document) × idf(term)
```

**Index Operations:**
- `invalidateIndex()`: Mark index as stale after memory changes
- `rebuildIndex()`: Rebuild from all memories
- Index is lazily rebuilt on first retrieval after invalidation

### Retrieval Query

```typescript
interface RetrievalQuery {
  text: string;              // Main query
  context?: string;          // Additional context for boosting
  filters?: {
    memoryTypes?: LongTermMemoryType[];
    categories?: string[];
    tags?: string[];
    dateRange?: { from?: string; to?: string };
    minImportance?: number;
    includeEpisodic?: boolean;
    includeChunks?: boolean;
  };
  weights?: RetrievalWeights;
}
```

---

## Fact Extraction

### Automatic Extraction

The `ConversationSummarizer` extracts facts from messages using pattern matching:

```typescript
const factPatterns = [
  // Decisions
  { pattern: /decided|chose|selected|went with/, type: 'decision', confidence: 0.8 },
  
  // Preferences
  { pattern: /prefer|like|want|need/, type: 'preference', confidence: 0.7 },
  
  // Constraints
  { pattern: /must|should|cannot|can't|need to/, type: 'constraint', confidence: 0.7 },
  
  // Goals
  { pattern: /goal|objective|aim|target/, type: 'goal', confidence: 0.8 },
];
```

### Fact Lifecycle

1. **Extraction**: Facts extracted from messages → `pendingFacts`
2. **Validation**: Confidence score calculated (0-1)
3. **Promotion**: Facts above threshold promoted to long-term memory
4. **Manual**: Users can manually promote facts

```typescript
interface ExtractedFact {
  id: string;
  content: string;
  type: LongTermMemoryType;
  confidence: number;
  sourceMessageId: string;
  extractedAt: string;
  promoted: boolean;
}
```

---

## Memory Consolidation

Periodic consolidation maintains system health:

```typescript
consolidate(): ConsolidationResult {
  // 1. Update decay factors for all memories
  longTermStore.updateDecayFactors();
  
  // 2. Archive old, low-importance memories
  for (const memory of allMemories) {
    const effectiveScore = importance × decayFactor;
    if (createdAt < cutoff && effectiveScore < 0.3) {
      expire(memory.id);
      memoriesArchived++;
    }
  }
  
  // 3. Consolidate episodic memories (merge overlapping)
  episodicStore.consolidate();
  
  // 4. Rebuild retrieval index
  retrievalEngine.rebuildIndex();
  
  return { memoriesArchived, memoriesMerged, tokensReclaimed };
}
```

---

## Storage Structure

All data persisted as human-readable JSON:

```
.project-memory/
├── long-term-memory.json    # Array of LongTermMemory
├── episodic-memory.json     # Array of EpisodicMemory
├── conversations.json       # Array of Conversation
└── conversation-chunks.json # Array of ConversationChunk
```

### ID Generation

```typescript
function generateId(): string {
  const timestamp = Date.now().toString(36);  // Sortable prefix
  const random = uuidv4().split('-')[0];       // Uniqueness
  return `${timestamp}-${random}`;             // e.g., "lxyz123-a1b2c3d4"
}
```

---

## Key Design Patterns

### 1. Lazy Loading
Stores load data from disk only on first access:
```typescript
protected load(): void {
  if (this.loaded) return;
  // Load from JSON file
  this.loaded = true;
}
```

### 2. Dirty Tracking
Changes are batched and written on flush:
```typescript
protected markDirty(): void {
  this.dirty = true;
}

public flush(): void {
  if (this.dirty) {
    save();
    this.dirty = false;
  }
}
```

### 3. Access Recording
Every retrieval updates access metadata:
```typescript
protected recordAccess(id: string): void {
  item.metadata.accessCount++;
  item.metadata.lastAccessedAt = now();
  item.metadata.decayFactor = calculateDecay(item.metadata);
}
```

### 4. Temporal Validity
Memories have explicit validity periods:
```typescript
// Check if memory is currently valid
isValid(memory) = validFrom <= now && (!validUntil || validUntil > now)

// Time-travel query
getValidAt(timestamp) = memories.filter(m => 
  m.validFrom <= timestamp && (!m.validUntil || m.validUntil > timestamp)
)
```

### 5. Relationship Graphs
Memories can be linked:
```typescript
interface MemoryRelationship {
  targetId: string;
  type: 'related_to' | 'depends_on' | 'contradicts' | 'supersedes' | ...;
  strength: number;  // 0-1
  createdAt: string;
}
```

---

## Performance Characteristics

### Scalability

| Metric | Value | Notes |
|--------|-------|-------|
| Conversation length | 250+ turns | Tested in demo |
| Chunk creation | ~25 chunks for 250 turns | 10 msgs/chunk |
| Retrieval time | <5ms | TF-IDF based |
| Memory consolidation | <100ms | For 100 memories |
| Token estimation | ~4 chars/token | Approximation |

### Memory Efficiency

- Recent messages: 20 kept verbatim (~8K tokens)
- Chunks: Summaries ~100-200 tokens each
- Long-term: Deduplicated, decayed
- Episodic: Capped at configurable limit

---

## Usage Example

```typescript
import { MemorySystem } from './src';

// Initialize
const memory = new MemorySystem({
  memoryDir: './.project-memory',
  projectName: 'My Project',
  maxContextTokens: 128000,
  chunkSize: 10,
  maxRecentMessages: 20,
});

// Conversation flow
memory.startConversation();
memory.addMessage('user', 'What database should we use?');
memory.addMessage('assistant', 'I recommend PostgreSQL for this use case.');
memory.addMessage('user', 'We decided to use PostgreSQL.');

// Build context for next LLM call
const context = memory.buildContext('What was our database decision?');
console.log(context.allocation.totalTokens);  // Tokens used
console.log(context.retrievalResults);        // Retrieved memories

// Search memories
const results = memory.search('PostgreSQL database');

// End and persist
memory.endConversation('Database selection complete');
memory.flush();
```

---

## Configuration Reference

```typescript
interface MemorySystemConfig {
  // Storage
  memoryDir: string;              // Default: '.project-memory'
  projectName: string;            // Default: 'Project'
  
  // Context window
  maxContextTokens: number;       // Default: 128000
  workingMemoryTokens: number;    // Default: 8000
  systemPromptTokens: number;     // Default: 2000
  
  // Conversation
  chunkSize: number;              // Default: 10
  maxRecentMessages: number;      // Default: 20
  
  // Memory retention
  shortTermRetentionTurns: number;     // Default: 50
  consolidationThresholdDays: number;  // Default: 30
  maxEpisodicMemories: number;         // Default: 100
  
  // Retrieval
  retrievalTopK: number;          // Default: 10
  relevanceThreshold: number;     // Default: 0.3
  recencyWeight: number;          // Default: 0.3
  importanceWeight: number;       // Default: 0.4
}
```

---

This implementation provides a robust foundation for maintaining context and memory in long-running AI assistant conversations, enabling coherent multi-session interactions while managing token budgets efficiently.
