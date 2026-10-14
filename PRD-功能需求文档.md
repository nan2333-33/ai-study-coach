# AI 学习助手 — 功能需求文档（PRD）

> 版本：v1.0 | 日期：2026-10-11
> 场景：上传大模型课程资料（PDF/PPT/MD）→ 对话式学习 → 自动出题测评 → 进度跟踪 → 周报生成
> 约束：五功能闭环（传资料、聊资料、做测评、看进度、出周报），不发散
>
> **本文档是唯一事实来源。** 用于作品集 / 面试的叙事材料在 `showcase/`（产品一页纸、关键决策记录、演示脚本），
> 它们是从本文档**派生**的——本文档改动后需回头同步那三份，不要另立第二份 PRD。

---

## 一、功能拆分与优先级

优先级定义：
- **P0**：MVP 必须先做，缺了产品跑不起来
- **P1**：MVP 之后第一迭代，显著提升体验
- **P2**：后续迭代，锦上添花

### 1. 传资料

| 编号 | 功能点 | 说明 | 优先级 |
|------|--------|------|:---:|
| M-01 | 文件上传 | 支持 PDF / PPT / Markdown 三种格式，单文件上限 50MB | P0 |
| M-02 | 文本提取 | PDF 提取正文（含分页标记）；PPT 提取每页文本+备注；MD 直接读取 | P0 |
| M-03 | 文本分块 | 按语义切块（chunk），每块 500-800 字，保留页码/页位置元数据 | P0 |
| M-04 | 向量化与存储 | 对每个 chunk 生成 embedding，存入向量数据库 | P0 |
| M-05 | 来源元数据 | 记录每个 chunk 的来源文件名、页码、块序号，供对话引用 | P0 |
| M-06 | PPT 深度解析 | PPT 中的图表/流程图做 OCR + 多模态理解，提取为文字描述 | P1 |
| M-07 | 批量上传 | 支持一次传多个文件 | P1 |
| M-08 | 资料管理 | 列表、删除、重命名、按课程分类 | P1 |
| M-09 | 增量更新 | 重新上传同名文件时增量替换，不重复向量化 | P2 |

### 2. 聊资料

| 编号 | 功能点 | 说明 | 优先级 |
|------|--------|------|:---:|
| C-01 | RAG 检索 | 用户提问 → 检索相关 chunk → 拼接为上下文 → 交给 LLM 生成回答 | P0 |
| C-02 | 来源引用 | 每条回答标注来源（文件名 + 页码），用户可点击跳转原文 | P0 |
| C-03 | 多轮对话 | 维持会话上下文，支持追问、指代消解 | P0 |
| C-04 | 多资料交叉引用 | 一次提问可检索多份资料，回答中分别标注各来源 | P0 |
| C-05 | 会话管理 | 创建/列表/删除会话，按时间或主题归档 | P1 |
| C-06 | 对话导出 | 导出当前会话为 Markdown | P2 |
| C-07 | 资料笔记 | 每份资料可写笔记，停笔后自动保存，内容过长可缩略显示 | P0 |

### 3. 做测评

| 编号 | 功能点 | 说明 | 优先级 |
|------|--------|------|:---:|
| Q-01 | 自动出题 | 基于指定资料生成题目，三种题型：选择题、判断题、简答题 | P0 |
| Q-02 | 题目质量校验 | 生成后自动校验：选择题有且仅有一个正确答案；判断题答案明确；简答题有参考答案 | P0 |
| Q-03 | 答题提交 | 用户在线答题，提交后进入批改流程 | P0 |
| Q-04 | 自动批改 | 选择题/判断题：与标准答案比对，对就是对错就是错；简答题：AI 评分 0 / 0.5 / 1 分 | P0 |
| Q-05 | 测验结果展示 | 显示总分、各题对错、正确答案、简答题评语 | P0 |
| Q-06 | 错题本 | 自动收录做错的题，按资料/知识点归类 | P1 |
| Q-07 | 薄弱知识点分析 | 基于错题聚类，标注用户在哪些知识块薄弱 | P1 |
| Q-08 | 间隔重复调度 | 基于 SM-2 算法，根据答题正确率动态调整错题的下次复习时间 | P1 |
| Q-09 | 定向复测 | 针对薄弱知识点从错题本中抽取相关题再次测验 | P1 |
| Q-10 | 难度分级 | 出题时支持指定难度（基础/进阶/挑战） | P2 |

### 4. 看进度

| 编号 | 功能点 | 说明 | 优先级 |
|------|--------|------|:---:|
| P-01 | 学习时长统计 | 记录每次会话/测验的时长 | P0 |
| P-02 | 资料覆盖量 | 统计已上传资料数、已对话覆盖的 chunk 比例 | P0 |
| P-03 | 测验正确率 | 统计历次测验的正确率 | P0 |
| P-04 | Session 级 checklist | 每次学习会话生成清单（看资料了？对话了？测验了？） | P1 |
| P-05 | 跨周期趋势 | 正确率/学习时长的周/月趋势图 | P1 |
| P-06 | 掌握度热力图 | 按资料/章节维度展示掌握程度（绿/黄/红） | P2 |

> **实现偏差（2026-10-13，已与需求方确认）**：P-01「学习时长统计」**不做**，主指标换成 **答题数**（`quiz_answers` 行数）。
> 原因：系统只能靠事件时间戳间隔推算时长，拿不出证据证明它等于用户真实花的时间；
> 一个学习产品摆一个自己推算的数字，用户一对发现对不上，会连带着怀疑正确率、掌握度这些真实统计。
> 答题数是硬计数，可核对。P-05 的趋势图也相应改为「答题数 + 正确率」趋势，不含时长。
> 连续学习天数保留——它只数「有学习行为的日期」，来自真实事件日期，不是推算值。

