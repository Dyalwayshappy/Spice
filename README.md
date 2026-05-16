<div align="center">
  <img src="spice_image.jpg" alt="spice" width="500">
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

**Spice** is a **decision-layer runtime — a brain above agents**, *inspired by the rise of execution agents like Claude Code, Codex, Hermes, and OpenClaw, and by the idea of a world model.*

Spice controls agent actions before execution.

It turns messy context into source-backed, comparable, approval-aware decisions — before handing work to executors like Claude Code, Codex, Hermes, or OpenClaw.

It helps you decide **what should happen next**, **why that option is better**, and **what evidence supports it**.

While execution agents are getting better at doing things,

Spice focuses on the missing layer:

👉 **What should be done next — and why.**

---

## ❗️ 30s Dogfooding example

In this demo, Spice is used to decide its own next step: **state-as-context**, **OpenChronicle proactive perception**, or **executor handoff**.  
The default view stays conversational, while `/details` expands the full auditable Decision Card.

<table>
  <tr>
    <td align="center" width="50%">
      <img src="spice_dogfooding1.gif" alt="Spice dogfooding demo 1" width="100%">
    </td>
    <td align="center" width="50%">
      <img src="spice_dogfooding2.gif" alt="Spice dogfooding demo 2" width="100%">
    </td>
  </tr>
</table>


















---




## ⚡ Why it matters

Today, we have powerful agents that can do almost anything:

- write code
- analyze data
- browse tools
- automate workflows
- hand off tasks to other systems

But in most agent systems, **decision and execution are tightly coupled**.

Most agent benchmarks measure the final task result.

That is useful, but it also means decision quality is usually inferred indirectly from outcomes:

```text
final result = decision quality + tool ability + execution reliability + environment conditions
```

When a task succeeds or fails, the most important part is often hard to inspect:

> **Why was this action chosen?**

Spice separates the decision layer from the execution layer.

Before an agent acts, Spice turns the next action into a source-backed, comparable, approval-aware decision:


- what options were considered
- what evidence supports them
- why one action was selected
- what trade-offs were rejected
- whether execution should require approval

```text
Execution agents answer: how do we do it?

Spice answers: should we do it, and why?
```

---

## 🧠 What is Spice?

Spice is a **decision runtime for agentic AI systems**.

It gives AI systems a structured loop:

```text
perception → state model → simulation → decision → execution → reflection
```

It allows AI systems to:

- understand context (Decision relevant state)
- reason about possible futures (simulation)
- make structured decisions (decision)
- delegate actions to agents (execution)
- learn from outcomes (Decision Evolution)

Spice does not replace agents like Claude Code, Codex, Hermes, or OpenClaw.

It gives them an auditable, traceable, and evolving decision layer before execution.
  
---



## 🎬 Demo of Spice
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


##  👨‍🔧 Spice: Decision Layer Architecture

<p align="center">
  <img src="spice_structure.png" alt="spice structure" width="800">
</p>


---

## 🧭 Decision Guidance: decision.md

The easiest way to use Spice locally is the interactive decision shell:

```bash
spice setup
spice shell
```
In a workspace initialized by **spice setup**, local decision guidance lives at:

```text
.spice/decision.md
```

**decision.md** tells Spice how to compare candidate decisions within the capabilities supported by the active runtime and policy adapter.


It can guide:

- what Spice optimizes for
- how trade-offs are weighted
- which constraints should matter
- what kinds of decisions should be preferred or avoided

> decision.md is decision guidance.

It is not:

- memory
- a prompt dump
- an execution script
- an agent workflow
- a tool permission file

Editing **decision.md** can change how Spice ranks and explains options, but it does not grant execution capability. Execution still goes through runtime guardrails, approval boundaries, and configured executors.

A typical flow looks like:

```bash
spice setup
$EDITOR .spice/decision.md
spice shell
```


Then ask Spice what to do next:
```text
spice> Read this repo and tell me what we should prioritize next.
```

Spice will respond conversationally by default, while keeping the full audit trail available through commands like:

