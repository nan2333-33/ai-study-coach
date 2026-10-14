# AI 学习助手

> 基于自己资料的 AI 学习教练：**传资料 → 聊资料 → 做测评 → 看进度 → 出周报**。

**📄 [产品一页纸（建议从这里看起）](showcase/01-产品一页纸.md)** ｜ [关键决策记录](showcase/02-关键决策记录.md) ｜ [演示脚本](showcase/03-演示脚本.md)

---

## 这个项目解决什么

学大模型课程，资料看完就忘。现有工具都只解决一半：

| 工具 | 能做什么 | 缺什么 |
|---|---|---|
| Gemini Notebook（原 NotebookLM） | 基于资料对话、出题、掌握度看板 | 不回顾**跨周期**的学习轨迹 |
| RemNote | 成熟的间隔重复 | 不能对自己的资料提问 |

**没有一款**把「这一周到底学会了什么、下周该干什么」周期性地交还给用户。

结果就是：资料读了、笔记记了，但没人告诉你「哪些真的记住了、哪些该回头看」。

## 五个环节

| 环节 | 做法 |
|---|---|
| 传资料 | PDF / PPT / Markdown 自动解析、语义切块、向量化 |
| 聊资料 | RAG 对话，每条回答附来源引用，可点开看原文片段 |
| 做测评 | 按资料自动生成选择 / 判断 / 简答，客观题自动批改、简答题由模型改卷 |
| 看进度 | 按知识点聚合掌握度，输出雷达图与薄弱点清单 |
| 出周报 | 汇总做题量、覆盖率、正确率趋势、薄弱 TOP3、下周计划，可导出 md / docx / pdf |

## 演示

> 📌 截图与演示录屏待补充，素材将放在 `docs/demo/` 下。

本项目**没有在线 Demo**，必须本地启动。原因是它要用**你自己的大模型 API Key**——
托管到公网等于替所有访问者付调用费，而资料解析和对话每次都要真金白银调模型。

---

## 几个实现判断

- **主动砍掉了「学习时长」**。它只能靠事件时间戳的间隔推算，系统自己拿不出证据证明它等于用户真实花的时间。一个学习产品摆一个自己算不出来的数，用户一旦发现对不上，会连带着怀疑正确率、掌握度这些**真实统计**。改用**答题数**（`quiz_answers` 行数，答一题落一条，硬计数可核对）。取舍理由见 [一页纸 Tradeoff](showcase/01-产品一页纸.md)。
- **回答必须带来源引用**。RAG 回答下方标注「引用了 N 处资料」，可展开看原文片段——学习工具里，能追溯比答得快重要。
- **知识点做了语义聚类**。大模型给知识点起名时每次略有出入（「Transformer的起源」会有三种写法），同一个概念会裂成多条、掌握度被稀释。用 embedding 相似度 + 层次聚类归并设置保守阈值：**少并只是难看，多并会把「你不会的部分」平均掉**，后者对学习产品是最糟的错误。
- **接口失败不显示成空状态**。曾经跨域被拦时列表渲染成「还没有资料」，用户以为资料被删了，实际一个没丢。现在会明确告诉你是连不上后端，并给出可执行的排查步骤。
- **全本地自托管**：资料、向量库、数据库都在本机，不上传第三方。

技术栈：Flask + SQLAlchemy + SQLite（可换 PostgreSQL）+ ChromaDB；大模型 DeepSeek；向量模型阿里云百炼 `text-embedding-v4`。前端原生 HTML/CSS/JS，**无构建步骤**。

> ⚠️ 本项目**需要本地运行**（要填你自己的大模型 API Key），**没有在线 Demo**。
> 想直接看效果：Windows 双击根目录 `一键启动.bat`，会自动起服务并打开浏览器。
> 下面是完整运行说明。

---

# 运行说明

> 面向第一次接触本项目的人。按本文档顺序执行，即可把**后端 + 前端**完整跑起来。
> 全程不需要前端构建工具（没有 npm install、没有打包），前端是原生 HTML/CSS/JS。
>
> **赶时间的话**：Windows 直接双击根目录 **`一键启动.bat`**，它会自动装依赖、起后端和前端、等后端就绪后打开浏览器。

