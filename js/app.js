/* =========================================================
   app.js — hash 路由 + 页面渲染 + 交互
   ========================================================= */

/* ---------- 工具函数 ---------- */
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

function toast(msg, type) {
  const t = $("#toast");
  t.textContent = msg;
  t.className = "toast";
  if (type) t.classList.add("toast--" + type);
  t.classList.add("show");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => t.classList.remove("show"), 2200);
}

const fileTypeLabel = (t) => ({ pdf: "PDF", ppt: "PPT", md: "MD", doc: "DOC", txt: "TXT" }[t] || t.toUpperCase());
const statusBadge = (s) => ({ ready: '<span class="badge badge--ready">已就绪</span>', processing: '<span class="badge badge--processing">解析中</span>', error: '<span class="badge badge--error">失败</span>' }[s] || s);

/* 判断题选项是前后端约定死的二选一：A=正确，B=错误 */
const JUDGMENT_OPTIONS = { A: "正确", B: "错误" };

/* 选项归一化：后端 SQLite 的 JSON 列、大模型输出都可能给出字符串或数组，
   这里一律转成 { A: "xxx", B: "xxx" } 这种对象再用。 */
function normalizeOptions(options, fallback) {
  let o = options;
  if (typeof o === "string") {
    try { o = JSON.parse(o); } catch (e) { o = null; }
  }
  if (o && typeof o === "object" && !Array.isArray(o) && Object.keys(o).length) {
    const out = {};
    Object.keys(o).forEach((k) => (out[String(k)] = String(o[k])));
    return out;
  }
  if (Array.isArray(o) && o.length) {
    const out = {};
    const letters = "ABCDEFGH";
    o.forEach((v, i) => (out[i < letters.length ? letters[i] : String(i + 1)] = String(v)));
    return out;
  }
  return fallback || null;
}

/* 判断题答案归一：true/A/对 → "A"；false/B/错 → "B" */
function normJudgment(v) {
  const s = String(v == null ? "" : v).trim().toLowerCase();
  if (["a", "true", "1", "yes", "t", "对", "正确"].includes(s)) return "A";
  if (["b", "false", "0", "no", "f", "错", "错误"].includes(s)) return "B";
  return "";
}

/* ---------- 全局状态 ---------- */
const state = {
  chat: { sessionId: null, materialId: null, thinking: false },
  currentMaterialId: null, // 笔记弹窗当前资料
  currentQuiz: null,
  noteTimer: null,
  reportRange: "week", // week | custom
  currentReport: null,
};

/* =========================================================
   路由
   ========================================================= */
const PAGES = {
  chat: { title: "问一问", sub: "跟你的资料对话，AI 回答会标注引用来源", init: renderChat },
  quiz: { title: "测评", sub: "基于资料自动出题，检测知识点掌握", init: renderQuiz },
  progress: { title: "进度", sub: "做题量、资料覆盖、测验正确率一目了然", init: renderProgress },
  report: { title: "报告", sub: "选择周期，AI 自动汇总学习成果、薄弱点与下周建议", init: renderReport },
  materials: { title: "资料库", sub: "上传 PDF / PPT / Markdown，系统自动解析、语义切块、向量化", init: renderMaterials },
};