```text
/details    expand the full Decision Card
/sources    show evidence used
/why        explain trade-offs
/sim        show simulation
/json       inspect raw artifacts
```

Advanced profile/demo flows may also use .spice/decision/decision.md, especially in the older quickstart and domain-adapter examples. For the current interactive runtime, .spice/decision.md is the default local decision guidance file.

See docs/decision.md and docs/decision_quickstart.md for the full guidance contract.

---


##  ⚙ Install

**Install from source**

```bash

git clone https://github.com/Dyalwayshappy/Spice.git
cd Spice

python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

pip install -U pip
pip install -e .
```

Then verify:

```bash
spice --help
```

**Install from PyPI (stable, recommended)**

```bash
pip install spice-runtime
```

Then verify the CLI:

```bash
spice --help
```

##  Upgrade

```bash
pip install -U spice-runtime
```






---

## 🚀 Quick Start

The fastest way to try Spice is the interactive decision shell.

```bash
pip install spice-runtime
spice setup
spice shell
```

spice setup creates a local Spice workspace:

```text
.spice/
  config.json          # LLM / executor / perception config
  .env                 # optional saved API keys
  decision.md          # user-editable decision guidance
  state/state.json     # local decision state
  sessions/            # conversation/session records
  runs/                # run artifacts
  decisions/           # Decision Cards
  perceptions/         # workspace / URL / delegated perception artifacts
  approvals/           # approval checkpoints
  outcomes/            # execution outcomes
  memory/              # decision memory and summaries
```

Then start a session:

```bash
spice/spice shell
```

Try:
```text
spice> Read this repo and tell me what we should prioritize next.
spice> Why not option B?
spice> Give me a two-week plan for A.
spice> Execute the selected option.
```

By default, Spice responds conversationally and keeps the audit card folded.

Useful shell commands:

```text
/details     expand the full Decision Card
/sources     show evidence and sources used
/why         explain why the selected option won
/sim         show simulation metadata
/json        inspect raw artifacts
/context     inspect compiled decision context
/workspace   inspect workspace perception
/refine      adjust the latest decision
/execute     request approval-gated execution
/help        show shell commands
```

---

### 1. Configure A Model

You can configure an LLM during spice setup, or later:

```bash
spice config enable-llm \
  --provider openrouter \
  --model minimax/minimax-m2.7
```

Spice will read the API key from the provider-specific environment variable.

Example:
```bash
export OPENROUTER_API_KEY="your-openrouter-api-key"
spice shell
```

Supported LLM providers:

| Provider | Config value | API key env | Notes |
|:---|:---|:---|:---|
| Deterministic | `deterministic` | none | No hosted model. Useful for smoke tests and fallback behavior. |
| OpenRouter | `openrouter` | `OPENROUTER_API_KEY` | Recommended first hosted path. Works with models such as `minimax/minimax-m2.7`. |
| OpenAI | `openai` | `OPENAI_API_KEY` | Chat-completions compatible provider. |
| Anthropic | `anthropic` | `ANTHROPIC_API_KEY` | Claude provider. |
| DeepSeek | `deepseek` | `DEEPSEEK_API_KEY` | Works for normal responses; some flash models may be less stable for strict JSON simulation output. |
| MiMo / Xiaomi | `mimo` | `XIAOMI_API_KEY` | MiMo provider support. |
| Subprocess | `subprocess` | custom | Advanced local/custom provider path. |

Spice uses the LLM for candidate expansion, semantic routing, simulation metadata, response composition, and follow-up understanding. Runtime guardrails still own execution boundaries, evidence checks, and approval rules.

---


### 2. Configure An Executor

Execution is optional.

Spice can make decisions without executing anything. If you configure an executor, Spice still requires approval before crossing the execution boundary.

Supported executors:

| Executor | Config value | What it is for | Boundary |
|:---|:---|:---|:---|
| Dry run | `dry_run` | Local no-op execution preview | Safe default |
| SDEP subprocess | `sdep_subprocess` | Any local executor that speaks SDEP over subprocess | Protocol boundary |
| Codex | `codex` | Handoff to Codex CLI | Approval-gated |
| Claude Code | `claude_code` | Handoff to Claude Code CLI | Approval-gated |
| Hermes | `hermes` | Handoff to Hermes CLI | Approval-gated |



