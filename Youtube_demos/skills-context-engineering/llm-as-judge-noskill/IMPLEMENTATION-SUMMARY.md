# LLM-as-Judge Implementation Summary (v1)

## Overview

LLM-as-Judge v1 is a TypeScript library for evaluating AI-generated content using LLM-based assessment. It provides three core evaluation patterns: **Direct Scoring**, **Pairwise Comparison**, and **Rubric Generation**.

---

## Architecture

```
src/
├── types.ts               # Type definitions
├── llm-client.ts          # OpenAI API communication
├── direct-scoring.ts      # Single response evaluation
├── pairwise-comparison.ts # A/B comparison
├── rubric-generation.ts   # Dynamic rubric creation
├── example.ts             # Usage examples
└── index.ts               # Module exports
```

---

## Core Components

### 1. LLM Client (`llm-client.ts`)

Handles communication with OpenAI-compatible APIs.

```typescript
class LLMClient {
  constructor(config: LLMJudgeConfig);
  
  // Send prompt and get text response
  async chat(systemPrompt: string, userPrompt: string, options?): Promise<string>;
  
  // Send prompt and parse JSON response
  async chatJSON<T>(systemPrompt: string, userPrompt: string, options?): Promise<T>;
}
```

**Configuration:**
| Option | Default | Description |
|--------|---------|-------------|
| `apiKey` | `OPENAI_API_KEY` env | API key |
| `model` | `gpt-4-turbo-preview` | Model to use |
| `baseUrl` | `OPENAI_BASE_URL` env | Custom API endpoint |
| `temperature` | `0.3` | Response determinism |
| `maxTokens` | `4096` | Max response length |

**JSON Extraction:**
```typescript
// Extracts JSON from markdown code blocks or raw JSON
const jsonMatch = response.match(/```json\n?([\s\S]*?)\n?```/) || 
                  response.match(/\{[\s\S]*\}/);
```

---

### 2. Direct Scoring (`direct-scoring.ts`)

Evaluates a single response against specified criteria.

#### Type Definitions

```typescript
interface ScoringCriteria {
  name: string;           // e.g., "accuracy", "relevance"
  description: string;    // What this criterion measures
  weight?: number;        // 0-1, defaults to equal weights
  minScore?: number;      // Defaults to 1
  maxScore?: number;      // Defaults to 10
}

interface DirectScoreRequest {
  prompt: string;              // Original prompt given to AI
  response: string;            // Response to evaluate
  referenceAnswer?: string;    // Expected answer for comparison
  criteria: ScoringCriteria[]; // Scoring criteria
  context?: string;            // Additional context
}

interface CriterionScore {
  criterion: string;     // Criterion name
  score: number;         // Numeric score
  maxScore: number;      // Maximum possible score
  reasoning: string;     // Explanation for score
}

interface DirectScoreResult {
  scores: CriterionScore[];   // Per-criterion scores
  overallScore: number;        // Weighted score (0-100)
  summary: string;             // Brief assessment
  suggestions: string[];       // Improvement suggestions
}
```

#### Scoring Algorithm

```typescript
function calculateWeightedScore(scores, criteria): number {
  let totalWeight = 0;
  let weightedSum = 0;

  for (const score of scores) {
    const weight = criterion?.weight ?? 1 / criteria.length;
    totalWeight += weight;
    
    // Normalize to 0-100 scale
    const normalizedScore = (score.score / score.maxScore) * 100;
    weightedSum += normalizedScore * weight;
  }

  return weightedSum / totalWeight;
}
```

#### System Prompt

```
You are an expert evaluator tasked with assessing the quality of AI-generated responses.
For each criterion, you must:
1. Carefully analyze the response against the criterion
2. Provide a numeric score within the specified range
3. Explain your reasoning clearly and specifically

Be objective and consistent in your scoring. Reference specific parts of the response.
```

#### API Functions

