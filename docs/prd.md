# 1. 产品概述

## 1.1 产品名称

**Agent-Eval-CLI**

## 1.2 产品定位

Agent-Eval-CLI 是一个 **完全 local-first 的 Agent 批量评测与异常分析命令行工具**。
它通过本地配置和本地测试数据集，对 Agent 服务进行批量执行、混合评估、失败聚类和分析报告生成，帮助开发者持续发现问题、定位问题、归纳问题，为后续人工调优或结合 Claude Code 进行项目改造与修复提供结构化输入。

## 1.3 产品目标

本产品第一阶段不追求自动修复，不提供线上可观测平台，而是聚焦以下核心目标：

1. **批量执行 Agent 测试**
   基于本地测试集和配置，对目标 Agent 执行大规模批量测试。

2. **结构化评估测试结果**
   支持硬断言、语义评估、执行语义检查等多种评估方式。

3. **尽可能还原执行现场**
   通过最小调试元信息采集机制，在不引入在线 tracing 平台的前提下，尽可能保留 Agent 的执行上下文。

4. **发现并归类异常问题**
   对失败样例进行结构化归因和聚类，形成问题簇。

5. **生成本地分析报告**
   输出适合开发者阅读的报告，以及适合后续调优工具消费的机器可读结果文件。

## 1.4 非目标

以下能力不属于当前版本主目标：

* 不提供 SaaS 服务
* 不依赖 Langfuse 等线上 observability 平台
* 不提供 Web Dashboard
* 不在 V1 中内置自动修复闭环
* 不强依赖 Claude Code 作为运行时内核
* 不要求完整 span 级 tracing 体系

## 1.5 目标用户

* 持续开发 Agent / LLM 应用的独立开发者
* 小型敏捷研发团队
* 偏好终端环境、local-first 工作流的工程师
* 希望通过测试与报告持续改进 Agent 质量的开发者

---

# 2. 产品核心设计原则

## 2.1 完全 local-first

所有配置、测试数据、执行结果、分析报告全部保存在本地文件系统中，不依赖线上平台。

## 2.2 评测与调优解耦

产品本体只负责“评测、分析、归类、报告”，不将自动修复与自动调优纳入核心执行链路。

## 2.3 最小可复原执行现场

不追求完整 tracing 平台，而通过统一的 `debug_meta` 协议记录最小必要调试现场。

## 2.4 文件协议优先

所有结果均以本地文件落盘，既适合人阅读，也适合后续程序消费。

## 2.5 接入成本分层

支持从纯黑盒评测到轻量观测评测的分层接入方式，降低原始 Agent 项目的接入门槛。

---

# 3. 产品能力边界

---

## 3.1 当前版本必须具备的能力

### 3.1.1 批量执行

* 支持读取本地测试集
* 支持串行与并发执行
* 支持超时、重试、失败容错
* 当前本地实现支持脚本模式、HTTP/API 模式与 Python 本地适配器模式
* 默认示例与适配器路径均保持 local-first/offline，不要求线上服务或 live LLM

### 3.1.2 混合评估

* 硬断言评估
* LLM 语义评估
* 执行语义评估

### 3.1.3 异常发现与聚类

* 标记失败样例
* 提取 failure signature
* 进行规则聚类
* LLM 总结与命名进入 V1.1

### 3.1.4 本地结果与报告

* 保存原始执行结果
* 保存评估结果
* 保存失败样例
* 保存聚类结果
* 生成 Markdown 汇总报告
* 生成可供后续修复工具消费的 JSON 结构化结果

---

## 3.2 当前版本不包含的能力

* Node adapter mode（仍作为后续 V1.1+ 候选）
* LLM cluster 总结与命名（仍作为后续 V1.1+ 候选）
* 加权 pass rule（仍作为后续 V1.1+ 候选）
* 更细粒度 failure signature 与更丰富执行语义断言（后续 V1.5+ 候选）
* Web/SaaS Dashboard、线上 observability、数据库或实时 trace 可视化
* 自动 patch 代码
* 自动修改 Prompt
* 自动提交修复 PR
* 线上运行态观测平台
* 团队协作界面
* 实时 trace 可视化