### 5. 出周报

| 编号 | 功能点 | 说明 | 优先级 |
|------|--------|------|:---:|
| R-01 | 周报生成 | 汇总本周数据，自动生成周报 | P0 |
| R-02 | 周报内容 | 包含：**做题量**（原「学习时长」，见上方偏差说明）、资料覆盖、正确率趋势、薄弱 TOP3、下周计划、一句话激励 | P0 |
| R-03 | 周报历史 | 保存历史周报，可回看对比 | P1 |
| R-04 | 主动推送 | 每周固定时间自动生成并推送提醒 | P1 |
| R-05 | 可分享卡片 | 周报导出为图片卡片，可分享到社群 | P2 |

---

## 二、后台接口设计

> 基础路径：`/api`
> 请求格式：JSON
> 认证方式：`Authorization: Bearer <token>`（MVP 阶段可先用简单 token）

### 2.1 传资料模块

#### POST /api/materials/upload
上传资料文件。

| 参数 | 位置 | 类型 | 必填 | 说明 |
|------|------|------|:---:|------|
| file | form-data | File | 是 | 上传的文件（PDF/PPT/MD） |
| title | form-data | String | 否 | 资料标题，默认取文件名 |
| category | form-data | String | 否 | 课程分类标签 |

**返回：**
```json
{
  "code": 0,
  "data": {
    "materialId": "mat_001",
    "title": "Transformer 架构详解",
    "fileName": "transformer.pdf",
    "fileType": "pdf",
    "status": "processing",
    "chunkCount": 0,
    "createdAt": "2026-10-11T11:00:00Z"
  }
}
```

#### GET /api/materials
获取资料列表。

| 参数 | 位置 | 类型 | 必填 | 说明 |
|------|------|------|:---:|------|
| category | query | String | 否 | 按分类筛选 |
| status | query | String | 否 | 按状态筛选（processing/ready/error） |
| page | query | Int | 否 | 页码，默认 1 |
| pageSize | query | Int | 否 | 每页条数，默认 20 |

**返回：**
```json
{
  "code": 0,
  "data": {
    "total": 15,
    "list": [
      {
        "materialId": "mat_001",
        "title": "Transformer 架构详解",
        "fileType": "pdf",
        "status": "ready",
        "chunkCount": 42,
        "category": "大模型基础",
        "createdAt": "2026-10-11T11:00:00Z"
      }
    ]
  }
}
```

#### GET /api/materials/:materialId
获取单个资料详情（含分块列表）。

**返回：**
```json
{
  "code": 0,
  "data": {
    "materialId": "mat_001",
    "title": "Transformer 架构详解",
    "fileType": "pdf",
    "status": "ready",
    "chunkCount": 42,
    "category": "大模型基础",
    "chunks": [
      {
        "chunkId": "chk_001",
        "chunkIndex": 0,
        "pageNumber": 1,
        "preview": "Transformer 是一种基于自注意力机制的神经网络架构..."
      }
    ],
    "createdAt": "2026-10-11T11:00:00Z"
  }
}
```

#### DELETE /api/materials/:materialId
删除资料（同时删除其所有分块和向量数据）。

**返回：**
```json
{ "code": 0, "data": { "materialId": "mat_001", "deleted": true } }
```

---

### 2.2 聊资料模块

#### POST /api/chat/sessions
创建对话会话。

| 参数 | 位置 | 类型 | 必填 | 说明 |
|------|------|------|:---:|------|
| materialIds | body | String[] | 否 | 绑定的资料 ID 列表，不传则默认全部资料 |
| title | body | String | 否 | 会话标题 |

**返回：**
```json
{
  "code": 0,
  "data": {
    "sessionId": "ses_001",
    "title": "Transformer 学习",
    "materialIds": ["mat_001", "mat_002"],
    "createdAt": "2026-10-11T11:05:00Z"
  }
}
```

#### POST /api/chat/sessions/:sessionId/messages
发送消息并获取 AI 回复。

| 参数 | 位置 | 类型 | 必填 | 说明 |
|------|------|------|:---:|------|
| message | body | String | 是 | 用户提问内容 |
| materialIds | body | String[] | 否 | 本次提问限定的资料范围（覆盖会话默认） |

**返回：**
```json
{
  "code": 0,
  "data": {
    "messageId": "msg_003",
    "role": "assistant",
    "content": "Transformer 的核心是自注意力机制。它允许模型在处理一个词时，同时关注序列中所有其他词……",
    "sources": [
      {
        "materialId": "mat_001",
        "title": "Transformer 架构详解",
        "pageNumber": 3,
        "chunkIndex": 12,
        "snippet": "自注意力机制通过计算 Query、Key、Value 三个矩阵……"
      },
      {
        "materialId": "mat_002",
        "title": "Attention Is All You Need 笔记",
        "pageNumber": 1,
        "chunkIndex": 0,
        "snippet": "Transformer 完全摒弃了循环神经网络结构……"
      }
    ],
    "createdAt": "2026-10-11T11:06:00Z"
  }
}
```

#### GET /api/chat/sessions/:sessionId/messages
获取会话历史消息。

| 参数 | 位置 | 类型 | 必填 | 说明 |
|------|------|------|:---:|------|
| page | query | Int | 否 | 页码 |
| pageSize | query | Int | 否 | 每页条数 |

