# Where memory loses its context

SEAM preserves the original text in the examples examined here, but its default
memory formation path can assign statements to the wrong speaker and omit
source-event information. Those errors matter before retrieval begins: the
graph can turn a mistaken identity into a recurring observation.

This is the first investigation under SEAM's new memory formation roadmap.
It identifies specific inputs and outputs to guide the next design step.
It does not claim that the problems are fixed or that a benchmark score has
improved.

## What we examined

We traced the native LoCoMo loader through the conversation adapter, compiler,
canonical storage, entity identity, graph products and retrieval. The inspected
revision was `614141c5aa96fd51d4dee2e09c186bb4035c0377`.

Small synthetic examples isolated individual behaviors. The real conversation
adapter used its pinned local embedding model. A separate direct-storage
control tested source identity. No answer-generating model or paid evaluation
was involved.

## Finding 1: two speakers become one “I”

Alice says: “I moved to Oslo. I enjoy painting.” Bob says: “I moved to Rome.
I enjoy hiking.” Each turn carries its own speaker and date.

The first sentence of each turn receives the expected subject. The second
sentence receives the generic subject “I.” During persistence, those two
mentions merge into the same entity. Graph products then produce a recurring
observation about “I,” combining Alice's painting and Bob's hiking across
different source episodes.

The source text and evidence links remain intact. A control using a different
speaker-prefix format also binds both propositions to Alice correctly. This
narrows the issue to how the adapter's source context reaches the compiler;
SEAM already has identity storage and evidence tracking.

## Finding 2: source events need their own identity

Two dialogue objects with different dialogue IDs but identical speaker, date
and text become equal turns in the native loader. The adapter subsequently
stores one source document. Their distinct event identities never reach
persistence.

The same synthetic example supplies a caption in a separate field. That field
does not survive the native loader. A direct query of the stored text finds
the known dialogue words but not the supplied caption marker. This is a claim
about that specific route: captions already included inside message text are
a different case.

The direct-storage control retains two copies of the same text when given two
distinct source references. The next design therefore needs to distinguish a
repeated real-world event from an idempotent replay of the same event.

## Finding 3: sentence splitting is not enough

| Example | Observed behavior |
| --- | --- |
| Japanese prose without ASCII words | Original text is retained, but no proposition spans or claims are emitted. Ingestion still reports one compiled chunk. |
| “Dr. Chen moved to Oslo. She works there.” | The abbreviation becomes its own proposition, followed by separate Chen and She subjects. |
| Two speakers separated only by a newline | One proposition is attributed to the first speaker. |
| A long unpunctuated passage | A 10,000-character input produces one 9,999-character proposition span. |

Every emitted span checked in this probe points to the exact corresponding
source text. That useful property must survive a segmentation change.
Preserving the original text and covering it with usable propositions are
separate requirements.

## Finding 4: temporal wording needs careful interpretation

“I lived in Oslo. I now live in Rome.” survives as two content claims. The
default path does not turn them into typed event or state intervals.

That does not make the statements contradictory or mean all time information
is lost. A message's date, an event's date, the time of ingestion and an unknown
date mean different things. Existing temporal and identity controls provide
machinery to reuse once source-grounded facts arrive.

## What already works

The adapter retrieves the complete source turns in the synthetic question
control. Source spans and provenance remain available. The full adapter probe
contains 74 graph edges and produces source-backed summaries; the graph is
not empty merely because the default sample contains no typed relation rows.

Two focused test runs passed: 55 compile, identity and temporal compatibility
cases, followed by 98 extraction and graph cases. These checks establish their
named properties at the inspected revision. They do not erase the gaps shown
by the diagnostic examples, prove independent reproduction or establish a
benchmark result.

## What follows

The next design work defines stable source-event identity, validated speaker
context, timestamp meaning and attachment provenance. It must distinguish the
speaker from the subject of a sentence: Alice talking about Bob does not make
every statement a fact about Alice.

Segmentation then needs explicit coverage, size and context requirements.
Temporal projections should use the existing identity, provenance and graph
systems. Earlier experiments with entity aggregation, dossiers, decomposition
and alias folding did not establish the desired benchmark gain; this audit
does not revive those approaches without new evidence.

Formation correctness comes first. Any later claim about retrieval or answer
quality requires a separately defined evaluation with fixed conditions and
appropriate comparison data.
