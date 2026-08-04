"use strict";

const SETTINGS_KEY = "rinbossMarketplaceSettings";
const BATCH_KEY = "rinbossMarketplaceBatch";
const ALARM_NAME = "rinbossMarketplaceCollectPage";
const SOURCES = {
  amazon: {
    label: "Amazon",
    productsKey: "rinbossMarketplaceAmazonProducts",
    urlPattern: /^https:\/\/(?:www\.)?amazon\.com\//i,
    contentFile: "content.js",
    searchUrl(keyword, page) {
      const params = new URLSearchParams({ k: keyword });
      if (page > 1) params.set("page", String(page));
      return `https://www.amazon.com/s?${params.toString()}`;
    },
  },
  temu: {
    label: "Temu US",
    productsKey: "rinbossMarketplaceTemuProducts",
    urlPattern: /^https:\/\/(?:[a-z0-9-]+\.)?temu\.com\//i,
    contentFile: "temu_content.js",
    searchUrl(keyword) {
      return `https://www.temu.com/search_result.html?search_key=${encodeURIComponent(keyword)}`;
    },
  },
};

const now = () => new Date().toISOString();
const source = (marketplace) => SOURCES[marketplace] || SOURCES.temu;

const saveBatch = async (changes) => {
  const current = (await chrome.storage.local.get(BATCH_KEY))[BATCH_KEY] || {};
  const batch = { ...current, ...changes, updatedAt: now() };
  await chrome.storage.local.set({ [BATCH_KEY]: batch });
  return batch;
};

const finishBatch = async (status, message) => {
  await chrome.alarms.clear(ALARM_NAME);
  return saveBatch({ running: false, stopRequested: false, status, message, finishedAt: now() });
};

const schedule = async (batch, message) => {
  await chrome.alarms.clear(ALARM_NAME);
  await saveBatch({ status: "waiting", message });
  chrome.alarms.create(ALARM_NAME, { when: Date.now() + batch.delaySeconds * 1000 });
};

const navigate = async () => {
  const batch = (await chrome.storage.local.get(BATCH_KEY))[BATCH_KEY];
  if (!batch?.running) return;
  if (batch.stopRequested) return finishBatch("stopped", "Đã dừng theo yêu cầu.");
  const keyword = batch.keywords?.[batch.keywordIndex];
  if (!keyword) return finishBatch("completed", `Hoàn tất ${batch.completedPages || 0} lượt.`);
  const config = source(batch.marketplace);
  await saveBatch({
    status: "navigating",
    currentKeyword: keyword,
    message: `Đang mở “${keyword}” — lượt ${batch.pageNumber}/${batch.pagesPerKeyword}…`,
  });
  try {
    if (batch.marketplace === "temu" && batch.pageNumber > 1) {
      await schedule(batch, `Chờ ${batch.delaySeconds} giây trước lượt cuộn Temu tiếp theo…`);
    } else {
      await chrome.tabs.update(batch.tabId, { url: config.searchUrl(keyword, batch.pageNumber) });
    }
  } catch (error) {
    await finishBatch("error", `Không mở được ${config.label}: ${error?.message || error}`);
  }
};

const mergeProducts = async (batch, result) => {
  const config = source(batch.marketplace);
  const values = await chrome.storage.local.get([config.productsKey, SETTINGS_KEY]);
  const stored = Array.isArray(values[config.productsKey]) ? values[config.productsKey] : [];
  const excludeBrands = values[SETTINGS_KEY]?.excludeBrands !== false;
  const incoming = (result.products || []).filter(
    (product) => !(batch.marketplace === "amazon" && excludeBrands && product._excluded_brand)
  );
  const identity = (product) => batch.marketplace === "amazon"
    ? product.asin
    : (product.product_id || product.product_url || `${product.keyword}|${product.title}`);
  const merged = new Map(stored.map((product) => [identity(product), product]));
  incoming.forEach((product) => {
    const cleaned = { ...product };
    delete cleaned._excluded_brand;
    delete cleaned._fresh;
    merged.set(identity(cleaned), cleaned);
  });
  await chrome.storage.local.set({ [config.productsKey]: Array.from(merged.values()) });
  return { incoming: incoming.length, total: merged.size };
};

const advance = async (batch, readCount, totalProducts) => {
  let keywordIndex = batch.keywordIndex;
  let pageNumber = batch.pageNumber + 1;
  if (pageNumber > batch.pagesPerKeyword || batch.lastCardCount === 0) {
    keywordIndex += 1;
    pageNumber = 1;
  }
  const completedPages = (batch.completedPages || 0) + 1;
  const collectedThisRun = (batch.collectedThisRun || 0) + readCount;
  if (batch.stopRequested) {
    await finishBatch("stopped", `Đã dừng sau lượt hiện tại; tổng kho ${totalProducts} sản phẩm.`);
    return;
  }
  if (keywordIndex >= batch.keywords.length) {
    await saveBatch({ completedPages, collectedThisRun, keywordIndex, pageNumber });
    await finishBatch("completed", `Hoàn tất ${completedPages} lượt; tổng kho ${totalProducts} sản phẩm.`);
    return;
  }
  await saveBatch({ completedPages, collectedThisRun, keywordIndex, pageNumber });
  await navigate();
};