---

# 4. 典型使用场景

## 4.1 场景一：本地批量回归测试

开发者修改了 Agent 路由逻辑后，希望批量回归一组测试集，确认没有明显退化。

## 4.2 场景二：RAG Agent 异常分析

开发者希望定位哪些问题是“未触发检索”导致，哪些问题是“检索触发了但未使用结果”导致。

## 4.3 场景三：版本迭代对比

开发者希望对比不同版本 Agent 在同一批数据集上的通过率与主要失败簇变化。

## 4.4 场景四：为 Claude Code 调优提供输入

开发者希望先通过 Agent-Eval-CLI 生成结构化问题报告，再在后续单独的调优流程中使用 Claude Code 做代码与 Prompt 调整。

---

# 5. 用户工作流

## 5.1 初始化项目

用户执行：

```bash
agent-eval init
```

生成：

* `eval.yaml`
* `cases/`
* `runs/`
* `reports/`

## 5.2 准备测试数据

用户在 `cases/*.jsonl` 中编写测试用例。

## 5.3 接入原始 Agent

用户按项目情况选择：

* HTTP 模式
* 脚本模式
* 本地适配器模式

如需更低接入成本，可后续通过 Claude Code 进行项目适配改造。

## 5.4 执行批量评测

用户执行：

```bash
agent-eval run
```

工具完成：

* 读取 case
* 批量执行 Agent
* 采集结果与最小调试现场
* 执行评估
* 提取失败样例
* 聚类
* 生成报告

## 5.5 查看分析结果

用户执行：

```bash
agent-eval inspect --run latest
```

查看：

* 某个 run 的总览
* 某个 case 的具体失败原因
* 某个 cluster 的共性问题

## 5.6 导出后续调优输入

用户执行：

```bash
agent-eval export --run latest
```

生成：

* `repair_input.json`

供后续 Claude Code 调优流程使用。

---

# 6. 系统整体架构

---

## 6.1 架构概览

```text
+-------------------------+
|      CLI Interface      |
+-------------------------+
            |
            v
+-------------------------+
|   Config / Dataset      |
+-------------------------+
            |
            v
+-------------------------+
|       Runner Engine     |
| (execute target agent)  |
+-------------------------+
            |
            v
+-------------------------+
|   Result Collector      |
| raw output + debug meta |
+-------------------------+
            |
            v
+-------------------------+
|   Evaluation Engine     |
| rule eval + DeepEval    |
+-------------------------+
            |
            v
+-------------------------+
|   Failure Clusterer     |
+-------------------------+
            |
            v
+-------------------------+
|     Report Generator    |
+-------------------------+
            |
            v
+-------------------------+
| Local File Artifacts    |
+-------------------------+
```

---

## 6.2 核心模块

### 6.2.1 CLI Interface

负责命令解析、参数路由、输出控制台结果。

### 6.2.2 Config / Dataset Loader

负责加载：

* `eval.yaml`
* case 文件
* 模型配置
* runner 配置

### 6.2.3 Runner Engine

负责：

* 调用 Agent
* 并发控制
* 超时重试
* 错误捕获
* 采集原始结果

### 6.2.4 Result Collector

负责将每次执行结果统一封装为标准结构，并落盘。

### 6.2.5 Evaluation Engine

负责：

* 执行硬断言
* 执行语义评估
* 执行执行语义检查

### 6.2.6 Failure Clusterer

负责：

* 生成 failure signature
* 聚类失败样例
* 生成高层问题簇

### 6.2.7 Report Generator

负责：

* 统计汇总
* Markdown 报告
* JSON 报告
* 调优输入导出

---

# 7. 接入模式设计

