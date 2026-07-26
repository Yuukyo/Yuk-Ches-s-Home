(() => {
  "use strict";

  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
  const escapeHtml = (value = "") => String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");

  const state = {
    config: {},
    messages: [],
    items: [],
    graves: [],
    rewards: {},
    queue: [],
    attachments: [],
    reply: null,
    selectedMessage: null,
    recordKind: "",
    ledgerTab: "ledger",
    galleryTab: "favorites",
    books: [],
    currentBook: null,
    currentChunk: null,
    currentReadingText: "",
    dialogSubmit: null,
  };

  async function api(path, options = {}) {
    const response = await fetch(path, {
      credentials: "same-origin",
      ...options,
      headers: {
        ...(options.body instanceof FormData ? {} : { "Content-Type": "application/json" }),
        ...(options.headers || {}),
      },
    });
    const type = response.headers.get("content-type") || "";
    let body;
    if (type.includes("application/json")) body = await response.json();
    else body = await response.text();
    if (!response.ok) {
      const message = body && typeof body === "object" ? body.error : body;
      const error = new Error(message || `请求失败（${response.status}）`);
      error.status = response.status;
      throw error;
    }
    return body;
  }

  function toast(message, type = "") {
    const item = document.createElement("div");
    item.className = `toast ${type}`.trim();
    item.textContent = message;
    $("#toast-region").append(item);
    window.setTimeout(() => item.remove(), 3800);
  }

  function setBusy(button, busy, text = "处理中…") {
    if (!button) return;
    if (busy) {
      button.dataset.original = button.textContent;
      button.textContent = text;
      button.disabled = true;
    } else {
      button.textContent = button.dataset.original || button.textContent;
      button.disabled = false;
    }
  }

  function localDate(value) {
    if (!value) return "";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return "";
    return new Intl.DateTimeFormat("zh-CN", {
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    }).format(date);
  }

  function numeric(value) {
    const number = Number(value || 0);
    return Number.isFinite(number) ? number : 0;
  }

  function activeItems(kind = "") {
    return state.items.filter((item) =>
      item.status !== "archived" && (!kind || item.kind === kind));
  }

  async function boot() {
    updateClock();
    window.setInterval(updateClock, 1000);
    bindGlobalEvents();
    try {
      const auth = await api("/api/auth/status");
      if (!auth.authenticated) {
        $("#auth-overlay").classList.remove("hidden");
        $("#auth-overlay").setAttribute("aria-hidden", "false");
        return;
      }
      await loadHome();
    } catch (error) {
      toast(error.message, "error");
    }
  }

  async function loadHome() {
    const data = await api("/api/bootstrap");
    state.config = data.config || {};
    state.messages = data.messages || [];
    state.items = data.items || [];
    state.graves = data.graves || [];
    state.rewards = data.rewards || {};
    applyConfig();
    renderAll();
    loadWeather();
    loadQuote();
    loadIntegrations();
    pollEvents();
  }

  function applyConfig() {
    const config = state.config;
    $("#chat-ai-name").textContent = config.ai_name || "AI";
    $("#setting-user-name").value = config.user_name || "";
    $("#setting-ai-name").value = config.ai_name || "";
    const profile = config.profile || {};
    $("#setting-character-prompt").value = profile.character_prompt || "";
    $("#setting-relationship").value = profile.relationship || "";
    $("#setting-worldbook").value = profile.worldbook || "";
    $("#setting-proactive").checked = Boolean(profile.proactive_enabled);
    updateClock();
  }

  function updateClock() {
    const now = new Date();
    $("#clock").textContent = `${String(now.getHours()).padStart(2, "0")}:${String(now.getMinutes()).padStart(2, "0")}`;
    const start = new Date(`${state.config.start_date || "2024-09-01"}T00:00:00`);
    const days = Math.max(0, Math.floor((now - start) / 86400000));
    $("#days-label").textContent = `Since ${formatStartDate(start)} · 我们已经一起走过了 ${days} 天`;
  }

  function formatStartDate(date) {
    if (Number.isNaN(date.getTime())) return "2024.9.1";
    return `${date.getFullYear()}.${date.getMonth() + 1}.${date.getDate()}`;
  }

  async function loadWeather() {
    try {
      const weather = await api("/api/weather");
      const temperature = weather.temperature == null ? "" : ` ${Math.round(weather.temperature)}°C`;
      $("#weather-label").textContent = `${weather.location || ""} · ${weather.condition || "窗外安静"}${temperature}`;
    } catch {
      $("#weather-label").textContent = "窗外安静，家里有光";
    }
  }

  async function loadQuote() {
    try {
      const quote = await api("/api/daily-quote");
      $("#daily-quote").textContent = `“${quote.content}”`;
    } catch {
      // Keep the built-in quote.
    }
  }

  function enterHome() {
    const splash = $("#splash-screen");
    splash.classList.add("leaving");
    $("#home-shell").classList.remove("hidden");
    window.setTimeout(() => splash.classList.add("hidden"), 760);
    scrollMessages();
  }

  function showScreen(id) {
    $$(".screen").forEach((screen) => screen.classList.toggle("active", screen.id === id));
    $$(".nav-link").forEach((button) => button.classList.toggle("active", button.dataset.screen === id));
    closeDrawer();
    closeSheets();
    if (id === "records-screen") renderTimeline();
    if (id === "ledger-screen") renderLedger();
    if (id === "rewards-screen") renderRewards();
    if (id === "gallery-screen") renderGallery();
    if (id === "blackroom-screen") renderBlackroom();
    if (id === "reading-screen") loadBooks();
  }

  function openDrawer() {
    $("#drawer").classList.add("open");
    $("#drawer-scrim").classList.remove("hidden");
  }

  function closeDrawer() {
    $("#drawer").classList.remove("open");
    $("#drawer-scrim").classList.add("hidden");
  }

  function openSheet(id) {
    closeSheets();
    const sheet = $(id);
    sheet.classList.remove("hidden");
    sheet.setAttribute("aria-hidden", "false");
  }

  function closeSheets() {
    $$(".sheet").forEach((sheet) => {
      sheet.classList.add("hidden");
      sheet.setAttribute("aria-hidden", "true");
    });
  }

  function renderAll() {
    renderMessages();
    renderQueue();
    renderTimeline();
    renderLedger();
    renderRewards();
    renderGallery();
    renderBlackroom();
  }

  function renderMessages() {
    const list = $("#message-list");
    list.textContent = "";
    if (!state.messages.length) {
      const empty = document.createElement("div");
      empty.className = "empty-state";
      empty.innerHTML = "<span>⌂</span><h2>家已经准备好了</h2><p>第一句话，会成为新家里最早的一页。</p>";
      list.append(empty);
      return;
    }
    state.messages.forEach((message) => {
      const row = document.createElement("div");
      const role = message.role === "assistant" ? "assistant" :
        message.role === "user" ? "user" : "system";
      row.className = `message-row ${role}`;
      row.dataset.messageId = message.id;
      const bubble = document.createElement("div");
      bubble.className = "bubble";
      const metadata = message.metadata || {};
      if (metadata.quote) {
        const quote = document.createElement("div");
        quote.className = "quote";
        quote.textContent = metadata.quote;
        bubble.append(quote);
      }
      const content = document.createElement("div");
      content.textContent = message.content;
      bubble.append(content);
      if (role !== "system") {
        const meta = document.createElement("div");
        meta.className = "bubble-meta";
        const favorites = metadata.favorite_by || [];
        if (favorites.length) {
          const mark = document.createElement("span");
          mark.className = "favorite-mark";
          mark.textContent = favorites.includes("ai") ? "♥ AI 收藏" : "♥";
          meta.append(mark);
        }
        const time = document.createElement("time");
        time.textContent = localDate(message.created_at);
        meta.append(time);
        bubble.append(meta);
        bindLongPress(row, () => {
          state.selectedMessage = message;
          updateMessageMenu(message);
          openSheet("#message-menu");
        });
      }
      row.append(bubble);
      list.append(row);
    });
  }

  function bindLongPress(element, callback, delay = 520) {
    let timer = null;
    let moved = false;
    const clear = () => {
      window.clearTimeout(timer);
      timer = null;
    };
    element.addEventListener("pointerdown", () => {
      moved = false;
      timer = window.setTimeout(() => {
        if (!moved) callback();
      }, delay);
    });
    element.addEventListener("pointermove", () => { moved = true; clear(); });
    element.addEventListener("pointerup", clear);
    element.addEventListener("pointercancel", clear);
    element.addEventListener("contextmenu", (event) => {
      event.preventDefault();
      callback();
    });
  }

  function updateMessageMenu(message) {
    const reroll = $('[data-message-action="reroll"]');
    reroll.style.display = message.role === "assistant" ? "" : "none";
  }

  function scrollMessages() {
    window.requestAnimationFrame(() => {
      const list = $("#message-list");
      list.scrollTop = list.scrollHeight;
    });
  }

  function renderQueue() {
    const queue = $("#queued-list");
    queue.textContent = "";
    state.queue.forEach((text, index) => {
      const chip = document.createElement("span");
      chip.className = "queued-chip";
      chip.innerHTML = `<span>${escapeHtml(text)}</span><button aria-label="移除">×</button>`;
      $("button", chip).addEventListener("click", () => {
        state.queue.splice(index, 1);
        renderQueue();
      });
      queue.append(chip);
    });
    queue.classList.toggle("hidden", state.queue.length === 0);
    renderAttachments();
  }

  function renderAttachments() {
    const box = $("#attachment-preview");
    box.textContent = "";
    state.attachments.forEach((item, index) => {
      const chip = document.createElement("span");
      chip.className = "attachment-chip";
      chip.innerHTML = `<span>⇧ ${escapeHtml(item.title)}</span><button aria-label="移除">×</button>`;
      $("button", chip).addEventListener("click", () => {
        state.attachments.splice(index, 1);
        renderAttachments();
      });
      box.append(chip);
    });
    box.classList.toggle("hidden", state.attachments.length === 0);
  }

  function queueCurrentMessage() {
    const input = $("#message-input");
    const text = input.value.trim();
    if (!text) return toast("先写一句话");
    if (state.queue.length >= 9) return toast("一次最多连续发送 10 条", "error");
    state.queue.push(text);
    input.value = "";
    resizeComposer();
    renderQueue();
  }

  async function sendMessages(innerThought = "") {
    const input = $("#message-input");
    const current = input.value.trim();
    const messages = [...state.queue, ...(current ? [current] : [])];
    if (!messages.length && !state.attachments.length) return;
    if (!messages.length) messages.push("看看我发来的附件。");
    const button = $("#send-button");
    setBusy(button, true, "…");
    const optimistic = messages.map((content, index) => ({
      id: `pending-${Date.now()}-${index}`,
      role: "user",
      content,
      metadata: {
        quote: index === 0 ? state.reply?.content : "",
        inner_thought: index === messages.length - 1 ? innerThought : "",
      },
      created_at: new Date().toISOString(),
    }));
    state.messages.push(...optimistic);
    state.queue = [];
    input.value = "";
    renderQueue();
    renderMessages();
    scrollMessages();
    try {
      const result = await api("/api/chat", {
        method: "POST",
        body: JSON.stringify({
          messages,
          inner_thought: innerThought,
          quote: state.reply?.content || "",
          attachment_ids: state.attachments.map((item) => item.id),
          reading_context: state.currentReadingText || "",
        }),
      });
      const pendingIds = new Set(optimistic.map((item) => item.id));
      state.messages = state.messages.filter((item) => !pendingIds.has(item.id));
      state.messages.push(...(result.user_messages || []), result.message);
      state.attachments = [];
      clearReply();
      renderMessages();
      renderAttachments();
      scrollMessages();
      if (result.memory_warning) toast(`记忆暂未同步：${result.memory_warning}`);
    } catch (error) {
      const pendingIds = new Set(optimistic.map((item) => item.id));
      state.messages = state.messages.filter((item) => !pendingIds.has(item.id));
      renderMessages();
      toast(error.message, "error");
    } finally {
      setBusy(button, false);
    }
  }

  function setReply(message) {
    state.reply = message;
    $("#reply-preview-text").textContent = message.content;
    $("#reply-preview").classList.remove("hidden");
    $("#message-input").focus();
  }

  function clearReply() {
    state.reply = null;
    $("#reply-preview").classList.add("hidden");
  }

  async function runMessageAction(action) {
    const message = state.selectedMessage;
    if (!message) return;
    closeSheets();
    if (action === "quote") return setReply(message);
    if (action === "forward") return shareMessage(message);
    if (action === "edit") {
      return openDialog({
        kicker: "EDIT",
        title: "编辑消息",
        fields: [{ name: "content", label: "内容", type: "textarea", value: message.content, required: true }],
        submit: async (values) => {
          const updated = await api(`/api/messages/${message.id}`, {
            method: "PATCH",
            body: JSON.stringify({ content: values.content }),
          });
          replaceMessage(updated);
          toast("消息已编辑");
        },
      });
    }
    if (action === "favorite") {
      try {
        const updated = await api(`/api/messages/${message.id}`, {
          method: "PATCH",
          body: JSON.stringify({ favorite_by: "user" }),
        });
        replaceMessage(updated);
        renderGallery();
        toast("收藏状态已更新");
      } catch (error) { toast(error.message, "error"); }
      return;
    }
    if (action === "delete") {
      return openDialog({
        kicker: "GRAVEYARD",
        title: "把这句话放进坟场？",
        fields: [{ name: "reason", label: "删除原因（可选）", type: "textarea", value: "" }],
        danger: true,
        submit: async (values) => {
          const removed = await api(`/api/messages/${message.id}`, {
            method: "DELETE",
            body: JSON.stringify({ reason: values.reason }),
          });
          state.messages = state.messages.filter((item) => item.id !== message.id);
          state.graves.unshift(removed);
          renderMessages();
          renderBlackroom();
          toast("已放进坟场");
        },
      });
    }
    if (action === "reroll") return reroll(message);
  }

  function replaceMessage(updated) {
    const index = state.messages.findIndex((item) => item.id === updated.id);
    if (index >= 0) state.messages[index] = updated;
    renderMessages();
  }

  async function reroll(message = null) {
    const target = message || [...state.messages].reverse().find((item) => item.role === "assistant");
    if (!target) return toast("还没有可以重回的 AI 消息");
    toast("正在走向另一种回答…");
    try {
      const result = await api(`/api/messages/${target.id}/reroll`, {
        method: "POST",
        body: "{}",
      });
      state.messages = state.messages.filter((item) => item.id !== target.id);
      state.messages.push(result.message);
      state.graves.unshift(result.grave);
      renderMessages();
      renderBlackroom();
      scrollMessages();
    } catch (error) { toast(error.message, "error"); }
  }

  function shareMessage(message) {
    const canvas = $("#share-canvas");
    const ctx = canvas.getContext("2d");
    const width = 900;
    const lines = wrapCanvasText(ctx, message.content, 32, 760);
    canvas.width = width;
    canvas.height = Math.max(520, 280 + lines.length * 52);
    ctx.fillStyle = "#f7f1e5";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.fillStyle = "#173c2e";
    ctx.font = "700 22px serif";
    ctx.fillText("YUK & CHES'S HOME", 70, 70);
    ctx.fillStyle = "#6e776d";
    ctx.font = "18px sans-serif";
    ctx.fillText(message.role === "assistant" ? state.config.ai_name : state.config.user_name, 70, 125);
    ctx.fillStyle = message.role === "assistant" ? "#ffffff" : "#b8d3b7";
    roundedRect(ctx, 55, 155, 790, canvas.height - 255, 28);
    ctx.fill();
    ctx.fillStyle = "#253027";
    ctx.font = "28px serif";
    lines.forEach((line, index) => ctx.fillText(line, 90, 220 + index * 52));
    ctx.fillStyle = "#7c847b";
    ctx.font = "16px sans-serif";
    ctx.fillText(localDate(message.created_at), 70, canvas.height - 50);
    const link = document.createElement("a");
    link.download = `聊天记录-${Date.now()}.png`;
    link.href = canvas.toDataURL("image/png");
    link.click();
    toast("聊天图片已生成");
  }

  function wrapCanvasText(ctx, text, fontSize, maxWidth) {
    ctx.font = `${fontSize}px serif`;
    const lines = [];
    for (const paragraph of String(text).split("\n")) {
      let line = "";
      for (const character of paragraph) {
        const next = line + character;
        if (ctx.measureText(next).width > maxWidth && line) {
          lines.push(line);
          line = character;
        } else {
          line = next;
        }
      }
      lines.push(line || " ");
    }
    return lines;
  }

  function roundedRect(ctx, x, y, width, height, radius) {
    ctx.beginPath();
    if (typeof ctx.roundRect === "function") {
      ctx.roundRect(x, y, width, height, radius);
      return;
    }
    const r = Math.min(radius, width / 2, height / 2);
    ctx.moveTo(x + r, y);
    ctx.arcTo(x + width, y, x + width, y + height, r);
    ctx.arcTo(x + width, y + height, x, y + height, r);
    ctx.arcTo(x, y + height, x, y, r);
    ctx.arcTo(x, y, x + width, y, r);
    ctx.closePath();
  }

  function renderTimeline() {
    const list = $("#timeline-list");
    const items = activeItems().filter((item) =>
      ["note", "task", "habit", "mood", "attachment", "link"].includes(item.kind) &&
      (!state.recordKind || item.kind === state.recordKind));
    list.textContent = "";
    if (!items.length) {
      list.innerHTML = "<div class='empty-state'><span>◷</span><h2>时间轴还是空的</h2><p>从一张便签、一次心情或一个小习惯开始。</p></div>";
      return;
    }
    items.forEach((item) => {
      const node = document.createElement("article");
      node.className = "timeline-item";
      const done = item.status === "done";
      node.innerHTML = `
        <div class="timeline-time">${escapeHtml(localDate(item.happened_at || item.created_at))}</div>
        <div class="timeline-card ${done ? "done" : ""}">
          <h3>${escapeHtml(item.title || kindName(item.kind))}</h3>
          <p>${escapeHtml(item.content || "")}</p>
          <footer>
            <span><span class="kind-badge">${escapeHtml(kindName(item.kind))}</span>${numeric(item.value) ? `<span class="points-badge"> +${numeric(item.value)} 分</span>` : ""}</span>
            <span class="timeline-actions">
              ${["task", "habit"].includes(item.kind) ? `<button data-item-action="toggle" data-id="${item.id}">${done ? "恢复" : "完成"}</button>` : ""}
              <button data-item-action="delete" data-id="${item.id}">归档</button>
            </span>
          </footer>
        </div>`;
      list.append(node);
    });
  }

  function kindName(kind) {
    return {
      note: "便签", task: "清单", habit: "习惯", mood: "心情",
      attachment: "附件", link: "链接", music: "音乐", transaction: "记账",
      account: "资产", saving_plan: "存钱计划", shopping: "购物清单",
      reward_offer: "兑换项目", scene: "小剧场", image: "生图",
    }[kind] || kind;
  }

  async function itemAction(action, id) {
    const item = state.items.find((entry) => entry.id === id);
    if (!item) return;
    try {
      if (action === "toggle") {
        const updated = await api(`/api/items/${id}`, {
          method: "PATCH",
          body: JSON.stringify({ status: item.status === "done" ? "active" : "done" }),
        });
        replaceItem(updated);
        if (updated.status === "done") await evaluateRewards(false);
      } else if (action === "delete") {
        await api(`/api/items/${id}`, { method: "DELETE", body: "{}" });
        state.items = state.items.filter((entry) => entry.id !== id);
      }
      renderAll();
    } catch (error) { toast(error.message, "error"); }
  }

  function replaceItem(updated) {
    const index = state.items.findIndex((item) => item.id === updated.id);
    if (index >= 0) state.items[index] = updated;
    else state.items.unshift(updated);
  }

  function newRecord(kind = "note") {
    openDialog({
      kicker: "TIMELINE",
      title: "写进生活记录",
      fields: [
        {
          name: "kind", label: "类型", type: "select", value: kind,
          options: [
            ["note", "便签"], ["task", "清单"], ["habit", "习惯打卡"],
            ["mood", "心情"], ["link", "链接"],
          ],
        },
        { name: "title", label: "标题", type: "text", required: true },
        { name: "content", label: "内容", type: "textarea" },
        { name: "value", label: "积分（清单/习惯留空时由 AI 建议）", type: "number" },
      ],
      submit: async (values) => {
        const created = await createItem({
          ...values,
          value: values.value ? Number(values.value) : 0,
        });
        state.items.unshift(created);
        renderTimeline();
        toast("已经写进时间轴");
      },
    });
  }

  async function createItem(data) {
    return api("/api/items", { method: "POST", body: JSON.stringify(data) });
  }

  function renderLedger() {
    const target = $("#ledger-content");
    if (state.ledgerTab === "assets") return renderAssets(target);
    if (state.ledgerTab === "stats") return renderStats(target);
    if (state.ledgerTab === "plans") return renderPlans(target);
    const transactions = activeItems("transaction");
    const expense = transactions
      .filter((item) => (item.metadata || {}).direction !== "income")
      .reduce((sum, item) => sum + numeric(item.value), 0);
    const income = transactions
      .filter((item) => (item.metadata || {}).direction === "income")
      .reduce((sum, item) => sum + numeric(item.value), 0);
    target.innerHTML = `
      <section class="summary-card">
        <small>本期总支出</small><strong>¥${expense.toFixed(2)}</strong>
        <div class="summary-row">
          <div class="summary-mini"><small>总收入</small><b>¥${income.toFixed(2)}</b></div>
          <div class="summary-mini"><small>结余</small><b>¥${(income - expense).toFixed(2)}</b></div>
        </div>
      </section>
      <div class="ledger-list">${transactions.map(transactionHtml).join("") || emptyInline("还没有账目")}</div>`;
  }

  function transactionHtml(item) {
    const metadata = item.metadata || {};
    const income = metadata.direction === "income";
    return `<div class="ledger-row">
      <span class="ledger-icon">${income ? "↙" : "↗"}</span>
      <div class="ledger-info"><b>${escapeHtml(item.title || "未分类")}</b><small>${escapeHtml(metadata.category || "日常")} · ${escapeHtml(localDate(item.happened_at))}</small></div>
      <strong class="amount ${income ? "in" : "out"}">${income ? "+" : "-"}¥${numeric(item.value).toFixed(2)}</strong>
    </div>`;
  }

  function renderAssets(target) {
    const accounts = activeItems("account");
    const total = accounts.reduce((sum, item) => sum + numeric(item.value), 0);
    target.innerHTML = `
      <section class="summary-card"><small>净资产</small><strong>¥${total.toFixed(2)}</strong></section>
      <div class="ledger-list">${accounts.map((item) => `<div class="ledger-row"><span class="ledger-icon">◫</span><div class="ledger-info"><b>${escapeHtml(item.title)}</b><small>${escapeHtml(item.content || "账户")}</small></div><strong class="amount">¥${numeric(item.value).toFixed(2)}</strong></div>`).join("") || emptyInline("添加一个账户开始统计")}</div>
      <div class="padded"><button id="new-account-button" class="secondary-btn full-width">添加资产账户</button></div>`;
    $("#new-account-button")?.addEventListener("click", newAccount);
  }

  function renderStats(target) {
    const transactions = activeItems("transaction");
    const groups = {};
    transactions.forEach((item) => {
      if ((item.metadata || {}).direction === "income") return;
      const category = (item.metadata || {}).category || "其他";
      groups[category] = (groups[category] || 0) + numeric(item.value);
    });
    const total = Object.values(groups).reduce((sum, value) => sum + value, 0);
    target.innerHTML = `<section class="summary-card"><small>支出统计</small><strong>¥${total.toFixed(2)}</strong></section>
      <div class="ledger-list">${Object.entries(groups).sort((a,b) => b[1]-a[1]).map(([name, value]) => `<div class="ledger-row"><div class="ledger-info"><b>${escapeHtml(name)}</b><div class="progress-bar"><i style="width:${total ? Math.round(value/total*100) : 0}%"></i></div></div><strong class="amount out">¥${value.toFixed(2)}</strong></div>`).join("") || emptyInline("有账目后会在这里看见分类统计")}</div>`;
  }

  function renderPlans(target) {
    const plans = activeItems().filter((item) => ["saving_plan", "shopping"].includes(item.kind));
    target.innerHTML = `<div class="padded"><div class="section-heading"><div><small>PLANS</small><h2>每日小票与未来清单</h2></div><button id="new-plan-button" class="text-button">添加</button></div>
      ${plans.map((item) => `<article class="gallery-card"><h3>${escapeHtml(item.title)}</h3><p>${escapeHtml(item.content || "")}</p><footer><span>${kindName(item.kind)}</span><b>${numeric(item.value) ? `¥${numeric(item.value).toFixed(2)}` : ""}</b></footer></article>`).join("") || emptyInline("还没有存钱计划或购物清单")}</div>`;
    $("#new-plan-button")?.addEventListener("click", newPlan);
  }

  function emptyInline(text) {
    return `<div class="empty-state"><span>·</span><p>${escapeHtml(text)}</p></div>`;
  }

  function newTransaction() {
    openDialog({
      kicker: "LEDGER",
      title: "记一笔",
      fields: [
        { name: "title", label: "项目", type: "text", required: true },
        { name: "value", label: "金额", type: "number", required: true },
        { name: "direction", label: "方向", type: "select", value: "expense", options: [["expense", "支出"], ["income", "收入"]] },
        { name: "category", label: "分类", type: "text", value: "日常" },
        { name: "content", label: "备注", type: "textarea" },
      ],
      submit: async (values) => {
        const created = await createItem({
          kind: "transaction",
          title: values.title,
          content: values.content,
          value: Number(values.value),
          metadata: { direction: values.direction, category: values.category },
        });
        state.items.unshift(created);
        renderLedger();
      },
    });
  }

  function newAccount() {
    openDialog({
      kicker: "ASSET",
      title: "添加资产账户",
      fields: [
        { name: "title", label: "账户名", type: "text", required: true },
        { name: "value", label: "当前余额", type: "number", required: true },
        { name: "content", label: "备注", type: "text" },
      ],
      submit: async (values) => {
        const created = await createItem({ kind: "account", ...values, value: Number(values.value) });
        state.items.unshift(created);
        renderLedger();
      },
    });
  }

  function newPlan() {
    openDialog({
      kicker: "PLAN",
      title: "添加计划",
      fields: [
        { name: "kind", label: "类型", type: "select", value: "saving_plan", options: [["saving_plan", "存钱计划"], ["shopping", "购物清单"]] },
        { name: "title", label: "名称", type: "text", required: true },
        { name: "value", label: "目标金额", type: "number" },
        { name: "content", label: "说明", type: "textarea" },
      ],
      submit: async (values) => {
        const created = await createItem({ ...values, value: Number(values.value || 0) });
        state.items.unshift(created);
        renderLedger();
      },
    });
  }

  function renderRewards() {
    $("#reward-balance").textContent = numeric(state.rewards.balance).toFixed(0);
    $("#reward-earned").textContent = numeric(state.rewards.earned).toFixed(0);
    $("#shopping-fund").textContent = numeric(state.rewards.shopping_fund).toFixed(0);
    const offers = activeItems("reward_offer");
    $("#reward-shop").innerHTML = offers.map((item) => `<article class="shop-card">
      <div class="shop-icon">✦</div><h3>${escapeHtml(item.title)}</h3><p>${escapeHtml(item.content || "今晚可以兑换")}</p>
      <footer><b>${numeric(item.value)} 分</b><button data-redeem-id="${item.id}">兑换</button></footer>
    </article>`).join("") || `<article class="shop-card"><div class="shop-icon">☕</div><h3>一起放松一会儿</h3><p>可以先添加你们自己的娱乐项目。</p><footer><b>示例</b></footer></article>`;
  }

  async function evaluateRewards(showToast = true) {
    try {
      const result = await api("/api/rewards/evaluate", { method: "POST", body: "{}" });
      state.rewards = result.summary;
      if (showToast) toast(result.awarded.length ? `获得 ${result.awarded.reduce((sum, item) => sum + numeric(item.value), 0)} 积分` : "没有新的已完成事项");
      await refreshItems();
    } catch (error) { toast(error.message, "error"); }
  }

  async function redeemOffer(id) {
    const offer = state.items.find((item) => item.id === id);
    if (!offer) return;
    try {
      const result = await api("/api/rewards/redeem", {
        method: "POST",
        body: JSON.stringify({ title: offer.title, content: offer.content, points: offer.value }),
      });
      state.items.unshift(result.item);
      state.rewards = result.summary;
      renderRewards();
      toast(`已经兑换「${offer.title}」`);
    } catch (error) { toast(error.message, "error"); }
  }

  function newRewardOffer() {
    openDialog({
      kicker: "REWARD",
      title: "添加娱乐兑换",
      fields: [
        { name: "title", label: "项目", type: "text", required: true },
        { name: "value", label: "需要积分", type: "number", required: true },
        { name: "content", label: "说明", type: "textarea" },
      ],
      submit: async (values) => {
        const created = await createItem({ kind: "reward_offer", ...values, value: Number(values.value) });
        state.items.unshift(created);
        renderRewards();
      },
    });
  }

  async function settleRewards() {
    try {
      const result = await api("/api/rewards/settle", { method: "POST", body: "{}" });
      state.rewards = result.summary;
      state.items.unshift(result.spend, result.fund);
      renderRewards();
      toast("剩余积分已经转进购物基金");
    } catch (error) { toast(error.message, "error"); }
  }

  function renderGallery() {
    const target = $("#gallery-content");
    if (state.galleryTab === "images") return renderImages(target);
    if (state.galleryTab === "scenes") return renderScenes(target);
    const favorites = state.messages.filter((message) =>
      (message.metadata?.favorite_by || []).includes("user"));
    target.innerHTML = favorites.map((message) => `<article class="gallery-card"><h3>${message.role === "assistant" ? escapeHtml(state.config.ai_name) : escapeHtml(state.config.user_name)}</h3><p>${escapeHtml(message.content)}</p><footer><span>${escapeHtml(localDate(message.created_at))}</span><span>♥ 已收藏</span></footer></article>`).join("") || emptyInline("收藏的消息会放在这里");
  }

  function renderImages(target) {
    const images = activeItems("image");
    target.innerHTML = `<section class="generator-form">
      <div class="section-heading"><div><small>NAI / IMAGE API</small><h2>生成我们的图</h2></div></div>
      <label class="field"><span>提示词</span><textarea id="image-prompt" rows="4" placeholder="描述想生成的画面"></textarea></label>
      <label class="field"><span>负面提示词</span><textarea id="image-negative" rows="2"></textarea></label>
      <button id="generate-image-button" class="primary-btn full-width">开始生图</button>
    </section>
    ${images.map((item) => `<article class="gallery-card">
      <img class="gallery-image" src="/api/files/${encodeURIComponent(item.id)}" alt="${escapeHtml(item.title)}" loading="lazy">
      <h3>${escapeHtml(item.title)}</h3><p>${escapeHtml(item.content)}</p>
      <footer><span>${escapeHtml(localDate(item.created_at))}</span><span>${escapeHtml(item.metadata?.provider || "")}</span></footer>
    </article>`).join("") || emptyInline("生成的图片会收藏在这里")}`;
    $("#generate-image-button")?.addEventListener("click", generateImage);
  }

  async function generateImage() {
    const prompt = $("#image-prompt").value.trim();
    if (!prompt) return toast("请先写提示词");
    const button = $("#generate-image-button");
    setBusy(button, true, "正在生成，可能需要一两分钟…");
    try {
      const item = await api("/api/images/generate", {
        method: "POST",
        body: JSON.stringify({
          prompt,
          negative_prompt: $("#image-negative").value.trim(),
        }),
      });
      state.items.unshift(item);
      renderGallery();
      toast("图片已经回家");
    } catch (error) { toast(error.message, "error"); }
    finally { setBusy(button, false); }
  }

  function renderScenes(target) {
    const scenes = activeItems("scene");
    target.innerHTML = scenes.map((item) => `<article class="gallery-card"><h3>${escapeHtml(item.title)}</h3><p>${escapeHtml(item.content)}</p><footer><span>${item.metadata?.author === "ai" ? "AI 创作" : "我的创作"}</span><span>${escapeHtml(localDate(item.created_at))}</span></footer></article>`).join("") || emptyInline("小剧场还没有开幕");
  }

  function newScene() {
    openDialog({
      kicker: "THEATER",
      title: "添加小剧场",
      fields: [
        { name: "title", label: "标题", type: "text", required: true },
        { name: "content", label: "正文", type: "textarea", required: true },
      ],
      submit: async (values) => {
        const created = await createItem({ kind: "scene", ...values, metadata: { author: "user", ai_read: false } });
        state.items.unshift(created);
        state.galleryTab = "scenes";
        syncTabs("#gallery-tabs", "galleryTab", "scenes");
        renderGallery();
      },
    });
  }

  function renderBlackroom() {
    const aiFavorites = [
      ...state.messages.filter((message) => (message.metadata?.favorite_by || []).includes("ai")),
      ...activeItems("ai_favorite"),
    ];
    fillBlackroom("#ai-favorites", aiFavorites, (item) => item.content);
    fillBlackroom("#ai-memos", activeItems("ai_memo"), (item) => item.content || item.title);
    fillBlackroom("#ai-wallet", activeItems("ai_wallet"), (item) => `${item.title || "记录"} ${numeric(item.value) ? `· ${numeric(item.value)}` : ""}`);
    fillBlackroom("#graveyard", state.graves, (item) => `${item.content}${item.deletion_reason ? `\n删除原因：${item.deletion_reason}` : ""}`);
  }

  function fillBlackroom(selector, items, text) {
    const target = $(selector);
    target.textContent = "";
    if (!items.length) {
      target.innerHTML = "<div class='blackroom-entry'>这里暂时很安静。</div>";
      return;
    }
    items.forEach((item) => {
      const entry = document.createElement("div");
      entry.className = "blackroom-entry";
      entry.textContent = text(item);
      target.append(entry);
    });
  }

  async function loadIntegrations() {
    try {
      const status = await api("/api/integrations/status");
      renderIntegrationStatus(status);
      const allOk = ["ai", "supabase"].every((key) => status[key]?.enabled);
      $("#connection-dot").className = `status-dot ${allOk ? "ok" : "error"}`;
      $("#connection-copy").textContent = allOk ? "核心服务已连接" : "部分服务等待配置";
    } catch (error) {
      $("#connection-dot").className = "status-dot error";
      $("#connection-copy").textContent = "连接检查失败";
    }
  }

  function renderIntegrationStatus(status) {
    const definitions = [
      ["ai", "聊天 API", status.ai?.enabled, status.ai?.model || "未配置"],
      ["supabase", "Supabase", status.supabase?.enabled, status.supabase?.backend || "SQLite"],
      ["memory", "Ombre Brain 记忆", status.memory?.ok, status.memory?.message || "未配置"],
      ["reading", "共读 MCP", status.reading?.ok, status.reading?.message || "未配置"],
      ["image", "NAI / 生图", status.image?.enabled, status.image?.model || "未配置"],
    ];
    $("#integration-list").innerHTML = definitions.map(([, name, ok, detail]) =>
      `<div class="integration-row ${ok ? "ok" : "error"}"><span><b>${escapeHtml(name)}</b><small>${escapeHtml(detail)}</small></span><i></i></div>`).join("");
    const memoryStatus = $("#memory-status");
    memoryStatus.textContent = status.memory?.message || "未启用";
    memoryStatus.className = `integration-status ${status.memory?.ok ? "ok" : "error"}`;
  }

  async function searchMemory() {
    const query = $("#memory-query").value.trim();
    if (!query) return toast("写下想回忆的内容");
    const button = $("#memory-search-button");
    setBusy(button, true);
    try {
      const result = await api("/api/memory/search", {
        method: "POST", body: JSON.stringify({ query }),
      });
      $("#memory-result").textContent = result.text || "没有找到相关记忆";
      $("#memory-result").classList.remove("hidden");
    } catch (error) { toast(error.message, "error"); }
    finally { setBusy(button, false); }
  }

  async function saveMemory() {
    const content = $("#memory-content").value.trim();
    if (!content) return toast("记忆内容不能为空");
    const button = $("#memory-save-button");
    setBusy(button, true);
    try {
      await api("/api/memory/remember", {
        method: "POST", body: JSON.stringify({ content }),
      });
      $("#memory-content").value = "";
      toast("已经交给 Ombre Brain 好好记住");
    } catch (error) { toast(error.message, "error"); }
    finally { setBusy(button, false); }
  }

  async function saveProfile(event) {
    event.preventDefault();
    const button = $('button[type="submit"]', event.currentTarget);
    setBusy(button, true);
    try {
      const result = await api("/api/settings", {
        method: "PUT",
        body: JSON.stringify({
          user_name: $("#setting-user-name").value.trim(),
          ai_name: $("#setting-ai-name").value.trim(),
          character_prompt: $("#setting-character-prompt").value.trim(),
          relationship: $("#setting-relationship").value.trim(),
          worldbook: $("#setting-worldbook").value.trim(),
          proactive_enabled: $("#setting-proactive").checked,
        }),
      });
      state.config = result.config;
      applyConfig();
      toast("我们的设定已经保存");
    } catch (error) { toast(error.message, "error"); }
    finally { setBusy(button, false); }
  }

  async function importOvo(mode) {
    const file = $("#ovo-import-file").files[0];
    if (!file) return toast("请先选择 OVO 导出的 JSON 文件");
    if (mode === "replace" && !window.confirm("现有聊天会进入坟场，再由导入记录替换。确定继续吗？")) return;
    const body = new FormData();
    body.append("file", file);
    body.append("mode", mode);
    try {
      const result = await api("/api/import/ovo", { method: "POST", body });
      toast(`成功导入 ${result.imported} 条，跳过 ${result.skipped} 条`);
      await loadHome();
      showScreen("chat-screen");
    } catch (error) { toast(error.message, "error"); }
  }

  async function exportChat() {
    try {
      const data = await api("/api/export/chat");
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
      const link = document.createElement("a");
      link.href = URL.createObjectURL(blob);
      link.download = `Yuk-Ches-聊天备份-${new Date().toISOString().slice(0, 10)}.json`;
      link.click();
      URL.revokeObjectURL(link.href);
    } catch (error) { toast(error.message, "error"); }
  }

  async function loadBooks() {
    const list = $("#book-list");
    if (!state.config.features?.reading) {
      list.innerHTML = emptyInline("请先按 README 配置 co-reading-mcp");
      return;
    }
    list.innerHTML = "<p class='security-note'>正在整理书架…</p>";
    try {
      const data = await api("/api/reading/books");
      state.books = Array.isArray(data) ? data : (data.books || []);
      if (!state.books.length && data.text) {
        list.innerHTML = `<pre class="result-box">${escapeHtml(data.text)}</pre>`;
        return;
      }
      list.textContent = "";
      state.books.forEach((book) => {
        const button = document.createElement("button");
        button.className = `book-button ${state.currentBook?.id === book.id ? "active" : ""}`;
        button.innerHTML = `<b>${escapeHtml(book.title || book.id || "未命名")}</b><small>${escapeHtml(book.author || "")} ${book.progress != null ? `· ${Math.round(numeric(book.progress) * (numeric(book.progress) <= 1 ? 100 : 1))}%` : ""}</small>`;
        button.addEventListener("click", () => openBook(book));
        list.append(button);
      });
      if (!state.books.length) list.innerHTML = emptyInline("书架是空的，可以从右上角导入");
    } catch (error) {
      list.innerHTML = `<p class="form-error">${escapeHtml(error.message)}</p>`;
    }
  }

  async function openBook(book) {
    state.currentBook = book;
    loadBooks();
    const pane = $("#reading-pane");
    pane.innerHTML = "<p class='security-note'>正在翻目录…</p>";
    try {
      const data = await api(`/api/reading/books/${encodeURIComponent(book.id)}/chunks`);
      const chunks = Array.isArray(data) ? data : (data.chunks || []);
      if (!chunks.length && data.text) {
        pane.innerHTML = `<pre class="result-box">${escapeHtml(data.text)}</pre>`;
        return;
      }
      pane.innerHTML = `<div class="section-heading"><div><small>CONTENTS</small><h2>${escapeHtml(book.title || "目录")}</h2></div></div><div class="chunk-list"></div>`;
      const list = $(".chunk-list", pane);
      chunks.forEach((chunk, index) => {
        const button = document.createElement("button");
        button.className = "chunk-button";
        button.innerHTML = `<b>${escapeHtml(chunk.title || chunk.id || `第 ${index + 1} 节`)}</b><small>${chunk.read || chunk.completed ? "已读" : "未读"}</small>`;
        button.addEventListener("click", () => openChunk(book, chunk));
        list.append(button);
      });
    } catch (error) {
      pane.innerHTML = `<p class="form-error">${escapeHtml(error.message)}</p>`;
    }
  }

  async function openChunk(book, chunk) {
    const pane = $("#reading-pane");
    pane.innerHTML = "<p class='security-note'>正在展开书页…</p>";
    try {
      const data = await api(`/api/reading/books/${encodeURIComponent(book.id)}/chunks/${encodeURIComponent(chunk.id)}`);
      const text = data.text || data.content || data.chunk?.text || data.chunk?.content || JSON.stringify(data, null, 2);
      state.currentChunk = chunk;
      state.currentReadingText = String(text);
      pane.textContent = "";
      const toolbar = document.createElement("div");
      toolbar.className = "reading-toolbar";
      toolbar.innerHTML = "<button data-reading-action='back'>目录</button><button data-reading-action='mark'>标记已读</button><button data-reading-action='annotate'>写批注</button><button data-reading-action='chat'>带回聊天</button>";
      const article = document.createElement("article");
      article.className = "reading-text";
      article.textContent = text;
      pane.append(toolbar, article);
      $('[data-reading-action="back"]', toolbar).onclick = () => openBook(book);
      $('[data-reading-action="mark"]', toolbar).onclick = () => markRead(book, chunk);
      $('[data-reading-action="annotate"]', toolbar).onclick = () => annotateReading(book, chunk);
      $('[data-reading-action="chat"]', toolbar).onclick = () => {
        showScreen("chat-screen");
        $("#message-input").value = `读到「${chunk.title || chunk.id}」这里，我想和你聊聊。`;
        toast("当前段落会随消息一起发给 AI");
      };
    } catch (error) {
      pane.innerHTML = `<p class="form-error">${escapeHtml(error.message)}</p>`;
    }
  }

  async function markRead(book, chunk) {
    try {
      await api("/api/reading/mark-read", {
        method: "POST", body: JSON.stringify({ bookId: book.id, chunkId: chunk.id }),
      });
      toast("这一页已经读过");
    } catch (error) { toast(error.message, "error"); }
  }

  function annotateReading(book, chunk) {
    openDialog({
      kicker: "MARGIN",
      title: "写在页边",
      fields: [
        { name: "quote", label: "引用原文", type: "textarea", required: true },
        { name: "note", label: "批注", type: "textarea", required: true },
        { name: "mood", label: "此刻的心情", type: "text" },
      ],
      submit: async (values) => {
        await api("/api/reading/annotations", {
          method: "POST",
          body: JSON.stringify({ bookId: book.id, chunkId: chunk.id, ...values }),
        });
        toast("批注已经留在页边");
      },
    });
  }

  async function searchReading() {
    const query = $("#reading-search").value.trim();
    if (!query) return;
    const pane = $("#reading-pane");
    pane.innerHTML = "<p class='security-note'>正在书页间寻找…</p>";
    try {
      const params = new URLSearchParams({ q: query });
      if (state.currentBook?.id) params.set("bookId", state.currentBook.id);
      const data = await api(`/api/reading/search?${params}`);
      const results = Array.isArray(data) ? data : (data.results || data.matches || []);
      if (!results.length && data.text) {
        pane.innerHTML = `<pre class="result-box">${escapeHtml(data.text)}</pre>`;
        return;
      }
      pane.innerHTML = `<div class="section-heading"><div><small>SEARCH</small><h2>“${escapeHtml(query)}”</h2></div></div>${results.map((result) => `<article class="reading-search-result"><b>${escapeHtml(result.title || result.chunkId || "")}</b>\n${escapeHtml(result.text || result.excerpt || result.content || "")}</article>`).join("") || emptyInline("没有找到")}`;
    } catch (error) { pane.innerHTML = `<p class="form-error">${escapeHtml(error.message)}</p>`; }
  }

  async function importBook(file) {
    if (!file) return;
    const body = new FormData();
    body.append("file", file);
    toast("正在把书搬进共读室…");
    try {
      await api("/api/reading/import", { method: "POST", body });
      toast("书已经放上书架");
      await loadBooks();
    } catch (error) { toast(error.message, "error"); }
  }

  async function uploadAttachments(files) {
    for (const file of files) {
      const body = new FormData();
      body.append("file", file);
      try {
        const item = await api("/api/upload", { method: "POST", body });
        state.attachments.push(item);
        state.items.unshift(item);
        renderAttachments();
        toast(`已附上 ${item.title}`);
      } catch (error) { toast(`${file.name}：${error.message}`, "error"); }
    }
  }

  function newMusic() {
    openDialog({
      kicker: "LISTEN",
      title: "一起听歌",
      fields: [
        { name: "title", label: "歌名", type: "text", required: true },
        { name: "content", label: "音乐链接", type: "url", required: true },
      ],
      submit: async (values) => {
        const item = await createItem({ kind: "music", ...values });
        state.items.unshift(item);
        $("#message-input").value = `我们一起听「${values.title}」吧：${values.content}`;
        showScreen("chat-screen");
      },
    });
  }

  function openInnerThought() {
    openDialog({
      kicker: "PRIVATE CONTEXT",
      title: "告诉他此刻的内心想法",
      fields: [{ name: "thought", label: "这不是思维链，只是你愿意分享的情绪语境", type: "textarea", required: true }],
      submit: async (values) => sendMessages(values.thought),
    });
  }

  function newSticker() {
    openDialog({
      kicker: "STICKER",
      title: "添加表情包",
      fields: [
        { name: "title", label: "给它取个名字", type: "text", required: true },
        { name: "content", label: "图片链接", type: "url", required: true },
      ],
      submit: async (values) => {
        const item = await createItem({ kind: "sticker", ...values });
        state.items.unshift(item);
        $("#message-input").value = `[表情包：${values.title}] ${values.content}`;
      },
    });
  }

  function handlePlusAction(action) {
    closeSheets();
    if (action === "reroll") return reroll();
    if (action === "file" || action === "vision") {
      const input = $("#attachment-file-input");
      input.accept = action === "vision" ? "image/*" : ".txt,.md,.json,.csv,.docx,.pdf,image/*,audio/*,video/*";
      input.click();
      return;
    }
    if (action === "music") return newMusic();
    if (action === "record") return newRecord();
    if (action === "thought") return openInnerThought();
  }

  async function refreshItems() {
    state.items = await api("/api/items");
    const boot = await api("/api/bootstrap");
    state.rewards = boot.rewards || state.rewards;
    renderAll();
  }

  async function pollEvents() {
    if (!state.config.features?.proactive) return;
    try {
      const result = await api("/api/events");
      if (result.message && !state.messages.some((item) => item.id === result.message.id)) {
        state.messages.push(result.message);
        renderMessages();
        scrollMessages();
        toast(`${state.config.ai_name || "AI"} 发来了一条消息`);
      }
    } catch {
      // Polling is intentionally quiet.
    }
    window.setTimeout(pollEvents, 120000);
  }

  function resizeComposer() {
    const input = $("#message-input");
    input.style.height = "auto";
    input.style.height = `${Math.min(input.scrollHeight, 120)}px`;
  }

  function syncTabs(selector, property, value) {
    state[property] = value;
    $$(".tab", $(selector)).forEach((tab) => {
      const candidate = tab.dataset.ledgerTab || tab.dataset.galleryTab;
      tab.classList.toggle("active", candidate === value);
    });
  }

  function openDialog({ kicker = "NEW", title, fields, submit, danger = false }) {
    const dialog = $("#form-dialog");
    $("#dialog-kicker").textContent = kicker;
    $("#dialog-title").textContent = title;
    $("#dialog-error").textContent = "";
    const container = $("#dialog-fields");
    container.textContent = "";
    fields.forEach((field) => container.append(buildDialogField(field)));
    state.dialogSubmit = submit;
    const submitButton = $("#dialog-submit");
    submitButton.textContent = danger ? "确认" : "保存";
    submitButton.className = danger ? "danger-btn" : "primary-btn";
    dialog.showModal();
  }

  function buildDialogField(field) {
    const label = document.createElement("label");
    label.className = "dialog-field";
    const span = document.createElement("span");
    span.textContent = field.label;
    label.append(span);
    let input;
    if (field.type === "textarea") {
      input = document.createElement("textarea");
      input.rows = field.rows || 4;
      input.value = field.value || "";
    } else if (field.type === "select") {
      input = document.createElement("select");
      (field.options || []).forEach(([value, text]) => {
        const option = document.createElement("option");
        option.value = value;
        option.textContent = text;
        option.selected = value === field.value;
        input.append(option);
      });
    } else if (field.type === "checkbox") {
      input = document.createElement("input");
      input.type = "checkbox";
      input.checked = Boolean(field.value);
      label.classList.add("dialog-checkbox");
    } else {
      input = document.createElement("input");
      input.type = field.type || "text";
      input.value = field.value || "";
      if (field.type === "number") input.step = "any";
    }
    input.name = field.name;
    input.required = Boolean(field.required);
    input.placeholder = field.placeholder || "";
    label.append(input);
    return label;
  }

  async function submitDialog(event) {
    event.preventDefault();
    if (!state.dialogSubmit) return;
    const form = $("#dialog-form");
    if (!form.reportValidity()) return;
    const values = {};
    $$("[name]", $("#dialog-fields")).forEach((input) => {
      values[input.name] = input.type === "checkbox" ? input.checked : input.value.trim();
    });
    const button = $("#dialog-submit");
    setBusy(button, true);
    try {
      await state.dialogSubmit(values);
      $("#form-dialog").close();
    } catch (error) {
      $("#dialog-error").textContent = error.message;
    } finally {
      setBusy(button, false);
    }
  }

  function bindGlobalEvents() {
    $("#enter-home").addEventListener("click", enterHome);
    let splashStart = null;
    $("#splash-screen").addEventListener("pointerdown", (event) => { splashStart = event.clientY; });
    $("#splash-screen").addEventListener("pointerup", (event) => {
      if (splashStart != null && splashStart - event.clientY > 45) enterHome();
    });
    $("#login-form").addEventListener("submit", async (event) => {
      event.preventDefault();
      $("#login-error").textContent = "";
      try {
        await api("/api/auth/login", {
          method: "POST",
          body: JSON.stringify({ password: $("#login-password").value }),
        });
        $("#auth-overlay").classList.add("hidden");
        await loadHome();
      } catch (error) { $("#login-error").textContent = error.message; }
    });
    document.addEventListener("click", (event) => {
      const screenButton = event.target.closest("[data-screen]");
      if (screenButton) showScreen(screenButton.dataset.screen);
      if (event.target.closest(".drawer-button")) openDrawer();
      if (event.target.closest("[data-close-sheet]")) closeSheets();
      const plus = event.target.closest("[data-plus-action]");
      if (plus) handlePlusAction(plus.dataset.plusAction);
      const messageAction = event.target.closest("[data-message-action]");
      if (messageAction) runMessageAction(messageAction.dataset.messageAction);
      const itemButton = event.target.closest("[data-item-action]");
      if (itemButton) itemAction(itemButton.dataset.itemAction, itemButton.dataset.id);
      const redeem = event.target.closest("[data-redeem-id]");
      if (redeem) redeemOffer(redeem.dataset.redeemId);
    });
    $("#drawer-scrim").addEventListener("click", closeDrawer);
    $("#plus-button").addEventListener("click", () => openSheet("#plus-sheet"));
    $("#send-button").addEventListener("click", () => sendMessages());
    bindLongPress($("#send-button"), openInnerThought, 650);
    $("#queue-button").addEventListener("click", queueCurrentMessage);
    $("#message-input").addEventListener("input", resizeComposer);
    $("#message-input").addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        sendMessages();
      }
    });
    $("#clear-reply").addEventListener("click", clearReply);
    $("#sticker-button").addEventListener("click", newSticker);
    const profileTrigger = $("#profile-trigger");
    let profileLongPressed = false;
    bindLongPress(profileTrigger, () => {
      profileLongPressed = true;
      showScreen("blackroom-screen");
    }, 650);
    profileTrigger.addEventListener("click", () => {
      if (profileLongPressed) {
        profileLongPressed = false;
        return;
      }
      showScreen("settings-screen");
    });
    $("#new-record-button").addEventListener("click", () => newRecord());
    $("#record-filters").addEventListener("click", (event) => {
      const chip = event.target.closest("[data-kind]");
      if (!chip) return;
      state.recordKind = chip.dataset.kind;
      $$(".filter-chip", $("#record-filters")).forEach((item) => item.classList.toggle("active", item === chip));
      renderTimeline();
    });
    $("#new-transaction-button").addEventListener("click", newTransaction);
    $("#ledger-tabs").addEventListener("click", (event) => {
      const tab = event.target.closest("[data-ledger-tab]");
      if (!tab) return;
      syncTabs("#ledger-tabs", "ledgerTab", tab.dataset.ledgerTab);
      renderLedger();
    });
    $("#evaluate-rewards").addEventListener("click", () => evaluateRewards(true));
    $("#new-reward-button").addEventListener("click", newRewardOffer);
    $("#settle-rewards").addEventListener("click", settleRewards);
    $("#gallery-tabs").addEventListener("click", (event) => {
      const tab = event.target.closest("[data-gallery-tab]");
      if (!tab) return;
      syncTabs("#gallery-tabs", "galleryTab", tab.dataset.galleryTab);
      renderGallery();
    });
    $("#new-scene-button").addEventListener("click", newScene);
    $("#profile-form").addEventListener("submit", saveProfile);
    $("#memory-search-button").addEventListener("click", searchMemory);
    $("#memory-save-button").addEventListener("click", saveMemory);
    $("#ovo-import-file").addEventListener("change", (event) => {
      $("#ovo-file-name").textContent = event.target.files[0]?.name || "尚未选择文件";
    });
    $("#ovo-import-append").addEventListener("click", () => importOvo("append"));
    $("#ovo-import-replace").addEventListener("click", () => importOvo("replace"));
    $("#export-chat-button").addEventListener("click", exportChat);
    $("#logout-button").addEventListener("click", async () => {
      await api("/api/auth/logout", { method: "POST", body: "{}" });
      window.location.reload();
    });
    $("#reading-search-button").addEventListener("click", searchReading);
    $("#reading-search").addEventListener("keydown", (event) => {
      if (event.key === "Enter") searchReading();
    });
    $("#import-book-button").addEventListener("click", () => $("#book-file-input").click());
    $("#book-file-input").addEventListener("change", (event) => importBook(event.target.files[0]));
    $("#attachment-file-input").addEventListener("change", (event) => {
      uploadAttachments([...event.target.files]);
      event.target.value = "";
    });
    $("#dialog-form").addEventListener("submit", submitDialog);
    $$("[data-dialog-close]").forEach((button) => button.addEventListener("click", () => $("#form-dialog").close()));
    $("#form-dialog").addEventListener("close", () => { state.dialogSubmit = null; });
  }

  document.addEventListener("DOMContentLoaded", boot);
})();