const collect = async () => {
  let batch = (await chrome.storage.local.get(BATCH_KEY))[BATCH_KEY];
  if (!batch?.running) return;
  const config = source(batch.marketplace);
  try {
    const tab = await chrome.tabs.get(batch.tabId);
    if (!config.urlPattern.test(String(tab?.url || ""))) {
      await finishBatch("error", `Tab đã rời ${config.label}.`);
      return;
    }
    await saveBatch({ status: "collecting", message: `Đang đọc ${config.label}…` });
    const injection = await chrome.scripting.executeScript({
      target: { tabId: batch.tabId },
      files: [config.contentFile],
    });
    const result = injection?.[0]?.result;
    if (!result?.ok) throw new Error(result?.message || `Không đọc được ${config.label}.`);
    if (result.blocked) {
      await finishBatch("blocked", result.message || `${config.label} yêu cầu xác minh.`);
      return;
    }
    const merged = await mergeProducts(batch, result);
    batch = await saveBatch({
      lastPageCount: merged.incoming,
      lastCardCount: result.card_count || 0,
      message: `Lượt ${batch.pageNumber}: thấy ${result.card_count || 0} thẻ, đọc ${merged.incoming} sản phẩm.`,
    });
    await advance(batch, merged.incoming, merged.total);
  } catch (error) {
    await finishBatch("error", `Lỗi khi đọc trang: ${error?.message || error}`);
  }
};

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.type === "START_BATCH") {
    (async () => {
      const existing = (await chrome.storage.local.get(BATCH_KEY))[BATCH_KEY];
      if (existing?.running) throw new Error("Một phiên thu thập đang chạy.");
      const marketplace = message.marketplace === "amazon" ? "amazon" : "temu";
      const config = source(marketplace);
      const keywords = Array.from(new Set(
        (message.keywords || []).map((value) => String(value).trim()).filter(Boolean)
      )).slice(0, 50);
      const pagesPerKeyword = Math.min(10, Math.max(1, Number(message.pagesPerKeyword) || 1));
      const delaySeconds = Math.min(120, Math.max(8, Number(message.delaySeconds) || 10));
      if (!keywords.length) throw new Error("Danh sách ngách đang trống.");
      const tab = await chrome.tabs.get(message.tabId);
      if (!config.urlPattern.test(String(tab?.url || ""))) {
        throw new Error(`Hãy mở ${config.label} trong tab hiện tại.`);
      }
      const batch = {
        version: 2,
        marketplace,
        running: true,
        stopRequested: false,
        status: "starting",
        tabId: message.tabId,
        keywords,
        pagesPerKeyword,
        delaySeconds,
        keywordIndex: 0,
        pageNumber: 1,
        totalPages: keywords.length * pagesPerKeyword,
        completedPages: 0,
        collectedThisRun: 0,
        lastPageCount: 0,
        lastCardCount: null,
        currentKeyword: keywords[0],
        message: `Đang bắt đầu ${config.label}…`,
        startedAt: now(),
        updatedAt: now(),
      };
      await chrome.storage.local.set({ [BATCH_KEY]: batch });
      await navigate();
      return batch;
    })().then((batch) => sendResponse({ ok: true, batch })).catch((error) => {
      sendResponse({ ok: false, message: error?.message || String(error) });
    });
    return true;
  }
  if (message?.type === "STOP_BATCH") {
    (async () => {
      const batch = (await chrome.storage.local.get(BATCH_KEY))[BATCH_KEY];
      if (!batch?.running) return batch || null;
      return saveBatch({ stopRequested: true, message: "Sẽ dừng sau lượt hiện tại." });
    })().then((batch) => sendResponse({ ok: true, batch })).catch((error) => {
      sendResponse({ ok: false, message: error?.message || String(error) });
    });
    return true;
  }
});

chrome.tabs.onUpdated.addListener(async (tabId, changeInfo, tab) => {
  if (changeInfo.status !== "complete") return;
  const batch = (await chrome.storage.local.get(BATCH_KEY))[BATCH_KEY];
  if (!batch?.running || batch.tabId !== tabId) return;
  const config = source(batch.marketplace);
  if (!config.urlPattern.test(String(tab.url || ""))) return;
  await schedule(batch, `Trang đã tải. Chờ ${batch.delaySeconds} giây để ${config.label} hiển thị đủ kết quả…`);
});

chrome.tabs.onRemoved.addListener(async (tabId) => {
  const batch = (await chrome.storage.local.get(BATCH_KEY))[BATCH_KEY];
  if (batch?.running && batch.tabId === tabId) await finishBatch("error", "Tab thu thập đã bị đóng.");
});

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === ALARM_NAME) collect();
});
