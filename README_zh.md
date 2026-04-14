<div align="center">
  <img src="spice_logo.png" alt="spice" width="500">
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


当执行类 Agent（如 Claude Code, OpenClaw, Codex）在“做事”方面变得越来越强时，
Spice 专注于缺失的那一层：


👉 **接下来应该做什么 —— 以及为什么**

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

## ⚡ 为什么这很重要

今天，我们拥有可以完成几乎任何任务的强大 Agent：

- 编写代码 
- 分析数据  
- 自动化工作流

但当你坐下来准备使用它们时，依然面临同样的问题：

**我下一步该做什么**

这才是最难的部分

真正的瓶颈在于：

> **决策（Decision-making）**



Spice 正是为了解决这个问题而设计的

---

## 🧠 什么是 Spice?

Spice 提供了一个受“世界模型”概念启发的结构化认知闭环：

感知 (perception) → 状态建模 (state model) → 模拟 (simulation) → 决策 (decision) → 执行 (execution) → 反思 (reflection)

它使 AI 系统能够：

- 感知世界状态 (state)
- 推演未来的可能性 (simulation)
- 做出结构化决策 (decision)
- 将具体动作委派给 Agent (execution)
- 从结果中反思学习 (reflection)

  
---



## 🌱 了解 Spice Personal

Spice 是一个通用的**决策运行环境** —  

为了让这个概念具像化，我们构建了第一个reference：**Spice Personal**

他不仅仅是一个demo

他是一个能帮你完成以下任务的AI：

- 思考现实中的决策  (e.g. career, product, strategy) 
- 将你的世界结构化为“状态”
- 探索未来可能走向
- 决定下一步该做什么  
- 通过外部Agent执行操作 

路径:

> 问题 → 推理 → 决策 → 行动 → 结果