function router() {
  const key = (location.hash.replace(/^#\/?/, "") || "chat");
  const route = PAGES[key] ? key : "chat";
  $$(".page").forEach((p) => p.classList.toggle("is-active", p.dataset.route === route));
  $$(".nav__item").forEach((n) => n.classList.toggle("is-active", n.dataset.route === route));
  $("#page-title").textContent = PAGES[route].title;
  $("#page-sub").textContent = PAGES[route].sub;
  // 兜底：任何页面初始化抛错都不能静默白屏（曾经的坑：接口被跨域拦掉 →
  // 列表渲染成空 → 用户以为资料被删了，实际数据一个没丢）
  Promise.resolve()
    .then(() => PAGES[route].init())
    .catch((e) => {
      console.error("[router]", route, e);
      toast("页面加载失败：" + ((e && e.message) || "请确认后端已启动"), "error");
    });
}

/* =========================================================
   资料库（原传资料）
   ========================================================= */
async function renderMaterials() {
  const grid = $("#material-list");
  let list;
  try {
    const data = await API.listMaterials();
    list = data.list || [];
  } catch (e) {
    // 拿不到数据时必须显式报错，不能让列表空着（会被误读成「资料被删了」）
    console.error("[materials] list failed:", e);
    grid.innerHTML = errorState("资料列表加载失败", e);
    return;
  }

  const cats = [...new Set(list.map((m) => m.category).filter(Boolean))];
  const fc = $("#filter-category");
  fc.innerHTML = '<option value="">全部分类</option>' + cats.map((c) => `<option>${esc(c)}</option>`).join("");

  if (!list.length) {
    grid.innerHTML = emptyState("还没有资料", "点击右上角上传你的第一份课程资料");
    return;
  }
  grid.innerHTML = list
    .map((m) => {
      const isError = m.status === "error";
      const actions = `
        <div class="material-card__actions">
          ${isError
            ? `<button class="btn btn--primary btn--sm" data-retry="${esc(m.materialId)}">
                 <svg class="btn__icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M23 4v6h-6M1 20v-6h6M3.5 9a9 9 0 0 1 14.8-3.4L23 10M1 14l4.7 4.4A9 9 0 0 0 20.5 15"/></svg>
                 重试</button>`
            : `<button class="btn btn--ghost btn--sm" data-note="${esc(m.materialId)}">笔记</button>`}
          <button class="btn btn--ghost btn--sm btn-del" data-id="${esc(m.materialId)}">删除</button>
        </div>`;
      return `
      <div class="material-card ${isError ? "material-card--error" : ""}">
        <div class="material-card__top">
          <div class="file-icon file-icon--${esc(m.fileType)}">${fileTypeLabel(m.fileType)}</div>
          <div>
            <div class="material-card__title">${esc(m.title)}</div>
            <div class="material-card__meta">${esc(m.category || "未分类")} · ${m.chunkCount} 块</div>
          </div>
        </div>
        ${isError ? `<div class="material-card__err">⚠ ${esc(m.errorMessage || "解析失败，请点「重试」或删除后重新上传")}</div>` : ""}
        <div class="material-card__foot">
          ${statusBadge(m.status)}
          ${actions}
        </div>
      </div>`;
    })
    .join("");

  $$(".btn-del", grid).forEach((b) =>
    b.addEventListener("click", async () => {
      await API.deleteMaterial(b.dataset.id);
      toast("已删除资料");
      renderMaterials();
    })
  );
  $$("[data-note]", grid).forEach((b) =>
    b.addEventListener("click", () => openNote(b.dataset.note))
  );
  $$("[data-retry]", grid).forEach((b) =>
    b.addEventListener("click", () => retryUpload(b.dataset.retry))
  );
}

/* 上传交互 */
function bindUpload() {
  const zone = $("#upload-zone");
  const input = $("#file-input");
  zone.addEventListener("click", () => input.click());
  input.addEventListener("change", () => input.files[0] && doUpload(input.files[0]));
  ["dragover", "dragenter"].forEach((e) => zone.addEventListener(e, (ev) => { ev.preventDefault(); zone.classList.add("is-drag"); }));
  ["dragleave", "drop"].forEach((e) => zone.addEventListener(e, (ev) => { ev.preventDefault(); zone.classList.remove("is-drag"); }));
  zone.addEventListener("drop", (ev) => { const f = ev.dataTransfer.files[0]; if (f) doUpload(f); });
}
async function doUpload(file) {
  try {
    const fd = new FormData();
    fd.append("file", file);
    const d = await API.uploadMaterial(fd);
    toast("✓ 上传成功，正在解析…", "success");
    await renderMaterials();
    const id = d && (d.materialId || d.id);
    if (id) await pollMaterial(id); // 不轮询的话卡片会一直停在「解析中」
  } catch (e) {
    toast("✗ 上传失败，请重试", "error");
  }
}

/* 轮询单个资料状态直到 ready / error（最多 60 秒）。
   解析是后台异步跑的，上传或重试后必须轮询，否则卡片会一直卡在「解析中」。 */
async function pollMaterial(id) {
  for (let i = 0; i < 60; i++) {
    await new Promise((r) => setTimeout(r, 1000));
    const m = await API.getMaterial(id).catch(() => null);
    if (!m) continue;
    if (m.status === "ready") {
      await renderMaterials();
      toast("✓ 解析完成，已就绪", "success");
      return true;
    }
    if (m.status === "error") {
      await renderMaterials();
      toast("✗ 解析失败：" + (m.errorMessage || "请点击重试"), "error");
      return false;
    }
    if (i % 3 === 2) await renderMaterials(); // 解析中时定期刷新，保证卡片不假死
  }
  await renderMaterials();
  toast("解析仍在进行中，请稍后查看", "error");
  return false;
}

/* 失败资料重试：调用后端重新解析，轮询状态直到 ready / error */
async function retryUpload(id) {
  try {
    await API.retryMaterial(id);
  } catch (e) {
    toast("✗ 重试失败：" + (e.message || ""), "error");
    renderMaterials();
    return;
  }
  renderMaterials();
  toast("正在重新解析…", "success");
  await pollMaterial(id);
}

/* =========================================================
   问一问（聊天）
   ========================================================= */
async function renderChat() {
  // 不再每次都清空 sessionId：切到别的页面再回来，仍停在原来那次对话
  if (!state.chat) state.chat = { sessionId: null, materialId: null, thinking: false };
  await buildChatMaterialPicker();
  await renderSessionList();
  if (state.chat.sessionId) await openSession(state.chat.sessionId);
  else showChatEmpty();
}

/* ---------- 历史对话侧栏 ---------- */
/* 会话是按 updated_at 倒序返回的，最新聊过的排最前 */
async function renderSessionList() {
  const box = $("#chat-session-list");
  if (!box) return;
  let list = [];
  try {
    const d = await API.listSessions();
    // 过滤掉建了但一条消息都没发的空会话（点「新对话」不会立刻建会话，
    // 这里只是兜底清理历史遗留数据，避免侧栏出现一串「新对话」）
    list = (d.list || []).filter((s) => s.lastMessage);
  } catch (e) {
    $("#chat-session-count").textContent = "";
    box.innerHTML = `<div class="chat-sessions__empty">历史对话加载失败</div>`;
    return;
  }
  state.chatSessions = list;
  $("#chat-session-count").textContent = list.length ? `${list.length} 条` : "";
  if (!list.length) {
    box.innerHTML = `<div class="chat-sessions__empty">还没有历史对话。<br>点「新对话」开始一段，旧的会自动留在这里。</div>`;
    return;
  }
  const cur = state.chat.sessionId;
  box.innerHTML = list
    .map((s) => {
      const preview = (s.lastMessage || "").slice(0, 26);
      return `<div class="ses-item${s.sessionId === cur ? " is-active" : ""}" data-sid="${esc(s.sessionId)}">
        <div class="ses-item__title">${esc(s.title || "新对话")}</div>
        <div class="ses-item__meta">${esc(preview)}${(s.lastMessage || "").length > 26 ? "…" : ""}</div>
        <button class="ses-item__del" data-sid="${esc(s.sessionId)}" title="删除这条对话">×</button>
      </div>`;
    })
    .join("");
}

async function openSession(id) {
  if (state.chat.thinking) return;
  const box = $("#chat-messages");
  state.chat.sessionId = id;
  $("#btn-del-chat").hidden = false;
  box.innerHTML = `<div class="chat-empty"><div class="chat-empty__sub">正在加载对话…</div></div>`;
  try {
    const d = await API.getMessages(id, { page: 1, pageSize: 200 });
    const list = d.list || [];
    if (list.length) {
      box.innerHTML = list.map(renderBubble).join("");
      scrollChat();
    } else {
      showChatEmpty();
    }
  } catch (e) {
    box.innerHTML = `<div class="chat-empty"><div class="chat-empty__sub">加载失败：${esc((e && e.message) || "未知错误")}</div></div>`;
  }
  // 恢复这条对话当时选的资料范围（会话只有一个资料时才回填，多个不猜）
  const s = (state.chatSessions || []).find((x) => x.sessionId === id);
  if (s && Array.isArray(s.materialIds) && s.materialIds.length === 1) {
    setChatMaterial(s.materialIds[0]);
  }
  await renderSessionList();
}

/* 程序化设置顶部资料下拉（自定义下拉要同时改隐藏 select 和显示文字） */
function setChatMaterial(materialId) {
  const sel = $("#chat-material");
  if (!sel) return;
  const opt = Array.from(sel.options).find((o) => o.value === materialId);
  sel.value = opt ? materialId : "";
  const wrap = sel.closest(".select-wrap");
  const label = wrap && $(".dd-value", wrap);
  if (label) label.textContent = (opt || sel.options[0]).textContent;
}

/* 顶部资料下拉：列出已就绪资料，选哪份跟哪份聊；空值=普通对话 */
async function buildChatMaterialPicker() {
  const data = await API.listMaterials();
  const mats = (data.list || []).filter((m) => m.status === "ready");
  $("#chat-material").innerHTML =
    '<option value="">不限定资料（普通对话）</option>' +
    mats.map((m) => `<option value="${esc(m.materialId)}">${esc(m.title)}</option>`).join("");
}

function showChatEmpty() {
  $("#chat-messages").innerHTML = `
    <div class="chat-empty">
      <div class="chat-empty__icon">
        <svg width="34" height="34" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
      </div>
      <div class="chat-empty__title">问一问，和你的资料对话</div>
      <div class="chat-empty__sub">在顶部选一份资料定向提问，或不选资料开启普通对话。基于资料回答时，AI 会标注引用来源，方便你回看原文。</div>
      <div class="chat-empty__chips">
        试试问：
        <button class="chip" data-q="用一句话解释自注意力机制，并说明 Q、K、V 的作用">自注意力机制是什么？</button>
        <button class="chip" data-q="多头注意力和单头注意力有什么区别？为什么要用多头？">多头注意力 vs 单头</button>
        <button class="chip" data-q="位置编码在 Transformer 里起什么作用？没有它会怎样？">位置编码的作用</button>
      </div>
    </div>`;
  $$(".chat-empty__chips .chip").forEach((c) =>
    c.addEventListener("click", () => {
      $("#chat-input").value = c.dataset.q;
      sendMessage();
    })
  );
}

/* 引用来源的 HTML（默认收起）。流式与非流式共用同一份，保证样式一致 */
function sourcesHtml(sources) {
  if (!sources || !sources.length) return "";
  const items = sources
    .map(
      (s) => `<div class="src-item">
          <div class="src-item__head">📄 《${esc(s.title)}》第 ${esc(s.pageNumber)} 页</div>
          <div class="src-item__snippet">${esc(s.snippet || "")}</div>
        </div>`
    )
    .join("");
  return `
      <button class="src-toggle" data-sources-toggle type="button">
        <svg class="src-toggle__chevron" viewBox="0 0 10 6" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M1 1l4 4 4-4"/></svg>
        引用了 ${sources.length} 处资料
      </button>
      <div class="src-panel" hidden>${items}</div>`;
}

function renderBubble(msg) {
  const isUser = msg.role === "user";
  const content = isUser ? esc(msg.content) : renderMarkdown(msg.content);
  return `<div class="bubble bubble--${isUser ? "user" : "assistant"}">
    <div class="bubble__avatar">${isUser ? "我" : "AI"}</div>
    <div class="bubble__body">
      <div class="bubble__content">${content}</div>
      ${isUser ? "" : sourcesHtml(msg.sources)}
    </div>
  </div>`;
}

async function sendMessage() {
  const input = $("#chat-input");
  const text = input.value.trim();
  if (!text || state.chat.thinking) return;

  if (!state.chat.sessionId) {
    try {
      const s = await API.createSession({
        title: text.slice(0, 20),
        materialIds: $("#chat-material").value ? [$("#chat-material").value] : [],
      });
      state.chat.sessionId = s.sessionId;
      $("#btn-del-chat").hidden = false;
      renderSessionList(); // 新会话立刻出现在侧栏
    } catch (e) {
      toast("✗ 创建会话失败：" + (e.message || ""), "error");
      return;
    }
  }

  const box = $("#chat-messages");
  box.querySelector(".chat-empty")?.remove();
  box.insertAdjacentHTML("beforeend", renderBubble({ role: "user", content: text }));
  input.value = "";
  autoGrow(input);
  scrollChat();

  // 正在思考
  state.chat.thinking = true;
  setChatBusy(true);
  const thinkId = "think-" + Date.now();
  box.insertAdjacentHTML(
    "beforeend",
    `<div class="bubble bubble--assistant" id="${thinkId}">
      <div class="bubble__avatar">AI</div>
      <div class="bubble__body"><div class="thinking">
        <span class="thinking__dot"></span><span class="thinking__dot"></span><span class="thinking__dot"></span>
        正在思考…
      </div></div>
    </div>`
  );
  scrollChat(box.lastElementChild); // 对齐到「正在思考」这一行，回答回来时视口不跳动

  const materialId = $("#chat-material").value;
  const streamId = "stream-" + Date.now();
  let streamEl = null;      // 流式气泡 DOM
  let streamedText = "";    // 已收到的完整文本
  let pendingSources = [];  // meta 事件带来的引用来源
  let rafId = null;         // 渲染节流：一帧最多重绘一次
  let err = null;
  let reply = null;

  // 首个 token 到达时才建气泡：这之前保留「正在思考」，和 DeepSeek 一致
  function ensureStreamBubble(sources) {
    if (streamEl) return streamEl;
    document.getElementById(thinkId)?.remove();
    box.insertAdjacentHTML(
      "beforeend",
      `<div class="bubble bubble--assistant" id="${streamId}">
        <div class="bubble__avatar">AI</div>
        <div class="bubble__body">
          <div class="bubble__content"><span class="stream-cursor"></span></div>
          ${sourcesHtml(sources)}
        </div>
      </div>`
    );
    streamEl = document.getElementById(streamId);
    scrollChat(streamEl); // 停在回答开头
    return streamEl;
  }

  function paintStream(el, text, done) {
    if (rafId) cancelAnimationFrame(rafId);
    rafId = requestAnimationFrame(() => {
      rafId = null;
      const c = el.querySelector(".bubble__content");
      if (!c) return;
      c.innerHTML = renderMarkdown(text) + (done ? "" : '<span class="stream-cursor"></span>');
      // 短回答：保持开头可见；内容超出可视区后才跟随底部
      const r = el.getBoundingClientRect();
      const br = box.getBoundingClientRect();
      if (r.bottom > br.bottom - 8) box.scrollTop = box.scrollHeight;
    });
  }

  const payload = { message: text, materialIds: materialId ? [materialId] : undefined };
  // 降级保护：api.js 若还是旧版本（浏览器缓存导致新旧文件错配），
  // 退回非流式接口，保证问答不整个挂掉，只是没有打字机效果
  const canStream = typeof API.streamMessage === "function";

  try {
    if (canStream) {
      reply = await API.streamMessage(
        state.chat.sessionId,
        payload,
        {
          onMeta: (sources) => { pendingSources = sources || []; },
          onDelta: (piece, full) => {
            streamedText = full;
            paintStream(ensureStreamBubble(pendingSources), full, false);
          },
        }
      );
    } else {
      reply = await API.sendMessage(state.chat.sessionId, payload);
    }
  } catch (e) {
    err = e;
  }

  document.getElementById(thinkId)?.remove();
  state.chat.thinking = false;
  setChatBusy(false);

  if (err) {
    const msg = (err && err.message) || "未知错误";
    if (streamEl) {
      // 已经吐了一部分：保留已生成内容，再补一行中断提示
      const c = streamEl.querySelector(".bubble__content");
      c.innerHTML =
        renderMarkdown(streamedText) +
        (streamedText
          ? `<p style="color:#c0392b">⚠ 生成中断：${esc(msg)}</p>`
          : `<span style="color:#c0392b">回复失败：${esc(msg)}</span>`);
    } else {
      box.insertAdjacentHTML(
        "beforeend",
        `<div class="bubble bubble--assistant">
          <div class="bubble__avatar">AI</div>
          <div class="bubble__body"><div class="bubble__content">
            <span style="color:#c0392b">回复失败：${esc(msg)}</span>
          </div></div>
        </div>`
      );
    }
    scrollChat(streamEl || undefined);
    return;
  }

  if (rafId) cancelAnimationFrame(rafId);
  if (streamEl) {
    // 收尾：去掉光标，用后端最终文本重绘一次（保证与落库内容完全一致）
    const finalText = (reply && reply.content) || streamedText;
    streamEl.querySelector(".bubble__content").innerHTML = renderMarkdown(finalText);
  } else {
    box.insertAdjacentHTML("beforeend", renderBubble(reply));
    scrollChat(box.lastElementChild); // 停在回答开头，而不是跳到最末尾
  }
  // 刷新侧栏：标题与"最后一条消息"预览会跟着更新，并置顶到最新
  await renderSessionList();
}

async function newChat() {
  if (state.chat.thinking) return;
  state.chat.sessionId = null;   // 旧会话仍留在数据库里，侧栏随时能点回来
  setChatBusy(false);
  $("#btn-del-chat").hidden = true;
  showChatEmpty();
  await renderSessionList();     // 刷新高亮：现在没有任何会话处于选中态
}

/* 删除当前打开的会话 */
async function deleteCurrentSession() {
  if (state.chat.thinking || !state.chat.sessionId) return;
  if (!confirm("删除这条对话？删除后无法恢复。")) return;
  const id = state.chat.sessionId;
  try {
    await API.deleteSession(id);
    toast("✓ 已删除该对话", "success");
  } catch (e) {
    toast("✗ 删除失败：" + ((e && e.message) || ""), "error");
    return;
  }
  state.chat.sessionId = null;
  $("#btn-del-chat").hidden = true;
  showChatEmpty();
  await renderSessionList();
}

function setChatBusy(busy) {
  $("#chat-input-bar").classList.toggle("is-busy", busy);
  $("#chat-input").disabled = busy;
  $("#btn-send").disabled = busy;
}

function autoGrow(el) {
  el.style.height = "auto";
  el.style.height = Math.min(el.scrollHeight, 160) + "px";
}
/* 没有传元素时滚到最底部；传了元素则滚动到这条消息的开头，
   便于从回答的第一行开始往下读，而不是一跳到底部看不到开头。
   用 getBoundingClientRect 计算，避免依赖 offsetParent。 */
function scrollChat(el) {
  const box = $("#chat-messages");
  if (!box) return;
  if (!el) {
    box.scrollTop = box.scrollHeight;
    return;
  }
  const delta = el.getBoundingClientRect().top - box.getBoundingClientRect().top;
  box.scrollTop += delta - 12; // 上方留 12px 呼吸位
}

/* 轻量 Markdown：标题 / 列表 / 代码块 / 粗体 / 行内代码（先转义防注入） */
function renderMarkdown(src) {
  const lines = String(src || "").split("\n");
  let html = "";
  let inCode = false;
  let codeBuf = [];
  let inUl = false;
  let inOl = false;

  const closeLists = () => {
    if (inUl) { html += "</ul>"; inUl = false; }
    if (inOl) { html += "</ol>"; inOl = false; }
  };
  const inline = (t) =>
    esc(t)
      .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
      .replace(/`([^`]+)`/g, "<code>$1</code>");

  for (const raw of lines) {
    if (raw.startsWith("```")) {
      if (!inCode) { closeLists(); inCode = true; codeBuf = []; }
      else { inCode = false; html += `<pre><code>${esc(codeBuf.join("\n"))}</code></pre>`; }
      continue;
    }
    if (inCode) { codeBuf.push(raw); continue; }

    const t = raw.trim();
    if (!t) { closeLists(); continue; }
    if (/^###\s+/.test(t)) { closeLists(); html += `<h3>${inline(t.replace(/^###\s+/, ""))}</h3>`; continue; }
    if (/^##\s+/.test(t)) { closeLists(); html += `<h2>${inline(t.replace(/^##\s+/, ""))}</h2>`; continue; }
    if (/^#\s+/.test(t)) { closeLists(); html += `<h1>${inline(t.replace(/^#\s+/, ""))}</h1>`; continue; }
    if (/^[-*]\s+/.test(t)) {
      if (inOl) { html += "</ol>"; inOl = false; }
      if (!inUl) { html += "<ul>"; inUl = true; }
      html += `<li>${inline(t.replace(/^[-*]\s+/, ""))}</li>`;
      continue;
    }
    if (/^\d+\.\s+/.test(t)) {
      if (inUl) { html += "</ul>"; inUl = false; }
      if (!inOl) { html += "<ol>"; inOl = true; }
      html += `<li>${inline(t.replace(/^\d+\.\s+/, ""))}</li>`;
      continue;
    }
    closeLists();
    html += `<p>${inline(t)}</p>`;
  }
  if (inCode) html += `<pre><code>${esc(codeBuf.join("\n"))}</code></pre>`;
  closeLists();
  return html;
}

/* =========================================================
   做测评
   ========================================================= */
/* 缓存已就绪资料，供「全部资料」出题使用 */
let _readyMaterials = [];
async function renderQuiz() {
  const data = await API.listMaterials();
  _readyMaterials = (data.list || []).filter((m) => m.status === "ready");
  $("#quiz-material").innerHTML = '<option value="">全部资料</option>' + _readyMaterials.map((m) => `<option value="${esc(m.materialId)}">${esc(m.title)}</option>`).join("");
  $("#quiz-view").innerHTML = emptyState("还没有测验", "选择资料与题量，点击「生成测验」");
}

async function generateQuiz() {
  const view = $("#quiz-view");
  const picked = $("#quiz-material").value;
  // 「全部资料」时用所有已就绪资料的 id，不能再用写死的示例 id
  const materialIds = picked ? [picked] : _readyMaterials.map((m) => m.materialId);
  if (!materialIds.length) {
    view.innerHTML = emptyState("暂无可用资料", "请先到「资料库」上传资料，并等它解析完成（状态变为已就绪）");
    toast("没有已就绪的资料，无法出题", "error");
    return;
  }
  view.innerHTML = '<div class="empty"><div class="loading-dots">正在出题</div></div>';
  try {
    const quiz = await API.generateQuiz({
      materialIds: materialIds,
      questionCount: Number($("#quiz-count").value),
      difficulty: $("#quiz-difficulty").value,
    });
    state.currentQuiz = quiz;
    state.quizStartTime = Date.now();
    view.innerHTML = quiz.questions.map((q, i) => renderQuestion(q, i)).join("") +
      `<div class="quiz-toolbar"><button class="btn btn--primary" id="btn-submit-quiz">提交批改</button></div>`;
    $("#btn-submit-quiz").addEventListener("click", () => submitQuiz(quiz));
  } catch (e) {
    view.innerHTML = emptyState("出题失败", e.message || "请稍后重试");
    toast("✗ 出题失败：" + (e.message || ""), "error");
  }
}

function renderQuestion(q, i) {
  const idx = i + 1;
  // 选择题与判断题都用 options 渲染；判断题没有 options 时按约定补 A/B
  if (q.type === "choice" || q.type === "judgment") {
    const isJudge = q.type === "judgment";
    const opts = normalizeOptions(q.options, isJudge ? JUDGMENT_OPTIONS : null) || {};
    const entries = Object.entries(opts);
    const body = entries.length
      ? entries
          .map(
            ([k, v]) =>
              `<label class="option"><input type="radio" name="q_${esc(q.questionId)}" value="${esc(k)}"><span><b>${esc(k)}.</b> ${esc(v)}</span></label>`
          )
          .join("")
      : `<div class="muted">（该题选项缺失，请重新生成测验）</div>`;
    return `<div class="question" data-id="${esc(q.questionId)}" data-type="${esc(q.type)}">
      <div class="question__meta"><span class="badge badge--type">${isJudge ? "判断题" : "选择题"}</span><span class="badge badge--neutral">${esc(q.knowledgePoint || "")}</span></div>
      <div class="question__stem">${idx}. ${esc(q.question)}</div>${body}</div>`;
  }
  return `<div class="question" data-id="${esc(q.questionId)}" data-type="shortAnswer">
    <div class="question__meta"><span class="badge badge--type">简答题</span><span class="badge badge--neutral">${esc(q.knowledgePoint || "")}</span></div>
    <div class="question__stem">${idx}. ${esc(q.question)}</div>
    <textarea class="textarea" name="q_${esc(q.questionId)}" placeholder="在此作答……"></textarea></div>`;
}

async function submitQuiz(quiz) {
  const answers = quiz.questions.map((q) => {
    if (q.type === "shortAnswer") {
      const ta = $(`textarea[name="q_${q.questionId}"]`);
      return { questionId: q.questionId, answer: ta ? ta.value.trim() : "" };
    }
    const checked = $(`input[name="q_${q.questionId}"]:checked`);
    return { questionId: q.questionId, answer: checked ? checked.value : "" };
  });
  const durMin = state.quizStartTime ? Math.max(1, Math.round((Date.now() - state.quizStartTime) / 60000)) : null;
  try {
    const res = await API.submitQuiz(quiz.quizId, answers, durMin);
    renderResult(quiz, res);
  } catch (e) {
    toast("✗ 批改失败：" + (e.message || ""), "error");
  }
}

async function renderResult(quiz, res, opts = {}) {
  const pct = Math.round((res.totalScore / res.maxScore) * 100);
  let correct = 0, wrong = 0, partial = 0;
  res.results.forEach((r) => {
    if (r.type === "shortAnswer") {
      if (r.score >= 1) correct++;
      else if (r.score > 0) partial++;
      else wrong++;
    } else {
      if (r.isCorrect) correct++; else wrong++;
    }
  });
  // 回看历史时用时来自记录本身，而不是当前这次答题的计时
  const dur = opts.durationSec != null
    ? opts.durationSec
    : (state.quizStartTime ? Math.round((Date.now() - state.quizStartTime) / 1000) : 0);
  const durText = dur >= 60 ? `${Math.floor(dur / 60)} 分 ${dur % 60} 秒` : `${dur} 秒`;

  let html = `<div class="result-summary">
    <div class="score-ring" style="--p:${pct}"><span>${pct}</span></div>
    <div class="result-summary__stats">
      <div class="rs"><div class="rs__value">${correct}</div><div class="rs__label">答对</div></div>
      <div class="rs"><div class="rs__value rs--wrong">${wrong}</div><div class="rs__label">答错</div></div>
      ${partial ? `<div class="rs"><div class="rs__value rs--partial">${partial}</div><div class="rs__label">部分正确</div></div>` : ""}
      <div class="rs"><div class="rs__value rs--time">${durText}</div><div class="rs__label">用时</div></div>
    </div>
  </div>`;

  res.results.forEach((r, i) => {
    const q = quiz.questions.find((x) => x.questionId === r.questionId) || {};
    const st = resultStatus(r);
    html += `<div class="result-question">
      <button class="result-question__head" data-result-toggle type="button">
        <span class="rq-badge rq-badge--${st.cls}">${st.label}</span>
        <span class="rq-stem">${i + 1}. ${esc(q.question || "（题目已失效）")}</span>
        <span class="rq-score">${r.score} 分</span>
        <svg class="rq-chevron" viewBox="0 0 10 6" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M1 1l4 4 4-4"/></svg>
      </button>
      <div class="result-question__body" hidden>${renderResultBody(q, r)}</div>
    </div>`;
  });

  const history = await API.getQuizHistory();
  html += renderHistory(history);

  $("#quiz-view").innerHTML = html;
}

function resultStatus(r) {
  if (r.type === "shortAnswer") {
    if (r.score >= 1) return { cls: "ok", label: "正确" };
    if (r.score > 0) return { cls: "partial", label: "部分" };
    return { cls: "wrong", label: "错误" };
  }
  return r.isCorrect ? { cls: "ok", label: "正确" } : { cls: "wrong", label: "错误" };
}

function renderResultBody(q, r) {
  // 后端返回的 options 也可能是字符串/数组，统一转成对象
  const opts = normalizeOptions(
    r.options != null ? r.options : q.options,
    q.type === "judgment" ? JUDGMENT_OPTIONS : null
  );
  if ((q.type === "choice" || q.type === "judgment") && opts) {
    const rows = Object.entries(opts).map(([k, v]) => optionRow(k, v, r, q.type)).join("");
    return `<div class="rq-options">${rows}</div>
      ${r.explanation ? `<div class="answer-key answer-key--review"><span class="label">AI 点评：</span>${esc(r.explanation)}</div>` : ""}`;
  }
  return `<div class="answer-key"><span class="label">你的答案：</span>${esc(r.userAnswer || "（未作答）")}</div>
    <div class="answer-key"><span class="label">参考答案：</span>${esc(r.referenceAnswer || "")}</div>
    <div class="answer-key answer-key--review"><span class="label">AI 点评：</span>${esc(r.explanation || "")}</div>`;
}

function optionRow(k, v, r, type) {
  let cls = "";
  let mark = "";
  let correct = r.correctAnswer;
  let mine = r.userAnswer;
  // 判断题可能存成 true/false，统一到 A/B 再和选项键比
  if (type === "judgment") {
    correct = normJudgment(correct);
    mine = normJudgment(mine);
  }
  if (String(k) === String(correct)) { cls = "is-correct"; mark = "✓"; }
  else if (mine && String(k) === String(mine)) { cls = "is-wrong"; mark = "✗"; }
  return `<div class="option option--result ${cls}"><span><b>${esc(k)}.</b> ${esc(v)}</span><span class="opt-mark">${mark}</span></div>`;
}

function renderHistory(h) {
  const items = h.list
    .map(
      (r) => `<div class="qh-item" data-sid="${esc(r.recordId)}" data-dur="${r.durationSec || 0}" title="点击查看这套题的题目与解析">
        <div class="qh-item__date">${esc(r.date)}</div>
        <div class="qh-item__main">
          <div class="qh-item__mat">${esc(r.material)}</div>
          <div class="qh-item__meta">${r.questionCount} 题 · 得分 ${r.score}/${r.maxScore} · 用时 ${Math.floor((r.durationSec || 0) / 60)}分${(r.durationSec || 0) % 60}秒</div>
        </div>
        <div class="qh-item__acc">${Math.round(r.accuracy * 100)}%</div>
        <div class="qh-item__hint">查看 ›</div>
      </div>`
    )
    .join("");
  return `<div class="panel quiz-history">
    <div class="panel__head"><span>历史测评</span><span class="muted">共 ${h.total} 次 · 点击任意一条可回看题目与解析</span></div>
    <div class="quiz-history__list">${items}</div>
  </div>`;
}

/* 回看某一次历史测评：结果里已带题干，直接拼出一个 quiz 交给 renderResult */
async function openHistoryResult(submissionId, durationSec) {
  try {
    const res = await API.getSubmission(submissionId);
    const quiz = {
      quizId: res.quizId,
      questions: res.results.map((r) => ({
        questionId: r.questionId,
        type: r.type,
        question: r.question,
        options: r.options,
      })),
    };
    await renderResult(quiz, res, { durationSec });
    $("#quiz-view").scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (e) {
    toast("✗ 加载失败：" + ((e && e.message) || ""), "error");
  }
}

/* =========================================================
   进度
   ========================================================= */
async function renderProgress() {
  const o = await API.getProgressOverview();
  const total = o.totalMaterials || 0;
  const masteredPct = total ? Math.round(((o.masteredMaterials || 0) / total) * 100) : 0;
  const stats = [
    { label: "资料总数", value: total, hint: `已掌握 ${o.masteredMaterials || 0} 份` },
    { label: "已掌握", value: o.masteredMaterials || 0, hint: `占比 ${masteredPct}%` },
    { label: "累计答题", value: o.totalQuestionCount || 0, hint: `本周 ${o.weekQuestionCount || 0} 题` },
    { label: "平均正确率", value: Math.round((o.avgAccuracy || 0) * 100) + "%", hint: `累计测验 ${o.totalQuizCount || 0} 次` },
    { label: "连续学习", value: (o.currentStreakDays || 0) + "天", hint: `坚持得越久记得越牢` },
    { label: "薄弱知识点", value: o.weakPointsCount || 0, hint: `需重点复习` },
  ];
  $("#progress-stats").innerHTML = stats
    .map((s) => `<div class="stat"><div class="stat__label">${s.label}</div><div class="stat__value">${s.value}</div><div class="stat__hint">${s.hint}</div></div>`)
    .join("");

  // 按「被考察次数」降序：考得最多的才是重要知识点，排前面
  const kps = (o.knowledgePoints || []).slice().sort((a, b) => (b.questionCount || 0) - (a.questionCount || 0));
  kpState = { all: kps, filter: "all", expanded: false };
  renderKpPanel();

  $("#weak-list").innerHTML = (o.weakPoints || [])
    .map((w) => `<div class="weak-item"><span>⚠ ${esc(w.knowledgePoint)}（错 ${w.errorCount} 次）</span><span>${esc(w.suggestedReview || "建议重新阅读相关资料")}</span></div>`)
    .join("");

  $("#mat-detail-list").innerHTML = o.materials
    .map(
      (m) => `<div class="mat-detail" data-mid="${esc(m.materialId)}">
        <div class="mat-detail__head">
          <div class="file-icon file-icon--${esc(m.fileType)}">${fileTypeLabel(m.fileType)}</div>
          <div class="mat-detail__title">${esc(m.title)}</div>
          <div class="mat-detail__mastery">掌握 ${Math.round(m.mastery * 100)}%</div>
        </div>
        <div class="mat-detail__note">
          <div class="note-clip" data-note-clip>
            <textarea class="textarea note-ta" data-note-ta placeholder="给这份资料记点笔记……（停笔自动保存）" rows="3">${esc(m.note ? m.note.content : "")}</textarea>
          </div>
          <div class="note-clip-ctrl" data-note-ctrl hidden>
            <span class="muted">缩略</span>
            <input type="range" min="20" max="100" value="100" data-note-slider />
            <span class="note-clip-val" data-note-val>100%</span>
          </div>
          <div class="note-saved" data-note-saved>已自动保存</div>
        </div>
      </div>`
    )
    .join("");

  bindMaterialNotes();

  const t = await API.getTrends();
  const pts = t.points || [];
  const max = pts.length ? Math.max(...pts.map((p) => p.value || 0)) : 0;
  $("#trend-bars").innerHTML = pts.length
    ? pts
        .map((p) => {
          const v = p.value || 0;
          const h = max > 0 ? Math.max(4, (v / max) * 100) : 4;
          return `<div class="trend-bar"><div class="trend-bar__val">${Math.round(v * 100)}%</div><div class="trend-bar__col" style="height:${h}%"></div><div class="trend-bar__label">${esc(p.label)}</div></div>`;
        })
        .join("")
    : '<div class="muted">暂无趋势数据</div>';
}

/* ---------- 知识点掌握：筛选 / 折叠 / 雷达只画 TOP N ---------- */
const KP_RADAR_MAX = 8; // 雷达轴数上限：再多标签就会互相压住，图就没有信息量了
const KP_PAGE = 12; // 列表默认显示条数
let kpState = { all: [], filter: "all", expanded: false };

function renderKpPanel() {
  const all = kpState.all;
  const counts = { all: all.length, 熟练: 0, 掌握: 0, 薄弱: 0 };
  all.forEach((k) => {
    if (counts[k.level] != null) counts[k.level] += 1;
  });

  const sum = $("#kp-summary");
  if (sum) {
    sum.textContent = all.length
      ? `共 ${all.length} 个 · 熟练 ${counts.熟练} · 掌握 ${counts.掌握} · 薄弱 ${counts.薄弱}`
      : "";
  }

  const tabs = [["all", "全部"], ["薄弱", "薄弱"], ["掌握", "掌握"], ["熟练", "熟练"]];
  $("#kp-tabs").innerHTML = tabs
    .map(([key, label]) => {
      const n = key === "all" ? counts.all : counts[key];
      const on = kpState.filter === key ? " is-on" : "";
      return `<button type="button" class="kp-tab${on}" data-kp-tab="${key}"${n === 0 ? " disabled" : ""}>${label}<span class="kp-tab__n">${n}</span></button>`;
    })
    .join("");

  // 雷达只画被考察最多的前 N 个，其余交给列表
  const radarPts = all.slice(0, KP_RADAR_MAX);
  const radarBox = $("#kp-radar");
  if (!radarPts.length) {
    radarBox.innerHTML = '<div class="muted">还没有知识点数据，先去做一次测评吧</div>';
  } else {
    const rest = all.length - radarPts.length;
    radarBox.innerHTML =
      renderRadar(radarPts) +
      (rest > 0 ? `<div class="kp-radar__note muted">按答题量取前 ${radarPts.length} 个（另有 ${rest} 个见右侧）</div>` : "");
  }

  const list = kpState.filter === "all" ? all : all.filter((k) => k.level === kpState.filter);
  const shown = kpState.expanded ? list : list.slice(0, KP_PAGE);
  const listBox = $("#kp-list");
  if (!list.length) {
    listBox.innerHTML = '<div class="muted">这一类暂时没有知识点</div>';
  } else {
    listBox.innerHTML =
      shown
        .map(
          (kp) => `<div class="kp-item">
        <div class="kp-item__top"><span class="kp-item__name">${esc(kp.name)}</span><span class="kp-level kp-level--${levelCls(kp.level)}">${esc(kp.level)}</span></div>
        <div class="progress"><div class="progress__bar" style="width:${Math.round((kp.mastery || 0) * 100)}%"></div></div>
        <div class="kp-item__meta">答 ${kp.questionCount || 0} 题 · 掌握度 ${Math.round((kp.mastery || 0) * 100)}%</div>
      </div>`
        )
        .join("") +
      (list.length > KP_PAGE
        ? `<button type="button" class="kp-more" data-kp-more>${kpState.expanded ? "收起" : `查看全部 ${list.length} 个`}</button>`
        : "");
  }

  bindKpControls();
}

function bindKpControls() {
  $$("[data-kp-tab]").forEach((btn) => {
    btn.addEventListener("click", () => {
      kpState.filter = btn.dataset.kpTab;
      kpState.expanded = false;
      renderKpPanel();
    });
  });
  const more = $("[data-kp-more]");
  if (more) {
    more.addEventListener("click", () => {
      kpState.expanded = !kpState.expanded;
      renderKpPanel();
    });
  }
}

function ellipsis(s, n) {
  return String(s).length > n ? String(s).slice(0, n) + "…" : String(s);
}

function levelCls(level) {
  return { 熟练: "top", 掌握: "mid", 薄弱: "low", 未学: "none" }[level] || "mid";
}

function bindMaterialNotes() {
  $$("#mat-detail-list .mat-detail").forEach((card) => {
    const mid = card.dataset.mid;
    const ta = $("[data-note-ta]", card);
    const saved = $("[data-note-saved]", card);
    const clip = $("[data-note-clip]", card);
    const ctrl = $("[data-note-ctrl]", card);
    const slider = $("[data-note-slider]", card);
    const val = $("[data-note-val]", card);

    const full = ta.scrollHeight;
    if (ta.value.trim().length > 120 && full > 110) {
      ctrl.hidden = false;
      clip.style.maxHeight = "110px";
      slider.value = Math.max(20, Math.round((110 / full) * 100));
      val.textContent = slider.value + "%";
    }
    slider.addEventListener("input", () => {
      const pct = Number(slider.value);
      clip.style.maxHeight = pct >= 100 ? "none" : Math.round((full * pct) / 100) + "px";
      val.textContent = pct + "%";
    });

    ta.addEventListener("input", () => {
      clearTimeout(ta._timer);
      ta._timer = setTimeout(async () => {
        await API.saveNote(mid, ta.value);
        saved.classList.add("show");
        setTimeout(() => saved.classList.remove("show"), 1500);
      }, 700);
    });
  });
}

function renderRadar(points) {
  // size 比 R 大不少，是给外圈的轴标签留位置；否则长名字会被画布裁掉
  const size = 380, cx = size / 2, cy = size / 2, R = 100, LABEL_GAP = 22;
  const n = points.length;
  const angle = (i) => -Math.PI / 2 + (i * 2 * Math.PI) / n;
  const pt = (i, r) => [cx + r * Math.cos(angle(i)), cy + r * Math.sin(angle(i))];
  let rings = "";
  for (let ring = 1; ring <= 4; ring++) {
    const r = (R * ring) / 4;
    const coords = points.map((_, i) => pt(i, r).map((v) => v.toFixed(1)).join(",")).join(" ");
    rings += `<polygon points="${coords}" class="radar-ring" />`;
  }
  let axes = "";
  points.forEach((p, i) => {
    const [x, y] = pt(i, R);
    axes += `<line x1="${cx}" y1="${cy}" x2="${x.toFixed(1)}" y2="${y.toFixed(1)}" class="radar-axis" />`;
    const [lx, ly] = pt(i, R + LABEL_GAP);
    const anchor = Math.abs(lx - cx) < 5 ? "middle" : lx > cx ? "start" : "end";
    axes += `<text x="${lx.toFixed(1)}" y="${(ly + 3).toFixed(1)}" text-anchor="${anchor}" class="radar-label"><title>${esc(p.name)}</title>${esc(ellipsis(p.name, 6))}</text>`;
    axes += `<text x="${lx.toFixed(1)}" y="${(ly + 16).toFixed(1)}" text-anchor="${anchor}" class="radar-label radar-label--val">${Math.round(p.mastery * 100)}%</text>`;
  });
  const dataCoords = points.map((p, i) => pt(i, R * p.mastery).map((v) => v.toFixed(1)).join(",")).join(" ");
  const dots = points
    .map((p, i) => { const [x, y] = pt(i, R * p.mastery); return `<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="3" class="radar-dot" />`; })
    .join("");
  return `<svg viewBox="0 0 ${size} ${size}" class="radar" role="img" aria-label="知识点掌握雷达图">${rings}${axes}<polygon points="${dataCoords}" class="radar-area" />${dots}</svg>`;
}

/* =========================================================
   报告
   ========================================================= */
async function renderReport() {
  setReportRange("week");
  let latest = null;
  try { latest = await API.getLatestReport(); } catch (e) {}
  $("#report-view").innerHTML = latest ? renderReportCard(latest) : emptyState("还没有周报", "选择周期后点击「生成周报」");
  await loadReportHistory();
}

function setReportRange(mode) {
  state.reportRange = mode;
  $$("#report-seg .segmented__btn").forEach((b) => b.classList.toggle("is-active", b.dataset.range === mode));
  $("#report-dates").hidden = mode !== "custom";
  if (mode === "custom") {
    const end = new Date();
    end.setDate(end.getDate() - 1);
    const start = new Date(end);
    start.setDate(start.getDate() - 6);
    $("#report-end").value = end.toISOString().slice(0, 10);
    $("#report-start").value = start.toISOString().slice(0, 10);
  }
}

async function generateReport() {
  const btn = $("#btn-gen-report");
  btn.disabled = true;
  $("#report-view").innerHTML = '<div class="empty"><div class="loading-dots">正在生成周报</div></div>';
  const body = {};
  if (state.reportRange === "custom") {
    const s = $("#report-start").value;
    const e = $("#report-end").value;
    if (s && e) body.weekStart = s, body.weekEnd = e;
  }
  try {
    const r = await API.generateReport(body);
    state.currentReport = r;
    $("#report-view").innerHTML = renderReportCard(r);
    toast("周报已生成");
    await loadReportHistory();
  } catch (e) {
    $("#report-view").innerHTML = emptyState("周报生成失败", e.message || "请稍后重试");
    toast("✗ 周报生成失败：" + (e.message || ""), "error");
  } finally {
    btn.disabled = false;
  }
}

function renderReportCard(r) {
  const s = r.sections || {};
  const qc = s.questionCount || {};
  const at = s.accuracyTrend || {};
  const mc = s.materialCoverage || {};
  // 后端某些周期可能算不出环比，这里兜底成 0，避免出现 NaN%
  const qPct = Number(qc.changePercent) || 0;
  const accPct = Number(at.changePercent) || 0;
  const qUp = qPct >= 0;
  const accUp = accPct >= 0;
  const wp = (s.weakPoints || [])
    .map((w) => `<div class="weak-item"><span>⚠ ${esc(w.knowledgePoint)}（错 ${w.errorCount} 次）</span><span>${esc(w.suggestedReview || "建议重新阅读相关资料")}</span></div>`)
    .join("");
  const plan = (s.nextWeekPlan || []).map((p) => `<li>${esc(p)}</li>`).join("");
  return `<div class="report-card">
    <div class="report-card__hero">
      <div>
        <h2>📊 学习周报</h2>
        <div class="period">${esc(r.weekStart)} ~ ${esc(r.weekEnd)}</div>
      </div>
      <div class="report-download">
        <button class="btn btn--ghost btn--sm" id="btn-download-report" type="button" aria-haspopup="true" aria-expanded="false">
          <svg class="btn__icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 3v12m0 0l-4-4m4 4l4-4M5 21h14"/></svg>
          <span>下载</span>
          <svg class="dd-chevron" viewBox="0 0 12 8" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M1 1.5L6 6.5l5-5"/></svg>
        </button>
        <div class="dd-menu dd-menu--right" id="report-format-menu" hidden>
          <div class="dd-option" role="button" data-fmt="md"><span>Markdown（.md）</span></div>
          <div class="dd-option" role="button" data-fmt="docx"><span>Word（.docx）</span></div>
          <div class="dd-option" role="button" data-fmt="pdf"><span>PDF（.pdf）</span></div>
        </div>
      </div>
    </div>
    <div class="report-section">
      <div class="report-section__title">✍️ 做题量</div>
      <div>本周共答 <b>${qc.thisWeek || 0}</b> 题（上周 ${qc.lastWeek || 0} 题），较上周 ${qUp ? "↑" : "↓"} ${Math.round(Math.abs(qPct) * 100)}%</div>
    </div>
    <div class="report-section">
      <div class="report-section__title">📚 资料覆盖</div>
      <div>新增资料 <b>${mc.newMaterials || 0}</b> 份，覆盖 <b>${mc.coveredChunks || 0}</b> 个知识块（覆盖率 ${Math.round((Number(mc.coverageRate) || 0) * 100)}%）</div>
    </div>
    <div class="report-section">
      <div class="report-section__title">🎯 正确率趋势</div>
      <div>本周 ${Math.round((Number(at.thisWeek) || 0) * 100)}%，上周 ${Math.round((Number(at.lastWeek) || 0) * 100)}%，<b class="t-primary">${accUp ? "↑" : "↓"} ${Math.round(Math.abs(accPct) * 100)}%</b></div>
    </div>
    <div class="report-section">
      <div class="report-section__title">🔥 薄弱知识点 TOP${(s.weakPoints || []).length}</div>
      ${wp}
    </div>
    <div class="report-section">
      <div class="report-section__title">📌 下周计划</div>
      <ul class="report-list">${plan}</ul>
    </div>
    <div class="report-section">
      <div class="report-section__title">💡 一句话</div>
      <div class="motivation">${esc(s.motivation)}</div>
    </div>
  </div>`;
}

/* 本地兜底生成的 Markdown（后端不可用时才用） */
function localMarkdown(r) {
  const s = r.sections || {};
  const qc = s.questionCount || {};
  const at = s.accuracyTrend || {};
  const mc = s.materialCoverage || {};
  const qPct = Number(qc.changePercent) || 0;
  const accPct = Number(at.changePercent) || 0;
  const L = [];
  L.push(`# 学习周报（${r.weekStart} ~ ${r.weekEnd}）`, "");
  L.push("## ✍️ 做题量");
  L.push(`本周共答 ${qc.thisWeek || 0} 题，较上周${qPct >= 0 ? "上升" : "下降"} ${Math.round(Math.abs(qPct) * 100)}%（上周 ${qc.lastWeek || 0} 题）。`, "");
  L.push("## 📚 资料覆盖");
  L.push(`新增资料 ${mc.newMaterials || 0} 份，覆盖 ${mc.coveredChunks || 0} 个知识块（覆盖率 ${Math.round((Number(mc.coverageRate) || 0) * 100)}%）。`, "");
  L.push("## 🎯 正确率趋势");
  L.push(`本周 ${Math.round((Number(at.thisWeek) || 0) * 100)}%，上周 ${Math.round((Number(at.lastWeek) || 0) * 100)}%，${accPct >= 0 ? "上升" : "下降"} ${Math.round(Math.abs(accPct) * 100)}%。`, "");
  L.push("## 🔥 薄弱知识点 TOP" + (s.weakPoints || []).length);
  (s.weakPoints || []).forEach((w, i) => L.push(`${i + 1}. **${w.knowledgePoint}**（错 ${w.errorCount} 次）—— 建议：${w.suggestedReview || "重新阅读相关资料"}`));
  L.push("");
  L.push("## 📌 下周计划");
  (s.nextWeekPlan || []).forEach((p) => L.push(`- ${p}`));
  L.push("", "## 💡 一句话", `> ${s.motivation || ""}`, "");
  const md = L.join("\n");
  const blob = new Blob([md], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `学习周报_${r.weekStart}_${r.weekEnd}.md`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

/* 下载周报：优先走后端（md / docx / pdf 共用同一份结构），失败时用本地 Markdown 兜底 */
async function downloadReport(r, fmt) {
  const format = fmt || "md";
  if (!r || !r.reportId) {
    toast("周报还没生成，无法下载");
    return;
  }
  try {
    await API.downloadReportFile(r.reportId, format);
    toast("已下载周报");
  } catch (e) {
    if (format !== "md") {
      toast("下载失败：" + (e && e.message ? e.message : e));
      return;
    }
    // md 降级为前端本地生成，后端挂了也能导出
    localMarkdown(r);
    toast("后端不可用，已用本地 Markdown 导出");
  }
}

async function loadReportHistory() {
  const h = await API.getReportHistory();
  $("#report-history-count").textContent = `共 ${h.total} 期`;
  if (!h.list.length) {
    $("#report-history-list").innerHTML = '<div class="muted" style="padding:16px">暂无历史周报</div>';
    return;
  }
  $("#report-history-list").innerHTML = h.list
    .map(
      (r) => `<button class="rh-item" data-rid="${esc(r.reportId)}" type="button">
        <div class="rh-item__date">${esc(r.weekStart)} ~ ${esc(r.weekEnd)}</div>
        <div class="rh-item__meta">${Math.round(r.accuracy * 100)}% 正确率 · ${r.weakPointCount} 个薄弱点</div>
        <div class="rh-item__acc">查看 ›</div>
      </button>`
    )
    .join("");
}

/* =========================================================
   资料笔记（C-07，归属资料库弹窗）
   ========================================================= */
async function openNote(materialId) {
  state.currentMaterialId = materialId;
  const data = await API.listMaterials();
  const m = (data.list || []).find((x) => x.materialId === materialId);
  $("#note-modal-title").textContent = "笔记 · " + (m ? m.title : "");
  const note = await API.getNote(materialId);
  const ta = $("#note-input");
  ta.value = note.content || "";
  $("#note-modal").hidden = false;
  clearTimeout(state.noteTimer);
  ta.oninput = () => {
    clearTimeout(state.noteTimer);
    state.noteTimer = setTimeout(() => saveNote(ta.value), 700); // 停笔 700ms 自动保存
  };
}
function closeNote() {
  $("#note-modal").hidden = true;
}
async function saveNote(content) {
  if (!state.currentMaterialId) return;
  await API.saveNote(state.currentMaterialId, content);
  const saved = $("#note-saved");
  if (saved) { saved.classList.add("show"); setTimeout(() => saved.classList.remove("show"), 1500); }
}

/* ---------- 空状态 ---------- */
function emptyState(title, sub) {
  return `<div class="empty"><div class="empty__icon">
    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8zM14 2v6h6"/></svg>
  </div><div style="font-weight:600">${esc(title)}</div><div class="muted" style="margin-top:4px">${esc(sub)}</div></div>`;
}

/* 请求失败时的错误态。
   关键：这里绝不能回落成 emptyState「还没有资料」。曾经接口被跨域拦掉时，
   列表渲染成空状态，用户读到的信息是「我的资料没了」——实际数据一个没丢，
   只是前端拿不到。学习产品里把「连不上后端」伪装成「数据丢失」最伤信任。 */
function errorState(what, e) {
  const msg = (e && e.message) || "";
  const isConn = /failed to fetch|networkerror|load failed|econnrefused|timeout/i.test(msg);
  const detail = isConn
    ? `后端没响应。请确认：<br>
       ① 后端正在运行（浏览器打开 <code>http://127.0.0.1:5000/api/materials</code> 应有 JSON）<br>
       ② 本页用 <code>http://127.0.0.1:8123</code> 打开，不要双击 index.html`
    : esc(msg);
  return `<div class="empty empty--error"><div class="empty__icon">
    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0zM12 9v4M12 17h.01"/></svg>
  </div><div style="font-weight:600">${esc(what)}</div>
  <div class="muted empty__fix">${detail}</div></div>`;
}

/* =========================================================
   自定义下拉组件
   ========================================================= */
function setupDropdowns() {
  $$(".dd-trigger").forEach((trigger) => {
    const wrap = trigger.closest(".select-wrap");
    const menu = $(".dd-menu", wrap);
    const source = $(".dd-source", wrap);
    if (!menu || !source) return;

    trigger.addEventListener("click", (e) => {
      e.stopPropagation();
      const isOpen = !menu.hidden;
      closeAllDropdowns();
      if (isOpen) return;
      menu.innerHTML = Array.from(source.options)
        .map((opt) => {
          const selected = opt.value === source.value;
          return `<div class="dd-option" role="option" data-value="${esc(opt.value)}" aria-selected="${selected}">
            <span>${esc(opt.text)}</span>
            <svg class="dd-check" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6L9 17l-5-5"/></svg>
          </div>`;
        })
        .join("");
      menu.hidden = false;
      trigger.setAttribute("aria-expanded", "true");
    });

    menu.addEventListener("click", (e) => {
      const opt = e.target.closest(".dd-option");
      if (!opt) return;
      source.value = opt.dataset.value;
      $(".dd-value", trigger).textContent = opt.querySelector("span").textContent;
      closeAllDropdowns();
    });
  });

  document.addEventListener("click", closeAllDropdowns);
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeAllDropdowns(); });
}

function closeAllDropdowns() {
  $$(".dd-menu").forEach((m) => (m.hidden = true));
  $$(".dd-trigger").forEach((t) => t.setAttribute("aria-expanded", "false"));
}

/* =========================================================
   启动
   ========================================================= */
window.addEventListener("hashchange", router);
window.addEventListener("DOMContentLoaded", () => {
  setupDropdowns();
  bindUpload();
  $("#btn-upload").addEventListener("click", () => $("#file-input").click());
  $("#btn-new-chat").addEventListener("click", newChat);
  $("#btn-del-chat").addEventListener("click", deleteCurrentSession);
  // 历史对话侧栏：点条目切过去，点 × 删除
  $("#chat-session-list").addEventListener("click", async (e) => {
    const delBtn = e.target.closest(".ses-item__del");
    if (delBtn) {
      e.stopPropagation();
      if (state.chat.thinking) return;
      if (!confirm("删除这条对话？删除后无法恢复。")) return;
      const id = delBtn.dataset.sid;
      try {
        await API.deleteSession(id);
        toast("✓ 已删除该对话", "success");
      } catch (err) {
        toast("✗ 删除失败：" + ((err && err.message) || ""), "error");
        return;
      }
      if (state.chat.sessionId === id) {
        state.chat.sessionId = null;
        $("#btn-del-chat").hidden = true;
        showChatEmpty();
      }
      await renderSessionList();
      return;
    }
    const item = e.target.closest(".ses-item");
    if (!item || !item.dataset.sid) return;
    if (item.dataset.sid === state.chat.sessionId) return; // 已经在看这条
    await openSession(item.dataset.sid);
  });
  $("#btn-send").addEventListener("click", sendMessage);
  $("#chat-input").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendMessage(); }
  });
  $("#chat-input").addEventListener("input", (e) => autoGrow(e.target));
  // 来源引用展开/收起（事件委托，气泡动态生成也生效）
  $("#chat-messages").addEventListener("click", (e) => {
    const toggle = e.target.closest("[data-sources-toggle]");
    if (!toggle) return;
    const panel = toggle.parentElement.querySelector(".src-panel");
    if (panel) { panel.hidden = !panel.hidden; toggle.classList.toggle("is-open"); }
  });
  // 资料笔记弹窗
  $$("[data-note-close]").forEach((el) => el.addEventListener("click", closeNote));
  $("#btn-generate").addEventListener("click", generateQuiz);
  $("#btn-gen-report").addEventListener("click", generateReport);
  // 报告：本周 / 自定义日期范围 切换
  $("#report-seg").addEventListener("click", (e) => {
    const b = e.target.closest(".segmented__btn");
    if (b) setReportRange(b.dataset.range);
  });
  // 报告：历史周报点击查看
  $("#report-history-list").addEventListener("click", async (e) => {
    const item = e.target.closest(".rh-item");
    if (!item) return;
    const r = await API.getReport(item.dataset.rid);
    state.currentReport = r;
    $("#report-view").innerHTML = renderReportCard(r);
    $("#report-view").scrollIntoView({ behavior: "smooth", block: "start" });
  });
  // 报告：下载当前周报（点按钮展开格式菜单，点菜单项才真正下载）
  $("#report-view").addEventListener("click", (e) => {
    const trigger = e.target.closest("#btn-download-report");
    if (trigger) {
      e.stopPropagation();
      if (!state.currentReport) {
        toast("周报还没生成，无法下载");
        return;
      }
      const menu = $("#report-format-menu");
      if (!menu) return;
      const open = menu.hidden;
      closeAllDropdowns();
      menu.hidden = !open;
      trigger.setAttribute("aria-expanded", String(open));
      return;
    }
    const opt = e.target.closest("#report-format-menu .dd-option");
    if (opt && state.currentReport) {
      closeAllDropdowns();
      downloadReport(state.currentReport, opt.dataset.fmt);
    }
  });
  // 测评结果：点击每题展开/收起答案与点评
  $("#quiz-view").addEventListener("click", (e) => {
    // 历史测评：点条目回看那套题
    const hist = e.target.closest(".qh-item");
    if (hist && hist.dataset.sid) {
      openHistoryResult(hist.dataset.sid, Number(hist.dataset.dur) || 0);
      return;
    }
    const toggle = e.target.closest("[data-result-toggle]");
    if (!toggle) return;
    const body = toggle.parentElement.querySelector(".result-question__body");
    if (body) { body.hidden = !body.hidden; toggle.classList.toggle("is-open"); }
  });
  router();
});
