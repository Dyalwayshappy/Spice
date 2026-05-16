<div align="center">
  <img src="spice_image.jpg" alt="spice" width="500">
  <h1>Spice — The Decision Layer Above Agents</h1>
  
  <p>
    <strong><a href="./README.md">English</a> / 中文</strong>
  </p>
  
  <p>
    <a href="https://pypi.org/project/spice-runtime/"><img src="https://img.shields.io/pypi/v/spice-runtime" alt="PyPI"></a>
    <img src="https://img.shields.io/badge/python-≥3.11-blue" alt="Python">
    <img src="https://img.shields.io/badge/license-MIT-green" alt="License">
    <a href="./COMMUNICATION.md"><img src="https://img.shields.io/badge/WeChat-Group-C5EAB4?style=flat&logo=wechat&logoColor=white" alt="WeChat"></a>
    <a href="https://discord.gg/DajVWWNMfE"><img src="https://img.shields.io/badge/Discord-Community-5865F2?style=flat&logo=discord&logoColor=white" alt="Discord"></a>
  </p>
</div>


> Agent 擅长**执行** 

> 但它们往往不知道下一步该做什么

**Spice** 是一个**决策层运行环境 —— Agent 之上的大脑。** 灵感来源于 **OpenClaw 等执行类 Agent 的兴起以及 世界模型（World Model）** 的概念。

Spice 会在 Agent 执行之前，对行为进行决策控制。

它会将混乱的上下文整理为：基于证据（source-backed）,可比较（comparable）,可审计（auditable）,支持审批（approval-aware）的结构化决策，然后再把任务交给 Claude Code、Codex、Hermes、OpenClaw 等执行层agent（executor）。

Spice 关注的是：

- 下一步应该做什么
- 为什么这是更好的选择
- 有哪些证据支持这个决策


当执行类 Agent（如 Claude Code, OpenClaw, Codex）在“做事”方面变得越来越强时，

Spice 专注于缺失的那一层：


👉 **接下来应该做什么 —— 以及为什么**

---

## ❗️ 30s Dogfooding example

在这个 dogfooding demo 里，我们让 Spice 读取自己的 repo，并判断 Spice 下一步应该优先做什么：state-as-context、更深的只读感知能力，还是 executor handoff。

默认界面保持对话式体验，而 /details 可以展开完整可审计的 Decision Card（决策卡）。

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

## ⚡ 为什么这很重要

今天，我们拥有可以完成几乎任何任务的强大 Agent：

- 写代码
- 分析数据
- 浏览工具
- 自动化工作流
- 调用其他系

但在大多数 Agent 系统中：

> “决策（decision）”与“执行（execution）”是强耦合的。

现在的大多数 benchmark 测量的都是最终结果：

```text
final result = decision quality + tool ability + execution reliability + environment conditions
```

但任务成功或失败时，最关键的问题往往难以观察：

> 为什么选择了这个动作？

Spice 将“决策层”与“执行层”彻底拆开。

在 Agent 执行之前，Spice 会把“下一步行动”变成一个：有证据支持,可比较,支持审批的结构化决策：

包括：
- 考虑过哪些选项
- 有哪些证据
- 为什么选择这个方案
- 放弃了哪些 trade-off
- 是否需要审批


```text
Execution agents 回答：
“怎么做（how）”

Spice 回答：
“该不该做（should）以及为什么（why）”
```

---

## 🧠 什么是 Spice?

Spice 是一个用于 Agentic AI 系统的 决策运行时（decision runtime）。


它为 AI 提供了一个结构化循环：

```text
perception → state model → simulation → decision → execution → reflection
```

它让 AI 系统能够：

- 理解决策相关上下文（Decision Relevant State）
- 推演未来可能性（Simulation）
- 做结构化决策（Decision）
- 把任务委托给执行器（Execution）
- 从结果中学习（Decision Evolution）


Spice 不会替代 Claude Code、Codex、Hermes、OpenClaw。

它是在执行之前，为这些 Agent 增加：可审计,可追踪,可演化的“决策层”。



---


## 🎬 Spice展示视频：
为了更直观地了解 Spice，