---

## 0. 先搞清楚这个项目长什么样

```
vibecoding-ai学习助手/
├── index.html          ← 前端唯一入口（单页应用，hash 路由）
├── css/                ← 样式（reset / layout / components / pages）
├── js/
│   ├── api.js          ← 所有后端接口封装 + 演示数据开关
│   └── app.js          ← 页面渲染与交互
└── backend/            ← Python Flask 后端
    ├── app.py          ← 入口
    ├── config.py       ← 所有配置项（读 .env）
    ├── .env.example    ← 配置模板
    ├── requirements.txt
    ├── models/         ← 13 张数据库表
    ├── routes/         ← 接口实现
    ├── services/       ← 大模型 / 向量库 / 提示词
    └── data/           ← 运行时自动生成（数据库、上传文件、向量库）
```

前端 5 个页面：**问一问**（RAG 对话）→ **测评**（自动出题批改）→ **进度**（掌握度可视化）→ **报告**（AI 周报）→ **资料库**（上传管理）。

**技术栈**：后端 Flask + SQLAlchemy + SQLite + ChromaDB；大模型 DeepSeek；向量模型阿里云百炼 `text-embedding-v4`。

---

## 1. 环境准备

| 依赖 | 版本要求 | 说明 |
|---|---|---|
| Python | **3.10 ~ 3.13**（实测 3.11 / 3.13 均可） | 后端运行必需 |
| 浏览器 | Chrome / Edge 等现代浏览器 | 前端 |
| Node.js | **不需要** | 前端无构建步骤 |

检查 Python 版本：

```bash
python --version
```

