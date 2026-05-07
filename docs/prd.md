# Agent-Tune-CLI 自动化评估与调优工具

## 1. 产品概述
### 1.1 产品背景
在 Agent 和 LLM 应用的开发过程中，效果评估和错误调优往往占据大量时间。传统的测试手段难以应对生成式 AI 的不确定性，且修复过程依赖人工排查日志和手动修改代码。本产品旨在构建一个运行在终端的轻量级自动化测试与自修复闭环（Agentic CI/CD），大幅缩短独立开发者和敏捷团队的迭代周期。

### 1.2 核心目标
* **零侵入性 (Zero-Intrusion)：** 无需修改待测 Agent 核心业务逻辑，通过 REST API 和标准 Header 进行黑盒测试与白盒观测。
* **规范驱动 (Spec-Driven)：** 以结构化的数据集作为 Executable Spec，以结构化的诊断报告驱动 AI 辅助编程工具。
* **端到端自动化：** 实现“批量执行 -> 自动评估 -> 失败聚类 -> 代码修复 -> 回归验证”的完整微循环。

### 1.3 目标用户
* 专注于 Micro SaaS 与 Agent 应用开发的独立开发者。
* 习惯在终端环境（如 Ghostty、Tmux）工作，并熟练使用 Vibe Coding 或命令行 AI 辅助编程工具的工程师。

---

## 2. 系统架构与技术栈选型

本系统采用极简的解耦架构，通过 CLI 串联三大开源/成熟工具组件：

* **执行与可观测层：** HTTP/REST Client + **Langfuse** (承载日志、Trace、耗时与工具调用记录)。
* **评估与诊断层：** **DeepEval** (承载 LLM-as-a-Judge 自动化打分) + 轻量级大模型聚类。
* **自动修复层：** **Claude Code** (承载基于诊断规范的终端无缝代码修改)。



---

## 3. 核心工作流 (User Journey)

用户在终端下的标准操作路径如下：

1.  **初始化 (`agent-tune init`)：** 在 Agent 项目根目录生成 `tune.yaml` 和默认的数据集模板目录。
2.  **编写规范：** 用户在 `test_cases.json` 中填充业务场景、输入载荷与断言标准。
3.  **运行评估 (`agent-tune run`)：** 引擎批量调用 Agent API，拉取 Langfuse Trace，交由 DeepEval 打分，并输出控制台汇总报告。
4.  **智能诊断 (`agent-tune diagnose`)：** 提取失败样例，调用 LLM 进行根因聚类分析，生成结构化文档 `diagnostic.md`。
5.  **一键修复 (`agent-tune fix`)：** 唤起 Claude Code 读取 `diagnostic.md` 执行代码修改，并在完成后自动触发 Regression 回归测试。

---

## 4. 功能需求详细说明

### 4.1 初始化与配置模块 (Configuration)
* **功能描述：** 提供全局配置能力，支持多环境变量，确保敏感凭证安全。
* **需求细项：**
    * 必须支持从系统环境变量读取密钥（如 `${LANGFUSE_PUBLIC_KEY}`）。
    * 定义 `tune.yaml`，包含 API 地址、Payload 映射规则（JSON Path 支持）以及 Trace ID 注入方式（默认通过 `X-Tune-Trace-Id` Header）。
    * 支持自定义 Claude Code 唤起指令及工作区路径约束。

### 4.2 批量执行引擎 (Execution Runner)
* **功能描述：** 解析测试数据集，并发/串行向目标 Agent 发起 HTTP 请求。
* **需求细项：**
    * **动态 Payload 组装：** 根据 `tune.yaml` 的 `payload_mapping` 将数据集的 `inputs` 动态渲染为 API Request Body。
    * **Trace 绑定：** 为每个 Test Case 生成 UUID，通过 Header 注入，等待 Agent 响应后，轮询/拉取 Langfuse API 获取完整执行拓扑（包含内部 Tool Calls、Retrieved Documents 等）。
    * **容错处理：** 支持网络超时重试及限流控制。

### 4.3 自动化评估与诊断模块 (Evaluator & Diagnoser)
* **功能描述：** 对执行结果进行多维断言，并生成高行动力（Actionable）的诊断报告。
* **需求细项：**
    * **多态断言适配：** 支持基于大模型的判别（`llm_as_judge`）、结构化匹配（`json_schema_match`）、工具调用检查（`tool_call_check`）等。
    * **失败聚类 (Clustering)：** 调用辅助 LLM 接口，将未通过测试的用例按 `tags` 和错误表象进行合并（例如：3个用例均因“未调用检索工具”失败）。
    * **报告生成：** 输出符合 Spec 规范的 Markdown 文件，必须包含错误分类、期望输出、实际 Langfuse Trace 截取及修复建议。

### 4.4 终端自主修复引擎 (Auto-Fix Integration)
* **功能描述：** 无缝连接终端 AI 编码助手，形成闭环。
* **需求细项：**
    * **子进程唤醒：** 基于配置的 CLI 命令（如 `claude -p "..."`），在后台或当前 TTY 拉起子进程。
    * **上下文收敛：** 限制 AI 助手的修改范围，强制其依据 `diagnostic.md` 中的规范进行点对点修复，避免全局代码篡改。
    * **状态监听：** 捕获修复工具的 Exit Code，若成功退出，则自动带上 `--regression` 标识重新执行失败的用例集。

---

## 5. 数据协议与接口标准

### 5.1 评估数据集规范 (`test_cases.json`)
作为核心的测试协议，支持灵活的断言组合。
* **`id` / `tags`**: 唯一标识与聚类标签。
* **`inputs`**: 任意格式的输入集合，解耦 API 结构。
* **`context`**: RAG 场景下的黄金文档对照组。
* **`assertions`**: 多维校验规则数组（支持 Threshold、Schema、Exact Match）。

### 5.2 诊断报告结构规范 (`diagnostic.md`)
专为投喂给大模型（如 Claude Code）优化的结构。
* **[Issue Cluster]**: 问题分类与高频特征。
* **[Actual vs Expected]**: 具体样例的对比。
* **[Trace Context]**: 失败瞬间的完整调用栈/参数（精准切片，剔除冗余日志）。
* **[Required Action]**: 明确的修复指令（修改 Prompt、调整路由逻辑或修正数据解析）。

---

## 6. 非功能性需求
1.  **轻量化：** CLI 工具本身使用单文件二进制发布（如 Go/Rust）或轻量的 Node.js/Python 脚本，不引入重度本地数据库依赖。
2.  **兼容性：** 能够良好运行在 Tmux 等多窗口终端下，不阻塞用户的日常 Shell 交互。
3.  **安全性：** 工具绝不在日志或生成报告中硬编码任何 API 密钥；对 LLM-as-a-Judge 的 prompt 进行防注入处理。