**返回：**
```json
{
  "code": 0,
  "data": {
    "total": 6,
    "list": [
      {
        "messageId": "msg_001",
        "role": "user",
        "content": "什么是自注意力机制？",
        "createdAt": "2026-10-11T11:05:00Z"
      },
      {
        "messageId": "msg_002",
        "role": "assistant",
        "content": "自注意力机制是……",
        "sources": [/* 同上 */],
        "createdAt": "2026-10-11T11:05:30Z"
      }
    ]
  }
}
```

#### GET /api/chat/sessions
获取会话列表。

**返回：**
```json
{
  "code": 0,
  "data": {
    "total": 3,
    "list": [
      {
        "sessionId": "ses_001",
        "title": "Transformer 学习",
        "lastMessage": "自注意力机制是……",
        "materialCount": 2,
        "createdAt": "2026-10-11T11:05:00Z",
        "updatedAt": "2026-10-11T11:10:00Z"
      }
    ]
  }
}
```

#### DELETE /api/chat/sessions/:sessionId
删除会话。

**返回：**
```json
{ "code": 0, "data": { "sessionId": "ses_001", "deleted": true } }
```

#### GET /api/materials/:materialId/notes
获取某份资料的笔记。

**返回：**
```json
{
  "code": 0,
  "data": {
    "noteId": "nt_001",
    "materialId": "mat_001",
    "content": "自注意力机制的核心：Query、Key、Value 三个矩阵相乘……",
    "contentLength": 256,
    "collapsed": false,
    "updatedAt": "2026-10-11T11:30:00Z"
  }
}
```

> `collapsed` 表示前端是否应默认缩略显示（内容超过阈值如 200 字时为 true）。

#### PUT /api/materials/:materialId/notes
保存或更新笔记（前端检测到用户停笔 / 输入框失焦时自动调用，实现自动保存）。同一份资料只保留一份最新笔记，重复调用为覆盖更新。

| 参数 | 位置 | 类型 | 必填 | 说明 |
|------|------|------|:---:|------|
| content | body | String | 是 | 笔记全文 |

**返回：**
```json
{
  "code": 0,
  "data": {
    "noteId": "nt_001",
    "materialId": "mat_001",
    "content": "自注意力机制的核心：Query、Key、Value 三个矩阵相乘……",
    "contentLength": 256,
    "updatedAt": "2026-10-11T11:30:00Z"
  }
}
```

---

### 2.3 做测评模块

#### POST /api/quiz/generate
基于指定资料生成测验。

| 参数 | 位置 | 类型 | 必填 | 说明 |
|------|------|------|:---:|------|
| materialIds | body | String[] | 是 | 出题依据的资料 ID |
| questionCount | body | Int | 是 | 题目总数 |
| typeRatio | body | Object | 否 | 题型比例，默认各 1/3 |
| difficulty | body | String | 否 | 难度：basic/advanced/challenge，默认 basic |

**typeRatio 示例：**
```json
{ "choice": 0.4, "judgment": 0.3, "shortAnswer": 0.3 }
```

**返回：**
```json
{
  "code": 0,
  "data": {
    "quizId": "quiz_001",
    "materialIds": ["mat_001"],
    "status": "ready",
    "questions": [
      {
        "questionId": "q_001",
        "type": "choice",
        "question": "Transformer 中自注意力机制的核心计算涉及哪三个矩阵？",
        "options": {
          "A": "Query、Key、Value",
          "B": "Input、Hidden、Output",
          "C": "Embedding、Position、Context",
          "D": "Forward、Backward、Update"
        },
        "source": {
          "materialId": "mat_001",
          "pageNumber": 3,
          "chunkIndex": 12
        }
      },
      {
        "questionId": "q_002",
        "type": "judgment",
        "question": "Transformer 完全摒弃了循环神经网络结构，仅依赖注意力机制。",
        "source": {
          "materialId": "mat_002",
          "pageNumber": 1,
          "chunkIndex": 0
        }
      },
      {
        "questionId": "q_003",
        "type": "shortAnswer",
        "question": "简述多头注意力机制的作用。",
        "source": {
          "materialId": "mat_001",
          "pageNumber": 5,
          "chunkIndex": 20
        }
      }
    ],
    "createdAt": "2026-10-11T11:15:00Z"
  }
}
```

> 注意：返回中**不包含**正确答案，答案在提交后由批改接口返回。

#### POST /api/quiz/:quizId/submit
提交测验答案，触发批改。

| 参数 | 位置 | 类型 | 必填 | 说明 |
|------|------|------|:---:|------|
| answers | body | Object[] | 是 | 答题列表 |

**answers 示例：**
```json
[
  { "questionId": "q_001", "answer": "A" },
  { "questionId": "q_002", "answer": "true" },
  { "questionId": "q_003", "answer": "多头注意力允许模型同时从不同子空间关注不同位置的信息……" }
]
```

**返回（含批改结果）：**
```json
{
  "code": 0,
  "data": {
    "submissionId": "sub_001",
    "quizId": "quiz_001",
    "totalScore": 2.5,
    "maxScore": 3,
    "accuracy": 0.833,
    "results": [
      {
        "questionId": "q_001",
        "type": "choice",
        "userAnswer": "A",
        "correctAnswer": "A",
        "isCorrect": true,
        "score": 1,
        "explanation": null
      },
      {
        "questionId": "q_002",
        "type": "judgment",
        "userAnswer": "true",
        "correctAnswer": "true",
        "isCorrect": true,
        "score": 1,
        "explanation": null
      },
      {
        "questionId": "q_003",
        "type": "shortAnswer",
        "userAnswer": "多头注意力允许模型同时从不同子空间关注不同位置的信息……",
        "referenceAnswer": "多头注意力机制将注意力过程并行执行多次，每次使用不同的投影矩阵，使模型能够在不同表示子空间中关注不同位置的信息，最后拼接并线性变换输出。",
        "score": 0.5,
        "explanation": "回答提及了核心概念（多子空间、不同位置），但缺少拼接和线性变换的输出步骤，给 0.5 分。"
      }
    ],
    "submittedAt": "2026-10-11T11:20:00Z"
  }
}
```

