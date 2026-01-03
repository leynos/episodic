# Compatibility of LangGraph/Celery with Hexagonal Architecture in Episodic System

## Architectural Mismatches and Boundary Friction

**Domain Purity vs. Orchestration Frameworks:** The Episodic system enforces
Hexagonal Architecture, meaning core business logic (the domain) should remain
independent of frameworks or infrastructure. Introducing LangGraph (an agentic
workflow engine) and Celery (for async task execution) can threaten this
separation if not carefully managed. A key friction is ensuring the domain’s
*purity*: domain services and entities should not directly depend on LangGraph
graphs or Celery mechanics. For example, the design mandates that domain
modules remain *framework-agnostic*, so if domain logic starts relying on
Celery task behaviours or LangGraph-specific classes, that’s a boundary
violation. The LangGraph design intentionally addresses this by treating itself
as an **internal orchestration mechanism** that does *not replace the hexagonal
design*. In practice, this means any use of LangGraph must be confined to the
application layer (e.g. orchestration services) and **never bleed into domain
objects or rules**, preserving clean ports/adapters separation.

**Ports and Adapter Layering:** Hexagonal Architecture relies on **ports** as
the integration boundaries – domain services call out via abstract interfaces,
and adapters implement those interfaces for infrastructure or external
services. LangGraph and Celery can introduce friction if they bypass these port
abstractions. For instance, if a LangGraph node directly calls an external API
or writes to a database without going through a port adapter, it violates
adapter layering. The Episodic design explicitly guards against this:
*LangGraph graphs invoke the `LLMPort`, `TTSPort`, and other evaluator ports;
the graph itself does not expose external integration points*. This ensures
that even though LangGraph is orchestrating the workflow, every external
interaction (LLM calls, TTS syntheses, storage of results) still happens via a
proper port interface. A potential mismatch arises if developers treat Celery
tasks as an **end-run around ports** – e.g. a Celery task using a database ORM
or calling an API client directly. Such shortcuts break hexagonal principles by
mixing infrastructure calls into what should be a domain workflow. Therefore,
**adapter layering must be strictly respected**: LangGraph/Celery orchestration
logic should remain in the application layer and invoke only domain services or
ports, never directly calling outbound adapters in-line.

**Graph-Based Logic vs. Domain Rules Clarity:** Another friction point is how
business rules are encoded. In a hexagonal design, business rules belong in the
domain layer or application logic, not scattered across infrastructure.
LangGraph introduces **conditional routing and stateful control flow** – e.g.
edges that decide whether to refine content or proceed to approval based on QA
scores. This is actually aligned with domain intent (since it implements policy
like “if QA fails, iterate again”), but the challenge is to keep this logic
from becoming opaque or entangled with the framework. If too much domain
decision-making is baked into LangGraph graph definitions, it might be harder
to test or reuse outside the LangGraph context. The design document mitigates
this by treating those conditional edges *as an expression of business rules*
rather than ad-hoc code. Still, developers must be careful: **domain rules
encoded in the graph should mirror the domain’s own policies**. Any mismatch
(say the graph logic diverges from what the domain model allows) would be a
sign of architectural friction. Essentially, the graph should orchestrate calls
and decisions *consistent with the domain’s rules*, not invent its own logic
outside of domain oversight.

**Celery Task Scope and Domain Boundaries:** Celery is used to run background
tasks in the Episodic system, which likely includes executing LangGraph
workflows asynchronously. A potential boundary issue here is the **scope of
Celery tasks** – if a single Celery task tries to perform an entire multi-step
generation workflow end-to-end, it may end up intermixing concerns. For
example, a monolithic task might call an LLM, evaluate results, update the
database, and send notifications all in one go, crossing multiple layers.
Hexagonal architecture would prefer these actions be broken into distinct steps
behind ports (LLMPort, persistence repository, notification adapter, etc.). The
**friction** arises if Celery tasks aren’t carefully constrained to calling
domain services for each step. If a task reaches directly into an adapter (e.g.
writing to Postgres or object storage without a domain service orchestrating
it), that’s a boundary breach. The design calls for guardrails (like lint rules
and architecture tests) to prevent cross-layer imports, but as graphs grow
complex, there’s a risk that a Celery task or LangGraph node could slip in a
direct adapter call out of convenience. In summary, keeping Celery tasks
**encapsulated** — each task performing a well-defined unit of work via the
proper port or domain service — is critical to avoid blurring the hexagonal
layers.

