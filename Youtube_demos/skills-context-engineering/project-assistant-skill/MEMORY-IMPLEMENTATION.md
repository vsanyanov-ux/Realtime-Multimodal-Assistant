# Project Assistant Memory Implementation - Technical Summary

## Overview

The project assistant implements a **layered memory architecture** using the **file-system-as-memory pattern**. All memory is persisted as human-readable JSON files, providing transparency, debuggability, and simple recovery. The system tracks three primary entity types: **Decisions**, **Tasks**, and **Entities**, with full temporal validity support.

---

## Memory Architecture Layers

### Layer 1: Working Memory (Volatile)
- Current conversation context held in the LLM context window
- Automatically populated with relevant memory items via `buildContextSummary()`
- Lost when session ends

### Layer 2: Short-Term Memory (Session-Scoped)
- Conversation messages stored in `Conversation` objects
- Tracked via `currentConversation` in MemoryManager
- Persisted to `conversations.json` when session ends

### Layer 3: Long-Term Memory (Persistent)
- Decisions, Tasks, and Entities stored in separate JSON files
- Survives across sessions indefinitely
- Supports consolidation to remove outdated items

---

## Storage Structure

```
{memoryDir}/
├── decisions.json      # Array of Decision objects
├── tasks.json          # Array of Task objects  
├── entities.json       # Array of Entity objects
└── conversations.json  # Array of Conversation objects (last 100)
```

---

## Core Data Structures

### Base Interface (StoredItem)
All stored items inherit temporal tracking fields:

```typescript
interface StoredItem {
  id: string;           // Unique ID: `{timestamp}-{random9chars}`
  createdAt: string;    // ISO timestamp
  updatedAt: string;    // ISO timestamp
  validFrom: string;    // When fact became valid
  validUntil?: string;  // When fact expired (undefined = still valid)
}
```

### Decision Structure

```typescript
interface Decision extends StoredItem {
  type: 'decision';
  title: string;
  description: string;
  rationale: string;           // Why this decision was made
  context: string;             // Background information
  status: 'proposed' | 'accepted' | 'rejected' | 'superseded' | 'deprecated';
  alternatives?: string[];     // Options considered
  consequences?: string[];     // Trade-offs and impacts
  relatedDecisions?: string[]; // IDs of related decisions
  relatedTasks?: string[];     // IDs of tasks spawned by this decision
  tags: string[];
  supersededBy?: string;       // ID of decision that replaced this one
}
```

**Supersession Pattern**: When a decision is superseded:
1. New decision is created with `relatedDecisions` containing old ID
2. Old decision's `status` set to `'superseded'`
3. Old decision's `supersededBy` set to new decision ID
4. Old decision's `validUntil` set to current timestamp

### Task Structure

```typescript
interface Task extends StoredItem {
  type: 'task';
  title: string;
  description: string;
  status: 'backlog' | 'planned' | 'in_progress' | 'blocked' | 'completed' | 'cancelled';
  priority: 'critical' | 'high' | 'medium' | 'low';
  assignee?: string;
  dueDate?: string;
  completedAt?: string;
  dependencies?: string[];      // Task IDs that must complete first
  blockedBy?: string;           // Description of blocker
  relatedDecisions?: string[];  // Decision IDs that spawned this task
  tags: string[];
  statusHistory: TaskStatusChange[];  // Full audit trail
}

interface TaskStatusChange {
  from: TaskStatus;
  to: TaskStatus;
  timestamp: string;
  reason?: string;
}
```

**Status History Pattern**: Every status change appends to `statusHistory` array, providing complete audit trail. The `unblock()` operation reads history to restore previous status.

### Entity Structure

```typescript
interface Entity extends StoredItem {
  type: 'entity';
  entityType: 'person' | 'technology' | 'component' | 'service' | 'concept' | 'other';
  name: string;
  description: string;
  properties: Record<string, unknown>;  // Flexible key-value store
  mentions: EntityMention[];            // Where entity was referenced
  relatedEntities?: string[];           // IDs of related entities
  tags: string[];
}

interface EntityMention {
  context: string;      // Text context where mentioned
  timestamp: string;
  source: string;       // 'conversation' or 'manual'
}
```