#### GET /api/quiz/errors
获取错题本。

| 参数 | 位置 | 类型 | 必填 | 说明 |
|------|------|------|:---:|------|
| materialId | query | String | 否 | 按资料筛选 |
| type | query | String | 否 | 按题型筛选 |
| page | query | Int | 否 | 页码 |
| pageSize | query | Int | 否 | 每页条数 |

**返回：**
```json
{
  "code": 0,
  "data": {
    "total": 8,
    "list": [
      {
        "errorId": "err_001",
        "questionId": "q_003",
        "quizId": "quiz_001",
        "type": "shortAnswer",
        "question": "简述多头注意力机制的作用。",
        "userAnswer": "多头注意力允许模型……",
        "referenceAnswer": "多头注意力机制将注意力过程并行执行多次……",
        "score": 0.5,
        "source": { "materialId": "mat_001", "pageNumber": 5, "chunkIndex": 20 },
        "nextReviewAt": "2026-10-13T11:20:00Z",
        "reviewCount": 0,
        "createdAt": "2026-10-11T11:20:00Z"
      }
    ]
  }
}
```

#### GET /api/quiz/weak-points
获取薄弱知识点分析。

| 参数 | 位置 | 类型 | 必填 | 说明 |
|------|------|------|:---:|------|
| period | query | String | 否 | 统计周期：week/month，默认 week |

**返回：**
```json
{
  "code": 0,
  "data": {
    "totalErrors": 8,
    "weakPoints": [
      {
        "knowledgePoint": "多头注意力机制",
        "errorCount": 3,
        "accuracy": 0.33,
        "materialIds": ["mat_001"],
        "suggestedReview": "建议重新阅读 Transformer 架构详解第 5 页"
      },
      {
        "knowledgePoint": "位置编码",
        "errorCount": 2,
        "accuracy": 0.5,
        "materialIds": ["mat_001", "mat_003"],
        "suggestedReview": "建议重新阅读 Transformer 架构详解第 2 页"
      },
      {
        "knowledgePoint": "Layer Normalization",
        "errorCount": 2,
        "accuracy": 0.0,
        "materialIds": ["mat_001"],
        "suggestedReview": "建议重新阅读 Transformer 架构详解第 7 页"
      }
    ]
  }
}
```

#### GET /api/review/scheduled
获取今日待复习的错题（间隔重复调度）。

**返回：**
```json
{
  "code": 0,
  "data": {
    "dueCount": 5,
    "items": [
      {
        "errorId": "err_001",
        "questionId": "q_003",
        "type": "shortAnswer",
        "question": "简述多头注意力机制的作用。",
        "source": { "materialId": "mat_001", "pageNumber": 5 },
        "nextReviewAt": "2026-10-11T11:20:00Z",
        "reviewCount": 1,
        "easeFactor": 2.5,
        "interval": 1
      }
    ]
  }
}
```

---

### 2.4 看进度模块

#### GET /api/progress/overview
获取学习进度总览。

**返回：**
```json
{
  "code": 0,
  "data": {
    "totalMaterials": 12,
    "totalChunks": 480,
    "coveredChunks": 210,
    "coverageRate": 0.4375,
    "totalQuizCount": 15,
    "avgAccuracy": 0.72,
    "totalStudyMinutes": 360,
    "weekStudyMinutes": 120,
    "currentStreakDays": 4,
    "lastStudyAt": "2026-10-11T11:20:00Z"
  }
}
```

#### GET /api/progress/sessions
获取学习会话记录（Session 级 checklist）。

| 参数 | 位置 | 类型 | 必填 | 说明 |
|------|------|------|:---:|------|
| page | query | Int | 否 | 页码 |
| pageSize | query | Int | 否 | 每页条数 |

**返回：**
```json
{
  "code": 0,
  "data": {
    "total": 20,
    "list": [
      {
        "sessionId": "ls_001",
        "date": "2026-10-11",
        "durationMinutes": 35,
        "checklist": {
          "viewedMaterial": true,
          "chatted": true,
          "quizzed": false
        },
        "materialIds": ["mat_001"],
        "quizId": null,
        "score": null
      }
    ]
  }
}
```

#### GET /api/progress/trends
获取跨周期趋势数据。

| 参数 | 位置 | 类型 | 必填 | 说明 |
|------|------|------|:---:|------|
| metric | query | String | 否 | 指标：accuracy/studyTime/coverage，默认 accuracy |
| granularity | query | String | 否 | 粒度：week/month，默认 week |
| periods | query | Int | 否 | 返回最近 N 个周期，默认 8 |

**返回：**
```json
{
  "code": 0,
  "data": {
    "metric": "accuracy",
    "granularity": "week",
    "points": [
      { "label": "W37", "value": 0.55 },
      { "label": "W38", "value": 0.60 },
      { "label": "W39", "value": 0.68 },
      { "label": "W40", "value": 0.72 }
    ]
  }
}
```

---

### 2.5 出周报模块

#### POST /api/report/generate
生成周报（可指定周期，默认本周）。

| 参数 | 位置 | 类型 | 必填 | 说明 |
|------|------|------|:---:|------|
| weekStart | body | String | 否 | ISO 日期，默认本周一 |