Check executor status:

```bash
spice executor list
spice executor doctor
```

Execute only after approval:

```bash
spice approval list
spice approval approve <approval_id>
spice execute <approval_id>
```

Spice separates decision from execution:

```text
Spice decides what should happen next.
Executors do the work after approval.
```

---


### 3.Configure Perception

Perception is how Spice gathers decision-relevant evidence.

Supported perception paths:

| Perception path | How it is triggered | What it reads | Notes |
|:---|:---|:---|:---|
| Manual input | User message / shell | User-provided context | Always available |
| Workspace perception | User asks about repo/files/current implementation | Local workspace files, git status, repo map, package metadata, tests, symbols | Read-only; does not write or run tests |
| URL perception | User includes a URL | Web page text | Read-only. GitHub repo deep inspection is still being improved. |
| Poll perception | `spice perceive --provider poll` | URL or explicit command output | Command polling requires explicit opt-in |
| OpenChronicle | `spice perceive --provider open_chronicle` | OpenChronicle MCP context | Optional external perception provider |
| Delegated perception | User asks for deeper external investigation | Findings/sources reported by an executor such as Hermes | Requires investigation consent; read-only; not execution |


Examples:

```bash
spice perceive --provider poll --poll-url "https://example.com/status"
spice perceive --provider open_chronicle
```

In the shell, Spice can automatically trigger read-only workspace or URL perception when the user asks for evidence:

```text
spice> Read this repo and tell me what is missing.
spice> Based on this URL, what should we do next? https://example.com/spec
```

Use /sources to inspect what Spice actually read.

---

### 4. What Spice Tool Calls Are For

Spice uses tool calls for perception, not uncontrolled execution.

Read-only perception tools may inspect:

```text
repo_map
search
read_file
git_status
git_diff
git_log
read_package_metadata
read_test_structure
python_symbol_index
read_python_symbol
fetch_url
```

These tools are used to build source-backed decision context.

They are not allowed to:

```text
write files
patch code
delete or move files
install packages
run tests
run terminal commands
execute side-effect tasks
```

If a decision needs side effects, Spice creates an approval checkpoint first.

If a task needs deeper external research, Spice can ask for investigation consent and delegate a read-only investigation to an executor. That is separate from execution approval.


```text
local perception -> delegated read-only investigation -> approval-gated execution
```

---

### 5. Edit decision.md

The main user-editable decision guidance file is:

```text
.spice/decision.md
```

Edit it to change how Spice compares options:
```bash
$EDITOR .spice/decision.md
```

**decision.md** can influence preferences, constraints, trade-offs, and decision style.

Editing decision.md does not grant execution capability. Execution still goes through runtime guardrails and approval boundaries.

---

### 6. Run One-Off CLI Decisions

You can also use Spice without entering the shell.

Advisory decision:

```bash
spice decide "What should we prioritize next?" --advise
```

One-shot run:
```bash
spice run --once "Read this repo and suggest the safest next action"
```

JSON artifact output:
```bash
spice run --once "What should we do next?" --json
```

Refine the latest decision:
```bash
spice refine "Assume we only have one developer for two weeks."
```

Inspect session history:
```bash
spice session list
spice session current
spice session timeline session.default
```

Check workspace health:
```bash
spice doctor
```

---

### 7. Legacy Quickstart And Domain Demos

The older framework quickstart is still available for people building custom domains or studying the deterministic core loop:

```bash
spice quickstart --force
```

Core-only mode:
```bash
spice quickstart --core-only --force
```

That flow creates example artifacts under:
```text
.spice/quickstart/
.spice/quickstart_llm/
.spice/decision/decision.md
.spice/decision/support/default_support.json
```

Use this path if you are building a custom **DomainSpec**, policy adapter, or SDEP executor demo.

For the current interactive product experience, start with:

```bash
spice setup
spice shell
```










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