```typescript
// Full scoring with custom criteria
scoreResponse(request: DirectScoreRequest, config?): Promise<EvaluationResult<DirectScoreResult>>

// Quick scoring with default criteria (accuracy, relevance, completeness, clarity)
quickScore(prompt: string, response: string, config?): Promise<EvaluationResult<DirectScoreResult>>

// Batch scoring (parallel)
batchScore(requests: DirectScoreRequest[], config?): Promise<EvaluationResult<DirectScoreResult>[]>
```

---

### 3. Pairwise Comparison (`pairwise-comparison.ts`)

Compares two responses to determine which is better.

#### Type Definitions

```typescript
interface PairwiseComparisonRequest {
  prompt: string;
  responseA: string;
  responseB: string;
  referenceAnswer?: string;
  criteria: ScoringCriteria[];
  context?: string;
}

type ComparisonWinner = 'A' | 'B' | 'tie';

interface CriterionComparison {
  criterion: string;
  winner: ComparisonWinner;
  scoreA?: number;
  scoreB?: number;
  reasoning: string;
}

interface PairwiseComparisonResult {
  winner: ComparisonWinner;
  confidence: number;              // 0-1
  criteriaComparisons: CriterionComparison[];
  summary: string;
  strengthsA: string[];
  strengthsB: string[];
}
```

#### Winner Determination Algorithm

```typescript
function determineOverallWinner(comparisons, criteria) {
  let scoreA = 0, scoreB = 0;

  for (const comp of comparisons) {
    const weight = criterion?.weight ?? 1 / criteria.length;

    if (comp.winner === 'A') scoreA += weight;
    else if (comp.winner === 'B') scoreB += weight;
    else {
      // Tie splits weight
      scoreA += weight * 0.5;
      scoreB += weight * 0.5;
    }
  }

  const diff = Math.abs(scoreA - scoreB);
  const confidence = Math.min(diff * 2, 1);

  // Tie if difference < 5%
  if (diff < 0.05) return { winner: 'tie', confidence: 1 - diff * 10 };
  return { winner: scoreA > scoreB ? 'A' : 'B', confidence };
}
```

#### Tournament Mode

```typescript
// Compare multiple responses pairwise, rank by win rate
tournamentCompare(
  prompt: string,
  responses: string[],
  criteria: ScoringCriteria[],
  config?
): Promise<EvaluationResult<{
  rankings: Array<{
    index: number;
    wins: number;
    losses: number;
    ties: number;
  }>
}>>
```

---

### 4. Rubric Generation (`rubric-generation.ts`)

Dynamically generates evaluation rubrics for different task types.

#### Type Definitions

```typescript
type TaskType = 
  | 'qa' | 'summarization' | 'translation' 
  | 'code_generation' | 'creative_writing' 
  | 'reasoning' | 'instruction_following' 
  | 'conversation' | 'custom';

interface RubricGenerationRequest {
  taskType: TaskType;
  taskDescription: string;
  examplePrompt?: string;
  exampleResponse?: string;
  numCriteria?: number;      // Defaults to 5
  focusAreas?: string[];
}

interface RubricLevel {
  score: number;
  label: string;             // e.g., "Excellent", "Good"
  description: string;
}

interface GeneratedCriterion {
  name: string;
  description: string;
  weight: number;            // 0-1
  levels: RubricLevel[];     // 5 levels (1-5)
}

interface GeneratedRubric {
  taskType: TaskType;
  title: string;
  description: string;
  criteria: GeneratedCriterion[];
  usageTips: string[];
}
```

#### Predefined Templates

```typescript
RUBRIC_TEMPLATES = {
  factualQA: () => ({
    taskType: 'qa',
    focusAreas: ['factual accuracy', 'source reliability', 'completeness'],
    numCriteria: 5,
  }),

  codingTask: () => ({
    taskType: 'code_generation',
    focusAreas: ['correctness', 'code quality', 'efficiency', 'documentation'],
    numCriteria: 5,
  }),

  creativeStory: () => ({
    taskType: 'creative_writing',
    focusAreas: ['creativity', 'narrative flow', 'character development'],
    numCriteria: 5,
  }),

  summarization: () => ({
    taskType: 'summarization',
    focusAreas: ['key point coverage', 'conciseness', 'accuracy'],
    numCriteria: 4,
  }),

  instructionFollowing: () => ({
    taskType: 'instruction_following',
    focusAreas: ['instruction compliance', 'completeness', 'format adherence'],
    numCriteria: 4,
  }),
};
```

