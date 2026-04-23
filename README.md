<div align="center">
  <img src="spice_logo.png" alt="spice" width="500">
  <h1>Spice — The Decision Layer Above Agents</h1>

  
  <p>
    <strong>English / <a href="./README_zh.md">中文</a></strong>
  </p>
  
  <p>
    <a href="https://pypi.org/project/spice-runtime/"><img src="https://img.shields.io/pypi/v/spice-runtime" alt="PyPI"></a>
    <img src="https://img.shields.io/badge/python-≥3.11-blue" alt="Python">
    <img src="https://img.shields.io/badge/license-MIT-green" alt="License">
    <a href="./COMMUNICATION.md"><img src="https://img.shields.io/badge/WeChat-Group-C5EAB4?style=flat&logo=wechat&logoColor=white" alt="WeChat"></a>
    <a href="https://discord.gg/DajVWWNMfE"><img src="https://img.shields.io/badge/Discord-Community-5865F2?style=flat&logo=discord&logoColor=white" alt="Discord"></a>
  </p>
  
</div>


> Agents can **execute**. 

> But they don’t know what to do next.

**Spice** is a **decision-layer runtime — a brain above agents.** inspired by **the rise of execution agents like OpenClaw** and the idea of **world model**.

While execution agents (Claude Code, OpenClaw, Codex) are getting better at doing things,  
Spice focuses on the missing layer:

👉 **What should be done next — and why.**

---

## 🎬 Demo of Spice：
To gain a more intuitive understanding of Spice, 

