---
conceptType: llm
outputPredicate: customer_summary
llmConfig:
  provider: anthropic
  model: claude-sonnet-4-6
  output_columns: [Id, summary]
---
Summarize each customer's risk profile in one sentence, given {{ Id }} and their attributes.