## Operational Risks with Async Agentic Workflows

**Hidden Coupling and Implicit Dependencies:** When using LangGraph and Celery,
there’s a risk of *hidden coupling* between components that should remain
independent. For instance, LangGraph’s StateGraph holds state across iterative
steps, and Celery tasks might pass around IDs or partial data. If the workflow
logic assumes certain tasks always run in a set order or that certain state is
pre-populated in a global context, implicit coupling emerges that is not at the
port level. One example could be a Celery task that expects a previous task to
have written a specific database record or file. If that dependency isn’t
explicit via a domain event or state check, the coupling is hidden and can
break the moment the execution order changes or tasks get retried.
**Orchestration leakage into the domain** is another form of hidden coupling:
if domain entities or services begin to incorporate knowledge of the
orchestrator (e.g. an `Episode` domain object carrying a “current graph node”
state or having to know it’s mid-generation), then the domain is now coupled to
the workflow process. The Episodic design tries to avoid this by keeping the
LangGraph state in its own structure (the StateGraph) and using domain
identifiers (episode ID, run ID) to tie into persistence. However, the
operational risk remains that future changes – say adding a new subgraph or
parallel step – might introduce subtle coupling (like two parallel tasks both
modifying the same piece of domain data). To mitigate this, the team needs to
make inter-task contracts explicit: use well-defined message schemas or
database state transitions (through ports) so that each task knows what it can
expect (e.g. a Celery task only proceeds when the domain signals that QA
results are stored and ready). Hidden coupling can also be addressed by
**comprehensive tracing and logging**, something the LangGraph framework
emphasizes so that unseen dependencies can be spotted in how the agent executes
[LangGraph blog](https://blog.langchain.com/building-langgraph/).

**Orchestration Logic Leaking into Domain Layer:** A subtle risk is
**orchestration leakage**, where the process control code (which ideally
belongs in the application layer or orchestrator) starts creeping into the
domain logic. This can happen if, for example, domain services begin to take on
responsibilities for calling the next step in a workflow or deciding Celery
task routing. In a Hexagonal approach, the domain should be unaware of *how*
its operations are sequenced or parallelized. If a domain function directly
triggers a Celery task or branches based on a workflow state machine, that’s
leakage. The design document explicitly separates concerns: domain services
expose operations (e.g. “generate draft content” or “evaluate content quality”)
and the **LangGraph orchestrator decides the ordering and conditional flow**
around those operations. Operationally, maintaining this separation means that
any logic about “what to do next if condition X” stays in the LangGraph/Celery
layer, not in the domain objects. A point of friction could be handling failure
conditions – for example, if content generation fails, who decides to retry? If
the domain service itself automatically triggers a retry, it might entangle
orchestration concerns. Instead, the agentic system (LangGraph/Celery) should
catch the failure (perhaps via a Celery retry or a graph loop) and then invoke
the domain operation again or route to an escalation. Ensuring that failure
handling, retries, and multi-step sequences are managed by the orchestration
layer prevents those concerns from leaking into domain code. The **operational
risk** if this leaks is that it becomes hard to change the workflow, because
domain logic changes become necessary, and tight coupling can emerge where
domain functions assume they’re always called as part of a Celery flow
(reducing modularity).

**Asynchronous Execution and Long-Running Tasks:** By design, the agentic
workflows here are asynchronous and can be long-running – generating a podcast
episode with multiple iterations and audio synthesis can span minutes or even
hours, especially with human approval in the loop. This introduces challenges
around reliability and consistency. One major risk is that *long-running tasks
can fail mid-way*, and if not handled, all progress is lost. The LangGraph
design explicitly identifies this risk: if an agent fails on minute 9 of a
10-minute run, restarting from scratch is expensive
[LangGraph blog](https://blog.langchain.com/building-langgraph/). In a Celery
context, workers might crash or tasks might be killed for taking too long. To
combat this, LangGraph leverages **checkpointing** – saving the state of the
workflow periodically so it can resume without restarting entirely
[LangGraph blog](https://blog.langchain.com/building-langgraph/). The Episodic
system implements this by serializing the StateGraph state to a database at key
checkpoints. While this addresses reliability, it brings operational overhead:
the system must ensure that after a crash or a deliberate pause (like waiting
for human feedback), the resume logic correctly restores state and continues
via Celery without missteps. If Celery tasks aren’t properly encapsulated
around these checkpoints, scenarios can arise where a task resumes with stale
data or double-processing after a retry. There’s also the question of
**timeouts and resource usage**: Celery tasks have time limits (which might be
extended for these workflows). A risk is that a single LangGraph execution
might exhaust worker resources if it isn’t broken into smaller tasks. The
design’s use of a task queue (Celery/RabbitMQ) is meant to decouple the user
request from the agent execution
[LangGraph blog](https://blog.langchain.com/building-langgraph/), but it’s
crucial to also break the work into manageable chunks. For example, running
each major phase (generation, evaluation, refinement) as separate tasks or
sub-tasks can prevent any one task from running prohibitively long.
**Asynchronous orchestration** also means dealing with eventual consistency: a
user might query the episode status while tasks are ongoing. The domain model
accounts for this by tracking a generation run’s status and progress in the
database (e.g. an episode has a status “in_progress” with iteration count) so
that at any point it reflects the last checkpointed state. The operational
challenge is ensuring that this state is updated *only* at well-defined points
(to avoid race conditions) – likely right after a checkpoint is saved or a step
completes. If two parallel Celery tasks try to update the episode status
concurrently (say one finishing QA evaluation and another finishing audio mix),
careful locking or conflict handling is needed. In short, asynchronous and
long-running execution demands robust **synchronization and error-handling
strategies**: checkpointing, idempotent task design (so retries don’t corrupt
state), and timeouts on Celery tasks to avoid runaway processes.

**Parallelism and Concurrency Issues:** LangGraph enables parallel branches
(e.g. running multiple QA evaluators in parallel), which Celery can facilitate
via task groups. While this speeds up execution, it introduces typical
concurrency risks. If those parallel tasks need to merge results, there’s a
risk of a partial failure deadlocking the process (Celery chords help by only
firing the next step after all tasks return, but if one task hangs, the
orchestrator waits indefinitely). The design includes toggles to enable/disable
parallel evaluation, indicating awareness that concurrency might be tuned for
safety. From an architectural view, as long as these parallel tasks operate on
isolated data (e.g. each evaluator works on a copy of the draft and writes its
own result via a port), domain purity is okay. But operationally, if they
inadvertently share domain state (say two tasks both update the same episode
record’s QA field), that’s a race condition. The mitigation is to aggregate
results in a single place (the orchestrator or a dedicated port) rather than
letting each parallel path mutate shared state. The **risk of orchestration
leakage** here is if the domain layer tried to handle merging or conflict
resolution – it really should be the orchestrator’s job to collect parallel
outcomes and decide. Celery’s orchestration must be configured such that one
task (e.g. a chord callback) performs the aggregation and routes the next step,
which aligns with LangGraph’s approach of an Aggregate node after parallel
evaluators. The system should also monitor for **orchestration timing issues**:
e.g. if a human-in-the-loop approval comes in *before* the orchestrator has
actually paused at the checkpoint, or if two approvals come in due to user
error, etc. These edge cases require careful design of locking and idempotency
(perhaps the first approval resumes the workflow and any subsequent ones are
ignored or logged). Without these safeguards, asynchronous flows can introduce
subtle bugs that break the expected hexagonal isolation (for example, an
approval event might trigger a domain action at the wrong time if not sequenced
properly with the orchestrator’s state).

## Enforcement Challenges at Scale

**Complex Graphs Testing Hexagonal Boundaries:** The Episodic system has strict
architectural enforcement (lint rules and tests for dependency direction).
However, as LangGraph workflows grow and increase in complexity, maintaining
those enforcement guarantees becomes harder. A large LangGraph StateGraph can
involve many nodes and transitions – effectively a mini-application within the
application. Ensuring that none of those nodes violates boundaries (e.g.
calling unauthorized modules) is challenging. Architecture tests typically
check static module dependencies, but if a LangGraph node dynamically imports
an adapter or uses a global that references an external service, it might slip
past static analysis. Furthermore, if the team adds new features to the
workflow under time pressure, there’s a temptation to put “just this one call”
directly in the node for expedience, especially if the port interface isn’t
readily available. Over time, these small exceptions can accumulate into
**boundary creep**, where the clean separation erodes. For example, imagine a
new requirement to send a Slack alert when a generation fails; a developer
might naively put a Slack API call inside a failure-handling node. This would
break hexagonal rules (Slack integration should be through an outbound port),
but if not caught, it becomes an architectural debt. The **enforcement
mechanisms can break down** when humans maintain the graphs: as the StateGraph
grows, it’s harder to visually spot a boundary violation, and the tests might
not specifically cover “inside graph execution” scenarios. It’s crucial to
extend architecture governance to LangGraph code – possibly by treating graph
definitions as code that must also adhere to import rules (e.g. only import
domain and port modules, not external SDKs). The design document’s stance is
that *LangGraph does not supersede the hexagonal model*, so the intent is
clear; the challenge is purely one of discipline and tooling at scale.
**Regular code reviews and automated checks** focusing on graph nodes can help
ensure that even as the workflow logic scales out, it remains a first-class
citizen of the hexagonal architecture rather than a place where rules are
inadvertently relaxed.

**Celery Task Encapsulation and Domain Isolation:** As the system scales, there
may be many Celery tasks representing various nodes or sub-processes (content
generation, QA checks, audio synthesis, etc.). If these tasks are not properly
encapsulated, the risk is that domain logic gets scattered and harder to
control. *Encapsulation* here means each task should have a single clear
responsibility and a defined interaction point with the domain. When tasks
start doing too much, they can create **operational brittleness**. For
instance, a task that orchestrates an entire subgraph internally might
duplicate logic that exists in the LangGraph definition, causing divergence. Or
a task might directly manipulate persistent state across different domain
aggregates (updating content and audio records together) which normally would
be handled in a domain service transaction. At scale, these patterns are
dangerous: they introduce hidden dependencies between tasks and domain data
that aren’t obvious. If a Celery task fails halfway through a multi-step
sequence it was handling on its own, the domain could be left in a
half-consistent state (since that task might have performed some updates and
not others). The Episodic design tries to avoid this by using **short,
checkpointed steps** – for example, generating content up to an approval point,
then pausing, then separately handling the approval and resumption. Each of
those steps can be a separate task or series of tasks. If a task is kept small
(e.g. “call LLM and save draft” as one task, “run QA evaluators” as another,
“aggregate results and decide route” as a third), it’s easier to maintain
domain isolation because each task goes through well-defined ports and commits
its results before handing off. **Enforcement breaks down if tasks overstep
their bounds**: for example, if a “monolithic” task is created to speed things
up, and it bypasses intermediate persistence or port calls, it may work
initially but will be fragile to failures and difficult to verify. Therefore,
at scale, a key discipline is to *modularize the Celery workflow* in tandem
with the LangGraph structure, so that each node or subgraph corresponds to a
cohesive unit of work that can be independently verified to respect hexagonal
boundaries.

**State and Persistence Complexity:** The use of **state persistence and
subgraphs** in LangGraph adds another layer of complexity to enforcement. Since
the StateGraph (and possibly subgraphs within it) maintain in-memory state that
gets serialized to the `workflow_checkpoints` table, there is a question of how
much of that state is purely domain data versus orchestration metadata.
Ideally, the checkpoint contains only the minimum needed to resume (e.g.
current node, iteration counters, perhaps partial results), while the canonical
source of truth for content, QA scores, audio files, etc., remains in the
domain models (Postgres tables for episodes, findings, audio assets). If
developers start storing domain data exclusively in the LangGraph state
(because it’s convenient to carry it through the graph), that data might bypass
domain validation or not get persisted in the normal tables. Enforcement of
hexagonal design would dictate that **important domain state changes go through
domain repositories**, not just live in the orchestration layer’s memory. The
design addresses this by logging QA results and iteration history in dedicated
tables (e.g. `generation_iterations`, `qa_findings`) alongside the checkpoint
blob. However, if the graph expands beyond a few dozen nodes, the temptation
might be to put more into the state blob and less in structured tables (since
LangGraph can serialize complex objects). This could lead to *boundary
blurring*, where some business data lives only in a LangGraph snapshot (an
adapter-level concern) rather than the domain model. Should that snapshot fail
to restore or get out of sync, the domain might not even be aware of some
intermediate decisions. Thus, one enforcement challenge is ensuring that
**state persistence remains a technical convenience and not a source of
truth**. Regular audits of what goes into the checkpoint state versus what is
persisted via ports can catch any drift. The design even includes audit links
from checkpoints to approval events, showing an intent to integrate the two
worlds; maintaining that link is essential so that every checkpoint corresponds
to a known domain event or status. In summary, as the workflows become more
elaborate, the team must **vigilantly enforce the hexagonal boundaries with
tooling and reviews**, since manual enforcement can falter under complexity.
The goal is that even as LangGraph and Celery enable rich, asynchronous
workflows, the fundamental architecture (ports, adapters, and a clean domain
core) does not degrade.

## Alignment of LangGraph Features with Hexagonal Principles

Despite the above challenges, many LangGraph features can be made to fit neatly
within a Hexagonal Architecture if used with discipline:

- **State Persistence via Ports/Adapters:** LangGraph’s checkpointing mechanism
  is aligned with hexagonal principles *when implemented as an adapter*. In the
  Episodic system, checkpoint data is stored in Postgres, which is accessed
  through the usual data access layer (likely via a repository port). The
  design explicitly mentions a `workflow_checkpoints` table for serialized
  graph state, keyed by episode ID. By treating checkpoint persistence as just
  another outbound persistence detail, the domain logic stays clean – the
  domain doesn’t need to know about how the graph state is saved, it just knows
  that workflows can resume. This separation means the LangGraph runtime uses
  an adapter to persist and retrieve state (e.g. a CheckpointRepository),
  preserving the port abstraction. The **alignment** here is good: it uses the
  database (an external resource) through well-defined tables and presumably
  via the same ORM/repository patterns as any other data, rather than some
  ad-hoc file or in-memory store. One caveat is to ensure the serialization
  format (possibly JSON or pickled Python objects in `state_blob`) doesn’t
  become a liability – e.g. if it’s pickled Python, that’s not
  language-agnostic and ties the implementation details into the data store. A
  better alignment with hexagonal thinking might be to serialize only
  domain-relevant portions in a neutral format (JSON of statuses, etc.), but
  since the checkpoint is largely an internal concern, this is a minor issue.
  Overall, state persistence via LangGraph can coexist with hexagonal
  architecture as long as it’s funneled through the persistence adapter and
  kept in sync with domain state (as done with linking checkpoints to episode
  status and approval events).

- **Subgraphs and Modular Workflows:** LangGraph supports structuring workflows
  possibly as subgraphs or nested flows (for example, the content generation
  and audio synthesis are separate graphs in this system). This modularity
  actually complements hexagonal design: each subgraph can correspond to a
  distinct **use case** or bounded context (content creation vs. audio
  rendering), each accessed via a port or application service. The Episodic
  system indeed has a *Content Generation Orchestrator* and a separate *Audio
  Synthesis Pipeline*, each employing LangGraph for their domain-specific
  workflows. In hexagonal terms, each of these orchestrators can be viewed as
  an **application service** coordinating domain operations through ports.
  Subgraphs should adhere to the same rule: they shouldn’t directly call each
  other’s internals in uncontrolled ways. Instead, one graph’s output becomes
  input to the next phase via a domain interaction (e.g. once content is
  approved, the domain triggers the audio pipeline via a port call). This
  appears to be how Episodic is designed: approved content is packaged and
  handed over, likely via a domain event or service call, to the audio
  generation process. Thus, subgraphs align well if they are treated as
  **separate adapters or services** connected by the domain’s outputs/inputs.
  Potential misalignment would be if subgraphs share a lot of global state or
  if one tries to directly invoke another’s steps (which would tangle their
  concerns). Fortunately, treating them hexagonally – as independent processes
  that communicate through defined interfaces (like a content-approved event) –
  preserves domain decoupling. Essentially, LangGraph’s ability to compose
  graphs can be harnessed in a hex architecture by letting each graph
  correspond to a distinct adapter driving domain operations, rather than one
  mega-graph that blurs all stages.

- **Conditional Routing as Business Rules:** The use of conditional edges in
  LangGraph to encode business logic is actually quite aligned with hexagonal
  principles, as long as the entire LangGraph orchestration is viewed as part
  of the **application logic** (the “inside” part of the hexagon that
  coordinates domain activities). For example, the decision to route a draft
  back for refinement if QA scores fall below a threshold is a *business rule*.
  In a traditional hex design, one might implement that in a service class
  method (if score < X then call refine). LangGraph simply provides a
  declarative way to represent that rule as a graph transition. The Episodic
  design embraces this: *threshold checks, retry limits, and escalation
  policies manifest as edge conditions rather than scattered if-else logic*.
  This can actually improve domain purity by localizing the workflow logic in
  one place (the graph definition) instead of potentially duplicating checks
  across multiple services. However, to remain faithful to hexagonal
  architecture, those conditions should use **domain data and domain services**
  to evaluate. That is, the graph might query “is the QA pass threshold met?”
  which should be answered by data obtained via the domain (e.g. an evaluator
  service returned a score via a port). As long as that’s the case – and it is,
  since the evaluators are LangGraph nodes that call QA ports and produce
  structured results – then the conditional routing is simply orchestrating
  domain outcomes. It adheres to the *Ports Remain the Integration Boundary*
  rule by not reaching outside for information; it uses what the domain has
  provided (scores, counts, flags) to make decisions. The alignment could break
  if someone coded an edge condition that relies on infrastructure (imagine a
  condition that directly checks an external service’s status or a file’s
  existence). But given the design’s emphasis that graphs invoke ports and not
  external APIs directly, this is likely avoided. In summary, conditional logic
  in LangGraph aligns with hex architecture **when it’s effectively
  implementing domain policy**. It should be seen as an extension of the
  domain’s decision-making, not separate from it. Tests and reviews can ensure
  that the same business rules are understood at the domain level (perhaps
  documented in the domain model or configuration) so the graph isn’t a silo of
  hidden logic.

- **Checkpointing and Long-Running Workflow Management:** Checkpointing is a
  feature that doesn’t typically appear in a standard hexagonal architecture,
  but it can be incorporated in a hex-compatible way. In hexagonal terms,
  checkpointing is part of the **application state management** – it’s about
  preserving the state of an ongoing use case. The Episodic system integrates
  checkpointing through its adapters: saving state to the
  `workflow_checkpoints` table and tying that to domain entities (episodes and
  approvals). This design means the domain is at least aware that a workflow
  can be paused and resumed (since an Episode can have a “pending approval”
  status and a linked checkpoint ID, perhaps), but the domain doesn’t need to
  know *how* the resume works internally. That’s handled by the orchestration
  engine reading from the checkpoint store. This separation keeps the domain
  **pure** in the sense that an `Episode` might have a status “Awaiting
  Approval” and that’s all the domain cares about; the details of how the
  partial content and state are stored are left to the adapter behind
  `workflow_checkpoints`. One alignment concern is to ensure that the **ports**
  cover the checkpointing actions too. For instance, there could be a
  `CheckpointPort` or simply the use of an existing persistence port to save
  the state blob, which is invoked by the LangGraph runtime. As long as that’s
  done, checkpointing doesn’t violate hex architecture; it’s an internal
  mechanism realized through an outbound adapter (the database). The benefits
  of checkpointing (resume on failure, pause for human-in-the-loop) are
  well-aligned with the needs of long-running domain processes, and indeed the
  domain design explicitly calls for resumable workflows and pause/resume
  functionality as a requirement. By **linking checkpoint events to domain
  events** (like approvals), they ensure that even though a lot of complex
  state is being managed, it’s still hooked into the domain’s notions of
  progress. The key is that checkpointing remains *orthogonal* to core business
  logic: it should be possible to reason about the domain process (e.g. content
  creation cycle) without delving into the checkpoint internals except when
  diagnosing failures. As implemented, the alignment seems strong –
  checkpointing is a supportive technical feature that doesn’t break the
  hexagonal structure, instead it augments the reliability of long-running
  domain workflows through a clearly defined adapter.

## Strategies to Preserve Architecture Discipline

Normative orchestration guardrails are defined in
[Orchestration guardrails](episodic-podcast-generation-system-design.md#orchestration-guardrails)
 and serve as the source of truth for port-only dependencies, checkpoint
payload boundaries, and idempotency requirements. This document focuses on
boundary risks and alignment, while implementation details should defer to the
system design guardrails.

Following those guardrails keeps LangGraph and Celery aligned with hexagonal
architecture by preserving port boundaries, isolating orchestration state from
domain state, and maintaining replaceable adapters.