> Windows 若提示 `python 不是内部或外部命令`，去 [python.org](https://www.python.org/downloads/) 重装并勾选 **Add Python to PATH**。

---

## 2. 后端配置（关键步骤）

### 2.1 创建虚拟环境并安装依赖

进入 `backend` 目录操作：

```bash
cd backend
```

**Windows（CMD / Git Bash）**
```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

**Windows（PowerShell）**
```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

**macOS / Linux**
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

激活成功后命令行前面会出现 `(.venv)`。

> **国内网络请务必加 `-i https://pypi.tuna.tsinghua.edu.cn/simple`**（清华镜像）。
> 直连 PyPI 官方源大概率会在下载 `chromadb` 时超时失败，报错形如
> `ReadTimeoutError: HTTPSConnectionPool(host='files.pythonhosted.org')`。
> 其他可选镜像：阿里云 `https://mirrors.aliyun.com/pypi/simple/`。
>
> 安装 `chromadb` 耗时较长（2~5 分钟，它自带 onnxruntime 等大依赖），属正常现象，请耐心等待。

### 2.2 生成配置文件

**方式一：命令行一步到位（最省事）**

```bash
python setup_env.py --set LLM_API_KEY=sk-你的DeepSeek密钥 --set EMB_API_KEY=sk-你的百炼密钥
```

只改这两项，其余保持模板默认值。适合已经拿到两个 Key、想直接填完的场景。

**方式二：配置向导（推荐首次使用）**

```bash
python setup_env.py
```

按提示逐项填写即可。好处是**密钥只在你自己的终端里输入，不会进对话记录或日志**，也不会填错文件；每一项会显示当前值（已打码），直接回车表示保留（只有 2 个 Key 需要真正输入，其余一路回车即可）。

随时可以复查配置是否完整：

```bash
python setup_env.py --check
```

**方式三：手动复制模板**

```bash
# Windows
copy .env.example .env

# macOS / Linux
cp .env.example .env
```

然后用任意文本编辑器打开 `backend/.env` 修改。

### 2.3 必须填写的配置项

模板里已经预填好了大模型地址、向量模型地址、模型名和维度，**你只需要填 2 个密钥**：

| 配置项 | 填什么 | 从哪获取 |
|---|---|---|
| `LLM_API_KEY` | DeepSeek 的 API Key（`sk-` 开头） | https://platform.deepseek.com/api_keys |
| `EMB_API_KEY` | 阿里云百炼的 API Key（`sk-` 开头） | https://bailian.console.aliyun.com/ → 右上角头像 → API-KEY |

改完用 `python setup_env.py --check` 确认两项都变成 `[OK]`。

> ⚠️ **注意变量名的坑**：向量模型的 Key 是 **`EMB_API_KEY`**（`EMB_`，不是 `EMBED_`）。这两个名字只差两个字母，写错不会报错，但资料会一直解析失败。模板里已用正确写法并在注释中标出。

改完后 `.env` 关键部分长这样（只有两处 `sk-` 需要你替换）：

```ini
# ===== 大模型：DeepSeek（对话 / 出题 / 批改 / 周报）=====
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_API_KEY=sk-在这里填你的DeepSeek密钥
LLM_MODEL=deepseek-chat

# ===== 向量模型：阿里云百炼（资料向量化）=====
EMBED_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
EMB_API_KEY=sk-在这里填你的百炼密钥
EMBED_MODEL=text-embedding-v4
EMBED_DIM=1024
```

**其余保持默认的部分**（不用动）：

```ini
PORT=5000                              # 后端端口
CORS_ORIGINS=http://127.0.0.1:8123     # 允许跨域的前端地址
DB_URL=sqlite:///./data/app.db         # SQLite，自动建库建表，无需手动迁移
UPLOAD_MAX_MB=50                       # 单文件上传上限
CHUNK_MIN=500                          # 分块目标字数下限
CHUNK_MAX=800                          # 分块目标字数上限
RETRIEVE_MIN_SCORE=0.15                # 余弦相似度下限，低于此值的片段丢弃
RETRIEVE_TOP_K=8                       # 单次检索返回片段数
```

### 2.4 配置项速查

| 配置 | 作用 | 改了会怎样 |
|---|---|---|
| `PORT` | 后端监听端口 | 改了前端 `js/api.js` 的 `base` 也要同步改 |
| `CORS_ORIGINS` | 允许访问后端的前端地址 | 前端端口不是 8123 就必须改这里，否则浏览器报跨域错误 |
| `DB_URL` | 数据库地址 | 可换 PostgreSQL：`postgresql+psycopg://user:pass@localhost:5432/ailms` |
| `LLM_*` | 对话/出题/批改/周报用的大模型 | 兼容 OpenAI Chat Completions 格式，可换其他厂商 |
| `EMBED_*` | 资料向量化 | **必须与向量库维度一致**，见下方注意 |
| `EMBED_DIM` | 向量维度 | 百炼 `text-embedding-v4` 用 **1024** |
| `RETRIEVE_MIN_SCORE` | 检索严格度 | 调高→回答更严谨但可能检索不到；调低→容易答非所问 |

> ⚠️ **关于 `EMBED_DIM`**：改这个值之后，已有的向量库维度对不上会报错。解决方法是删掉 `backend/data/chroma/` 目录让系统重建（已有资料需要重新上传）。

---

## 3. 启动后端

在 `backend` 目录下，**虚拟环境已激活**的状态执行：

```bash
python app.py
```

看到类似输出即启动成功：

```
 * Running on http://127.0.0.1:5000
 * Debug mode: on
```

**验证后端是否正常**（新开一个终端）：

```bash
curl http://127.0.0.1:5000/api/materials
```

返回 `{"code":0,"data":{"list":[],"total":0},"msg":"ok"}` 说明后端正常。

> Windows 若没有 curl，浏览器直接访问 http://127.0.0.1:5000/api/materials 看到同样的 JSON 即可。

**首次启动会自动完成**：
- 创建 `backend/data/` 目录
- 建 SQLite 数据库和 13 张表（`data/app.db`）
- 初始化 ChromaDB 向量库（`data/chroma/`）
- 创建上传目录（`data/uploads/`）

不需要手动执行任何数据库迁移命令。

---

## 4. 启动前端

### 4.1 为什么不能双击 index.html

**必须用 HTTP 服务打开，不能直接双击 `index.html`。**

直接双击会以 `file://` 协议打开，浏览器会因为安全策略拦截所有接口请求，页面会白屏或全是假数据。

### 4.2 启动方式（任选一种）

#### 方式一：Python 自带（推荐，零安装）

在**项目根目录**（`index.html` 所在的那一层，不是 backend 里）执行：

```bash
python -m http.server 8123
```

看到 `Serving HTTP on 0.0.0.0 port 8123` 即成功。

#### 方式二：VS Code Live Server

安装 Live Server 插件 → 右键 `index.html` → "Open with Live Server"。
默认端口是 5500，**需要在 `backend/.env` 里把 `CORS_ORIGINS` 改成 `http://127.0.0.1:5500` 并重启后端**。

#### 方式三：Node 的 serve

```bash
npx serve -l 8123 .
```

### 4.3 打开页面

在浏览器地址栏输入：

```
http://127.0.0.1:8123
```

> ⚠️ **务必写 `127.0.0.1`，不要写 `localhost`**。`.env` 里 `CORS_ORIGINS` 配的是 `http://127.0.0.1:8123`，浏览器用 `localhost` 访问时来源不匹配，会被跨域拦截。
>
> 想彻底避免这个坑，可以把 `CORS_ORIGINS` 改成 `*`（允许任何来源），改完重启后端。

---

## 5. 让前端连上后端

前端默认已配置好连接本地后端，在 `js/api.js` 开头：

```js
const API = {
  base: "http://127.0.0.1:5000",   // 后端地址，端口改了就同步改这里
  useMock: false,                   // false = 连真实后端
  ...
}
```

| 场景 | `base` | `useMock` |
|---|---|---|
| 正常联调（默认） | `http://127.0.0.1:5000` | `false` |
| 后端没启动，只想看界面效果 | 任意 | `true` |

`useMock: true` 时前端用内置演示数据，完全不请求后端，适合离线看 UI。

---

## 6. 验证是否真的跑通了

按顺序做一遍，全通过说明环境没问题：

| # | 操作 | 预期结果 |
|---|---|---|
| 1 | 打开 http://127.0.0.1:8123 | 页面正常显示，左侧导航有 5 个入口 |
| 2 | 进「资料库」→ 上传一个 PDF/MD/TXT | 弹出「✓ 上传成功，正在解析…」，卡片先显示「解析中」，几十秒后变「已就绪」并显示分块数 |
| 3 | 进「问一问」→ 顶部选刚上传的资料 → 提问 | AI 基于资料回答，回答下方出现「引用了 N 处资料」，可展开看原文片段 |
| 4 | 进「测评」→ 选资料 → 生成测验 | 出选择题/判断题/简答题；提交后显示得分与每题点评 |
| 5 | 进「进度」 | 6 张统计卡有数据，雷达图、知识点列表、薄弱点都有内容 |
| 6 | 进「报告」→ 生成周报 | 生成出本周做题量、覆盖率、正确率、薄弱点、下周计划 |

### 6.1 两个一键自检脚本（不用手动点页面）

```bash
# 1) 只测两个 Key 是不是真能用（不启动服务也能跑，消耗极少量额度）
python tests/test_apikey_live.py

# 2) 完整闭环：自动上传测试资料 → 解析 → RAG 提问 → 出题 → 批改 → 进度 → 周报 → 清理
#    需要先启动后端
python tests/test_e2e_live.py
```

`test_e2e_live.py` 会用 `tests/fixtures/RAG学习笔记.md` 当测试资料，跑完自动删掉，不留垃圾数据。它还会校验「判断题选项是否为 A正确/B错误」「周报字段是否齐全（前端不会显示 NaN）」这类前后端契约。

**第 2 步如果卡片一直显示「解析失败」**，把鼠标停在卡片上会看到失败原因（如密钥没配、向量模型地址不对），按提示改 `.env` 后点「重试」即可，不用重新上传。

---

## 7. 常见问题排查

| 现象 | 原因 | 解决办法 |
|---|---|---|
| 页面能打开但所有数据都是空的/假的 | `useMock` 是 `true` | 改 `js/api.js` 的 `useMock: false` |
| 浏览器控制台报 `CORS policy` / `blocked by CORS` | 前端端口与 `CORS_ORIGINS` 不一致，或用了 `localhost` | 用 `127.0.0.1:8123` 访问；或把 `CORS_ORIGINS` 改成 `*` 后重启后端 |
| 控制台报 `Failed to fetch` / `net::ERR_CONNECTION_REFUSED` | 后端没启动或端口不对 | 确认 `python app.py` 在跑，且 `base` 端口与后端一致 |
| 资料上传成功但一直「解析中」 | 首次解析要调向量模型，较慢 | 等 1~2 分钟；大文件更久 |
| 资料上传后变「解析失败」 | 密钥没填、填错变量名，或向量模型地址不对 | 卡片上直接显示失败原因；运行 `python setup_env.py --check` 确认两项 Key 都是 `[OK]`；注意是 `EMB_API_KEY` 不是 `EMBED_API_KEY` |
| 聊天提示「资料检索失败：EMBED_BASE_URL 未正确配置」 | `EMBED_BASE_URL` 还是占位符 | 改成 `https://dashscope.aliyuncs.com/compatible-mode/v1` 并**重启后端** |
| 聊天提示「大模型调用失败」 | `LLM_API_KEY` 无效或余额不足 | 去 DeepSeek 控制台检查 Key 与余额 |
| 向量维度报错（dimension mismatch） | `EMBED_DIM` 改过，或换过向量模型 | 后端启动时会自动检测并重建向量库（控制台会打印「自动重建 collection」）；**重建后旧向量作废，需要把资料重新上传一次**。若仍报错，手动删 `backend/data/chroma/` 再重启 |
| 启动时报 `Address already in use` | 5000 端口被占用 | 改 `.env` 的 `PORT`，同步改 `js/api.js` 的 `base` |
| 启动时报 `No module named 'flask'` | 虚拟环境没激活，或依赖没装 | 确认命令行有 `(.venv)` 前缀，重跑 `pip install -r requirements.txt` |
| pip 报 `ReadTimeoutError` / 卡住不动 | 直连 PyPI 官方源超时 | 加清华镜像：`pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple` |
| 双击 index.html 打开是白屏 | 用了 `file://` 协议 | 必须用 HTTP 服务打开，见第 4 节 |
| 周报里没有「学习时长」这一项 | 故意的。时长只能靠时间戳间隔**推算**，用户一对发现对不上，会连带着怀疑正确率这些真实统计 | 主指标是**答题数**（`quiz_answers` 硬计数）。详见 7.1 |
| 周报下载成 PDF 报「缺少依赖」 | 没装 `reportlab` | 重跑 `pip install -r requirements.txt` |

### 7.1 为什么没有「学习时长」，主指标是「做题量」

学习时长只能靠事件时间戳的间隔**推算**（每个事件记几分钟、间隔封顶多少），
系统自己也拿不出证据证明它等于用户真实花的时间。
一个学习产品摆一个自己推算的数字，用户一旦发现对不上，会连带着怀疑正确率、掌握度这些**真实统计**。

所以时长被完全移除，周报和进度页都不再显示，主指标换成 **答题数**：

| 指标 | 怎么来的 | 可验证吗 |
|---|---|---|
| 学习时长（已移除） | 时间戳间隔 × 折算规则 | ❌ 推算 |
| **答题数** | `quiz_answers` 行数 | ✅ 答一题落一条 |

口径是「答了几道题」，不是「做了几套测评」——后者会被一套 3 题 / 一套 20 题的差异带偏。

保留的一项时间指标是**连续学习天数**：它只是数「有学习行为的日期」连续了几天，来自真实事件日期。
今天还没学不算断签（晚上才打开 App 的用户不该被判成断了）。

统计逻辑都在 `backend/services/tracking.py`（`question_count` / `activity_days` / `streak_days` / `daily_detail`），
不引入前端埋点，历史事件也能统计到。存量周报在启动时会按各自周期重算回填，不会出现「进度页 78 题、周报 0 题」。

### 7.2 周报导出格式

点周报卡片上的「下载」会弹出格式菜单：

| 选项 | 说明 |
|---|---|
| Markdown（.md） | 纯文本，后端不可用时前端也能本地生成兜底 |
| Word（.docx） | `python-docx` 生成，正文微软雅黑 |
| PDF（.pdf） | `reportlab` 生成，优先嵌入微软雅黑，找不到系统字体时回退内置中文 CID 字体 |

三种格式共用 `services/exporters.py` 里同一份结构化文档，不会出现「Markdown 改了 Word 没跟着改」。

> 后端改了 `.env` 之后**必须重启后端**才生效（`python app.py` 开的 debug 模式会热重载代码，但配置不会自动重读）。

---

## 8. 停止服务与重置

**停止**：在对应的终端窗口按 `Ctrl + C`。

**重置全部数据**（回到全新状态）：

```bash
# 停掉后端后执行
rm -rf backend/data        # macOS / Linux
# Windows 手动删除 backend\data 文件夹即可
```

`backend/data/` 里包含：SQLite 数据库、上传的原文件、ChromaDB 向量库。删掉后重启后端会自动重建，但**已上传的资料会全部丢失**。

---

## 9. 最小启动流程（给赶时间的人）

### 9.1 不想碰命令行：双击 `启动.bat`

项目根目录下有个 **`启动.bat`**，双击它会弹出一个菜单：

```
1   填写密钥（只需做一次）
2   检查密钥是否填好
3   启动后端（自动装依赖，弹出新窗口别关）
4   启动前端（弹出新窗口，别关）
5   打开浏览器
9   跑一遍完整自检（上传-对话-出题-周报）
0   退出
```

第一次用按 `1 → 3 → 4 → 5`，之后每次按 `3 → 4 → 5`。两个黑窗口开着别关，关了服务就停了。

### 9.2 只想启后端：双击 `启动后端.bat`

根目录的 **`启动后端.bat`** 是给"从零开始"的人准备的，双击后全自动完成：

1. **找 Python** —— 找不到会提示去哪下载、要勾选 Add Python to PATH
2. **建虚拟环境** —— 没有 `backend\.venv` 就自动 `python -m venv .venv`
3. **装依赖** —— 检测 `flask / chromadb / sqlalchemy / pypdf / python-docx / python-pptx / python-dotenv` 是否已装齐，缺了才装；默认走清华镜像，失败自动换官方源重试
4. **启动** —— 在虚拟环境里 `python app.py`

依赖已装的情况下会直接跳过第 2、3 步，几秒钟就起来，不会每次重复安装。

> 这个脚本只管后端，前端还需要另起一个（菜单里按 `4`，或自己跑 `python -m http.server 8123`）。

### 9.2 用命令行

```bash
# 终端 1 —— 后端
cd backend
python -m venv .venv
.venv\Scripts\activate          # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
python setup_env.py --set LLM_API_KEY=sk-xxx --set EMB_API_KEY=sk-xxx
#            或者：python setup_env.py （交互式，密钥不进对话记录）
python app.py

# 终端 2 —— 前端（在项目根目录，不是 backend 里）
python -m http.server 8123

# 浏览器打开 http://127.0.0.1:8123
```

---

## 10. 补充说明

- **资料解析是异步的**：上传接口立即返回，后台慢慢做「读文字 → 语义切块 → 向量化 → 存向量库」，前端靠轮询刷新状态。所以大文件上传后需要等一会儿才会变成「已就绪」。
- **判断题选项固定在后端**：`{"A":"正确","B":"错误"}`，答案统一存 `A`/`B`。
- **还有 3 个接口是空实现**（返回空数组，不是 bug，是 PRD 里的 P1 功能尚未开发）：错题本列表 `/api/quiz/errors`、间隔重复 `/api/review/scheduled`、学习会话记录 `/api/progress/sessions`。
- **测试**：
  - `python tests/test_apikey_live.py` —— 两个 Key 的真实连通性（含向量维度校验）
  - `python tests/test_e2e_live.py` —— 完整闭环端到端（需先启动后端）
  - `python tests/test_contract_audit.py` —— 45 项前后台契约测试（不联网）
  - 另有 `test_endpoints.py`、`test_llm_integration.py`、`test_material_pipeline.py`
- **详细需求与接口设计**见 `PRD-功能需求文档.md`；**前后台一致性审计**见 `前后台接口一致性审计报告.md`。