#### Utility Functions

```typescript
// Convert rubric to ScoringCriteria for direct scoring
rubricToScoringCriteria(rubric: GeneratedRubric): ScoringCriteria[]

// Format rubric as markdown documentation
rubricToMarkdown(rubric: GeneratedRubric): string
```

---

## Result Type Pattern

All evaluation functions return a discriminated union for error handling:

```typescript
type EvaluationResult<T> = 
  | { success: true; data: T }
  | { success: false; error: EvaluationError };

interface EvaluationError {
  code: string;      // 'SCORING_ERROR', 'COMPARISON_ERROR', etc.
  message: string;
  details?: unknown;
}
```

**Usage:**
```typescript
const result = await scoreResponse(request);

if (result.success) {
  console.log(result.data.overallScore);
} else {
  console.error(result.error.message);
}
```

---

## Usage Examples

### Direct Scoring

```typescript
import { scoreResponse, quickScore } from 'llm-as-judge';

// Quick score with defaults
const result = await quickScore(
  'What is the capital of France?',
  'The capital of France is Paris.'
);

// Custom criteria
const result = await scoreResponse({
  prompt: 'Explain recursion',
  response: 'Recursion is when a function calls itself...',
  criteria: [
    { name: 'Technical Accuracy', description: '...', weight: 0.4 },
    { name: 'Clarity', description: '...', weight: 0.3 },
    { name: 'Examples', description: '...', weight: 0.3 },
  ],
});
```

### Pairwise Comparison

```typescript
import { quickCompare, tournamentCompare } from 'llm-as-judge';

// Compare two responses
const result = await quickCompare(
  'Write a haiku about coding',
  'Response A...',
  'Response B...'
);

// Tournament with multiple responses
const tournament = await tournamentCompare(
  'Write a function to sort an array',
  [response1, response2, response3, response4],
  criteria
);
console.log(tournament.data.rankings);
```

### Rubric Generation

```typescript
import { generateRubric, quickRubric, RUBRIC_TEMPLATES } from 'llm-as-judge';

// Quick rubric for task type
const rubric = await quickRubric('code_generation');

// From template
const rubric = await generateRubric(RUBRIC_TEMPLATES.codingTask());

// Custom
const rubric = await generateRubric({
  taskType: 'custom',
  taskDescription: 'Customer support response quality',
  focusAreas: ['helpfulness', 'empathy', 'resolution'],
  numCriteria: 4,
});
```

---

## Configuration

### Environment Variables

| Variable | Description |
|----------|-------------|
| `OPENAI_API_KEY` | OpenAI API key (required) |
| `OPENAI_BASE_URL` | Custom API endpoint |
| `LLM_JUDGE_MODEL` | Model override |

### API Key Loading

```typescript
// Loads from root .env file
import * as dotenv from 'dotenv';
dotenv.config({ path: path.resolve(process.cwd(), '.env') });
```

---

## Key Characteristics

1. **Structured JSON Output**: All evaluations request JSON from LLM
2. **Weighted Scoring**: Criteria can have custom weights
3. **Normalized Scores**: Overall scores normalized to 0-100
4. **Tie Handling**: Pairwise comparison supports ties (<5% difference)
5. **Batch Processing**: Parallel evaluation support
6. **Template System**: Predefined rubrics for common tasks
7. **Markdown Export**: Rubrics can be formatted as documentation

---

## Limitations (v1)

1. **No Position Bias Mitigation**: Pairwise comparison susceptible to order effects
2. **No Evidence Collection**: Scores provided without explicit evidence chain
3. **Fixed Scale**: Direct scoring uses 1-10, no flexibility
4. **No Confidence Calibration**: Confidence is estimate, not calibrated
5. **No Strictness Control**: Rubrics don't support strictness levels
6. **No Domain Specialization**: No domain-specific terminology support
7. **No Edge Case Handling**: Rubrics lack edge case guidance

These limitations are addressed in v2.