---

## 7.1 Mode A：HTTP 模式

适合已有服务化 Agent。

### 输入

* API URL
* 请求方法
* body 模板
* headers 模板

### 输出

* HTTP 响应
* 状态码
* 耗时
* 可选 `debug_meta`

### 优点

* 通用性强
* 最少侵入

### 局限

* 若无 `debug_meta`，只能做黑盒评测

---

## 7.2 Mode B：脚本模式

通过本地命令执行目标 Agent。

例如：

```bash
python run_agent.py --input-file tmp_case.json
```

### 适用场景

* 未服务化的本地项目
* CLI 驱动型 Agent

---

## 7.3 Mode C：本地适配器模式

当前本地发布面通过 Python adapter 调用本地函数；Node adapter 仍作为后续候选，不属于当前支持面。

### 适用场景

* 单仓库开发
* 本地开发效率优先
* 需要更细粒度采集调试信息

---

# 8. 核心数据协议设计

---

## 8.1 配置文件 `eval.yaml`

```yaml
project:
  name: my-agent
  mode: http

runner:
  concurrency: 5
  timeout_seconds: 60
  retry_times: 1
  fail_fast: false

target:
  http:
    url: "http://localhost:8000/chat"
    method: "POST"
    headers:
      Content-Type: "application/json"
    payload_mapping:
      query: "$.inputs.query"
      user_id: "$.inputs.user_id"

dataset:
  paths:
    - "cases/smoke.jsonl"
    - "cases/rag.jsonl"

evaluation:
  llm_judge:
    enabled: false
    provider: stub
    model: stub
  rule_assertions:
    enabled: true

cluster:
  enabled: true
  llm_summary: false

artifacts:
  root_dir: "./runs"
  save_raw_response: true
  save_debug_meta: true
```

---

## 8.2 测试用例协议 `cases/*.jsonl`

每行一个 case：

```json
{
  "id": "rag_001",
  "tags": ["rag", "pricing"],
  "priority": "p1",
  "inputs": {
    "query": "请介绍产品套餐价格",
    "user_id": "u001"
  },
  "context": {
    "golden_docs": []
  },
  "assertions": [
    {
      "type": "llm_judge",
      "metric": "correctness"
    },
    {
      "type": "json_schema_match",
      "target": "$.answer"
    }
  ],
  "expected_execution": {
    "expected_route": "knowledge_qa",
    "must_call_tools": ["retriever.search"],
    "forbid_tools": [],
    "max_tool_calls": 3,
    "min_retrieval_docs": 1
  },
  "evaluation_policy": {
    "reruns": 1,
    "pass_rule": "all"
  }
}
```

---

## 8.3 原始执行结果协议 `raw_results.jsonl`

```json
{
  "run_id": "2026-05-07_001",
  "case_id": "rag_001",
  "status": "success",
  "latency_ms": 1450,
  "request": {
    "query": "请介绍产品套餐价格"
  },
  "response": {
    "answer": "..."
  },
  "debug_meta": {
    "route": "knowledge_qa",
    "retrieval_used": true,
    "retrieval_doc_count": 3,
    "tool_calls": [
      {
        "name": "retriever.search",
        "latency_ms": 120
      }
    ],
    "fallback_used": false,
    "error_code": ""
  },
  "error": null
}
```

---

## 8.4 评估结果协议 `eval_results.jsonl`

```json
{
  "run_id": "2026-05-07_001",
  "case_id": "rag_001",
  "passed": false,
  "assertion_results": [
    {
      "type": "llm_judge",
      "metric": "correctness",
      "passed": false,
      "score": 0.42,
      "reason": "回答未覆盖价格关键信息"
    },
    {
      "type": "tool_call_check",
      "passed": true
    }
  ],
  "failure_signature": {
    "assertion_type": "llm_judge",
    "error_code": "insufficient_answer",
    "route_name": "knowledge_qa",
    "tool_name": ""
  }
}
```

