# Vibelo Recommendation

This context defines the language used by Vibelo's personalized image retrieval and model lifecycle.

## Language

**Image Embedding**:
A normalized semantic vector produced from a published image by the configured SigLIP encoder.
_Avoid_: Feature, image feature

**Behavior Sequence**:
One actor's time-ordered impressions and interactions used to represent recent intent.
_Avoid_: History, logs

**Retrieval Example**:
A behavior sequence prefix paired with its next qualified positive image and optional mature negative exposures.
_Avoid_: Training row, sample

**Two-Tower Artifact**:
A versioned pair of learned user and item encoders plus their immutable configuration and evaluation metadata.
_Avoid_: Model file, weights

**Candidate Model**:
A two-tower artifact that completed training but is not yet serving traffic.
_Avoid_: Latest model

**Learned Index**:
A versioned Milvus collection containing every published image encoded by one specific two-tower artifact.
_Avoid_: Vector table, model collection

**Current Model**:
The candidate model whose learned index passed publication checks and is selected for online retrieval.
_Avoid_: Production file, active JSON

**Previous Model**:
The last current model retained with its learned index for immediate rollback.
_Avoid_: Backup model

**Exposure Decision**:
One ordered recommendation result with its decision id, route, score, position, and model version.
_Avoid_: Impression batch

## Relationships

- A **Behavior Sequence** produces zero or more **Retrieval Examples**.
- A **Retrieval Example** trains one **Two-Tower Artifact**.
- A **Candidate Model** must own exactly one ready **Learned Index** before becoming the **Current Model**.
- A **Current Model** replaces at most one **Previous Model**.
- An **Exposure Decision** records which **Current Model** influenced an ordered result.

## Example dialogue

> **Dev:** "Can the new **Candidate Model** serve immediately after training?"
> **Domain expert:** "No. Build and verify its **Learned Index** first; only then promote it to the **Current Model**, while retaining the old one as the **Previous Model**."

## Flagged ambiguities

- "Recall model" previously referred both to heuristic behavior weights and learned encoders; only a **Two-Tower Artifact** is a trained retrieval model.