please visit our carefully prepared demo about conflicts between life and work events: [Spice-live-demo](https://www.bilibili.com/video/BV1rhDRB7Ehn/)

---
### Demo Video

1. Bilibili

<div align="center">
<a href="https://www.bilibili.com/video/BV1rhDRB7Ehn/" target="_blank"><img src="spice_demo.PNG" alt="Spice Demo Video" width="75%"/></a>

Click the image to watch the full demo video of using Spice to handle conflicts between the digital and physical worlds.
</div>

---

2. YouTube

<div align="center">
<a href="https://youtu.be/SNDsimjlvM4" target="_blank"><img src="spice_demo2.PNG" alt="Spice Demo Video" width="75%"/></a>

Click the image to watch the full demo video of using Spice to handle conflicts between the digital and physical worlds.
</div>

---



## ⚡ Why it matters

Today, we have powerful agents that can do almost anything:

- write code  
- analyze data  
- automate workflows

But when you sit down to use them, you still face the same problem:

**What should I do next?**

That’s the hard part.

The real bottleneck is:

> **Decision-making.**

Spice is designed to solve that.

---

## 🧠 What is Spice?

Spice provides a structured cognitive loop inspired by the concept of world model :

perception → state model → simulation → decision → execution → reflection

It allows AI systems to:

- understand context (state)
- reason about possible futures (simulation)
- make structured decisions (decision)
- delegate actions to agents (execution)
- learn from outcomes (Decision Evolution)

  
---


## 🧩 Example: from idea → decision → next step 

### 1. Scenario 

> "I want to quickly build a lightweight tool for a small group of friends."

A simple, real-world goal with clear constraints


### 2. What Spice does

#### Input: Real-world intent with constraints

![demo1](./demo1.png)

<p align="center"><em>starts from intent</em></p>


---


#### Decision → Comparison

![demo2](./demo2.png)

<p align="center"><em>From options → structured decision space</em></p>


---


#### Commitment → Next step

![demo3](./demo3.png)


<p align="center"><em>Decision becomes action</em></p>


---



### 3. About execution (next step)

Spice focuses on the **decision layer**.

In a full workflow, the selected decision can be passed to external agents (e.g. codex and claude code) for execution.

This example stops at decision + next step.

➡️ Next, we will take this exact scenario and connect it to an external agent to **actually build the tool end-to-end**.

> Decision → Execution → Outcome → Reflection

<sub>This is the full loop Spice is designed to enable.</sub>



---


## 🌍 Domain-agnostic Runtime

The underlying model is domain-agnostic.

Spice is a **general decision runtime** that can be applied to any domain where:

- there is context (state)
- there are possible futures (simulation)
- decisions need to be made
- actions can be executed by agents

This includes:

- individual decision making 
- product and business strategy  
- software development workflows  
- operations and automation systems  

Spice is not limited to one use case.

It is a **foundation for building decision systems.**


---


##  👨‍🔧 Spice: Decision Layer Architecture

<p align="center">
  <img src="spice_structure.png" alt="spice structure" width="800">
</p>


---

## 🧭 User Interface: decision.md

The main user-facing interface in Spice is `decision.md`.

Users configure how Spice should compare candidate decisions by editing:

```text
.spice/decision/decision.md
```

This file is decision guidance. It is not memory, not a prompt dump, not an execution runbook, and not an agent workflow.

Runtime-active in v1:

- **Primary Objective** — the dominant optimization direction
- **Preferences / Weights** — score dimensions used during candidate comparison
- **Hard Constraints** — veto boundaries, when supported by the active policy/domain adapter
- **Trade-off Rules** — a constrained executable subset for resolving conflicts

Runtime-inactive in v1:

- **Decision Principles**
- **Evaluation Criteria**
- **Reflection Guidance**

The bundled default profile is a starter template. Users should edit their local `decision.md`; they should not edit support JSON as normal configuration.

Runtime support comes from the active policy or domain adapter. The copied support JSON is only for explain/demo/debug flows.

See `docs/decision.md` and `docs/decision_quickstart.md` for the support contract and quickstart.


---


##  ⚙ Install(Extend the Spice framework to other domains)

**Install from source (latest features, for development)**

```bash

git clone https://github.com/Dyalwayshappy/Spice.git
cd Spice

python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

pip install -U pip
pip install -e .
```

**Install from PyPI (stable, recommended)**

```bash
pip install spice-runtime
```

##  Upgrade to latest version

```bash
pip install -U spice-runtime
spice --help
```





---

## 🚀 Quick Start

The fastest way to experience Spice is the integrated quickstart:

```bash
spice quickstart --force
```

This starts from the bundled example domain and walks through the full Spice boundary:

```text
decision.md -> example domain runtime -> OpenRouter/local LLM -> optional SDEP execution boundary
```

It creates:

```text
.spice/quickstart/                         # deterministic core-loop example
.spice/quickstart_llm/                     # LLM-ready example runtime
.spice/decision/decision.md                # user-editable decision profile
.spice/decision/support/default_support.json
```

The generated example runs immediately with deterministic defaults. No API key is required for the first run.

### What The Quickstart Shows

```text
perception -> state -> decision -> execution -> reflection
```

The default quickstart proves that Spice can:

- load a decision profile
- validate and explain decision guidance
- run a domain-specific decision loop
- attach model advisory through an explicit provider
- keep execution external, pluggable, and auditable through SDEP


The bundled quickstart domain is an example. Real projects define their own `DomainSpec`, domain adapter, supported score dimensions, constraint checks, and SDEP execution boundary.

### Core-only Mode

If you only want to see the deterministic Spice core loop:

```bash
spice quickstart --core-only --force
```

This creates only:

```text
.spice/quickstart/
```

Use this when you want to inspect the smallest loop without LLM wiring or `decision.md` setup.

### 1. Edit decision.md

The main user-editable file is:

```text
.spice/decision/decision.md
```

The safest first customization is the scoring weights:

```md
Preferences:
- outcome_value: 0.40
- risk_reduction: 0.25
- reversibility: 0.20
- confidence_alignment: 0.15
```

For example, to prefer safer and more reversible decisions:

```md
Preferences:
- outcome_value: 0.25
- risk_reduction: 0.35
- reversibility: 0.25
- confidence_alignment: 0.15
```

`decision.md` configures decision selection. It is not memory, an agent prompt, or an execution script.

### 2. Validate And Explain

```bash
spice decision explain .spice/decision/decision.md --support-json .spice/decision/support/default_support.json
```

Use `--json` for structured output.

The explanation shows:

- loaded artifact id/version
- validation status
- runtime-active and runtime-inactive sections
- supported and unsupported score dimensions
- supported and unsupported hard constraints
- supported and unsupported trade-off rules

Runtime support comes from the active policy or domain adapter. Editing support JSON alone does not add runtime capability.

### 3. Use OpenRouter

Attach a hosted model to the generated example runtime:

```bash
export OPENROUTER_API_KEY="your-openrouter-api-key"
export SPICE_DOMAIN_MODEL="openrouter:anthropic/claude-3.5-sonnet"
python .spice/quickstart_llm/run_demo.py
```

Optional OpenRouter attribution headers:

```bash
export SPICE_OPENROUTER_SITE_URL="https://github.com/Dyalwayshappy/Spice"
export SPICE_OPENROUTER_APP_NAME="Spice"
```

### 4. Use A Local Or Custom Model

```bash
SPICE_DOMAIN_MODEL="ollama run qwen2.5" python .spice/quickstart_llm/run_demo.py
```

Model selection is explicit:

- `deterministic` uses the built-in deterministic provider
- `openrouter:<model-id>` uses the OpenRouter provider
- any other value is treated as a subprocess command

Any subprocess command must read a prompt from stdin and return structured model output. Spice does not auto-load hidden model configuration in v1.

### 5. Use decision.md In Runtime Code

The quickstart shows the file-based configuration flow. In application code, attach the profile explicitly:

```python
from spice.decision import guided_policy_from_profile

policy = guided_policy_from_profile(
    base_policy,
    ".spice/decision/decision.md",
)
```

The active policy/domain adapter remains the source of runtime capability.

### 6. Connect An External Execution Agent

Models help Spice reason, simulate, and advise. External agents execute when you choose to connect them.

```text
Decision -> ExecutionIntent -> external agent -> ExecutionResult -> Outcome -> Reflection
```

Run the included SDEP execution demo:

```bash
python examples/sdep_agent_demo/run_sdep_adapter_demo.py
```

For production integrations, SDEP is the execution boundary:

- Spice produces a structured execution intent
- external agents execute through SDEP
- execution results return as structured outcomes
- Spice absorbs decision-relevant outcomes without owning execution internals

Mock and direct command executors are local test/debug utilities. They are not the recommended public execution path.

Execution is optional and pluggable, but when Spice talks to external agents, SDEP is the canonical boundary. It is not mixed into `decision.md`.


### 7. Latest User Experience Flow

```text
1. clone and install Spice
2. run spice quickstart
3. edit .spice/decision/decision.md
4. validate with spice decision explain
5. choose OpenRouter, deterministic, or local subprocess model
6. run the example domain
7. replace the example domain with your own DomainSpec/domain adapter
8. optionally connect external execution agents through SDEP
```



---

## 🔁 Spice + Hermes Reference Integration

Spice includes a working reference integration with Hermes to demonstrate the full decision-to-execution loop.

```text
WhatsApp / GitHub signal
-> Spice-Hermes Bridge
-> Spice decision_hub_demo
-> WorldState / ActiveDecisionContext
-> structured simulation
-> decision.md guided selection
-> SDEP execute.request
-> Hermes/Codex execution
-> SDEP execute.response
-> execution_result_observed
-> Spice state update
```

This integration demonstrates the intended separation:

- **Spice** handles state, simulation, decision selection, and decision evolution
- **Hermes** handles messaging ingress and execution
- **SDEP** is the execution boundary between decision and execution
- **Bridge** converts external signals and execution outcomes into structured Spice observations

This is a reference integration, not Spice core.

Start here:

- `spice-hermes-bridge/README.md` — run the local WhatsApp + Hermes + Spice loop
- `examples/decision_hub_demo/` — simulation-driven decision demo domain
- `examples/sdep_quickstart/` — build an SDEP executor
- `schemas/sdep/v0.1/` — SDEP JSON Schemas
- `examples/sdep_payloads/v0.1/` — SDEP example payloads

Use this section to understand how Spice sits above execution agents without becoming an execution framework.


---



## ✨ Features

Spice transforms your world into a structured decision system.

It enables a new way to think, decide, and act:



1. **Perception**  
   Understand your world and extract meaningful signals  

2. **State Modeling**  
   Turn it into a structured decision model

3. **Simulation**  
   Explore possible futures before taking action  

4. **Decision**  
   Compare trade-offs and then give you decision-making assistance. 

5. **Execution (optional)**  
  Delegate actions to external agents (e.g. Claude Code, Codex)  

6. **Reflection**  
   Learn from outcomes and continuously improve decisions


---



## 🔗 SDEP (Spice Decision Execution Protocol)

SDEP is a protocol-layer specification for connecting a decision system with external execution agents.

It defines a **standardized boundary** between:

- **Decision (what to do)**

- **Execution (how it is done)**

---

### Start Here

If you want to understand or implement SDEP, start from:

- **Protocol spec**: `docs/sdep_v0_1.md`
- **JSON Schemas**: `schemas/sdep/v0.1/`
- **Example payloads**: `examples/sdep_payloads/v0.1/`
- **Executor quickstart**: `examples/sdep_quickstart/`
- **Wrapper template**: `examples/sdep_wrapper_template/`

SDEP v0.1 defines:

- `execute.request`
- `execute.response`
- `agent.describe.request`
- `agent.describe.response`

The schemas validate the public wire contract. Domain-specific payloads such as `execution.parameters`, `execution.input`, `metadata`, and `traceability` remain open extension objects.

---

### 1. Positioning

Modern agent systems often follow patterns like ReAct or reinforcement learning loops, where:

reasoning and acting are interleaved inside a single loop

execution is implicit, embedded in the agent runtime

SDEP takes a different approach:

It externalizes the “Act” step into a first-class protocol boundary

| Layer                    | Role                                   |
|--------------------------|----------------------------------------|
| Methodology (ReAct, RL)  | how agents think & learn               |
| Protocol (SDEP)          | how decisions cross into execution     |
| Execution                | how actions are actually performed     |

---

### 2. Why SDEP Exists

In most systems today:

- decision logic is tightly coupled to specific tools
  
- execution is not standardized
  
- results lack the determinism and transparency required for production-grade reliability

SDEP introduces a clean separation:

- **Decision layer (Spice)** → produces structured intent
- **Execution layer (agents/tools)** → performs actions

This enables:

- interchangeable execution backends
- explicit decision → action mapping
- full traceability of “why this action happened”

> SDEP is not a reasoning framework.

> It is the interface contract between thinking and doing.

---

### 3. Core Abstractions

SDEP defines a minimal set of protocol primitives:

#### 3.1 ExecutionIntent

A structured representation of *what should be executed*.

Includes:

- intent type
- target (tool / agent / environment)
- input payload
- optional constraints / metadata

---

#### 3.2 ExecutionResult

A normalized representation of *what actually happened*.

Includes:

- status (success / failure / partial)
- outputs (logs, artifacts, messages)
- signals (e.g. requires_attention, retryable)

---

#### 3.3 Outcome

A domain-aware interpretation of execution results:

- maps raw results → state updates
- enables reflection and learning

---

### 4. Execution Flow

SDEP formalizes the boundary between decision and execution:

```
Decision
↓
ExecutionIntent
↓
[ SDEP Boundary ]
↓
External Agent / Tool
↓
ExecutionResult
↓
Outcome
↓
Reflection / State Update
```

Key idea:

> Everything crossing the boundary is **structured, explicit, and observable**

---

### 5. SDEP vs Existing Agent Patterns

#### vs ReAct

- ReAct: reasoning + acting inside one loop
- SDEP: **extracts “Act” into a protocol**

#### vs Reinforcement Learning

- RL: optimizes behavior via reward signals
- SDEP: defines **how actions are executed and observed**

#### vs Traditional Tool Calling

Tool calling is usually:

- implicit
- model-specific
- hard-coded

SDEP makes it:

- explicit
- model-agnostic
- auditable
- replayable

---

### 6. What This Enables

- **Same Brain, Different Agent**
  Switch execution backends without changing decision logic

- **Auditable systems**
  Every action has a traceable intent and result

- **Replay & simulation**
  Re-run decisions against different execution environments

- **Composable execution layer**
  CLI, APIs, agents, humans — all become interchangeable executors


---


### 7. Design Philosophy

> Execution will become cheap and abundant.
> Decision will become the bottleneck.

SDEP exists to ensure:

- decision systems are not locked into execution tools
- execution remains replaceable infrastructure
- the boundary between thinking and acting is **explicit and controllable**

---


## 🔌 Wrapper Ecosystem (External Agents)

Spice supports an open wrapper ecosystem.

Even if an external agent does not natively support SDEP, it can still be integrated through a wrapper.

---

### 1. What is a wrapper?

A wrapper is a **protocol bridge** between Spice and external agents.

Spice (SDEP) ↔ Wrapper ↔ External Agent

- Spice speaks in **ExecutionIntent / ExecutionResult (SDEP)**
- Agents speak in their own formats (CLI, JSON, HTTP, SDK, etc.)
- The wrapper translates between the two

---

### 2. Why wrappers matter

SDEP is a newly launched protocol that connects the **decision layer** with external execution agents; its ecosystem still needs development.

Wrappers make Spice immediately compatible with the existing ecosystem:

- Integrate CLI agents, SDK-based tools, and remote services  
- Avoid modifying existing agents  
- Enable gradual adoption of SDEP  

---

### 3. Integration model

- **Native SDEP agents** → connect directly  
- **Non-SDEP agents** → connect via wrapper  
- **Multiple agents** → route by capability or context


---



### 4. Our view

Wrappers exist to make Spice useful today.

They allow us to integrate with existing agents without requiring changes.

But we believe this is a transitional layer.

In the long term, we expect more agents to adopt SDEP natively —  
enabling a clean, direct connection between decision systems and execution.

> Wrappers make Spice practical.  
> SDEP is where the real value compounds.



---



## 📁 Project Structure

```
spice/
├── spice/                     # 🧠 Core decision runtime framework
│   ├── core/                  #    Runtime loop + state store
│   ├── protocols/             #    Observation/Decision/Execution contracts
│   ├── decision/              #    Decision policy primitives
│   ├── domain/                #    DomainPack abstractions
│   ├── domain_starter/        #    New-domain scaffold templates
│   ├── executors/             #    Executor interface + SDEP adapter
│   ├── llm/                   #    Optional LLM core/adapters/providers
│   ├── memory/                #    Context/memory components
│   ├── replay/                #    Replay utilities
│   ├── shadow/                #    Shadow-run evaluation
│   ├── evaluation/            #    Eval helpers
│   ├── entry/                 #    Core CLI/tooling (quickstart/init domain)
│   └── adapters/              #    External system adapters
├── tests/                     # ✅ Core test suite
├── docs/                      # 📚 Architecture + protocol docs (incl. SDEP)
├── schemas/                   # 📐 Machine-readable SDEP JSON Schemas
├── examples/                  # 🧪 Runtime, decision, and SDEP examples
│   ├── decision_hub_demo/     #    Simulation-driven decision demo domain
│   ├── sdep_agent_demo/       #    Minimal SDEP executor demo
│   ├── sdep_quickstart/       #    SDEP quickstart for executor authors
│   ├── sdep_payloads/         #    Example SDEP request/response payloads
│   └── sdep_wrapper_template/ #    Template for wrapping non-SDEP agents
├── spice-hermes-bridge/       # 🌉 Reference bridge: WhatsApp/GitHub -> Spice -> SDEP -> Hermes
├── pyproject.toml             # 📦 spice-runtime package metadata
├── README.md                  # 📝 Core project overview
├── LICENSE                    # ⚖️ MIT
└── .gitignore                 # 🙈 Ignore rules

```

--- 


## 🗺️ Roadmap

Spice is an evolving decision-layer system.

We’ve built the core runtime, personal reference app, and SDEP-based execution loop.  
Next, we focus on expanding capabilities and ecosystem.

PRs are welcome — the system is designed to be modular and extensible.

---

### Current

- [x] Decision runtime (perception → state → decision → reflection)  
- [x] Integrated quickstart and domain scaffolding 
- [x] SDEP (Decision → Execution protocol)  
- [x] Wrapper ecosystem for external agents  
- [x] End-to-end loop (decision → execution → outcome)  

---

### Next

- [ ] **Richer decision modeling**  
  Better simulation, trade-off analysis, and multi-step reasoning  

- [ ] **Stronger memory layer**  
  Cleaner WorldState governance, context slicing, and decision-relevant state updates

- [ ] **More execution integrations**  
  Expand agent ecosystem (CLI, APIs, tools, services)  

- [ ] **Multi-step decision workflows**  
  From single decisions → structured plans and execution chains  

- [ ] **Better observability**  
  Inspect decisions, execution traces, and state transitions  

---

### Longer-term

- [ ] **Domain expansion**  
  Apply Spice to new domains beyond personal (software, ops, research)

- [ ] **Native SDEP ecosystem**  
  More agents supporting SDEP directly (less reliance on wrappers)

- [ ] **Persistent decision systems**  
  Systems that continuously learn and evolve over time


---


## 🌌 Vision

We believe the future of AI is not just execution —  
but better ways to think and decide.

Spice is an attempt to build a new layer in the AI stack:  
a **decision layer** above agents.

---

Our goal is simple:

> **Everyone should have a Spice.**

A system that:

- understands your world  
- maintains your state  
- helps you think through decisions  
- and takes action when needed  

---

Not just a tool.  
Not just a chatbot.  

But a **decision brain**  
that evolves with context, outcomes, and goals over time.

We've recently been considering the commercialization path for Spice, and to achieve our vision, we'll be moving towards a **General AI Brain**. We're currently preparing a very compelling demo, so stay tuned!

---

We are still early.

But we believe this direction leads to:

- more thoughtful decisions  
- more capable systems  
- and a new way to interact with AI  

---

> Spice is not just an assistant.  
> It is a step toward a decision brain for everyone.


---

Finally，Thanks to everyone on LinuxDo for their support! Welcome to join https://linux.do/ for all kinds of technical exchanges, cutting-edge AI information, and AI experience sharing, all on Linuxdo!

---






## ⭐ Star History

<div align="center">
  <a href="https://star-history.com/#Dyalwayshappy/spice&Date">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/svg?repos=Dyalwayshappy/spice&type=Date&theme=dark" />
      <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/svg?repos=Dyalwayshappy/spice&type=Date" />
      <img alt="Star History Chart" src="https://api.star-history.com/svg?repos=Dyalwayshappy/spice&type=Date" style="border-radius: 15px; box-shadow: 0 0 30px rgba(0, 217, 255, 0.3);" />
    </picture>
  </a>
</div>

<p align="center">
  <em>⭐ Star us if you find Spice interesting</em><br><br>
  <img src="https://visitor-badge.laobi.icu/badge?page_id=Dyalwayshappy.spice&style=for-the-badge&color=00d4ff" alt="Views">
</p>


<p align="center">
  <sub>Everyone should have a Spice — a decision brain for thinking and action.</sub>
</p>