**返回：**
```json
{
  "code": 0,
  "data": {
    "reportId": "rpt_001",
    "weekStart": "2026-10-06",
    "weekEnd": "2026-10-12",
    "sections": {
      "studyTime": {
        "totalMinutes": 120,
        "changePercent": 0.15
      },
      "materialCoverage": {
        "newMaterials": 2,
        "coveredChunks": 45,
        "coverageRate": 0.4375
      },
      "accuracyTrend": {
        "thisWeek": 0.72,
        "lastWeek": 0.65,
        "changePercent": 0.107
      },
      "weakPoints": [
        {
          "knowledgePoint": "多头注意力机制",
          "errorCount": 3,
          "suggestedReview": "重新阅读 Transformer 架构详解第 5 页"
        },
        {
          "knowledgePoint": "位置编码",
          "errorCount": 2,
          "suggestedReview": "重新阅读 Transformer 架构详解第 2 页"
        },
        {
          "knowledgePoint": "Layer Normalization",
          "errorCount": 2,
          "suggestedReview": "重新阅读 Transformer 架构详解第 7 页"
        }
      ],
      "nextWeekPlan": [
        "复习错题本中 5 道到期题目（间隔重复）",
        "重点攻克多头注意力机制相关内容",
        "完成新资料 Attention 笔记的学习"
      ],
      "motivation": "本周正确率提升了 10.7%，坚持的节奏很稳，下周继续！"
    },
    "createdAt": "2026-10-12T08:00:00Z"
  }
}
```

#### GET /api/report/latest
获取最新一期周报。

**返回：** 同上结构。

#### GET /api/report/history
获取周报历史列表。

| 参数 | 位置 | 类型 | 必填 | 说明 |
|------|------|------|:---:|------|
| page | query | Int | 否 | 页码 |
| pageSize | query | Int | 否 | 每页条数 |

**返回：**
```json
{
  "code": 0,
  "data": {
    "total": 4,
    "list": [
      {
        "reportId": "rpt_001",
        "weekStart": "2026-10-06",
        "weekEnd": "2026-10-12",
        "studyMinutes": 120,
        "accuracy": 0.72,
        "weakPointCount": 3,
        "createdAt": "2026-10-12T08:00:00Z"
      }
    ]
  }
}
```

#### GET /api/report/:reportId
获取指定周报详情。

**返回：** 同 `POST /api/report/generate` 的返回结构。

---

## 三、数据库表设计

> 数据库选型建议：PostgreSQL（关系型主库）+ pgvector（向量存储扩展）
> 如果用 SQLite + 外部向量库（如 Chroma）也可，MVP 阶段够用。

### 3.1 ER 关系概览

```
materials ──< material_chunks
materials ──< material_notes
materials ──< chat_sessions ──< chat_messages
materials ──< quizzes ──< quiz_questions
quiz_questions ──< quiz_submissions ──< quiz_answers
quiz_answers ──> error_book ──> review_schedule
materials ──< knowledge_points ──< error_book
learning_sessions
weekly_reports
```

### 3.2 表结构

#### 表 1：materials（资料表）

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | VARCHAR(36) | PK | 资料 ID |
| title | VARCHAR(200) | NOT NULL | 资料标题 |
| file_name | VARCHAR(255) | NOT NULL | 原始文件名 |
| file_type | VARCHAR(10) | NOT NULL | 文件类型：pdf/ppt/md |
| file_path | VARCHAR(500) | NOT NULL | 存储路径 |
| file_size | INT | NOT NULL | 文件大小（字节） |
| category | VARCHAR(100) | | 课程分类 |
| status | VARCHAR(20) | NOT NULL DEFAULT 'processing' | 状态：processing/ready/error |
| chunk_count | INT | DEFAULT 0 | 分块数量 |
| total_pages | INT | | 总页数 |
| created_at | TIMESTAMP | NOT NULL DEFAULT NOW() | 创建时间 |
| updated_at | TIMESTAMP | NOT NULL DEFAULT NOW() | 更新时间 |

#### 表 2：material_chunks（资料分块表）

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | VARCHAR(36) | PK | 分块 ID |
| material_id | VARCHAR(36) | FK → materials.id | 所属资料 |
| chunk_index | INT | NOT NULL | 块序号（从 0 开始） |
| page_number | INT | | 来源页码 |
| content | TEXT | NOT NULL | 块文本内容 |
| embedding | VECTOR(1536) | | 向量（pgvector）或存外部向量库 ID |
| token_count | INT | | token 数量 |
| created_at | TIMESTAMP | NOT NULL DEFAULT NOW() | 创建时间 |

> 索引：`(material_id, chunk_index)` 唯一索引；`embedding` 向量索引（IVFFlat 或 HNSW）

#### 表 3：chat_sessions（对话会话表）

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | VARCHAR(36) | PK | 会话 ID |
| title | VARCHAR(200) | | 会话标题 |
| material_ids | JSON | | 绑定的资料 ID 列表 |
| message_count | INT | DEFAULT 0 | 消息数 |
| created_at | TIMESTAMP | NOT NULL DEFAULT NOW() | 创建时间 |
| updated_at | TIMESTAMP | NOT NULL DEFAULT NOW() | 最后活动时间 |

#### 表 4：chat_messages（对话消息表）

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | VARCHAR(36) | PK | 消息 ID |
| session_id | VARCHAR(36) | FK → chat_sessions.id | 所属会话 |
| role | VARCHAR(20) | NOT NULL | 角色：user/assistant |
| content | TEXT | NOT NULL | 消息内容 |
| sources | JSON | | 来源引用列表（materialId, pageNumber, chunkIndex, snippet） |
| token_count | INT | | token 数 |
| created_at | TIMESTAMP | NOT NULL DEFAULT NOW() | 创建时间 |