---

## 8.5 聚类结果协议 `clusters.json`

```json
{
  "run_id": "2026-05-07_001",
  "clusters": [
    {
      "cluster_id": "cluster_001",
      "title": "价格问答答案覆盖不足",
      "severity": "medium",
      "case_ids": ["rag_001", "rag_008"],
      "common_signature": {
        "assertion_type": "llm_judge",
        "error_code": "insufficient_answer"
      },
      "summary": "这些失败样例主要表现为回答不完整，未覆盖用户真正关注的套餐价格细节。",
      "suspected_modules": ["prompt_templates/pricing.md", "answer_formatter.py"]
    }
  ]
}
```

---

## 8.6 调优输入协议 `repair_input.json`

`repair_input.json` 与 `summary.md` 应由同一层本地分析结构生成，避免人类报告与机器可读调优输入出现诊断漂移。

```json
{
  "run_id": "2026-05-07_001",
  "project": "my-agent",
  "analysis": {
    "cluster_count": 1,
    "totals": {
      "total": 8,
      "passed": 6,
      "failed": 2,
      "pass_rate": 75.0
    },
    "tag_breakdown": {
      "pricing": {
        "total": 2,
        "passed": 0,
        "failed": 2,
        "pass_rate": 0.0
      }
    },
    "priority_breakdown": {
      "p1": {
        "total": 2,
        "passed": 0,
        "failed": 2,
        "pass_rate": 0.0
      }
    }
  },
  "clusters": [
    {
      "cluster_id": "cluster_001",
      "title": "价格问答答案覆盖不足",
      "severity": "medium",
      "cases": ["rag_001", "rag_008"],
      "common_signature": {
        "assertion_type": "llm_judge",
        "error_code": "insufficient_answer"
      },
      "suspected_modules": ["prompt_templates/pricing.md", "answer_formatter.py"],
      "evidence": [
        {
          "case_id": "rag_001",
          "reason": "回答未覆盖价格关键信息"
        }
      ],
      "analysis": {
        "representative_cases": ["rag_001", "rag_008"],
        "signature_explanation": "这些失败样例主要表现为回答不完整，未覆盖用户真正关注的套餐价格细节。",
        "affected_areas": ["route:knowledge_qa", "tag:pricing"],
        "suggested_investigation": "Start with representative cases rag_001, rag_008; review affected areas route:knowledge_qa, tag:pricing."
      }
    }
  ]
}
```

兼容性要求：

* 既有字段（如 `clusters[].cases`、`common_signature`、`evidence`、`suspected_modules`）保持稳定。
* 新增分析内容优先放在 `analysis` 命名空间下，作为 additive contract。
* 当本地证据无法推导怀疑模块时，`suspected_modules` 保持空数组，不臆测模块名。

---

# 9. 最小调试现场协议 `debug_meta`

这是 local-first 方案的关键设计点。

## 9.1 目标

在不引入 Langfuse 的前提下，为失败分析与聚类提供最小必要执行上下文。

## 9.2 推荐字段

```json
{
  "route": "knowledge_qa",
  "retrieval_used": true,
  "retrieval_doc_count": 3,
  "tool_calls": [
    {
      "name": "retriever.search",
      "latency_ms": 120
    }
  ],
  "fallback_used": false,
  "prompt_version": "v12",
  "config_version": "2026-05-07",
  "error_code": ""
}
```

## 9.3 原则

* 仅记录必要字段
* 尽量避免泄露敏感信息
* 优先记录结构化信息
* 避免记录完整 prompt 和全部中间上下文，除非明确配置允许

---

# 10. 评估体系设计

---

## 10.1 评估类型总览

### A. 硬断言

适合确定性场景。

V1 支持：

* HTTP 状态码检查
* JSON Schema 的对象 key/type 子集校验
* JSONPath 字段存在性检查
* Exact Match
* Contains
* 数值阈值判断

