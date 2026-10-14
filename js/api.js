/* =========================================================
   api.js — 请求封装 + PRD 接口 + 模拟数据
   ========================================================= */

const API = {
  // 接口基址 = 后端地址（下面所有 path 已自带 /api 前缀，这里不要再写 /api）
  // 后端默认跑在 http://127.0.0.1:5000，端口改了就同步改这里
  base: "http://127.0.0.1:5000",
  token: "dev-token",
  // 接真实后端：false。想离线看界面效果：改成 true（走内置演示数据，不请求后端）
  useMock: false,

  /* ---------- 请求封装 ---------- */
  /* 后端统一返回 { code, data, msg }。code !== 0 视为业务失败，直接抛错，
     避免前端拿到 null 还继续渲染（这是之前最容易静默出错的地方）。 */
  async request(method, path, body, params) {
    const p = this.useMock
      ? this._mock(method, path, body, params)
      : (() => {
          const url = new URL(this.base + path, location.origin);
          if (params) {
            Object.entries(params).forEach(([k, v]) => {
              if (v != null) url.searchParams.set(k, v);
            });
          }
          const opt = {
            method,
            headers: { Authorization: "Bearer " + this.token, "Content-Type": "application/json" },
          };
          if (body) opt.body = JSON.stringify(body);
          return fetch(url, opt).then((res) => res.json());
        })();

    return p.then((r) => {
      if (!r || r.code !== 0) throw new Error((r && r.msg) || "请求失败");
      return r.data;
    });
  },
  get(p, q) { return this.request("GET", p, null, q); },
  post(p, b) { return this.request("POST", p, b); },
  put(p, b) { return this.request("PUT", p, b); },
  del(p) { return this.request("DELETE", p); },

  /* 上传为 multipart，单独处理 */
  async uploadMaterial(formData) {
    if (this.useMock) {
      const file = formData.get("file");
      // 模拟：文件名含 "fail" 或体积 >50MB 视为上传失败，便于演示失败态与重试
      return new Promise((resolve, reject) => {
        try { resolve(MOCK.uploaded(file && file.name, file && file.size)); }
        catch (e) { reject(e); }
      });
    }
    const res = await fetch(this.base + "/api/materials/upload", {
      method: "POST",
      headers: { Authorization: "Bearer " + this.token },
      body: formData,
    });
    const r = await res.json();
    if (!r || r.code !== 0) throw new Error((r && r.msg) || "上传失败");
    return r.data;
  },

  /* ---------- 传资料模块 ---------- */
  listMaterials(q) { return this.get("/api/materials", q); },
  getMaterial(id) { return this.get("/api/materials/" + id); },
  deleteMaterial(id) { return this.del("/api/materials/" + id); },
  retryMaterial(id) { return this.post("/api/materials/" + id + "/retry", {}); },
  // 注：后端没有 /resolve 接口（解析是上传/重试后后台异步跑的），前端靠轮询 getMaterial 看状态

  /* ---------- 聊资料模块 ---------- */
  createSession(b) { return this.post("/api/chat/sessions", b); },
  sendMessage(sessionId, b) { return this.post("/api/chat/sessions/" + sessionId + "/messages", b); },

  /* 流式发消息：SSE 逐段返回，实现打字机效果。
     handlers: { onMeta(sources), onDelta(piece, fullText) }
     返回 Promise<{ messageId, content, sources, createdAt }> */
  async streamMessage(sessionId, b, handlers = {}) {
    const { onMeta, onDelta } = handlers;
    if (this.useMock) return this._mockStream(b, onMeta, onDelta);

    const res = await fetch(this.base + "/api/chat/sessions/" + sessionId + "/messages/stream", {
      method: "POST",
      headers: { Authorization: "Bearer " + this.token, "Content-Type": "application/json" },
      body: JSON.stringify(b),
    });

    // 检索失败、会话不存在等前置错误：后端返回的是普通 JSON，不是 SSE
    const ct = (res.headers.get("content-type") || "").toLowerCase();
    if (!ct.includes("text/event-stream")) {
      const r = await res.json().catch(() => null);
      throw new Error((r && r.msg) || "请求失败");
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let buf = "";
    let full = "";
    let sources = [];

    // SSE 帧以空行结尾，逐帧切出来解析
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });

      let cut;
      while ((cut = buf.indexOf("\n\n")) !== -1) {
        const frame = buf.slice(0, cut);
        buf = buf.slice(cut + 2);
        let event = "message";
        let payload = "";
        for (const line of frame.split("\n")) {
          if (line.startsWith("event:")) event = line.slice(6).trim();
          else if (line.startsWith("data:")) payload += line.slice(5).trim();
        }
        if (!payload) continue;
        let data;
        try { data = JSON.parse(payload); } catch (e) { continue; }

        if (event === "error") throw new Error(data.msg || "生成失败");
        if (event === "done") return data;
        if (event === "meta") {
          sources = data.sources || [];
          if (onMeta) onMeta(sources);
        } else if (event === "delta") {
          const piece = data.text || "";
          full += piece;
          if (onDelta) onDelta(piece, full);
        }
      }
    }
    // 连接断了但没收到 done：把已收到的内容当作结果返回，不丢字
    return { messageId: null, content: full, sources, createdAt: null };
  },

  // 离线演示：把模拟回答按 2 字一组延时吐出，效果与真实流式一致
  _mockStream(b, onMeta, onDelta) {
    const r = MOCK.reply(b);
    if (onMeta) onMeta(r.sources || []);
    const text = r.content;
    let i = 0;
    return new Promise((resolve) => {
      const tick = () => {
        if (i >= text.length) return resolve(r);
        const piece = text.slice(i, i + 2);
        i += 2;
        if (onDelta) onDelta(piece, text.slice(0, i));
        setTimeout(tick, 24);
      };
      setTimeout(tick, 300);
    });
  },
  getMessages(sessionId, q) { return this.get("/api/chat/sessions/" + sessionId + "/messages", q); },
  listSessions() { return this.get("/api/chat/sessions"); },
  deleteSession(sessionId) { return this.del("/api/chat/sessions/" + sessionId); },
  getNote(materialId) { return this.get("/api/materials/" + materialId + "/notes"); },
  saveNote(materialId, content) { return this.put("/api/materials/" + materialId + "/notes", { content }); },

  /* ---------- 做测评模块 ---------- */
  generateQuiz(b) { return this.post("/api/quiz/generate", b); },
  // durationMinutes 后端会存进提交记录，历史测评的「用时」靠它
  submitQuiz(quizId, answers, durationMinutes) {
    return this.post("/api/quiz/" + quizId + "/submit", { answers, durationMinutes });
  },
  getErrorBook(q) { return this.get("/api/quiz/errors", q); },
  getWeakPoints(p) { return this.get("/api/quiz/weak-points", p); },
  getReviewDue() { return this.get("/api/review/scheduled"); },
  getQuizHistory() { return this.get("/api/quiz/history"); },
  // 回看某一次历史测评（传历史列表里的 recordId）
  getSubmission(submissionId) { return this.get("/api/quiz/submissions/" + submissionId); },

  /* ---------- 看进度模块 ---------- */
  getProgressOverview() { return this.get("/api/progress/overview"); },
  getProgressSessions(q) { return this.get("/api/progress/sessions", q); },
  getTrends(q) { return this.get("/api/progress/trends", q); },

  /* ---------- 出周报模块 ---------- */
  generateReport(b) { return this.post("/api/report/generate", b); },
  getLatestReport() { return this.get("/api/report/latest"); },
  getReportHistory(q) { return this.get("/api/report/history", q); },
  getReport(id) { return this.get("/api/report/" + id); },
  /* 周报下载：后端按 format 返回 md / docx / pdf 二进制，这里直接触发浏览器保存 */
  async downloadReportFile(reportId, format) {
    const url = `${this.base}/api/report/${encodeURIComponent(reportId)}/download?format=${encodeURIComponent(format || "md")}`;
    const res = await fetch(url, { headers: { Authorization: "Bearer " + this.token } });
    if (!res.ok) throw new Error("下载失败（" + res.status + "）");
    const blob = await res.blob();
    // 文件名优先取后端 Content-Disposition，兜底自己拼
    let filename = null;
    const cd = res.headers.get("Content-Disposition") || "";
    const m = cd.match(/filename\*=UTF-8''(.+)$/i);
    if (m) {
      try { filename = decodeURIComponent(m[1]); } catch (e) { filename = m[1]; }
    }
    const extMap = { md: "md", docx: "docx", pdf: "pdf" };
    if (!filename) filename = `学习周报.${extMap[format] || "md"}`;
    const href = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = href;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(href);
  },

  /* =========================================================
     模拟数据（后端就绪前用于演示；结构与 PRD 返回一致）
     ========================================================= */
  _mock(method, path, body) {
    const wrap = (data) => ({ code: 0, data });
    const mat = (id) => path.match(new RegExp("^/api/materials/" + id + "$"));

    // —— 传资料 ——
    if (method === "GET" && path === "/api/materials") return Promise.resolve(wrap(MOCK.materials()));
    let m = path.match(/^\/api\/materials\/([^/]+)$/);
    if (m && method === "GET") return Promise.resolve(wrap(MOCK.materialDetail(m[1])));
    if (m && method === "DELETE") return Promise.resolve(wrap({ materialId: m[1], deleted: true }));
    let rm = path.match(/^\/api\/materials\/([^/]+)\/retry$/);
    if (rm && method === "POST") return Promise.resolve(wrap(MOCK.retry(rm[1])));
    if (method === "POST" && path === "/api/materials/upload") return Promise.resolve(wrap(MOCK.uploaded()));

    // —— 资料笔记（C-07）——
    let n = path.match(/^\/api\/materials\/([^/]+)\/notes$/);
    if (n && method === "GET") return Promise.resolve(wrap(MOCK.note(n[1])));
    if (n && method === "PUT") return Promise.resolve(wrap(MOCK.saveNote(n[1], body && body.content)));

    // —— 聊资料 ——
    if (method === "GET" && path === "/api/chat/sessions") return Promise.resolve(wrap(MOCK.sessions()));
    if (method === "POST" && path === "/api/chat/sessions") return Promise.resolve(wrap(MOCK.newSession(body)));
    let s = path.match(/^\/api\/chat\/sessions\/([^/]+)$/);
    if (s && method === "GET" && path.endsWith("/messages")) return Promise.resolve(wrap(MOCK.messages(s[1])));
    if (s && method === "POST" && path.endsWith("/messages")) return Promise.resolve(wrap(MOCK.reply(body)));
    if (s && method === "DELETE") return Promise.resolve(wrap({ sessionId: s[1], deleted: true }));

    // —— 做测评 ——
    if (method === "POST" && path === "/api/quiz/generate") return Promise.resolve(wrap(MOCK.quiz(body)));
    let q = path.match(/^\/api\/quiz\/([^/]+)\/submit$/);
    if (q && method === "POST") return Promise.resolve(wrap(MOCK.submit(body)));

    // —— 看进度 ——
    if (method === "GET" && path === "/api/progress/overview") return Promise.resolve(wrap(MOCK.progressOverview()));
    if (method === "GET" && path === "/api/progress/trends") return Promise.resolve(wrap(MOCK.trends()));
    if (method === "GET" && path === "/api/quiz/history") return Promise.resolve(wrap(MOCK.quizHistory()));

    // —— 出周报 ——
    if (method === "POST" && path === "/api/report/generate") return Promise.resolve(wrap(MOCK.report(body)));
    if (method === "GET" && path === "/api/report/latest") return Promise.resolve(wrap(MOCK.getLatestReport()));
    let rp = path.match(/^\/api\/report\/([^/]+)$/);
    if (rp && method === "GET") return Promise.resolve(wrap(MOCK.getReport(rp[1])));
    if (method === "GET" && path === "/api/report/history") return Promise.resolve(wrap(MOCK.getReportHistory()));

    return Promise.resolve(wrap({}));
  },
};