> 索引：`session_id` 普通索引

#### 表 5：quizzes（测验表）

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | VARCHAR(36) | PK | 测验 ID |
| material_ids | JSON | NOT NULL | 出题依据的资料 ID 列表 |
| question_count | INT | NOT NULL | 题目总数 |
| type_ratio | JSON | | 题型比例 |
| difficulty | VARCHAR(20) | DEFAULT 'basic' | 难度 |
| status | VARCHAR(20) | NOT NULL DEFAULT 'ready' | 状态 |
| created_at | TIMESTAMP | NOT NULL DEFAULT NOW() | 创建时间 |

#### 表 6：quiz_questions（题目表）

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | VARCHAR(36) | PK | 题目 ID |
| quiz_id | VARCHAR(36) | FK → quizzes.id | 所属测验 |
| type | VARCHAR(20) | NOT NULL | 题型：choice/judgment/shortAnswer |
| question | TEXT | NOT NULL | 题干 |
| options | JSON | | 选项（选择题用：{A:"...", B:"..."} ） |
| correct_answer | VARCHAR(50) | NOT NULL | 正确答案（选择题：A/B/C/D；判断题：true/false；简答题：参考答案文本） |
| reference_answer | TEXT | | 参考答案（简答题用，详细版） |
| source_material_id | VARCHAR(36) | FK → materials.id | 来源资料 |
| source_page_number | INT | | 来源页码 |
| source_chunk_index | INT | | 来源块序号 |
| knowledge_point_id | VARCHAR(36) | FK → knowledge_points.id | 关联知识点 |
| created_at | TIMESTAMP | NOT NULL DEFAULT NOW() | 创建时间 |

> 索引：`quiz_id` 普通索引

#### 表 7：quiz_submissions（提交记录表）

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | VARCHAR(36) | PK | 提交 ID |
| quiz_id | VARCHAR(36) | FK → quizzes.id | 所属测验 |
| total_score | DECIMAL(3,1) | NOT NULL | 总得分 |
| max_score | DECIMAL(3,1) | NOT NULL | 满分 |
| accuracy | DECIMAL(4,3) | NOT NULL | 正确率 |
| duration_minutes | INT | | 答题时长 |
| submitted_at | TIMESTAMP | NOT NULL DEFAULT NOW() | 提交时间 |

#### 表 8：quiz_answers（答题明细表）

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | VARCHAR(36) | PK | 答题 ID |
| submission_id | VARCHAR(36) | FK → quiz_submissions.id | 所属提交 |
| question_id | VARCHAR(36) | FK → quiz_questions.id | 题目 ID |
| user_answer | TEXT | NOT NULL | 用户答案 |
| is_correct | BOOLEAN | | 是否正确（选择题/判断题） |
| score | DECIMAL(2,1) | NOT NULL | 得分（0 / 0.5 / 1） |
| explanation | TEXT | | 评语（简答题用） |
| created_at | TIMESTAMP | NOT NULL DEFAULT NOW() | 创建时间 |

> 索引：`submission_id` 普通索引

#### 表 9：knowledge_points（知识点表）

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | VARCHAR(36) | PK | 知识点 ID |
| name | VARCHAR(100) | NOT NULL | 知识点名称 |
| material_id | VARCHAR(36) | FK → materials.id | 所属资料 |
| chapter | VARCHAR(100) | | 章节 |
| description | TEXT | | 知识点描述 |
| created_at | TIMESTAMP | NOT NULL DEFAULT NOW() | 创建时间 |

#### 表 10：error_book（错题本表）

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | VARCHAR(36) | PK | 错题记录 ID |
| question_id | VARCHAR(36) | FK → quiz_questions.id | 题目 ID |
| submission_id | VARCHAR(36) | FK → quiz_submissions.id | 来源提交 |
| user_answer | TEXT | NOT NULL | 用户答案 |
| reference_answer | TEXT | | 参考答案 |
| score | DECIMAL(2,1) | NOT NULL | 得分 |
| knowledge_point_id | VARCHAR(36) | FK → knowledge_points.id | 关联知识点 |
| source_material_id | VARCHAR(36) | | 来源资料 |
| source_page_number | INT | | 来源页码 |
| review_count | INT | DEFAULT 0 | 已复习次数 |
| next_review_at | TIMESTAMP | | 下次复习时间（SM-2 调度） |
| ease_factor | DECIMAL(2,1) | DEFAULT 2.5 | SM-2 难度因子 |
| interval_days | INT | DEFAULT 0 | SM-2 间隔天数 |
| status | VARCHAR(20) | DEFAULT 'active' | 状态：active/mastered |
| created_at | TIMESTAMP | NOT NULL DEFAULT NOW() | 首次做错时间 |
| updated_at | TIMESTAMP | NOT NULL DEFAULT NOW() | 最后更新时间 |

> 索引：`next_review_at` 普通索引（用于查询到期复习题）；`knowledge_point_id` 普通索引

#### 表 11：learning_sessions（学习会话记录表）

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | VARCHAR(36) | PK | 会话 ID |
| session_date | DATE | NOT NULL | 会话日期 |
| duration_minutes | INT | NOT NULL DEFAULT 0 | 学习时长 |
| viewed_material | BOOLEAN | DEFAULT FALSE | 是否看了资料 |
| chatted | BOOLEAN | DEFAULT FALSE | 是否对话了 |
| quizzed | BOOLEAN | DEFAULT FALSE | 是否测验了 |
| material_ids | JSON | | 涉及的资料 |
| chat_session_id | VARCHAR(36) | | 关联的对话会话 |
| quiz_id | VARCHAR(36) | | 关联的测验 |
| quiz_score | DECIMAL(3,1) | | 测验得分 |
| created_at | TIMESTAMP | NOT NULL DEFAULT NOW() | 创建时间 |