**Find-or-Create Pattern**: `findOrCreate()` method performs case-insensitive name lookup before creating, preventing duplicate entities. Updates existing entity with new info if found.

---

## Base Store Implementation

`BaseStore<T extends StoredItem>` provides common persistence operations:

### Lazy Loading
```typescript
protected load(): void {
  if (this.loaded) return;
  // Read JSON file, parse into Map<id, item>
  this.loaded = true;
}
```

### Persistence
```typescript
protected save(): void {
  // Convert Map to Array, write as formatted JSON
  fs.writeFileSync(this.storePath, JSON.stringify(items, null, 2));
}
```

### Common Operations
- `getAll()`, `getById(id)`, `exists(id)`, `delete(id)`, `count()`, `clear()`
- `filter(predicate)`, `find(predicate)` - functional query methods
- `searchText(text, getFields)` - case-insensitive text search
- `filterByDateRange(items, fromDate, toDate)` - temporal filtering
- `isCurrentlyValid(item)` - checks `validFrom`/`validUntil` against current time
- `getValidAt(timestamp)` - time-travel query for historical state
- `export()` / `import(items, merge)` - backup/restore

---

## Memory Manager (Coordinator)

`MemoryManager` coordinates all stores and provides unified interface:

### Initialization
```typescript
constructor(memoryDir?: string, projectName = 'Project') {
  this.memoryDir = memoryDir || '{cwd}/.project-assistant/memory';
  this.decisions = new DecisionStore(this.memoryDir);
  this.tasks = new TaskStore(this.memoryDir);
  this.entities = new EntityStore(this.memoryDir);
}
```

### Cross-Store Operations

**Unified Search**:
```typescript
searchAll(searchText: string, limit = 10): {
  decisions: Decision[];
  tasks: Task[];
  entities: Entity[];
}
```

**Tag-Based Retrieval**:
```typescript
getByTag(tag: string): { decisions, tasks, entities }
```

### Context Building for LLM

```typescript
buildContextSummary(relevantTerms: string[] = []): ContextSummary {
  return {
    recentDecisions: this.decisions.getActive().slice(0, 5),
    activeTasks: this.tasks.getActive().slice(0, 10),
    relevantEntities: /* entities matching terms or recent */,
    projectSummary: /* formatted status text */
  };
}
```

**Context Formatting**:
```typescript
formatContextForPrompt(context: ContextSummary): string
// Returns formatted text with sections:
// === PROJECT CONTEXT ===
// === RECENT DECISIONS ===
// === ACTIVE TASKS ===
// === KNOWN ENTITIES ===
```

### Memory Consolidation

```typescript
consolidate(options: ConsolidationOptions): {
  decisionsArchived: number;
  tasksCleaned: number;
  entitiesMerged: number;
}

interface ConsolidationOptions {
  archiveOlderThan?: number;      // Days, default 90
  removeSuperseded?: boolean;      // Default true
  removeCancelledTasks?: boolean;  // Default true
}
```

Consolidation removes:
- Superseded decisions older than threshold
- Cancelled tasks older than threshold

---

## Query Interfaces

### Decision Query

```typescript
interface DecisionQuery {
  status?: DecisionStatus[];
  tags?: string[];
  searchText?: string;
  fromDate?: string;
  toDate?: string;
  includeSuperseded?: boolean;  // Default false
  limit?: number;
}
```

### Task Query

```typescript
interface TaskQuery {
  status?: TaskStatus[];
  priority?: TaskPriority[];
  tags?: string[];
  assignee?: string;
  searchText?: string;
  fromDate?: string;
  toDate?: string;
  includeCompleted?: boolean;   // Default false
  includeCancelled?: boolean;   // Default false
  limit?: number;
}
```