👉 **[Spice Personal](https://github.com/Dyalwayshappy/spice_personal)** 


---


## 🧩 示例：从 想法 → 决策 → 下一步 

### 1. 场景

> "我想为我的游戏好友们快速构建一个轻量级群组工具"

一个简单的，带有明确约束条件的现实目标


### 2. Spice做了什么

#### 输入：带有约束条件的现实意图

![demo1](./demo1.png)

<p align="center"><em>从意图开始</em></p>


---


#### 决策 → 方案对比

![demo2](./demo2.png)

<p align="center"><em>从选项到结构化的决策空间</em></p>


---


#### 选择 → 下一步动作

![demo3](./demo3.png)


<p align="center"><em>决策转化为行动</em></p>


---



### 3. 关于执行 (next step)

Spice专注于**决策层**

在完整的工作流中，选定的决策可以通过外部Agent（如Codex或Claude Code）执行

本示例在“决策+下一步”处停止。

➡️ 接下来，我们将采用这个完全相同的场景，并连接到外部 Agent **执行决策展示完整链路**

> 决策 → 执行 → 结果 → 反思

<sub>这是Spice旨在实现的完整闭环</sub>



---


## 🌍 无关乎领域

Spice Personal只是一个参考

底层模型是领域无关的（Domain-agnostic）

Spice 是一个**通用决策运行环境**，可以应用于任何领域，只要：

- 有世界观 (state)
- 存在可能未来 (simulation)
- 需要做出决策
- 动作可由Agent执行

这包括:

- 个人决策制定 
- 产品和业务策略
- 软件开发工作流  
- 运营和自动化系统 

Spice不局限于单一用例

他是**构建决策系统的基础**

---


##  👨‍🔧 Spice: 决策层架构

<p align="center">
  <img src="spice_structure.png" alt="spice structure" width="800">
</p>


---

## 🧭 用户界面: decision.md

Spice的核心用户界面是 `decision.md`.

用户可以通过编辑来配置 Spice 如何比较候选决策：

```text
.spice/decision/decision.md
```

需要注意的是，此文件为决策指导文件（Decision Guide），并非记忆信息、prompt构建、执行手册或agent工作流。

在v1中参与运行（Runtime-active）:

- **Primary Objective（核心目标）** — 决策优化的主要方向（最重要的优化目标）
- **Preferences / Weights（偏好/权重）** — 在候选方案比较时使用的评分维度及权重
- **Hard Constraints（硬约束）** — 否决条件（在当前 policy / domain adapter 支持的情况下生效）
- **Trade-off Rules（权衡规则）** — 用于解决冲突的可执行规则（受限子集）


在 v1 中暂未参与运行（Runtime-inactive）:

- **Decision Principles（决策原则）**
- **Evaluation Criteria（评估标准）**
- **Reflection Guidance（反思指导）**


默认配置说明：
仓库中提供的默认 profile 只是一个起始模板（starter template）。用户应修改本地的`.spice/decision/decision.md`；而不应修改 support JSON 文件（这些文件不是常规配置入口）。

Runtime 支持说明：
实际的决策执行能力由当前使用的：policy（策略）或 domain adapter（领域适配器）提供支持。
复制出来的 support JSON 仅用于：解释（explain），演示（demo），调试（debug）

更多说明请参考：`docs/decision.md` 和 `docs/decision_quickstart.md` 

---



##  ⚙ 安装(将 Spice 框架扩展到其他领域)

**Install from source (最新功能，用于开发)**

```bash

git clone https://github.com/Dyalwayshappy/Spice.git
cd Spice

python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

pip install -U pip
pip install -e .
```

**从 PyPI 安装（稳定版，推荐）**

```bash
pip install spice-runtime
```

##  升级到最新版本

```bash
pip install -U spice-runtime
spice --help
```





---

## 🚀 快速开始

体验 Spice 的最快方式是使用内置的 quickstart：

```bash
spice quickstart --force
```

该命令会从内置示例 domain 启动，并完整跑通 Spice 的核心边界：
```text
decision.md -> example domain runtime -> OpenRouter/local LLM -> optional external executor
```

执行后会生成以下目录结构:

```text
.spice/quickstart/                         # deterministic core-loop example
.spice/quickstart_llm/                     # LLM-ready example runtime
.spice/decision/decision.md                # user-editable decision profile
.spice/decision/support/default_support.json
```

生成的示例可以直接运行，使用默认的 deterministic 配置，首次运行无需 API Key。


### Quickstart 展示了什么

```text
perception -> state -> decision -> execution -> reflection
```

默认 quickstart 展示了 Spice 的核心能力：

- 加载决策配置（decision profile）
- 校验并解释决策规则
- 运行领域内的决策循环
- 通过显式 provider 接入模型建议（model advisory）
- 执行层保持可选 & 可插拔（pluggable）

注意：内置 domain 只是示例。实际项目需要定义：

- DomainSpec
- domain adapter
- score 维度
- 约束检查逻辑
- 执行边界（executor）

### Core-only 模式

如果只想查看最小的核心决策循环：

```bash
spice quickstart --core-only --force
```

仅生成:

```text
.spice/quickstart/
```

适用于只想理解核心 loop，而不引入 LLM 或 `decision.md` 配置的场景


### 1. 编辑 decision.md

主要用户配置文件:

```text
.spice/decision/decision.md
```

最推荐的第一步修改是评分权重（Preferences）：

```md
Preferences:
- outcome_value: 0.40
- risk_reduction: 0.25
- reversibility: 0.20
- confidence_alignment: 0.15
```

例如：更偏向安全和可回滚的决策：

```md
Preferences:
- outcome_value: 0.25
- risk_reduction: 0.35
- reversibility: 0.25
- confidence_alignment: 0.15
```

`decision.md` 的作用是控制决策选择逻辑，不是：memory（记忆），agent prompt，执行脚本


### 2. 校验与解释（Validate & Explain） 

```bash
spice decision explain .spice/decision/decision.md --support-json .spice/decision/support/default_support.json
```

可加 `--json` 获取结构化输出。

输出内容包括：

- artifact id / version
- 校验状态
- runtime-active / inactive 区块
- 支持 / 不支持的评分维度
- 支持 / 不支持的硬约束
- 支持 / 不支持的权衡规则

Runtime 能力来自 policy / domain adapter，仅修改 support JSON 不会增加能力。


### 3. 使用 OpenRouter 模型

接入托管模型：

```bash
export OPENROUTER_API_KEY="your-openrouter-api-key"
export SPICE_DOMAIN_MODEL="openrouter:anthropic/claude-3.5-sonnet"
python .spice/quickstart_llm/run_demo.py
```

可选 attribution：

```bash
export SPICE_OPENROUTER_SITE_URL="https://github.com/Dyalwayshappy/Spice"
export SPICE_OPENROUTER_APP_NAME="Spice"
```

### 4. 使用本地或自定义模型

```bash
SPICE_DOMAIN_MODEL="ollama run qwen2.5" python .spice/quickstart_llm/run_demo.py
```

模型选择规则：

- `deterministic` 内置确定性 provider
- `openrouter:<model-id>` → OpenRouter
- 其他 → 作为 subprocess 命令执行

要求：subprocess 必须从 stdin 读取 prompt，并输出结构化结果。v1 不支持自动加载隐藏模型配置。



### 5. 在代码中使用 decision.md

Quickstart 展示的是文件配置方式，在代码中可以这样接入：

```python
from spice.decision import guided_policy_from_profile

policy = guided_policy_from_profile(
    base_policy,
    ".spice/decision/decision.md",
)
```

实际 runtime 能力仍由 policy / domain adapter 决定。


### 6. 接入外部执行 Agent

模型负责：

- 推理（reasoning）
- 模拟（simulation）
- 建议（advisory）

真正执行由外部 agent 完成：


```text
Decision -> ExecutionIntent -> external agent -> ExecutionResult -> Outcome -> Reflection
```

运行内置 SDEP demo：

```bash
python examples/sdep_agent_demo/run_sdep_adapter_demo.py
```

可选执行方式：

- `MockExecutor` （本地 / demo）
- `CLIAdapterExecutor` （命令行工具）
- `SDEPExecutor` （支持 SDEP 的 agent）

执行是可选 + 可插拔的，不会写入 `decision.md`.

### 7. 最新用户使用流程

```text
1. clone 并安装 Spice
2. 运行 spice quickstart
3. 编辑 .spice/decision/decision.md
4. 使用 spice decision explain 校验
5. 选择模型（OpenRouter / deterministic / 本地）
6. 运行示例 domain
7. 替换为自己的 DomainSpec / domain adapter
8. 可选接入外部执行器或 SDEP agent
```



---



## ✨ 功能特性

Spice 将你的世界转化为结构化的决策系统

它开启了一种思考、决策和行动的新方式：



1. **感知（Perception）**  
   理解你的世界并提取有意义的信号 

2. **状态建模（State Modeling）**  
   将其转化为结构化的决策模型

3. **模拟（Simulation）**  
   在采取行动前探索可能的未来  

4. **决策（Decision）**  
   比较权衡，然后为你提供决策辅助 

5. **执行（Execution - optional）**  
  将动作委派给外部 Agent（例如 Claude Code, Codex）

6. **反思（Reflection）**  
   从结果中学习并不断优化决策


---



## 🔗 SDEP (Spice Decision Execution Protocol)

SDEP 是 Spice 定义的协议，用于连接**决策层**与外部执行 Agent

Spice决定*应该做什么*

SDEP处理*该决策如何执行以及结果如何回流*

---

### 1. 什么需要 SDEP

大多数 AI 系统将推理和执行紧密耦合

SDEP 引入了清晰的分离：

- **决策层 (Spice)** → 确定意图和方向
   
- **执行层 (agents/tools)** → 执行现实世界的动作


这使得 Spice 能够充当**Agent 之上的大脑**，而不是绑定到任何单一工具

---

### 2. SDEP 的作用

SDEP负责：

- **编码执行意图**  
  将决策转化为结构化的、可执行的请求  

- **调度到外部Agent**  
  （CLI 工具、子进程、远程服务等）

- **接收结构化结果**  
  捕获执行的输出、状态和信号  

- **将结果反馈回系统**  
  启用状态更新、反思和后续决策  

---

### 3. 执行流程

Decision → ExecutionIntent → Agent → Result → Outcome → Reflection

- Spice 产生决策  
- SDEP 将其编码为执行意图  
- 外部 Agent 执行任务  
- 结果被返回并结构化
- Spice 更新状态并继续推理
  
---

### 4. 这能带来什么

- 接入不同的执行 Agent（不止数字世界的agent）
  
- 保持决策逻辑独立于执行工具
 
- 构建可审计、可回溯的决策系统
   
- 在不改变大脑的情况下进化执行端（同样的大脑，不同的 Agent）

> Spice 不是一个执行 Agent  
> 它是位于 Agent 之上的决策层


---


## 🔌 Wrapper Ecosystem (External Agents)

Spice 支持开放的封装器（Wrapper）生态系统

即使外部 Agent 不原生支持 SDEP，仍可以通过封装器进行集成

---

### 1. 什么是封装器？

封装器是 Spice 与外部 Agent 之间的**协议桥梁**

Spice (SDEP) ↔ Wrapper ↔ External Agent

- Spice使用 **ExecutionIntent / ExecutionResult (SDEP)** 进行通信
- Agent 使用它们自己的格式（CLI, JSON, HTTP, SDK 等）进行通信
- 封装器在两者之间进行翻译

---

### 2. 为什么要做Wrapper

SDEP 是一个新推出的连接**决策层**与外部执行 Agent 的协议；其生态系统仍需发展

Wrapper使 Spice 能够立即与现有生态系统兼容：

- 集成 CLI Agent、基于 SDK 的工具和远程服务  
- 无需修改现有的 Agent  
- 实现 SDEP 的逐步采用  

---

### 3. Integration model

- **原生 SDEP agents** → 直接连接 
- **非SDEP agents** → 通过Wrapper连接 
- **多个 agents** → 据能力或上下文进行路由


---



### 4. 我们的观点

封装器的存在是为了让 Spice 在今天就能发挥作用

它们允许我们在不需要修改的情况下集成现有的 Agent

但我们认为这只是一个过渡

从长期来看，我们期望更多的 Agent 原生支持 SDEP —  
从而在决策系统和执行端之间建立简洁、直接的连接

> 封装器让 Spice 具有实用性 
> SDEP 才是产生真实价值沉淀的地方



---












## 📁 项目结构

```
spice/
├── spice/                     # 🧠 核心决策运行框架
│   ├── core/                  #    运行循环 + 状态存储
│   ├── protocols/             #    观察/决策/执行契约
│   ├── decision/              #    决策策略原语
│   ├── domain/                #    领域包 (DomainPack) 抽象
│   ├── domain_starter/        #    新领域脚手架模板
│   ├── executors/             #    执行器接口 + SDEP 适配器
│   ├── llm/                   #    可选的 LLM 核心/适配器/提供商
│   ├── memory/                #    上下文/记忆组件
│   ├── replay/                #    回放工具
│   ├── shadow/                #    影子运行评估
│   ├── evaluation/            #    评估助手
│   ├── entry/                 #    核心 CLI/tooling (快速开始/初始化领域)
│   └── adapters/              #    外部系统适配器
├── tests/                     # ✅ 核心测试套件
├── docs/                      # 📚 架构 + 协议文档 (包括 SDEP)
├── examples/                  # 🧪 运行环境和 SDEP 示例
├── pyproject.toml             # 📦 spice-runtime 包元数据
├── README.md                  # 📝 核心项目概览
├── LICENSE                    # ⚖️ MIT
└── .gitignore                 # 🙈 忽略规则

```

--- 


## 🗺️ 计划路线

Spice 是一个不断进化的决策层系统

我们已经构建了核心运行环境、个人参考应用以及基于 SDEP 的执行循环  
接下来，我们将专注于扩展功能和生态系统

欢迎提交 PR —— 系统设计为模块化且可扩展

---

### 当前进展

- [x] 决策运行环境 (perception → state → decision → reflection)  
- [x] 个人参考应用 (CLI + onboarding)  
- [x] SDEP (Decision → Execution protocol)  
- [x] 外部 Agent 的封装器生态系统
- [x] End-to-end loop (decision → execution → outcome)  

---

### 下一步

- [ ] **更丰富的决策建模**  
  更好的模拟、权衡分析和多步推理 

- [ ] **更强的记忆层**  
  长期状态、上下文压缩和记忆提供商

- [ ] **更多的执行端集成**  
  扩展 Agent 生态系统

- [ ] **多步决策工作流**  
  从单一决策 → 结构化计划和执行链 

- [ ] **更好的可观测性**  
  检查决策、执行追踪和状态转换  

---

### 长期目标

- [ ] **领域扩展**  
  将 Spice 应用于个人之外的新领域（软件、运营、研究包括但不仅限于数字世界）

- [ ] **原生 SDEP 生态**  
  更多直接支持 SDEP 的 Agent（减少对封装器的依赖）

- [ ] **持久决策系统**  
  能够随时间不断学习和进化的系统


---


## 🌌 愿景

我们相信 AI 的未来不仅仅是执行 —  
而是更好的思考和决策方式

Spice 旨在构建 AI 技术栈中的一个新层级：  
位于 Agent 之上的**决策层**

---

我们的目标很简单：

> **每个人都应该拥有一个 Spice（个性化的AI大脑）**

一个能够：

- 理解你的世界 
- 维护你的状态  
- 帮助你思考决策 
- 并在需要时采取行动的系统 

---

不仅仅是一个工具  
不仅仅是一个聊天机器人

而是一个**个人的决策大脑**
随时间推移与你共同进化

---

我们尚处于早期阶段

但我们相信这个方向将带来：

- 更深思熟虑的决策  
- 更强大的系统  
- 以及与 AI 交互的新方式  

---

> Spice 不不仅仅是一个助手  
> 它是迈向人人享有的决策大脑的一步


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