> 索引：`session_date` 普通索引

#### 表 12：weekly_reports（周报表）

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | VARCHAR(36) | PK | 周报 ID |
| week_start | DATE | NOT NULL | 周起始日期 |
| week_end | DATE | NOT NULL | 周结束日期 |
| study_minutes | INT | NOT NULL | 本周学习时长 |
| new_materials | INT | NOT NULL | 新增资料数 |
| covered_chunks | INT | NOT NULL | 覆盖分块数 |
| coverage_rate | DECIMAL(4,3) | NOT NULL | 覆盖率 |
| accuracy_this_week | DECIMAL(4,3) | | 本周正确率 |
| accuracy_last_week | DECIMAL(4,3) | | 上周正确率 |
| accuracy_change | DECIMAL(4,3) | | 正确率变化 |
| weak_points | JSON | NOT NULL | 薄弱知识点 TOP3 |
| next_week_plan | JSON | NOT NULL | 下周学习计划 |
| motivation | TEXT | NOT NULL | 激励语 |
| created_at | TIMESTAMP | NOT NULL DEFAULT NOW() | 创建时间 |

> 索引：`(week_start, week_end)` 唯一索引

#### 表 13：material_notes（资料笔记表）

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | VARCHAR(36) | PK | 笔记 ID |
| material_id | VARCHAR(36) | FK → materials.id | 所属资料 |
| content | TEXT | NOT NULL DEFAULT '' | 笔记全文 |
| content_length | INT | NOT NULL DEFAULT 0 | 笔记字数（用于判断是否缩略显示） |
| created_at | TIMESTAMP | NOT NULL DEFAULT NOW() | 创建时间 |
| updated_at | TIMESTAMP | NOT NULL DEFAULT NOW() | 最后更新时间 |

> 索引：`material_id` 唯一索引（每份资料仅一份笔记）
> 缩略规则：前端读取时若 `content_length` 超过阈值（默认 200 字），默认折叠为缩略显示，提供「展开」操作

---

## 四、系统提示词（三套）

以下三套系统提示词分别对应三个 AI 角色：日常聊天导师、出题官、改卷官。
实际使用时，根据当前任务切换对应的系统提示词。

---

### 4.1 系统提示词 A — 日常聊天导师

```markdown
# Role

你是一位面向 AI 产品经理的学习导师，专长大模型（LLM）领域知识。
用户正在学习大模型课程，手里有大量课程资料（PDF/PPT/Markdown），需要你帮他理解、消化这些资料内容。

# Core Principles

1. **资料优先**：回答必须基于用户上传的资料内容。检索到的资料片段是你的第一信源，优先用资料中的表述和逻辑回答。
2. **来源引用**：每条回答末尾必须标注来源，格式为「来源：《资料标题》第 N 页」。如果引用了多份资料，分别列出。
3. **有洞察不啰嗦**：用户是 AI 产品经理，不需要科普式解释。直接给结论和关键逻辑，控制篇幅。能用一句话说清的不用三句。
4. **坦诚说不知道**：如果资料中没有相关内容，明确说「当前资料中未覆盖这个知识点」，不要编造。可以建议用户补充相关资料。
5. **产品视角**：在解释技术概念时，适时关联产品视角（这个技术能做什么产品、有什么局限、商业化路径），但只在自然时提及，不硬塞。

# Response Format

- 正常回答控制在 3-5 段以内
- 涉及对比或分类时用表格
- 涉及流程时用步骤列表
- 回答末尾附来源引用

# Boundaries

- 不讨论与学习资料无关的话题
- 不给出投资建议或商业决策建议
- 不编造资料中没有的数据或结论
- 如果用户的问题超出当前资料范围，引导用户回到资料内容或建议补充资料
```

---

### 4.2 系统提示词 B — 出题官

```markdown
# Role

你是一位严格的出题官。你的任务是基于用户上传的学习资料，生成测验题目。
你必须确保每道题都能在资料中找到明确依据。

# Question Types

生成以下三种题型的题目：

1. **选择题**：4 个选项（A/B/C/D），有且仅有一个正确答案。干扰项必须具有迷惑性，但不能是「明显错误」的选项。
2. **判断题**：陈述一个与资料内容相关的论断，答案为 true 或 false。论断必须明确无歧义。
3. **简答题**：要求用户简述某个概念、原理或流程。必须提供参考答案用于后续评分。

# Core Rules

1. **严格基于资料**：每道题必须能在指定资料中找到明确出处。不得出资料范围之外的题目。每道题必须标注来源（资料 ID + 页码 + 块序号）。
2. **题目质量**：
   - 选择题的题干必须清晰，不产生歧义
   - 正确答案分布应随机，不要总是 A
   - 判断题不能过于简单（如「Transformer 是一种模型」这种常识题没有价值）
   - 简答题的参考答案必须完整，包含关键得分点
3. **难度控制**：
   - basic：直接考资料中的定义和概念
   - advanced：考资料中概念的应用和关联
   - challenge：考资料中隐含的逻辑推导和批判性思考
4. **不泄露答案**：生成题目时不在题干中暗示答案，不在选项注释中暴露正确答案。

# Output Format

严格输出以下 JSON 格式，不要输出任何其他内容：

```json
[
  {
    "type": "choice",
    "question": "题干文本",
    "options": {
      "A": "选项A",
      "B": "选项B",
      "C": "选项C",
      "D": "选项D"
    },
    "correctAnswer": "A",
    "source": {
      "materialId": "mat_001",
      "pageNumber": 3,
      "chunkIndex": 12
    },
    "knowledgePoint": "自注意力机制"
  },
  {
    "type": "judgment",
    "question": "论断文本",
    "correctAnswer": "true",
    "source": {
      "materialId": "mat_002",
      "pageNumber": 1,
      "chunkIndex": 0
    },
    "knowledgePoint": "Transformer架构"
  },
  {
    "type": "shortAnswer",
    "question": "题干文本",
    "referenceAnswer": "参考答案（含关键得分点）",
    "source": {
      "materialId": "mat_001",
      "pageNumber": 5,
      "chunkIndex": 20
    },
    "knowledgePoint": "多头注意力"
  }
]
```

# Boundaries

- 不出与资料无关的题目
- 不出开放性讨论题（如「你怎么看 Transformer 的未来」）
- 不出需要计算具体数值的题（除非资料中明确给出了计算方法）
- 每次生成的题目中，三种题型都要有
```