**Task Sorting**: Results sorted by priority (critical first), then by date (newest first).

### Entity Query

```typescript
interface EntityQuery {
  entityType?: EntityType[];
  tags?: string[];
  searchText?: string;
  limit?: number;
}
```

**Entity Sorting**: Results sorted by most recent mention timestamp.

---

## Specialized Store Methods

### DecisionStore
- `accept(id)` / `reject(id)` - change status
- `supersede(oldId, newDecisionInput)` - create replacement decision
- `getActive()` - accepted, not superseded
- `getDecisionHistory(id)` - follow supersession chain
- `linkToTask(decisionId, taskId)` - create relationship

### TaskStore
- `start(id)` / `complete(id)` / `cancel(id, reason)` - status transitions
- `block(id, blockedBy)` / `unblock(id)` - blocking management
- `getActive()` / `getBlocked()` / `getInProgress()` / `getOverdue()`
- `canStart(id)` - check if dependencies completed
- `getDependencyGraph()` - returns `Map<taskId, dependencyIds[]>`
- `linkToDecision(taskId, decisionId)` - create relationship

### EntityStore
- `findByName(name)` - case-insensitive lookup
- `findOrCreate(input)` - idempotent creation
- `addMention(id, context, source)` - record reference
- `setProperty(id, key, value)` - update single property
- `link(id1, id2)` - bidirectional relationship
- `merge(primaryId, secondaryId)` - combine duplicate entities
- `getByType(entityType)` / `getPeople()` / `getTechnologies()` / `getComponents()`

---

## Conversation Tracking

```typescript
interface Conversation {
  id: string;
  startedAt: string;
  endedAt?: string;
  messages: Message[];
  summary?: string;
  extractedDecisions?: string[];  // IDs created during conversation
  extractedTasks?: string[];
  extractedEntities?: string[];
}

interface Message {
  role: 'user' | 'assistant' | 'system';
  content: string;
  timestamp: string;
}
```

**Session Management**:
- `startConversation()` - begins new session
- `addMessage(role, content)` - appends to current conversation
- `endConversation(summary?)` - saves to history, clears current
- `getRecentConversations(limit)` - retrieves history

---

## AI Integration (Extraction)

When AI is enabled, conversations are analyzed to extract:

```typescript
interface ExtractedInfo {
  decisions: CreateDecisionInput[];
  tasks: CreateTaskInput[];
  entities: CreateEntityInput[];
  taskUpdates: Array<{ id: string; update: UpdateTaskInput }>;
  references: {
    decisionIds: string[];
    taskIds: string[];
    entityIds: string[];
  };
}
```

The extraction uses a dedicated prompt requesting JSON output, then processes results through `processExtracted()` which:
1. Creates new decisions/tasks via respective stores
2. Uses `findOrCreate()` for entities to prevent duplicates
3. Applies task updates for referenced existing tasks

---

## Key Design Patterns

1. **File-System-as-Memory**: JSON files provide transparent, debuggable, portable storage
2. **Lazy Loading**: Data loaded on first access, cached in memory Map
3. **Temporal Validity**: `validFrom`/`validUntil` enable time-travel queries
4. **Status History**: Full audit trail for tasks
5. **Supersession Chain**: Decisions link to their replacements
6. **Find-or-Create**: Idempotent entity creation prevents duplicates
7. **Relationship Links**: Bidirectional references between decisions, tasks, entities
8. **Context Injection**: Memory formatted and injected into LLM system prompt

---

## Statistics Available

Each store provides `getStats()` returning:

- **Decisions**: total, byStatus counts, tag distribution
- **Tasks**: total, byStatus, byPriority, overdue count, blocked count, averageCompletionTime
- **Entities**: total, byType counts, mostMentioned list, tag distribution

---

This implementation follows the memory-systems skill guidance for file-system-based persistence with temporal validity and provides a complete foundation for a project assistant that maintains continuity across sessions.
