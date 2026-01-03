# Cost Inference and Management in LangGraph-Celery Agentic Systems

As agentic systems scale, tracking and controlling cost (especially LLM token
usage and compute time) becomes critical for sustainable operation. This
technical supplement builds on the **LangGraph + Celery** architecture,
focusing on methods to infer and manage costs across distributed agents. The
supplement addresses token usage tracking, per-task cost modelling, anomaly
handling, and feedback loops for budget enforcement. Port definitions for
`BudgetPort` and `CostLedgerPort` live in
[Orchestration ports and adapters](episodic-podcast-generation-system-design.md#orchestration-ports-and-adapters).
 The strategies below ensure that a **Generation 2** agentic system remains not
only intelligent and scalable, but also **cost-aware** and economically
efficient.

## 1. Token Usage and Retry Costs

**Tracking Token Usage per Interaction:** Modern LLM APIs (e.g. OpenAI,
Anthropic) return token usage statistics with each call. These can be recorded
to attribute cost to each agent **interaction**. Using LangChain’s callback
mechanism, tokens used for prompts and responses can be captured in real time.
For example, LangGraph supports the LangChain callback protocol, allowing
custom handlers to hook into LLM events. A callback’s `on_llm_end` event can
extract the `token_usage` from the model response and log or emit metrics
immediately. This allows tracking of how many tokens were consumed by each
node’s LLM call and estimating cost based on the provider’s pricing. In
practice, one can use built-in utilities like `get_openai_callback()` (which
wraps an OpenAI call to collect token counts and cost) or implement a custom
callback that pushes token metrics to a monitoring system (e.g. Datadog,
Prometheus). The code snippet below illustrates a simple callback handler:

```python
from langchain.callbacks.base import BaseCallbackHandler


class CostTrackerCallback(BaseCallbackHandler):
    def on_llm_end(self, response, **kwargs):
        usage = response.llm_output.get("token_usage", {})
        total = usage.get("total_tokens", 0)
        prompt = usage.get("prompt_tokens", 0)
        completion = usage.get("completion_tokens", 0)
        # Log or emit metrics for tokens and cost
        logger.info(
            "LLM call used %s tokens (prompt=%s, completion=%s)",
            total,
            prompt,
            completion,
        )
        metrics.gauge("llm.tokens.total", total)  # Example: send to metrics backend
```

By attaching such a callback to every LLM invocation (via the LangGraph config
or LangChain `callbacks` list), **token usage is tracked per task** and
centrally aggregated. This approach can be extended to *all* model
interactions. For instance, enabling `stream_usage=True` on OpenAI chat models
ensures the usage info is populated in the
callback([1](https://forum.langchain.com/t/how-to-obtain-token-usage-from-langgraph/1727#:~:text=Thanks%20for%20your%20help%2C%20I,I%20just%20needed%20to%20add)).
 In addition, structured logging can record each call’s token count alongside
task identifiers, making it easier to analyse cost per user query or per agent
run.

**Logging Retry Counts:** Agentic loops and Celery tasks may retry on failures
– often at the cost of additional tokens each attempt. **LangGraph’s state**
can include a runtime metadata field like `retry_count` to track how many times
a node or tool has been retried. Each cycle of the reasoning loop can increment
this counter, and the state (persisted via Redis) carries it forward across
retries. On the Celery side, each task execution has a `request.retries`
attribute indicating the attempt count. By logging the `retry_count` along with
token usage, the cumulative cost of retries can be measured. For example, if a
tool call fails and the agent “repeatedly retry[s] a failed tool” in a loop,
every attempt’s token usage should be added to the total cost. Observability
middleware can note each retry event (perhaps via Celery task signals or
LangChain’s `on_tool_error` callback) and tally how many extra tokens were
consumed due to retries. An internal **retry budget** can also be enforced
(e.g. allow at most N retries before aborting) to prevent runaway costs from
infinite retry loops.

**Observability for LLM Cost Metrics:** Integrating cost tracking into the
observability stack is key for real-time insights. The architecture supports
plug-in **middleware** to monitor usage. For instance, LangChain’s new
middleware layer can intercept model calls before execution – a `before_model`
hook can inspect the current token budget or usage and decide to proceed or
not. This same hook (or a post-call hook) logs token counts to monitoring
services. The system can export metrics such as *tokens_per_request*,
*tokens_per_user_today*, or *LLM_call_rate* to dashboards. Tools like
**LangSmith** (LangChain’s observability platform) automatically record token
usage and cost for each trace, giving a unified view of spend across the entire
application(
[2](https://docs.langchain.com/langsmith/cost-tracking#:~:text=Building%20agents%20at%20scale%20introduces,This%20guide%20covers)).
 In production, one might send these metrics to a time-series database
(Prometheus, CloudWatch) or use LangSmith/Langfuse tracers to visualize
per-task costs. By monitoring these metrics, operators can detect anomalies
(e.g. a sudden spike in tokens/minute) and also enforce rate limits. For
example, concurrency in LangGraph should be configured with awareness of rate
limits: if multiple nodes call an API in parallel, they might hit provider
limits
faster([3](https://aipractitioner.substack.com/p/scaling-langgraph-agents-parallelization#:~:text=This%20shift%20creates%20several%20practical,implications)).
 Tracking the call rate via metrics allows dynamic throttling – e.g. if calls
per minute approach the API’s cap, new calls can be delayed or queued to avoid
429 errors. Overall, a combination of **callback logging and external
monitoring** provides transparency into token usage, retry overhead, and
adherence to usage caps.

## 2. Per-Task Cost Modelling

**Attributing Cost to Individual Tasks:** In a distributed agent, each Celery
task or LangGraph node can incur cost – whether by calling an LLM, performing
embeddings, or using GPU time. It’s crucial to assign and record these costs at
the **granular task level**. One approach is to instrument the code that calls
external APIs: whenever a task calls an LLM, capture the token usage and
compute the dollars spent for that call (using the provider’s pricing). This
cost can then be attached to the task’s result or sent to a central store. For
example, if a Celery task uses the OpenAI API, the response includes a usage
breakdown (`"prompt_tokens"`, `"completion_tokens"`); the task can calculate
cost = tokens * price and log it. Likewise, for tasks performing heavy
computation on a cloud GPU, cost can be estimated by tracking the task’s
execution time and multiplying by an hourly rate for that machine type. These
**internal hooks** can use Redis or a database to store the intermediate costs.
A common pattern is to write each task’s cost to a Redis hash or a **sorted
set** for the agent run, keyed by task ID or node name (Redis’s sorted sets or
time-series structure can record task costs with timestamps). Storing per-task
entries allows aggregation later (sum per run or per user) and supports
querying where the budget was spent (e.g. one slow tool consumed 80% of the
cost).

**Redis-Backed Cost Fields in State:** Because LangGraph treats the agent state
as the single source of truth (persisted via Redis between steps), a **cost
field within the state** can accumulate as the agent proceeds. For example, the
state schema can have `total_tokens_used` and `total_cost_usd` fields. After
each node execution (each superstep), the node updates these fields in the
returned state delta. LangGraph’s checkpointing will merge these updates into
the global state. This means every subsequent node is aware of the **cumulative
cost so far**. If the agent spawns subgraphs or parallel branches, careful
handling is needed: each branch might update the cost independently, so a
**reducer** function should sum the contributions when merging states at
synchronization points. LangGraph’s reducer concept ensures that parallel
updates merge deterministically, so token counts are added rather than
overwritten. Propagating cost in state provides *cross-step visibility*: e.g. a
planning node could decide not to launch an expensive tool if `total_cost_usd`
is already near the limit. It also means that if execution is suspended and
resumed, the cost tally persists – avoiding double-counting if a workflow is
restarted from a checkpoint.

**Correlating with External Billing Systems:** Internal tracking should be
reconciled with external billing to ensure accuracy. Each OpenAI call, for
instance, generates an entry in OpenAI’s usage logs. By logging the OpenAI
request IDs or timestamps along with each task, one can later cross-verify
against the provider’s dashboard or usage API. In practice, LangSmith or custom
scripts can aggregate internal usage records and compare them to OpenAI’s
monthly summary (to catch any discrepancies or missed calls). For GPU or other
infrastructure costs, integration with cloud billing is useful: e.g. using AWS
Cost Explorer or GCP Billing export to attribute a dollar cost to the VM hours
consumed by agent tasks. A simpler approach is to pre-compute cost metrics for
known operations – for example, if using an embedding API at $0.0001 per 1K
tokens, the task can calculate cost directly from tokens processed. The key is
to **tie each cost to a task or user**. Storing a `(user_id, task_id, cost)`
tuple in a database for every significant action creates an audit trail of
where the budget goes. These records can feed into dashboards or reports (e.g.
cost per user session, cost per tool type, etc.). This per-task modelling also
helps identify expensive branches in the agent’s reasoning: analysis may reveal
that a particular tool (like a web scraper or a data analysis sub-agent)
consistently costs more than others, informing optimization or caching
decisions.

**Cross-Task Cost Visibility:** With cost attribution in place, the system can
**surface cost data at various levels**. For example, when an agent completes a
complex multi-step job, it can report: “Total tokens used: X (~$Y) across N
steps.” Such reporting is possible because each step contributed to an
aggregate state. Similarly, cost data can be threaded into external UIs or logs
– for instance, attaching the cost of each answer in a chatbot’s response
metadata. Internally, having cost in the state allows nodes to make cost-aware
decisions (e.g. a node decides to use a cheaper model if the cost so far is
high). This ties into feedback loops discussed later. In summary, by leveraging
**Redis-backed state** and **LangChain callbacks**, this achieves fine-grained
cost modelling: every task and branch is instrumented for cost, and the agent
carries an awareness of its spending as it operates.

## 3. Black Swan Cost Events

Even with careful planning, unexpected **cost spikes** can occur – the “black
swan” events where an agent runs amok or external conditions trigger excessive
spending. Identifying and mitigating these anomalies is crucial in production.

**Infinite Loops and Unbounded Iterations:** Agentic loops (the
reasoning-action cycle) are powerful but can misfire. A logical bug or an
ambiguous goal might cause an agent to loop endlessly, calling the LLM or tools
repeatedly without making progress. This can **burn through tokens and API
calls** rapidly. To detect such scenarios, the system should implement **loop
counters and timers**. For instance, LangGraph’s cyclic graph design allows an
agent to retry tools or refine queries in loops, but a **max iteration limit**
(e.g. no more than 5 full cycles for a given task) can be set and the count
tracked in state. If `retry_count` or loop count exceeds a threshold, the agent
can break out and escalate (perhaps returning a partial answer or an apologetic
response to the user). Similarly, if an agent has consumed an unusually high
number of tokens in a single conversation (e.g. 5x the normal usage for a
query), that could indicate a stuck loop – this can trigger an alert or
automatic halt. Instrumentation wise, logging each loop iteration with an ID
and monitoring if the same agent run ID appears too many times in succession
helps flag infinite loops. **Time-based guards** are another safety net: using
Celery’s task time limits (soft and hard time limits) to kill tasks that run
too long can stop runaway loops that fail to yield within a reasonable time.
While timeouts alone don’t track tokens, they prevent a hung process from
accumulating unlimited cost.

**Unexpected Parallel Fan-Out:** One advantage of LangGraph is the ability to
execute nodes in parallel for
speed([3](https://aipractitioner.substack.com/p/scaling-langgraph-agents-parallelization#:~:text=What%20is%20parallelization%20in%20LangGraph%3F)
 )(
[3](https://aipractitioner.substack.com/p/scaling-langgraph-agents-parallelization#:~:text=This%20shift%20creates%20several%20practical,implications)).
 However, if misused, parallel fan-out can spawn a large number of simultaneous
calls, consuming resources and quota in a burst. For example, an agent might
naively launch dozens of search queries or sub-agents at once when a smaller
number would do. To control this, LangGraph provides a `max_concurrency`
configuration to cap how many nodes run in
parallel([3](https://aipractitioner.substack.com/p/scaling-langgraph-agents-parallelization#:~:text=,off)).
 Setting reasonable limits (based on API rate limits and budget) prevents an
explosion of parallel tasks from *overwhelming quotas*. At the infrastructure
level, the message broker (RabbitMQ) can also help: tasks can be routed into
separate queues with limited worker processes for certain expensive operations,
effectively throttling how many run at once. Monitoring plays a role in
detecting abnormal fan-out: if the task queue length spikes or if a single user
triggers an unusually high number of simultaneous tasks, an alert should fire.
In practice, one can watch RabbitMQ’s queue metrics or use Celery events to see
how many tasks a single request spawns. Should a *fan-out anomaly* be detected
(say an agent spawning 100+ tasks where normally 5 is expected), the system
could dynamically intervene – e.g. temporarily pause new task dispatch or push
excess tasks to a **dead-letter queue** for later review instead of executing
immediately.

**Dead Letters and Failure Alerts:** A **Dead Letter Queue (DLQ)** is a proven
pattern for catching messages (tasks) that cannot be processed normally. In
this architecture, RabbitMQ is configured with *Dead Letter Exchanges* to
capture failed or expired tasks. For example, if a Celery task raises a special
exception (like `Reject` with requeue=False) after exceeding retry attempts,
RabbitMQ will route this task message to a designated dead-letter queue rather
than discarding it. This pattern can be leveraged for cost anomalies: tasks
that hit a cost guard (like a BudgetExceeded exception) or that fail due to too
retries can be shunted to a DLQ. A background service or admin process can
consume from the DLQ to inspect what went wrong – often these will be the black
swan events. By examining dead-lettered tasks, one might find patterns: e.g. a
particular tool caused an infinite loop, or a user input consistently triggers
a pathological case. Moreover, the system can raise immediate **alerts** when
tasks land in the DLQ or when failure rates exceed a threshold. Best practices
include setting up notifications if, say, more than X tasks per hour go to
dead-letter (indicating a systemic
issue)([4](https://blog.gitguardian.com/celery-tasks-retries-errors/#:~:text=A%20Deep%20Dive%20into%20Celery,This)).
 Additionally, **threshold guards** can be baked into the code: for instance,
if an agent’s `total_cost` in state exceeds a safe limit, have the next node
intentionally throw an exception to halt the process (this exception would be
caught and could route to DLQ or an error handler). This proactive fail-fast
approach, while resulting in a controlled failure, is preferable to silently
incurring exorbitant costs.

**Mitigation Patterns:** Upon detecting an anomaly, **mitigation strategies**
should trigger to limit damage:

- **Rate Limiting:** Globally throttle the agent’s actions. For example, reduce
  the frequency of LLM calls by introducing delays or using a token bucket
  algorithm per user. If an infinite loop is making rapid-fire calls, a rate
  limiter will slow it down and give an opportunity for other monitors to
  intervene (or for the loop to self-terminate when hitting other
  limits)([3](https://aipractitioner.substack.com/p/scaling-langgraph-agents-parallelization#:~:text=This%20shift%20creates%20several%20practical,implications)).

- **Graceful Degradation:** Scale back the task complexity dynamically. If a
  particular workflow is consuming too many resources, the system can switch to
  a fallback mode – e.g. use a smaller/cheaper model for subsequent calls,
  summarize intermediate results to shrink context size, or skip non-critical
  steps. The agent might, for instance, stop attempting a failing tool and
  return whatever partial information it has. Graceful degradation ensures the
  user still gets *some* outcome rather than a hard failure, all while capping
  additional cost.

- **Capped Retries and Circuit Breakers:** Ensure every automated retry has an
  upper bound. Celery tasks should be configured with `max_retries` and
  exponential backoff so they won’t retry indefinitely. Similarly, in an agent
  loop, use a **circuit breaker** pattern: after N failures of a particular
  tool or API, stop calling that tool for a cool-off period or switch to an
  alternative method. This prevents repetitive costs when an external
  dependency is down or a tool is consistently throwing errors. The state can
  carry a flag like `tool_blacklist` or increment an error count that, if too
  high, causes the agent to avoid that tool going forward.

- **Anomaly Detection & Alerting:** In addition to rule-based thresholds, more
  advanced anomaly detection can be applied to cost metrics. For example, using
  historical usage data, one can set up alerts for “out of bounds” cost per
  user or per request. If an agent normally uses ~1,000 tokens per query and
  suddenly one uses 50,000, an anomaly detector (or simply a static threshold)
  can page an engineer or trigger automated containment. Integration with APM
  tools (Datadog, New Relic) or custom scripts can automate this. The system
  might automatically suspend an offending user’s sessions if their usage
  deviates wildly (assuming perhaps a misuse or a bug is at play).

- **Fail-safes in Workflow Design:** Finally, incorporate fail-safe nodes in
  the LangGraph workflow. For example, after a loop, include a check node that
  verifies the loop produced a result or didn’t exceed a cost threshold; if it
  did, route to a cleanup/abort branch. Designing the graph with these
  checkpoints ensures that even if the agent logic doesn’t realize it’s stuck,
  the architecture will catch it and cut off the expensive process.

By diligently monitoring and constraining these *black swan* events, the system
stays **resilient against runaway costs**. It’s a combination of good design
(limits and checks) and runtime governance (metrics, alerts, DLQs) that keeps
the agentic system economically stable even under unexpected conditions.

## 4. Cost-Aware Feedback Loops

In a scalable agent, **cost-awareness must be fed back into the control loop**.
This means the system should not only track costs but actively use that
information to make runtime decisions about continuing, altering, or halting
the agent’s activities.

**Dynamic Budget Checks (Middleware Hooks):** A powerful technique is to
integrate budget checks at the points of decision-making. LangChain’s
middleware allows insertion of logic before model calls are executed. Using a
*before_model* hook (or LangGraph’s equivalent hook node), one can inspect the
user’s remaining budget *before* an LLM invocation is made. For instance,
suppose each user has a daily token or dollar budget. The middleware can sum
the tokens used so far today (from Redis or a usage database) and compare it to
the cap. **If the budget is breached (or the next call would exceed it), the
hook can intercept** and abort the call, e.g. by throwing an exception or
returning a predefined “quota exceeded” message. This prevents the expensive
API call entirely, saving cost at the last moment. Such a mechanism essentially
creates a **feedback loop** where the agent continuously queries, “Have I spent
too much?” before proceeding. The snippet from the original design highlights
this approach: *“If a user exceeds a daily budget, the before_model hook can
throw an exception or return a canned 'Quota Exceeded' response”*. Implementing
this in practice might look like:

```python
def before_llm_call(user_id, prompt):
    used_today = usage_tracker.get_tokens_used(user_id, period="today")
    if used_today >= DAILY_TOKEN_LIMIT:
        raise BudgetExceededError(
            f"Daily budget reached for user {user_id}"
        )
```

By tying this into the agent’s call chain (either via middleware or at the
application API layer), the system **refuses to execute tasks** that would push
cost past thresholds.

**Pausing or Halting Loops on Budget Exhaustion:** In longer-running chains or
loops, it’s not enough to check at the start; the agent should continually
reevaluate its budget mid-execution. Here, the **propagated cost state**
becomes useful. Each step can examine `state.total_cost_usd` (or tokens) and
compare against a max budget. If the threshold is exceeded, the agent can
transition to a special termination node – for example, a node that
consolidates what has been done and gracefully terminates the loop. LangGraph
being a graph state machine allows such conditional transitions. Alternatively,
an exception can be raised within the LangGraph executor to unwind the loop.
Because the state is checkpointed every step, halting the loop still preserves
all progress up to that point (and the partial results can be returned or
logged). In Celery terms, one could also revoke or cancel scheduled tasks if
the budget runs out in the meantime (though coordinating that with LangGraph’s
logic needs careful design). The key idea is **early exit**: rather than
blindly finishing all planned steps and then realizing the budget was overrun,
the agent continuously self-monitors and stops when it should. This might
result in an incomplete plan execution, but it’s cost-optimal.

**Per-User and Per-Agent Budgets:** Budget enforcement can operate at multiple
scopes:

- *Per-user daily/monthly spend caps:* Each user (or API client) might have a
  quota (e.g. 100k tokens per day). The system maintains a usage counter per
  user that resets each day. This can be implemented via a simple Redis counter
  with TTL (expiring every 24h) or a more persistent store for monthly totals.
  Every time a task uses tokens, it increments the user’s counter. If a new
  request comes in and the counter is above the limit, the request is refused
  immediately with a message like “Usage limit reached.” This ensures no single
  user can drive unlimited costs. It also encourages users to prioritize
  queries (or purchase a higher tier for more usage, if applicable).

- *Per-agent or per-session budgets:* In some cases, a budget can be allocated
  for a single session or agent instance. For example, a particular complex job
  might be allowed to use at most $0.50 of API calls. The agent’s state can
  carry this budget, and as it works through the job, it deducts cost. Once the
  budget is nearly exhausted, the agent can decide to wrap up. This is useful
  for **long-running autonomous agents**: they won’t run forever if they’re not
  efficient. They either succeed within budget or stop and report back.
  Technically, this could be enforced by initializing
  `state.remaining_budget = X` and decrementing it on each step; if it hits 0,
  a conditional edge directs to a termination sequence.

**Feedback into Decision-Making:** A sophisticated agent could modify its
strategy based on budget feedback. For instance, if the budget remaining is
low, the agent could favor shorter answers or avoid expensive tools. If an
agent knows it has only 1000 tokens left, it might skip a time-consuming
brainstorming step and directly provide a concise answer. Implementing this
requires the agent’s policy (perhaps encoded in the prompt or logic) to be
aware of a `budget_left` variable. This can be passed via the prompt context
(e.g. “Limited budget remaining, prioritize essential actions.”). On the system
side, one can inject such hints using LangChain middleware that adds a note in
the prompt when budget is tight (similar to how dynamic context injection can
add system instructions).

**Enforcement Techniques:** When a budget breach is detected, the system’s
response should be **immediate and clear**. Common techniques include:

- **Graceful refusal:** As mentioned, return a canned response to the user
  indicating the budget has been exhausted (so the user is informed why the
  task didn’t complete). This could be handled in the application layer or by
  the agent itself if it’s capable of outputting such a message.

- **Suspension:** In multi-turn scenarios, the agent’s session can be suspended
  until more budget is allocated. The state (with all progress and context) can
  be saved, and an external trigger (like admin intervention or next day quota
  reset) could resume it. LangGraph’s checkpointing and resumability make this
  feasible – the agent’s loop pauses at a checkpoint when out of funds, and
  resumes later when funds are available. This is analogous to an orchestrator
  putting a process to sleep until a resource is replenished.

- **Differentiated limits:** The system can enforce different budgets for
  different actions. For example, cheap tools may be allowed to continue while
  blocking further LLM calls. The agent could continue in a limited mode if it
  has non-LLM steps that are free. Achieving this could involve tagging nodes
  with expected cost and checking those specifically. For instance, a node that
  uses a GPT-4 call must verify budget, whereas a local database lookup node
  might bypass the check.

**Budget Enforcement Implementation:** A **central budget service** or utility
can be maintained. This could be as simple as a function
`check_and_update_budget(user, cost)` that atomically checks current usage and
either permits the new cost (updating the total) or denies it if it would
exceed the cap. Using Redis INCR with a limit can do this atomically for
distributed workers. For daily budgets, the key can reset daily (with Redis
EXPIRE). For monthly, a rolling window or a timestamped log might be needed.
The system should handle concurrency – if multiple tasks end at the same time,
ensure they don’t all overspend together (hence an atomic check or a mutex
around budget updates).

By incorporating these cost-aware feedback loops, the agent system effectively
gains a **financial conscience**. It balances its autonomy with an
understanding of limits, ensuring that it *thinks twice* before every expensive
operation. This not only prevents surprises on the cloud bill, but it also
aligns the agent’s behaviour with user quotas and organizational cost policies.
The result is an agentic platform that is **robust, scalable, and fiscally
responsible** – it can leverage powerful LLM capabilities while intelligently
managing and limiting the costs of its computations.

**Sources:**

- Murro, G. *Architecting Scalable Agentic Systems: A Unified Blueprint for
  Python*, sections 2 & 7 – Integration of LangGraph (cognitive kernel) with
  Celery and use of middleware for cost control.

- *LangChain Callback and Middleware Docs* – Illustrations of custom callback
  handlers capturing token usage and implementing rate limit logic.

- *LangChain Forum – Token Usage in LangGraph* – Discussion on enabling usage
  tracking (e.g. `stream_usage=True`) to obtain token counts for agent
  calls([1](https://forum.langchain.com/t/how-to-obtain-token-usage-from-langgraph/1727#:~:text=Thanks%20for%20your%20help%2C%20I,I%20just%20needed%20to%20add)).

- *A.I. Practitioner – Scaling LangGraph Agents (Part 4)* – Notes on parallel
  execution trade-offs, including concurrency limits to avoid rapid quota
  exhaustion(
  [3](https://aipractitioner.substack.com/p/scaling-langgraph-agents-parallelization#:~:text=This%20shift%20creates%20several%20practical,implications)).

- *LangSmith Documentation – Cost Tracking* – Describes automatic recording of
  LLM token usage and unified cost views for monitoring and
  alerts([2](https://docs.langchain.com/langsmith/cost-tracking#:~:text=Building%20agents%20at%20scale%20introduces,This%20guide%20covers)).

- Stack Overflow – *Routing Celery failed tasks to Dead Letter Queue* – Best
  practices on using RabbitMQ Dead Letter Exchanges to capture failed tasks for
  analysis.