---

### 4.3 系统提示词 C — 改卷官

```markdown
# Role

你是一位严格但公正的改卷官。用户已经提交了测验答案，你的任务是批改并给出评分和评语。

# Grading Rules

## 选择题 / 判断题

- **对就是对，错就是错**，没有中间分。
- 用户答案与标准答案完全一致 → 得 1 分。
- 任何不一致 → 得 0 分。
- 不给解释，不给"鼓励性"的半分。
- 如果用户未作答（空答案），得 0 分。

## 简答题

- 满分 1 分，只能给 **0 / 0.5 / 1** 三个分数档，不出现其他分值。
- **1 分**：回答包含参考答案中的所有关键得分点，表述准确。
- **0.5 分**：回答包含部分关键得分点（至少 50%），但缺少重要内容或有轻微错误。
- **0 分**：回答与参考答案无关、严重错误、或基本未作答。
- 必须给出评语，说明扣分原因：缺少了什么、哪里不准确。

# Scoring Rubric for Short Answers

判断流程：
1. 提取参考答案中的关键得分点（通常 2-4 个）
2. 逐一检查用户答案是否覆盖每个关键得分点
3. 覆盖率 ≥ 80% → 1 分
4. 覆盖率 50%-80% → 0.5 分
5. 覆盖率 < 50% → 0 分

# Output Format

严格输出以下 JSON 格式，不要输出任何其他内容：

```json
[
  {
    "questionId": "q_001",
    "type": "choice",
    "userAnswer": "A",
    "correctAnswer": "A",
    "isCorrect": true,
    "score": 1,
    "explanation": null
  },
  {
    "questionId": "q_002",
    "type": "judgment",
    "userAnswer": "false",
    "correctAnswer": "true",
    "isCorrect": false,
    "score": 0,
    "explanation": null
  },
  {
    "questionId": "q_003",
    "type": "shortAnswer",
    "userAnswer": "用户回答文本",
    "referenceAnswer": "参考答案文本",
    "score": 0.5,
    "explanation": "回答提及了多头注意力允许并行关注不同位置这一关键点，但缺少「不同子空间投影」和「拼接线性变换」两个得分点，给 0.5 分。"
  }
]
```

# Boundaries

- 选择题和判断题绝对不给中间分，不受用户表述影响
- 简答题评分必须基于参考答案的关键得分点，不凭主观印象
- 评语只说事实（缺了什么、对了什么），不做情感性评价（不写"加油""不错"等）
- 如果用户答案与参考答案完全一致但表述不同（同义改写），不影响得分
```

---

## 五、MVP 范围确认

根据优先级标注，MVP（第一版）应包含以下功能点：

| 模块 | MVP 包含的功能点 | 暂不做的功能点 |
|------|-----------------|---------------|
| 传资料 | M-01 文件上传、M-02 文本提取、M-03 文本分块、M-04 向量化、M-05 来源元数据 | M-06 PPT深度解析、M-07 批量上传、M-08 资料管理、M-09 增量更新 |
| 聊资料 | C-01 RAG检索、C-02 来源引用、C-03 多轮对话、C-04 多资料交叉引用、C-07 资料笔记 | C-05 会话管理（简化版）、C-06 对话导出 |
| 做测评 | Q-01 自动出题、Q-02 质量校验、Q-03 答题提交、Q-04 自动批改、Q-05 结果展示 | Q-06 错题本、Q-07 薄弱分析、Q-08 间隔重复、Q-09 定向复测、Q-10 难度分级 |
| 看进度 | P-01 学习时长、P-02 资料覆盖量、P-03 测验正确率 | P-04 Session checklist、P-05 跨周期趋势、P-06 掌握度热力图 |
| 出周报 | R-01 周报生成、R-02 周报内容 | R-03 周报历史、R-04 主动推送、R-05 可分享卡片 |

> 说明：MVP 聚焦五功能闭环跑通（传→聊→测→追→报），P1 功能（错题本、间隔重复、薄弱分析等）在闭环验证后第一迭代补齐。

---

## 六、待确认事项

1. **技术栈**：前端（React/Vue？）、后端（Python FastAPI/Node Express？）、向量数据库（pgvector/Chroma/Milvus？）——等你指定
2. **LLM 接入**：用哪个模型（OpenAI/Claude/国产模型？）、API Key 从哪来
3. **部署方式**：本地运行还是云端部署
4. **MVP 范围**：上面第五节的 MVP 划分是否认可，还是要调整

> 以上待确认事项不影响本文档的有效性，开发前敲定即可。
> **在你明确说"开始开发"之前，不写任何代码。**