/* ---------- 模拟样本数据 ---------- */
const MOCK = {
  _materials: [
    { materialId: "mat_001", title: "Transformer 架构详解", fileType: "pdf", status: "ready", chunkCount: 42, category: "大模型基础", createdAt: "2026-10-09T10:00:00Z" },
    { materialId: "mat_002", title: "Attention Is All You Need 笔记", fileType: "md", status: "ready", chunkCount: 18, category: "大模型基础", createdAt: "2026-10-10T09:00:00Z" },
    { materialId: "mat_003", title: "位置编码与归一化", fileType: "ppt", status: "processing", chunkCount: 0, category: "大模型基础", createdAt: "2026-10-11T08:30:00Z" },
    { materialId: "mat_004", title: "大模型产品化实战", fileType: "pdf", status: "ready", chunkCount: 31, category: "应用落地", createdAt: "2026-10-08T14:00:00Z" },
    { materialId: "mat_005", title: "大模型推理优化（解析失败）", fileType: "pdf", status: "error", chunkCount: 0, category: "应用落地", createdAt: "2026-10-11T07:00:00Z" },
  ],
  materials() {
    return { total: this._materials.length, list: this._materials };
  },
  materialDetail(id) {
    const m = this._materials.find((x) => x.materialId === id) || this._materials[0];
    return { ...m, chunks: [{ chunkId: "chk_001", chunkIndex: 0, pageNumber: 1, preview: "Transformer 是一种基于自注意力机制的神经网络架构……" }] };
  },
  uploaded(name, size) {
    if (name && /fail/i.test(name)) throw new Error("上传失败（模拟）：文件名包含 fail");
    if (size && size > 50 * 1024 * 1024) throw new Error("文件超过 50MB 限制");
    const ext = (name && name.split(".").pop() || "pdf").toLowerCase();
    const fileType = ext === "pptx" ? "ppt" : ext;
    const m = {
      materialId: "mat_" + Date.now().toString().slice(-6),
      title: name || "新上传的资料",
      fileType: fileType,
      status: "processing",
      chunkCount: 0,
      category: "",
      createdAt: new Date().toISOString(),
    };
    this._materials.unshift(m);
    return m;
  },
  retry(id) {
    const m = this._materials.find((x) => x.materialId === id);
    if (m) m.status = "processing";
    return m || { materialId: id, status: "processing" };
  },
  note(id) {
    const long = "自注意力机制的核心：Query、Key、Value 三个矩阵相乘得到注意力权重。多头注意力并行多个子空间，最后拼接线性变换。位置编码弥补了置换不变性的缺陷，LayerNorm 稳定训练。这一章是理解 Transformer 的关键，建议反复阅读第 3~7 页并结合公式推导。";
    return { noteId: "nt_001", materialId: id, content: long, contentLength: long.length, collapsed: long.length > 200, updatedAt: "2026-10-11T11:30:00Z" };
  },
  saveNote(id, content) {
    return { noteId: "nt_001", materialId: id, content: content || "", contentLength: (content || "").length, updatedAt: new Date().toISOString() };
  },
  sessions() {
    return { total: 2, list: [
      { sessionId: "ses_001", title: "Transformer 学习", lastMessage: "自注意力机制是……", materialCount: 2, createdAt: "2026-10-11T11:05:00Z", updatedAt: "2026-10-11T11:10:00Z", materialIds: ["mat_001", "mat_002"] },
      { sessionId: "ses_002", title: "产品化讨论", lastMessage: "大模型落地的关键点……", materialCount: 1, createdAt: "2026-10-10T20:00:00Z", updatedAt: "2026-10-10T20:30:00Z", materialIds: ["mat_004"] },
    ] };
  },
  newSession() {
    return { sessionId: "ses_" + Date.now().toString().slice(-6), title: "新会话", materialIds: [], createdAt: new Date().toISOString() };
  },
  messages() {
    return { total: 2, list: [
      { messageId: "msg_001", role: "user", content: "什么是自注意力机制？", createdAt: "2026-10-11T11:05:00Z" },
      { messageId: "msg_002", role: "assistant", content: "自注意力机制是 Transformer 的核心。它让模型在处理某个词时，同时关注序列中所有其他词，通过 Query、Key、Value 三个矩阵计算注意力权重。", sources: [
        { materialId: "mat_001", title: "Transformer 架构详解", pageNumber: 3, chunkIndex: 12, snippet: "自注意力机制通过计算 Query、Key、Value 三个矩阵……" },
      ], createdAt: "2026-10-11T11:05:30Z" },
    ] };
  },
  reply(body) {
    const hasMat = body && Array.isArray(body.materialIds) && body.materialIds.length > 0;
    const content = hasMat
      ? "根据你上传的资料，自注意力的关键计算是 Q·Kᵀ 后 softmax 再乘 V，使每个位置都能聚合全局信息。这正是 Transformer 抛弃 RNN 循环结构、实现并行训练的基础。"
      : "这是一个好问题。当前没有选定资料，我以通用知识回答：自注意力机制让模型在处理某个词时关注序列中所有其他词，通过 Query、Key、Value 计算权重。若想获得基于你资料的精准解答，可在顶部选择对应资料，AI 会标注引用来源。";
    const sources = hasMat
      ? [
          { materialId: "mat_001", title: "Transformer 架构详解", pageNumber: 3, chunkIndex: 12, snippet: "自注意力机制通过计算 Query、Key、Value 三个矩阵……" },
          { materialId: "mat_002", title: "Attention Is All You Need 笔记", pageNumber: 1, chunkIndex: 0, snippet: "Transformer 完全摒弃了循环神经网络结构……" },
        ]
      : [];
    return { messageId: "msg_" + Date.now(), role: "assistant", content, sources, createdAt: new Date().toISOString() };
  },
  quiz(body) {
    const count = (body && body.questionCount) || 9;
    const base = [
      { questionId: "q_001", type: "choice", question: "Transformer 中自注意力机制的核心计算涉及哪三个矩阵？", options: { A: "Query、Key、Value", B: "Input、Hidden、Output", C: "Embedding、Position、Context", D: "Forward、Backward、Update" }, source: { materialId: "mat_001", pageNumber: 3, chunkIndex: 12 }, knowledgePoint: "自注意力机制" },
      { questionId: "q_002", type: "judgment", question: "Transformer 完全摒弃了循环神经网络结构，仅依赖注意力机制。", source: { materialId: "mat_002", pageNumber: 1, chunkIndex: 0 }, knowledgePoint: "Transformer 架构" },
      { questionId: "q_003", type: "shortAnswer", question: "简述多头注意力机制的作用。", source: { materialId: "mat_001", pageNumber: 5, chunkIndex: 20 }, knowledgePoint: "多头注意力" },
      { questionId: "q_004", type: "choice", question: "位置编码的主要作用是？", options: { A: "加快训练速度", B: "弥补注意力机制的置换不变性、注入顺序信息", C: "减少参数量", D: "防止过拟合" }, source: { materialId: "mat_003", pageNumber: 2, chunkIndex: 4 }, knowledgePoint: "位置编码" },
      { questionId: "q_005", type: "judgment", question: "Layer Normalization 在 Transformer 中用于稳定训练过程中的激活分布。", source: { materialId: "mat_003", pageNumber: 7, chunkIndex: 30 }, knowledgePoint: "Layer Normalization" },
      { questionId: "q_006", type: "shortAnswer", question: "为什么 Transformer 可以并行训练，而 RNN 不行？", source: { materialId: "mat_002", pageNumber: 1, chunkIndex: 1 }, knowledgePoint: "并行训练" },
    ];
    const list = [];
    for (let i = 0; i < count; i++) list.push(base[i % base.length]);
    return { quizId: "quiz_001", materialIds: ["mat_001"], status: "ready", questions: list, createdAt: new Date().toISOString() };
  },
  submit() {
    return { submissionId: "sub_001", quizId: "quiz_001", totalScore: 4.5, maxScore: 6, accuracy: 0.75, results: [
      { questionId: "q_001", type: "choice", userAnswer: "A", correctAnswer: "A", isCorrect: true, score: 1, explanation: "答对了。Q、K、V 是注意力的三个核心投影矩阵，缺一不可。" },
      { questionId: "q_002", type: "judgment", userAnswer: "true", correctAnswer: "true", isCorrect: true, score: 1, explanation: "判断正确，Transformer 确实以注意力机制替代了循环结构。" },
      { questionId: "q_003", type: "shortAnswer", userAnswer: "多头注意力并行多个子空间。", referenceAnswer: "多头注意力并行多次注意力，各子空间投影不同，最后拼接线性变换。", score: 0.5, explanation: "提及并行多子空间，但缺少「拼接 + 线性变换输出」步骤，给 0.5 分。" },
      { questionId: "q_004", type: "choice", userAnswer: "C", correctAnswer: "B", isCorrect: false, score: 0, explanation: "位置编码用于弥补注意力的置换不变性、注入顺序信息，应选 B。" },
      { questionId: "q_005", type: "judgment", userAnswer: "true", correctAnswer: "true", isCorrect: true, score: 1, explanation: "正确，LayerNorm 用于稳定训练过程中的激活分布。" },
      { questionId: "q_006", type: "shortAnswer", userAnswer: "因为自注意力一次看全序列，无时序依赖。", referenceAnswer: "RNN 按时间步顺序计算，前后依赖无法并行；自注意力一次计算全序列关系，可并行。", score: 0.5, explanation: "点出「无时序依赖」，但未对比 RNN 的顺序计算，给 0.5 分。" },
    ], submittedAt: new Date().toISOString() };
  },
  progressOverview() {
    const knowledgePoints = [
      { name: "自注意力机制", mastery: 0.9, level: "熟练" },
      { name: "Transformer 架构", mastery: 0.85, level: "熟练" },
      { name: "多头注意力", mastery: 0.55, level: "掌握" },
      { name: "位置编码", mastery: 0.4, level: "薄弱" },
      { name: "Layer Normalization", mastery: 0.65, level: "掌握" },
      { name: "并行训练", mastery: 0.78, level: "掌握" },
    ];
    const longNote = "自注意力机制的核心：Query、Key、Value 三个矩阵相乘得到注意力权重。多头注意力并行多个子空间，最后拼接线性变换。位置编码弥补了置换不变性的缺陷，LayerNorm 稳定训练。这一章是理解 Transformer 的关键，建议反复阅读第 3~7 页并结合公式推导，遇到卡壳的地方回到这份资料重新梳理。";
    const materials = [
      { materialId: "mat_001", title: "Transformer 架构详解", fileType: "pdf", chunkCount: 42, mastery: 0.88, note: { content: longNote, contentLength: longNote.length } },
      { materialId: "mat_002", title: "Attention Is All You Need 笔记", fileType: "md", chunkCount: 18, mastery: 0.8, note: { content: "", contentLength: 0 } },
      { materialId: "mat_003", title: "位置编码与归一化", fileType: "ppt", chunkCount: 0, mastery: 0.35, note: { content: "", contentLength: 0 } },
      { materialId: "mat_004", title: "大模型产品化实战", fileType: "pdf", chunkCount: 31, mastery: 0.6, note: { content: "", contentLength: 0 } },
    ];
    const weakPoints = [
      { knowledgePoint: "位置编码", errorCount: 4, suggestedReview: "重读《Transformer 架构详解》第 2 页" },
      { knowledgePoint: "多头注意力", errorCount: 3, suggestedReview: "重读《Transformer 架构详解》第 5 页" },
      { knowledgePoint: "Layer Normalization", errorCount: 2, suggestedReview: "重读《Transformer 架构详解》第 7 页" },
    ];
    return {
      totalMaterials: 12, masteredMaterials: 5, avgAccuracy: 0.72,
      weakPointsCount: weakPoints.length,
      knowledgePoints, materials, weakPoints,
      totalChunks: 480, coveredChunks: 210, coverageRate: 0.4375, totalQuizCount: 15,
      totalQuestionCount: 118, weekQuestionCount: 24, currentStreakDays: 4, lastStudyAt: "2026-10-11T11:20:00Z",
    };
  },
  quizHistory() {
    return { total: 4, list: [
      { recordId: "qr_004", date: "2026-10-11", material: "Transformer 架构详解", questionCount: 9, score: 7.5, maxScore: 9, accuracy: 0.83, durationSec: 423 },
      { recordId: "qr_003", date: "2026-10-10", material: "Attention Is All You Need 笔记", questionCount: 6, score: 4.5, maxScore: 6, accuracy: 0.75, durationSec: 298 },
      { recordId: "qr_002", date: "2026-10-09", material: "全部资料", questionCount: 12, score: 8, maxScore: 12, accuracy: 0.67, durationSec: 642 },
      { recordId: "qr_001", date: "2026-10-07", material: "Transformer 架构详解", questionCount: 9, score: 6, maxScore: 9, accuracy: 0.67, durationSec: 376 },
    ] };
  },
  trends() {
    return { metric: "accuracy", granularity: "week", points: [
      { label: "W37", value: 0.55 }, { label: "W38", value: 0.6 }, { label: "W39", value: 0.68 }, { label: "W40", value: 0.72 },
      { label: "W41", value: 0.7 }, { label: "W42", value: 0.78 }, { label: "W43", value: 0.8 }, { label: "W44", value: 0.83 },
    ] };
  },
  _reports: [
    { reportId: "rpt_003", weekStart: "2026-10-06", weekEnd: "2026-10-12", createdAt: "2026-10-12T08:00:00Z", sections: {
      questionCount: { thisWeek: 42, lastWeek: 36, changePercent: 0.167 },
      materialCoverage: { newMaterials: 2, coveredChunks: 45, coverageRate: 0.4375 },
      accuracyTrend: { thisWeek: 0.72, lastWeek: 0.65, changePercent: 0.107 },
      weakPoints: [
        { knowledgePoint: "多头注意力机制", errorCount: 3, suggestedReview: "重新阅读 Transformer 架构详解第 5 页" },
        { knowledgePoint: "位置编码", errorCount: 2, suggestedReview: "重新阅读 Transformer 架构详解第 2 页" },
        { knowledgePoint: "Layer Normalization", errorCount: 2, suggestedReview: "重新阅读 Transformer 架构详解第 7 页" },
      ],
      nextWeekPlan: ["复习错题本中 5 道到期题目（间隔重复）", "重点攻克多头注意力机制相关内容", "完成新资料 Attention 笔记的学习"],
      motivation: "本周正确率提升了 10.7%，坚持的节奏很稳，下周继续！",
    } },
    { reportId: "rpt_002", weekStart: "2026-09-29", weekEnd: "2026-10-05", createdAt: "2026-10-05T08:00:00Z", sections: {
      questionCount: { thisWeek: 36, lastWeek: 33, changePercent: 0.091 },
      materialCoverage: { newMaterials: 1, coveredChunks: 38, coverageRate: 0.39 },
      accuracyTrend: { thisWeek: 0.65, lastWeek: 0.6, changePercent: 0.083 },
      weakPoints: [
        { knowledgePoint: "位置编码", errorCount: 3, suggestedReview: "重新阅读 Transformer 架构详解第 2 页" },
        { knowledgePoint: "Layer Normalization", errorCount: 2, suggestedReview: "重新阅读 Transformer 架构详解第 7 页" },
      ],
      nextWeekPlan: ["巩固位置编码与归一化", "完成 Transformer 架构详解第 3~5 页精读"],
      motivation: "稳步上升，保持每周做题的节奏。",
    } },
    { reportId: "rpt_001", weekStart: "2026-09-22", weekEnd: "2026-09-28", createdAt: "2026-09-28T08:00:00Z", sections: {
      questionCount: { thisWeek: 33, lastWeek: 33, changePercent: 0 },
      materialCoverage: { newMaterials: 3, coveredChunks: 30, coverageRate: 0.33 },
      accuracyTrend: { thisWeek: 0.6, lastWeek: 0.52, changePercent: 0.154 },
      weakPoints: [
        { knowledgePoint: "自注意力机制", errorCount: 2, suggestedReview: "重新阅读 Transformer 架构详解第 3 页" },
      ],
      nextWeekPlan: ["开始做第一套测评", "建立错题本"],
      motivation: "万事开头难，已经迈出第一步，棒！",
    } },
  ],
  report(body) {
    const start = (body && body.weekStart) || this._isoWeekStart(new Date());
    const end = (body && body.weekEnd) || this._isoWeekEnd(new Date());
    const r = {
      reportId: "rpt_" + Date.now().toString().slice(-6),
      weekStart: start, weekEnd: end,
      createdAt: new Date().toISOString(),
      sections: {
        questionCount: { thisWeek: 48, lastWeek: 42, changePercent: 0.143 },
        materialCoverage: { newMaterials: 1, coveredChunks: 52, coverageRate: 0.49 },
        accuracyTrend: { thisWeek: 0.79, lastWeek: 0.72, changePercent: 0.097 },
        weakPoints: [
          { knowledgePoint: "多头注意力机制", errorCount: 2, suggestedReview: "重新阅读 Transformer 架构详解第 5 页" },
          { knowledgePoint: "位置编码", errorCount: 1, suggestedReview: "重新阅读 Transformer 架构详解第 2 页" },
        ],
        nextWeekPlan: ["复习本周错题本中点赞的 4 道题", "预习大模型产品化实战资料", "把本周错题再做一遍"],
        motivation: "本周正确率逼近 80%，薄弱点在收敛，节奏非常好！",
      },
    };
    this._reports.unshift(r);
    return r;
  },
  getLatestReport() { return this._reports[0]; },
  getReportHistory() {
    return { total: this._reports.length, list: this._reports.map((r) => ({
      reportId: r.reportId, weekStart: r.weekStart, weekEnd: r.weekEnd,
      questionCount: r.sections.questionCount.thisWeek,
      accuracy: r.sections.accuracyTrend.thisWeek,
      weakPointCount: r.sections.weakPoints.length,
      createdAt: r.createdAt,
    })) };
  },
  getReport(id) { return this._reports.find((r) => r.reportId === id) || this._reports[0]; },
  _isoWeekStart(d) {
    const x = new Date(d);
    const day = (x.getDay() + 6) % 7;
    x.setDate(x.getDate() - day); x.setHours(0, 0, 0, 0);
    return x.toISOString().slice(0, 10);
  },
  _isoWeekEnd(d) {
    const x = new Date(d);
    const day = (x.getDay() + 6) % 7;
    x.setDate(x.getDate() + (6 - day)); x.setHours(0, 0, 0, 0);
    return x.toISOString().slice(0, 10);
  },
};
