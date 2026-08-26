"use strict";

const STATE_KEY = "rinbossImageCollectorState";
const COLLECT_ALARM = "rinbossImageCollectorCollect";
const NEXT_ALARM = "rinbossImageCollectorNext";
const LOAD_TIMEOUT_ALARM = "rinbossImageCollectorLoadTimeout";
const BATCH_SIZE = 100;
const BATCH_PAUSE_SECONDS = 60;
const MIN_DELAY_SECONDS = 1;
const MAX_DELAY_SECONDS = 120;
const URL_ALIASES = ["product url", "amazon url", "temu url", "product link", "url", "link"];

const normalizeHeader = (value) => String(value || "").trim().toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
const now = () => new Date().toISOString();
const normalizeDelaySeconds = (value) => Math.min(
  MAX_DELAY_SECONDS,
  Math.max(MIN_DELAY_SECONDS, Number(value) || 8),
);
const getState = async () => (await chrome.storage.local.get(STATE_KEY))[STATE_KEY] || null;
const saveState = async (changes) => {
  const current = await getState() || {};
  const state = { ...current, ...changes, updatedAt: now() };
  await chrome.storage.local.set({ [STATE_KEY]: state });
  return state;
};

const productUrl = (row, headers) => {
  const mapped = new Map((headers || []).map((header) => [normalizeHeader(header), header]));
  for (const alias of URL_ALIASES) {
    const column = mapped.get(alias);
    const value = String(column ? row[column] : "").trim();
    if (/^https:\/\/(?:www\.)?amazon\.com\//i.test(value) || /^https:\/\/(?:[a-z0-9-]+\.)?temu\.com\//i.test(value)) return value;
  }
  const asinColumn = mapped.get("asin");
  const asin = String(asinColumn ? row[asinColumn] : "").trim();
  return /^[A-Z0-9]{10}$/i.test(asin) ? `https://www.amazon.com/dp/${asin}` : "";
};

const sourceForUrl = (url) => {
  if (/^https:\/\/(?:www\.)?amazon\.com\//i.test(url)) return { name: "Amazon", file: "amazon_gallery.js" };
  if (/^https:\/\/(?:[a-z0-9-]+\.)?temu\.com\//i.test(url)) return { name: "Temu", file: "temu_gallery.js" };
  return null;
};

const clearAlarms = async () => {
  await chrome.alarms.clear(COLLECT_ALARM);
  await chrome.alarms.clear(NEXT_ALARM);
  await chrome.alarms.clear(LOAD_TIMEOUT_ALARM);
};

const closeWorkingTab = async (state) => {
  if (!state?.tabId) return;
  try { await chrome.tabs.remove(state.tabId); } catch (_error) { /* tab already closed */ }
};

const finish = async (status, message, keepTab = false) => {
  await clearAlarms();
  const state = await getState();
  const finished = await saveState({
    running: false,
    stopRequested: false,
    status,
    message,
    tabId: keepTab ? state?.tabId : null,
    finishedAt: now(),
  });
  if (!keepTab) await closeWorkingTab(state);
  return finished;
};

const findPendingIndexes = (state, maximum) => (state.rows || []).map((_row, index) => index).filter((index) => {
  const row = state.rows[index];
  const url = productUrl(row, state.headers);
  const count = Number(row.image_gallery_count) || 0;
  const cleanVersionComplete = Number(state.version || 0) >= 3
    && row.image_gallery_status === "complete"
    && count >= maximum;
  return Boolean(url) && !cleanVersionComplete;
});

const navigateCurrent = async () => {
  let state = await getState();
  if (!state?.running) return;
  if (state.stopRequested && (state.processed || 0) > 0) {
    await finish("stopped", `Đã dừng sau ${state.processed}/${state.total} sản phẩm.`);
    return;
  }
  const rowIndex = state.queue?.[state.queuePosition];
  if (!Number.isInteger(rowIndex)) {
    await finish("completed", `Hoàn tất ${state.processed || 0}/${state.total || 0} sản phẩm.`);
    return;
  }
  const url = productUrl(state.rows[rowIndex], state.headers);
  const source = sourceForUrl(url);
  if (!source) {
    const rows = [...state.rows];
    rows[rowIndex] = { ...rows[rowIndex], image_gallery_count: 0, image_gallery_status: "missing_url" };
    state = await saveState({ rows, processed: (state.processed || 0) + 1, queuePosition: state.queuePosition + 1 });
    await navigateCurrent();
    return;
  }

  state = await saveState({
    status: "navigating",
    currentRow: rowIndex,
    currentUrl: url,
    currentSource: source.name,
    message: `Đang mở dòng ${rowIndex + 2} trên ${source.name}…`,
  });
  try {
    await chrome.alarms.clear(LOAD_TIMEOUT_ALARM);
    chrome.alarms.create(LOAD_TIMEOUT_ALARM, { when: Date.now() + 60000 });
    if (state.tabId) {
      try { await chrome.tabs.update(state.tabId, { url, active: false }); return; }
      catch (_error) { /* create a replacement below */ }
    }
    const tab = await chrome.tabs.create({ url, active: false });
    await saveState({ tabId: tab.id });
  } catch (error) {
    await finish("error", `Không mở được link sản phẩm: ${error?.message || error}`);
  }
};

const normalizeImageCandidate = (value, source) => {
  const raw = String(value || "").trim();
  if (!/^https?:\/\//i.test(raw)) return null;
  try {
    const parsed = new URL(raw);
    parsed.hash = "";

    if (source?.name === "Amazon") {
      const validHost = /(?:^|\.)(?:media-amazon\.com|ssl-images-amazon\.com|amazon\.com)$/i.test(parsed.hostname);
      const productPath = /^\/images\/I\//i.test(parsed.pathname);
      const knownNonProduct = /(?:prime[_-]?logo|marketing\/prime|\/images\/G\/)/i.test(raw);
      if (!validHost || !productPath || knownNonProduct) return null;
      parsed.pathname = parsed.pathname.replace(/\._[^/]*_(?=\.[a-zA-Z0-9]+$)/, "");
      parsed.search = "";
      return { url: parsed.toString(), key: parsed.pathname };
    }

    // Temu often serves the same asset with different resize query strings.
    // Keep the usable URL but compare by host + path to avoid duplicate images.
    return {
      url: parsed.toString(),
      key: `${parsed.hostname.toLowerCase()}${parsed.pathname}`,
    };
  } catch (_error) {
    return null;
  }
};

const mergeImages = (row, incoming, maximum, source) => {
  const images = [];
  const seen = new Set();
  const primary = normalizeImageCandidate(row.image_url, source);
  if (primary) seen.add(primary.key);

  const add = (value) => {
    const candidate = normalizeImageCandidate(value, source);
    if (!candidate || seen.has(candidate.key) || images.length >= maximum) return;
    seen.add(candidate.key);
    images.push(candidate.url);
  };
  (incoming || []).forEach(add);
  for (let index = 1; index <= 10; index += 1) add(row[`image_url_${index}`]);
  return { images: images.slice(0, maximum), primaryUrl: primary?.url || "" };
};

const scheduleNext = async (state) => {
  const atBatchBoundary = Number(state?.processed || 0) > 0
    && Number(state.processed) % BATCH_SIZE === 0;
  const delaySeconds = atBatchBoundary
    ? BATCH_PAUSE_SECONDS
    : normalizeDelaySeconds(state?.delaySeconds);

  if (atBatchBoundary) {
    state = await saveState({
      status: "batch_pause",
      message: `Đã xử lý ${state.processed}/${state.total} sản phẩm. Tự nghỉ ${BATCH_PAUSE_SECONDS} giây trước nhóm tiếp theo.`,
    });
  }
  chrome.alarms.create(NEXT_ALARM, { when: Date.now() + delaySeconds * 1000 });
  return state;
};

const collectCurrent = async () => {
  let state = await getState();
  if (!state?.running || !state.tabId) return;
  await chrome.alarms.clear(COLLECT_ALARM);
  await chrome.alarms.clear(LOAD_TIMEOUT_ALARM);
  const rowIndex = state.currentRow;
  const source = sourceForUrl(state.currentUrl || "");
  if (!Number.isInteger(rowIndex) || !source) {
    await finish("error", "Không xác định được sản phẩm hiện tại.");
    return;
  }
  try {
    await saveState({ status: "collecting", message: `Đang đọc ảnh gallery dòng ${rowIndex + 2}…` });
    const injection = await chrome.scripting.executeScript({ target: { tabId: state.tabId }, files: [source.file] });
    const result = injection?.[0]?.result;
    if (!result?.ok) throw new Error(result?.message || `Không đọc được ảnh ${source.name}.`);
    const rows = [...state.rows];
    const row = { ...rows[rowIndex] };
    if (result.blocked) {
      row.image_gallery_status = "blocked";
      row.image_gallery_count = 0;
      rows[rowIndex] = row;
      await saveState({ rows });
      await finish("blocked", result.message || `${source.name} yêu cầu xác minh; phiên đã dừng.`, true);
      return;
    }

    const maximum = Math.min(10, Math.max(1, Number(state.maxImages) || 5));
    const merged = mergeImages(row, result.images, maximum, source);
    const images = merged.images;
    row.image_url = merged.primaryUrl;
    // Remove stale values from a previous run before writing the clean gallery.
    for (let index = 1; index <= 10; index += 1) row[`image_url_${index}`] = "";
    for (let index = 1; index <= maximum; index += 1) row[`image_url_${index}`] = images[index - 1] || "";
    row.image_gallery_count = images.length;
    row.image_gallery_status = images.length >= maximum ? "complete" : images.length ? "partial" : "no_images";
    rows[rowIndex] = row;
    state = await saveState({
      rows,
      processed: (state.processed || 0) + 1,
      queuePosition: state.queuePosition + 1,
      status: "waiting",
      message: `Dòng ${rowIndex + 2}: lấy được ${images.length}/${maximum} ảnh.`,
    });
    if (state.stopRequested) {
      await finish("stopped", `Đã dừng sau ${state.processed}/${state.total} sản phẩm.`);
      return;
    }
    if (state.queuePosition >= state.queue.length) {
      await finish("completed", `Hoàn tất ${state.processed}/${state.total} sản phẩm.`);
      return;
    }
    await scheduleNext(state);
  } catch (error) {
    state = await getState();
    const rows = [...(state?.rows || [])];
    if (rows[rowIndex]) rows[rowIndex] = { ...rows[rowIndex], image_gallery_count: 0, image_gallery_status: "error" };
    state = await saveState({
      rows,
      processed: (state?.processed || 0) + 1,
      queuePosition: (state?.queuePosition || 0) + 1,
      status: "waiting",
      message: `Dòng ${rowIndex + 2} lỗi: ${error?.message || error}. Sẽ tiếp tục dòng sau.`,
    });
    if (state.stopRequested) await finish("stopped", `Đã dừng sau ${state.processed}/${state.total} sản phẩm; dòng cuối có lỗi.`);
    else if (state.queuePosition >= state.queue.length) await finish("completed", `Đã xử lý ${state.processed}/${state.total}; có dòng lỗi.`);
    else await scheduleNext(state);
  }
};

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.type === "START_IMAGE_BATCH") {
    (async () => {
      const state = await getState();
      if (!state?.rows?.length) throw new Error("Hãy nhập CSV trước.");
      if (state.running) throw new Error("Một phiên lấy ảnh đang chạy.");
      const maximum = Math.min(10, Math.max(1, Number(message.maxImages) || 5));
      const queue = findPendingIndexes(state, maximum);
      if (!queue.length) throw new Error("Không còn dòng hợp lệ cần lấy ảnh.");
      const started = await saveState({
        running: true,
        stopRequested: false,
        status: "starting",
        queue,
        queuePosition: 0,
        processed: 0,
        total: queue.length,
        maxImages: maximum,
        delaySeconds: normalizeDelaySeconds(message.delaySeconds),
        message: `Chuẩn bị xử lý ${queue.length} sản phẩm…`,
        startedAt: now(),
      });
      await navigateCurrent();
      return started;
    })().then((state) => sendResponse({ ok: true, state })).catch((error) => sendResponse({ ok: false, message: error?.message || String(error) }));
    return true;
  }
  if (message?.type === "STOP_IMAGE_BATCH") {
    saveState({ stopRequested: true, message: "Sẽ dừng sau sản phẩm hiện tại." })
      .then((state) => sendResponse({ ok: true, state }))
      .catch((error) => sendResponse({ ok: false, message: error?.message || String(error) }));
    return true;
  }
  if (message?.type === "CLEAR_IMAGE_BATCH") {
    (async () => {
      const state = await getState();
      await clearAlarms();
      await closeWorkingTab(state);
      await chrome.storage.local.remove(STATE_KEY);
    })().then(() => sendResponse({ ok: true })).catch((error) => sendResponse({ ok: false, message: error?.message || String(error) }));
    return true;
  }
});

chrome.tabs.onUpdated.addListener(async (tabId, changeInfo) => {
  if (changeInfo.status !== "complete") return;
  const state = await getState();
  if (!state?.running || state.tabId !== tabId || state.status !== "navigating") return;
  await chrome.alarms.clear(LOAD_TIMEOUT_ALARM);
  await saveState({ status: "waiting", message: `Trang đã tải; chờ 4 giây để hiện đủ gallery…` });
  chrome.alarms.create(COLLECT_ALARM, { when: Date.now() + 4000 });
});

chrome.tabs.onRemoved.addListener(async (tabId) => {
  const state = await getState();
  if (state?.running && state.tabId === tabId) await finish("error", "Tab lấy ảnh đã bị đóng.");
});

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === COLLECT_ALARM) collectCurrent();
  if (alarm.name === NEXT_ALARM) navigateCurrent();
  if (alarm.name === LOAD_TIMEOUT_ALARM) collectCurrent();
});

chrome.runtime.onStartup.addListener(async () => {
  const state = await getState();
  if (state?.running) await finish("stopped", "Trình duyệt vừa khởi động lại; hãy bấm bắt đầu để tiếp tục các dòng chưa đủ ảnh.");
});