请观看我们精心准备的关于生活与工作冲突的演示： [Spice-live-demo](https://www.bilibili.com/video/BV1rhDRB7Ehn/)

---
### Demo视频

1. Bilibili

<div align="center">
<a href="https://www.bilibili.com/video/BV1rhDRB7Ehn/" target="_blank"><img src="spice_demo.PNG" alt="Spice Demo Video" width="75%"/></a>

点击图片观看使用 Spice 处理数字世界和物理世界之间冲突的完整演示视频。
</div>

---


##  👨‍🔧 Spice: 决策层架构

<p align="center">
  <img src="spice_structure.png" alt="spice structure" width="800">
</p>


---

## 🧭 Decision Guidance：decision.md

本地使用 Spice 最简单的方法：

```bash
spice setup
spice shell
```
初始化后：

```text
.spice/decision.md
```
就是本地的“决策指导文件”。

**decision.md**定义：Spice 优化什么,如何权衡 trade-off,哪些 constraint 更重要,偏好哪些决策

> decision.md 是“决策指导”

它不是：

- memory
- a prompt dump
- an execution script
- an agent workflow
- a tool permission file

修改 decision.md会改变 Spice 如何“比较和解释决策”，但不会赋予执行权限,执行仍然受到runtime guardrail,approval boundary,executor config限制。


有关完整的指导合同，请参阅 docs/decision.md 和 docs/decision_quickstart.md。

---



##  ⚙ 安装

**Install from source**

```bash

git clone https://github.com/Dyalwayshappy/Spice.git
cd Spice

python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

pip install -U pip
pip install -e .
```

验证:

```bash
spice --help
```

**从 PyPI 安装（推荐）**

```bash
pip install spice-runtime
```

CLI验证:

```bash
spice --help
```

## 升级

```bash
pip install -U spice-runtime
```





---

## 🚀 快速开始


最快体验：

```bash
pip install spice-runtime
spice setup
spice shell
```

Spice 会创建工作目录包括：

```text
.spice/
  config.json          # LLM / executor / perception config
  decision.md          # user-editable decision guidance
  state/state.json     # local decision state
  sessions/            # conversation/session records
  runs/                # run artifacts
  decisions/           # Decision Cards
  perceptions/         # workspace / URL / delegated perception artifacts
  investigations/      # read-only investigation consent and records
  approvals/           # approval checkpoints
  outcomes/            # execution outcomes
  conversations/       # shell conversation turns
  memory/              # decision memory and summaries
  cache/               # runtime cache
  executors/           # local executor metadata/config
  skills/              # local skill metadata
  .env                 # optional saved API keys, if configured during setup
```

启动:

```bash
spice shell
```

实例:
```text
spice> Read this repo and tell me what we should prioritize next.
spice> Why not option B?
spice> Give me a two-week plan for A.
spice> /execute <approval_id>
```

默认情况下，Spice 会以对话方式回应，并保持审核卡折叠状态。

有效的command:

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

### 1. 配置模型（LLM）

您可以在 Spice 设置期间配置 LLM，也可以稍后配置：

```bash
spice config enable-llm \
  --provider openrouter \
  --model minimax/minimax-m2.7
```

Spice 将从环境变量中读取 API 密钥。

Example:
```bash
export OPENROUTER_API_KEY="your-openrouter-api-key"
spice shell
```

支持的LLM提供商：

| Provider | Config value | API key env | Notes |
|:---|:---|:---|:---|
| Deterministic | `deterministic` | none | No hosted model. Useful for smoke tests and fallback behavior. |
| OpenRouter | `openrouter` | `OPENROUTER_API_KEY` | Recommended first hosted path. Works with models such as `minimax/minimax-m2.7`. |
| OpenAI | `openai` | `OPENAI_API_KEY` | Chat-completions compatible provider. |
| Anthropic | `anthropic` | `ANTHROPIC_API_KEY` | Claude provider. |
| DeepSeek | `deepseek` | `DEEPSEEK_API_KEY` | Works for normal responses; some flash models may be less stable for strict JSON simulation output. |
| MiMo / Xiaomi | `mimo` | `XIAOMI_API_KEY` or `MIMO_API_KEY` | MiMo provider support. |
| Subprocess | `subprocess` | custom | Advanced local/custom provider path. |

Spice 使用 LLM 来candidate expansion，semantic routing，simulation，response composition但执行边界仍由 runtime guardrail 控制。

---


### 2. 配置 Executor

执行是可选的

Spice 可以在不执行任何操作的情况下做出决策。即使配置了执行器，Spice 仍然需要在跨越执行边界之前获得批准。

支持的执行层agent：

| Executor | Config value | What it is for | Boundary |
|:---|:---|:---|:---|
| Dry run | `dry_run` | Local no-op execution preview | Safe default |
| SDEP subprocess | `sdep_subprocess` | Any local executor that speaks SDEP over subprocess | Protocol boundary |
| Codex | `codex` | Handoff to Codex CLI | Approval-gated |
| Claude Code | `claude_code` | Handoff to Claude Code CLI | Approval-gated |
| Hermes | `hermes` | Handoff to Hermes CLI | Approval-gated |



Check执行层agent状态:

```bash
spice executor list
spice executor doctor
```

审批后执行:

```bash
spice approval list
spice approval approve <approval_id>
spice execute <approval_id>
```

Spice 将决策与执行分开:

```text
Spice 决定下一步该做什么
Executor 在审批后负责执行
```

---


### 3.感知（Perception）

Perception 是 Spice 获取“决策相关证据”的方式。

支持的感知方式:

| Perception path | How it is triggered | What it reads | Notes |
|:---|:---|:---|:---|
| Manual input | User message / shell | User-provided context | Always available |
| Workspace perception | User asks about repo/files/current implementation | Local workspace files, git status, repo map, package metadata, tests, symbols | Read-only; does not write or run tests |
| URL perception | User includes a URL | Web page text | Read-only. GitHub repo deep inspection is still being improved. |
| Poll perception | `spice perceive --provider poll` | URL or explicit command output | Command polling requires explicit opt-in |
| OpenChronicle | `spice perceive --provider open_chronicle` | OpenChronicle MCP context | Optional external perception provider |
| Delegated perception | may trigger investigation consent | Findings/sources reported by an executor such as Hermes | Requires investigation consent; read-only; not execution |


示例:

```bash
spice perceive --provider poll --poll-url "https://example.com/status"
spice perceive --provider open_chronicle
```

在 shell 中，当用户请求证据时，Spice 可以自动触发只读工作区或 URL 感知：

```text
spice> Read this repo and tell me what is missing.
spice> Based on this URL, what should we do next? https://example.com/spec
```

使用 /sources 查看 Spice 实际读取的内容。

---

### 4. Spice 的 Read-only 工具

Spice 使用工具调用来进行感知，而不是不受控制的执行。

只读感知工具可以检查：

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

这些工具用于构建基于数据源的决策背景。

不允许:

```text
write files
patch code
delete or move files
install packages
run tests
run terminal commands
execute side-effect tasks
```

如果决策需要更深入的操作，Spice 会首先创建一个审批检查点。

如果某项任务需要更深入的外部研究，Spice 可以请求调查许可，并将只读调查权限委托给执行层agent。这与执行许可不同。


```text
local perception -> delegated read-only investigation -> approval-gated execution
```

---

### 5. Edit decision.md

用户可编辑的主要决策指导文件是：

```text
.spice/decision.md
```

修改此设置以更改 Spice 比较选项的方式：
```bash
$EDITOR .spice/decision.md
```

**decision.md** 可以影响偏好、限制、权衡和决策风格。

编辑 decision.md 文件并不会授予执行权限。执行仍然需要经过运行时安全机制和审批流程。

---

### 6. Run One-Off CLI Decisions

您也可以不进入 shell 就使用 Spice。

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

对于构建自定义域或研究确定性核心循环的用户，旧版框架快速入门指南仍然可用：

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

如果您正在构建自定义 **DomainSpec**、策略适配器或 SDEP 执行器演示，请使用此路径。

对于当前的交互式产品体验，请从以下几点开始：

```bash
spice setup
spice shell
```













---



## ✨ 功能特性

Spice 将混乱的背景信息转化为结构化的、可审计的决策循环。

它带来了一种全新的思考、决策和行动方式：


1. **Perception**  
   从用户输入、本地工作区文件、URL、外部信号或委托的只读调查中读取与决策相关的上下文。
   
3. **State Modeling**  
   维护本地状态、会话历史记录、内存摘要和与决策相关的上下文。
   
5. **Simulation**  
   行动前比较候选期货：预期结果、下行风险、成功信号和置信度。
   
7. **Decision**  
   对选项进行排序，解释为什么某个选项胜出，说明为什么其他选项被拒绝，并保留完整的决策卡以供审核。
   
9. **Execution (optional)**  
   将已批准的操作通过明确的执行边界发送到外部执行器，例如 Codex、Claude Code、Hermes 或 SDEP 兼容代理。


11. **Reflection**  
    从后续跟进、审批、执行结果和内存回写中吸取经验教训。

---

## 🔁 Reference Integration: Spice + Hermes



该项目包含一个参考桥，展示了外部信号如何流入 Spice，以及如何通过 SDEP 将已批准的决定移交给 Hermes。

```text
External signal -> Spice decision runtime -> SDEP -> Hermes executor -> outcome -> reflection
```

如果你想学习完整的集成示例，请从这里开始：

- spice-hermes-bridge/README.md
- examples/decision_hub_demo/
- examples/sdep_quickstart/

这是一个参考集成，不是 Spice 核心。

---




## 🔗 SDEP (Spice Decision Execution Protocol)

SDEP 是 **决策** 和 **执行** 之间的协议边界。

Spice 仍然是决策运行时:

```text
Decision
-> ExecutionIntent
-> SDEP
-> External Agent
-> ExecutionResult
-> Outcome
-> Reflection
```

SDEP 提供了一套统一的协议边界，让外部执行层 Agent 可以作为 Spice 背后的执行端接入。


它是:

- **transport-agnostic** — the same payload shape can be carried over stdin/stdout, HTTP, queues, or RPC
- **protocol-first** — external agents do not need to understand Spice internals
- **auditable** — execution intent and execution result are structured and traceable
- **executor-agnostic** — different agents can implement the same wire contract

SDEP 不是推理框架，也不是agent loop

它定义了以下两者之间的**标准化边界**：

- **Decision (what should be done)**

- **Execution (how it is done)**

---

### Start Here

如果您想了解或实现SDEP，请从以下方面开始：

- **Protocol spec**: `docs/sdep_v0_1.md`
- **JSON Schemas**: `schemas/sdep/v0.1/`
- **Example payloads**: `examples/sdep_payloads/v0.1/`
- **Executor quickstart**: `examples/sdep_quickstart/`
- **Wrapper template**: `examples/sdep_wrapper_template/`
- **Reference adapter**: `spice/executors/sdep.py`
- **Example agent**: `examples/sdep_agent_demo/echo_agent.py`

SDEP v0.1包含:

- one shot `execute.request` / `execute.response`
- optional `agent.describe.request` / `agent.describe.response`
- sender/responder identity
- deterministic request identity and idempotency key
- explicit success/failure signaling
- canonical execution / outcome payloads

未来将会补充:

- streaming partial outputs
- async job polling
- capability negotiation handshake
- online autonomous policy mutation


有关完整的协议契约、规范规则、JSON 示例和映射详细信息，请参阅 docs/sdep_v0_1.md。


---

### 1. Positioning

现代智能体系统通常遵循 ReAct 或强化学习循环等模式，其中：

推理和执行在一个循环中交错进行。

执行是隐式的，嵌入在agent运行时中。

SDEP采取了不同的方法论:

它将“执行”步骤外部化为一级协议边界。

| Layer                    | Role                                   |
|--------------------------|----------------------------------------|
| Methodology (ReAct, RL)  | how agents think & learn               |
| Protocol (SDEP)          | how decisions cross into execution     |
| Execution                | how actions are actually performed     |


---

### 2. SDEP vs Existing Agent Patterns

#### vs ReAct

- ReAct: 推理 + 行动在一个循环内
- SDEP: 将“Act”提取到协议中

#### vs Reinforcement Learning

- RL: 通过奖励信号优化行为
- SDEP: 定义了**如何执行和观察操作**

#### vs Traditional Tool Calling

传统tool call通常是:

- implicit
- model-specific
- hard-coded

SDEP是:

- explicit
- model-agnostic
- auditable
- replayable

---

### 3. What This Enables

- **Same Brain, Different Agent**
  切换执行后端，无需更改决策逻辑

- **Auditable systems**
 每个行为都有可追溯的意图和结果

- **Replay & simulation**
  针对不同的执行环境重新运行决策

- **Composable execution layer**
  无论是 CLI、API、Agent，还是人工操作，都可以作为可替换的执行端接入。



---


## 🔌 Wrapper Ecosystem (External Agents)

SDEP 是清晰的边界。如今，wrapper使它变得实用。

如果执行层agent本身不支持 SDEP，它仍然可以通过封装程序进行连接：

```text
Spice -> SDEP -> Wrapper -> External Agent
```

该wrapper翻译如下：

- Spice’s structured ExecutionIntent / ExecutionResult
- the agent’s native interface, such as CLI, JSON, HTTP, SDK, or hosted API

这使得 Spice 可以与现有的执行代理协同工作，而无需更改它们的内部结构。

集成路径：

- **Native SDEP agent** -> connect directly
- **Non-SDEP agent** -> connect through a wrapper
- **Multiple agents** -> select by capability, context, or configured executor

wrapper是兼容层。长期协议边界是 SDEP。

---










## 📁 项目结构

```
Spice/
├── spice/                         # Core Spice runtime package
│   ├── runtime/                   # Shell, routing, approval flow, perception wiring, execution runtime
│   │   └── tui/                   # Terminal UI surfaces and conversation rendering
│   ├── decision/                  # Decision policies, profiles, comparison, and general decision models
│   ├── perception/                # Read-only perception providers and workspace/URL context sources
│   ├── executors/                 # Executor interfaces and SDEP adapter
│   ├── llm/                       # LLM clients, providers, composers, routers, simulation helpers
│   ├── memory/                    # Memory, context summaries, and memory writeback helpers
│   ├── core/                      # Core protocol loop primitives and state store
│   ├── protocols/                 # Observation / decision / execution protocol primitives
│   ├── domain/                    # DomainPack abstractions for custom domains
│   ├── domain_starter/            # New-domain scaffold templates
│   ├── replay/                    # Replay utilities
│   ├── shadow/                    # Shadow-run evaluation utilities
│   ├── evaluation/                # Evaluation helpers
│   ├── adapters/                  # External system adapters
│   └── entry/                     # CLI entrypoints, setup, quickstart, shell commands
│
├── tests/                         # Test suite, grouped by subsystem
│   ├── decision/                  # Decision comparison, profiles, general decision tests
│   ├── runtime/                   # Shell/runtime/routing/perception/execution/composer tests
│   ├── llm/                       # LLM provider, router, composer, simulation tests
│   ├── perception/                # Workspace, URL, OpenChronicle, poll perception tests
│   ├── executors/                 # Executor and SDEP integration tests
│   ├── memory/                    # Memory and context tests
│   ├── protocols/                 # Protocol contract tests
│   ├── entry/                     # CLI/setup command tests
│   ├── demos/                     # Demo scenario tests
│   └── replay/                    # Replay tests
│
├── docs/                          # Architecture, decision guidance, SDEP, runtime docs
├── schemas/                       # Machine-readable protocol schemas
│   └── sdep/v0.1/                 # SDEP v0.1 JSON Schemas
├── examples/                      # Demos, SDEP examples, wrapper templates
│   ├── decision_hub_demo/         # Simulation-driven decision demo domain
│   ├── incident_commander_demo/   # Incident response decision demo
│   ├── cli_adapter_demo/          # CLI adapter example
│   ├── sdep_agent_demo/           # Minimal SDEP executor demo
│   ├── sdep_quickstart/           # SDEP quickstart for executor authors
│   ├── sdep_payloads/             # Example SDEP request/response payloads
│   └── sdep_wrapper_template/     # Template for wrapping non-SDEP agents
├── spice-hermes-bridge/           # Reference bridge: external signals -> Spice -> SDEP -> Hermes
├── assets/                        # README/community assets
├── pyproject.toml                 # spice-runtime package metadata
├── README.md                      # Project overview
├── README_zh.md                   # Chinese README
├── LICENSE                        # MIT
└── .gitignore                     # Ignore rules
```

--- 


## 🗺️ 计划路线

Spice 是一个不断进化的决策层系统

目前的重点是构建代理之上的决策层：行动前进行基于来源的推理，承诺前进行明确的权衡，执行前进行审批控制的交接。

欢迎提交 PR —— 系统设计为模块化且可扩展

---

### 当前进展

- [x] **Interactive decision shell**  
  使用折叠式决策卡和审计命令进行类似Agent的对话

- [x] **Decision runtime**  
  感知 -> 状态 -> 模拟 -> 决策 -> 可选批准 -> 执行 -> 反思

- [x] **Source-backed perception**  
  只读工作区感知、URL 感知、`/sources`、引用检查和证据感知响应。

- [x] **LLM-assisted decision flow**  
  语义路由、候选扩展、模拟元数据、响应组成和后续处理。

- [x] **Approval-gated execution**  
  执行与决策分离，只有通过明确的审批检查点才能跨越边界。

- [x] **SDEP v0.1**  
  用于将 Spice 决策连接到外部执行agent的协议边界。 

---

### 下一步

- [ ] **Stronger model compatibility**  
  更好地适配不同 LLM Provider，尤其是严格 JSON simulation 输出和 composer fallback 行为。

- [ ] **Deeper read-only perception**  
  改进 GitHub repo 检查、更丰富的 URL 理解、更好的 repo map，以及基于来源证据的代码分析。

- [ ] **More executor integrations**  
  改进 Codex、Claude Code、Hermes，以及 SDEP 兼容执行器的 handoff 能力。

- [ ] **Better delegated perception**  
  允许外部 Agent 执行只读调查，同时由 Spice 保留来源追踪、用户授权和决策所有权。

- [ ] **Decision evolution**  
  改进用户追问、审批、执行结果和 memory 更新如何影响未来决策。

- [ ] **Observability and replay**  
  让决策、来源、审批、执行轨迹和状态变化更容易检查与回放。


---

### 长期目标

- [ ] **Native SDEP ecosystem**  
  让更多 Agent 直接支持 SDEP，减少对 wrapper 的依赖。

- [ ] **Multi-step decision workflows**  
  从单次决策扩展到结构化计划、分支路径和执行链。

- [ ] **Persistent decision systems**  
  构建能够持续维护上下文、从结果中学习，并随着时间提升决策质量的系统。

- [ ] **Domain expansion**  
  将 Spice 应用于软件开发、运维、研究、商业策略和个人决策系统。

---


## 🌌 愿景

我们相信，AI 的未来不只是更强的执行能力。

它同样需要更好的决策能力。

执行类 Agent 正在变得更快、更便宜、也更强大。

但在行动之前，仍然有一个更难的问题：

> 接下来应该做什么，为什么？  


Spice 试图构建一个新的layer：

> 一个 **Agent 之上的决策层**。

---

我们的目标很简单：

> **每个人都应该拥有一个 Spice。**


一个能够：

- 理解你的世界  
- 维护你的状态  
- 帮助你思考决策  
- 并在需要时交接行动  

---

它不只是一个工具。  
也不只是一个聊天机器人。

而是一个会随着上下文、结果和目标不断演化的 **决策大脑**。


---

我们仍然处在很早期。

但我们相信，这个方向会带来：

- 更审慎的决策  
- 更强大的系统  
- 以及一种与 AI 交互的新方式  

---

> Spice 不只是一个助手。
> 它是让每个人拥有决策大脑的一次尝试。

---

最后，感谢 LinuxDo 上的每一位朋友的支持！欢迎加入 https://linux.do/ 进行各类技术交流、前沿 AI 资讯及 AI 使用经验分享。

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
  <em>⭐ 如果你觉得 Spice 有趣，请为我们点亮 Star</em><br><br>
  <img src="https://visitor-badge.laobi.icu/badge?page_id=Dyalwayshappy.spice&style=for-the-badge&color=00d4ff" alt="Views">
</p>


<p align="center">
  <sub>每个人都应该拥有一个 Spice —— 用于思考和行动的决策大脑</sub>
</p>