### B. 语义评估

适合自然语言质量判断。

V1 基于可选 DeepEval provider 完成最小可用语义评估：

* `answer_relevancy`
* 默认离线 stub，不强制安装 DeepEval 或配置线上凭证

V1.1+ 可继续扩展：

* Correctness
* Faithfulness
* Completeness
* 自定义 LLM Judge Metric

### C. 执行语义评估

基于 `debug_meta` 与 `expected_execution` 完成。

支持：

* expected_route
* must_call_tools
* forbid_tools
* max_tool_calls
* min_retrieval_docs
* fallback_used 是否符合预期

---

## 10.2 评估执行顺序

建议固定为：

1. 硬断言
2. 执行语义评估
3. 语义评估

这样可以优先发现最确定的问题。

---

## 10.3 通过判定规则

V1 支持：

* 全部通过
* 任一通过
* 多数通过

V1.1+ 可继续扩展：

* 加权判定
* 多轮 rerun 后多数通过

---

# 11. 失败聚类设计

---

## 11.1 聚类目标

将离散失败样例归纳为少量高价值问题簇，降低人工分析成本。

## 11.2 聚类流程

### 第一步：提取 failure signature

从失败样例中提取：

* assertion_type
* error_code
* tool_name
* route_name
* tag
* priority

### 第二步：规则聚类

按 signature 进行稳定归并。

### 第三步：LLM 总结（V1.1+）

V1 仅要求稳定的规则聚类；V1.1+ 可选调用 LLM：

* 命名 cluster
* 总结共性
* 生成高层怀疑根因

---

## 11.3 失败签名示例

```json
{
  "assertion_type": "tool_call_check",
  "error_code": "tool_not_called",
  "tool_name": "retriever.search",
  "route_name": "knowledge_qa"
}
```

---

# 12. 报告系统设计

---

## 12.1 控制台输出

执行完成后在终端打印：

* 总 case 数
* 通过率
* 失败数
* Top 失败簇
* 运行目录

## 12.2 Markdown 汇总报告 `summary.md`

建议包含：

1. 本次运行摘要
2. 通过率统计
3. 按 tags 统计
4. 按 priority 统计
5. Top failure clusters
6. 每个 cluster 的典型样例
7. common signature / signature explanation
8. evidence snippets / failure reasons
9. 怀疑模块或 affected areas（仅在本地证据可推导时）
10. 建议排查方向

`summary.md` 与 `repair_input.json` 必须共享同一分析来源：Markdown 面向人工阅读，JSON 面向后续自动化调优，但二者的代表样例、证据、signature 解释、tag/priority 统计和建议排查方向应保持一致。

## 12.3 JSON 结果

输出：

* `raw_results.jsonl`
* `eval_results.jsonl`
* `failures.jsonl`
* `clusters.json`
* `repair_input.json`

---

# 13. 本地目录结构设计

```text
agent-eval/
  eval.yaml
  cases/
    smoke.jsonl
    rag.jsonl
  runs/
    2026-05-07_001/
      manifest.json
      raw_results.jsonl
      eval_results.jsonl
      failures.jsonl
      clusters.json
      summary.md
      repair_input.json
  reports/
    latest.md
```

## 13.1 目录说明

* `cases/`：测试集
* `runs/`：每次运行的完整产物
* `reports/`：快捷引用的最新报告
* `eval.yaml`：全局配置

---

# 14. CLI 命令设计

---

## 14.1 `agent-eval init`

初始化项目目录与模板文件。

### 输出

* `eval.yaml`
* `cases/sample.jsonl`
* 目录结构

---

## 14.2 `agent-eval run`

执行完整批量评测流程。

### 行为

* 读取配置
* 加载测试集
* 调用 Agent
* 评估结果
* 聚类失败
* 生成报告

### 常用参数

```bash
agent-eval run --dataset cases/rag.jsonl
agent-eval run --run-name exp_001
agent-eval run --concurrency 10
```

---

## 14.3 `agent-eval inspect`

查看某次 run / 某个 case / 某个 cluster 的详情。

### 示例

```bash
agent-eval inspect --run latest
agent-eval inspect --run 2026-05-07_001 --cluster cluster_001
agent-eval inspect --run 2026-05-07_001 --case rag_001
```

---

## 14.4 `agent-eval export`

导出后续调优使用的结构化输入。

### 示例

```bash
agent-eval export --run latest
```

---

# 15. Claude Code 协作定位

---

## 15.1 当前版本中的角色

Claude Code 不作为产品核心运行时，只作为后续协作工具预留。

### 职责一：项目适配改造助手

帮助原始 Agent 项目：

* 增加 `debug_meta`
* 生成 `eval.yaml`
* 生成本地适配器
* 生成脚本入口
* 规范输出结构

### 职责二：后续调优执行器

在未来独立调优服务中读取：

* `summary.md`
* `clusters.json`
* `repair_input.json`

再做：

* 代码修改
* Prompt 调整
* 回归验证

---

## 15.2 不承担的职责

在当前版本中，Claude Code 不负责：

* 主测试执行
* 主评估逻辑
* 主聚类逻辑
* 主报告逻辑

---

# 16. 技术选型建议

---

## 16.1 主实现语言

建议使用 **Python**。

### 原因

* DeepEval 原生位于 Python 生态
* JSONL / YAML / 报告处理方便
* CLI 开发成熟
* 便于未来与 Claude Code 协作脚本集成

## 16.2 推荐技术栈

* CLI：Typer / Click
* 配置：PyYAML
* 数据协议：Pydantic
* 并发执行：asyncio / httpx
* 评估：DeepEval
* 模板渲染：Jinja2
* 报告输出：Markdown 生成
* 测试：pytest

---

# 17. 非功能需求

---

## 17.1 可复现性

每次运行必须记录：

* run_id
* 时间戳
* 配置快照
* 数据集路径
* 模型配置
* 工具版本

## 17.2 本地可调试性

所有中间产物可直接打开查看，不依赖外部平台。

## 17.3 安全性

* 默认不记录敏感凭证
* 默认不记录完整 prompt 与敏感上下文
* 支持脱敏输出

## 17.4 性能

* 支持小规模并发
* 单机可运行
* 不依赖数据库

## 17.5 扩展性

后续可增加：

* 历史 run 对比
* CI 集成
* Claude Code bootstrap
* Claude Code 调优插件

---

# 18. 版本规划建议

---

## 当前已支持的本地发布面

聚焦：

* init
* run
* inspect
* export
* compare
* 本地文件落盘
* 脚本、HTTP/API、Python adapter 三种目标模式
* `evaluation_policy.reruns` 的本地重跑与 `attempts.jsonl` 辅助产物
* 混合评估：硬断言、执行语义评估、可选 DeepEval `answer_relevancy`
* 失败聚类
* `summary.md` 与 `repair_input.json` 共享本地分析来源的基础报告生成

## V1.1+ 候选

仍延期：

* 加权 pass rule
* LLM cluster summary / naming
* 更完整的人工深度报告体验（在当前 `summary.md`/`repair_input.json` 基础上继续扩展）

## V1.5+ 候选

增加：

* 更细粒度 failure signature
* 更丰富的执行语义断言
* 更好的 cluster 命名

## V2

独立引入：

* Claude Code bootstrap
* Claude Code 调优执行流
* 局部回归测试协同

---

# 19. 最终产品定义

**Agent-Eval-CLI 是一个完全 local-first 的 Agent 批量评测与异常分析命令行工具。**
它基于本地测试集和配置批量执行 Agent，采集最小可复原执行现场，对结果进行混合评估、失败聚类和报告生成，并输出适合后续 Claude Code 进行项目适配改造与持续调优的结构化分析结果。
