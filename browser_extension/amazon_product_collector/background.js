"use strict";

const PRODUCTS_KEY = "rinbossAmazonProducts";
const SETTINGS_KEY = "rinbossAmazonSettings";
const BATCH_KEY = "rinbossAmazonBatch";
const ALARM_NAME = "rinbossAmazonCollectPage";
const AMAZON_URL = /^https:\/\/(?:www\.)?amazon\.com\//i;

const now = () => new Date().toISOString();

const getValues = async () => chrome.storage.local.get([
  PRODUCTS_KEY,
  SETTINGS_KEY,
  BATCH_KEY,
]);

const saveBatch = async (changes) => {
  const values = await chrome.storage.local.get(BATCH_KEY);
  const current = values[BATCH_KEY] || {};
  const batch = { ...current, ...changes, updatedAt: now() };
  await chrome.storage.local.set({ [BATCH_KEY]: batch });
  return batch;
};

const finishBatch = async (status, message) => {
  await chrome.alarms.clear(ALARM_NAME);
  return saveBatch({
    running: false,
    stopRequested: false,
    status,
    message,
    finishedAt: now(),
  });
};

const searchUrl = (keyword, page) => {
  const params = new URLSearchParams({ k: keyword });
  if (page > 1) params.set("page", String(page));
  return `https://www.amazon.com/s?${params.toString()}`;
};

const navigateCurrentPage = async () => {
  const values = await chrome.storage.local.get(BATCH_KEY);
  const batch = values[BATCH_KEY];
  if (!batch?.running) return;
  if (batch.stopRequested) {
    await finishBatch("stopped", "Đã dừng theo yêu cầu.");
    return;
  }
  const keyword = batch.keywords?.[batch.keywordIndex];
  if (!keyword) {
    await finishBatch("completed", `Hoàn tất ${batch.completedPages || 0}/${batch.totalPages || 0} trang.`);
    return;
  }
  await chrome.alarms.clear(ALARM_NAME);
  await saveBatch({
    status: "navigating",
    currentKeyword: keyword,
    message: `Đang mở “${keyword}” — trang ${batch.pageNumber}/${batch.pagesPerKeyword}…`,
  });
  try {
    await chrome.tabs.update(batch.tabId, { url: searchUrl(keyword, batch.pageNumber) });
  } catch (error) {
    await finishBatch("error", `Không mở được tab Amazon: ${error?.message || error}`);
  }
};

const mergeProducts = async (result) => {
  const values = await getValues();
  const stored = Array.isArray(values[PRODUCTS_KEY]) ? values[PRODUCTS_KEY] : [];
  const excludeBrands = values[SETTINGS_KEY]?.excludeBrands !== false;
  const incoming = (result.products || []).filter(
    (product) => !(excludeBrands && product._excluded_brand)
  );
  const merged = new Map(stored.map((product) => [product.asin, product]));
  incoming.forEach((product) => {
    const cleaned = { ...product };
    delete cleaned._excluded_brand;
    delete cleaned._fresh;
    merged.set(cleaned.asin, cleaned);
  });
  await chrome.storage.local.set({ [PRODUCTS_KEY]: Array.from(merged.values()) });
  return { incoming: incoming.length, total: merged.size };
};

const advanceBatch = async (batch, pageProducts, totalProducts) => {
  let keywordIndex = batch.keywordIndex;
  let pageNumber = batch.pageNumber + 1;
  if (pageNumber > batch.pagesPerKeyword || batch.lastCardCount === 0) {
    keywordIndex += 1;
    pageNumber = 1;
  }
  const completedPages = (batch.completedPages || 0) + 1;
  const collectedThisRun = (batch.collectedThisRun || 0) + pageProducts;
  if (batch.stopRequested) {
    await finishBatch(
      "stopped",
      `Đã dừng sau trang hiện tại. Phiên này thêm ${collectedThisRun} sản phẩm; tổng kho ${totalProducts}.`
    );
    return;
  }
  if (keywordIndex >= batch.keywords.length) {
    await saveBatch({ completedPages, collectedThisRun, keywordIndex, pageNumber });
    await finishBatch(
      "completed",
      `Hoàn tất ${completedPages} trang. Phiên này thêm/cập nhật ${collectedThisRun} sản phẩm; tổng kho ${totalProducts}.`
    );
    return;
  }
  await saveBatch({
    completedPages,
    collectedThisRun,
    keywordIndex,
    pageNumber,
    status: "waiting",
    message: `Đã lấy trang vừa mở. Chuẩn bị ngách/trang tiếp theo…`,
  });
  await navigateCurrentPage();
};

const collectScheduledPage = async () => {
  const values = await chrome.storage.local.get(BATCH_KEY);
  let batch = values[BATCH_KEY];
  if (!batch?.running) return;
  try {
    const tab = await chrome.tabs.get(batch.tabId);
    if (!AMAZON_URL.test(String(tab?.url || ""))) {
      await finishBatch("error", "Tab đã rời amazon.com nên phiên cào được dừng.");
      return;
    }
    await saveBatch({ status: "collecting", message: "Đang đọc sản phẩm trên trang hiện tại…" });
    const injection = await chrome.scripting.executeScript({
      target: { tabId: batch.tabId },
      files: ["content.js"],
    });
    const result = injection?.[0]?.result;
    if (!result?.ok) throw new Error(result?.message || "Không đọc được nội dung Amazon.");
    if (result.blocked) {
      await finishBatch("blocked", result.message || "Amazon đang yêu cầu xác minh/CAPTCHA. Hãy xử lý thủ công rồi chạy lại sau.");
      return;
    }
    const merged = await mergeProducts(result);
    batch = await saveBatch({
      lastPageCount: merged.incoming,
      lastCardCount: result.card_count || 0,
      message: `Trang ${batch.pageNumber}: đọc ${result.card_count || 0} thẻ, lưu ${merged.incoming} sản phẩm.`,
    });
    await advanceBatch(batch, merged.incoming, merged.total);
  } catch (error) {
    await finishBatch("error", `Lỗi khi đọc trang: ${error?.message || error}`);
  }
};

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.type === "START_BATCH") {
    (async () => {
      const existing = (await chrome.storage.local.get(BATCH_KEY))[BATCH_KEY];
      if (existing?.running) throw new Error("Một phiên cào hàng loạt đang chạy.");
      const keywords = Array.from(new Set(
        (message.keywords || []).map((value) => String(value).trim()).filter(Boolean)
      )).slice(0, 50);
      const pagesPerKeyword = Math.min(10, Math.max(1, Number(message.pagesPerKeyword) || 1));
      const delaySeconds = Math.min(120, Math.max(8, Number(message.delaySeconds) || 10));
      if (!keywords.length) throw new Error("Danh sách ngách đang trống.");
      const tab = await chrome.tabs.get(message.tabId);
      if (!AMAZON_URL.test(String(tab?.url || ""))) {
        throw new Error("Hãy mở amazon.com trong tab hiện tại trước khi bắt đầu.");
      }
      const batch = {
        version: 1,
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
        message: "Đang bắt đầu phiên cào…",
        startedAt: now(),
        updatedAt: now(),
      };
      await chrome.storage.local.set({ [BATCH_KEY]: batch });
      await navigateCurrentPage();
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
      return saveBatch({
        stopRequested: true,
        message: "Đã nhận yêu cầu dừng; sẽ dừng sau khi xử lý trang hiện tại.",
      });
    })().then((batch) => sendResponse({ ok: true, batch })).catch((error) => {
      sendResponse({ ok: false, message: error?.message || String(error) });
    });
    return true;
  }
});

chrome.tabs.onUpdated.addListener(async (tabId, changeInfo, tab) => {
  if (changeInfo.status !== "complete") return;
  const batch = (await chrome.storage.local.get(BATCH_KEY))[BATCH_KEY];
  if (!batch?.running || batch.tabId !== tabId || !AMAZON_URL.test(String(tab.url || ""))) return;
  await chrome.alarms.clear(ALARM_NAME);
  await saveBatch({
    status: "waiting",
    message: `Trang đã tải. Chờ ${batch.delaySeconds} giây để Amazon hiển thị đủ kết quả…`,
  });
  chrome.alarms.create(ALARM_NAME, { when: Date.now() + batch.delaySeconds * 1000 });
});

chrome.tabs.onRemoved.addListener(async (tabId) => {
  const batch = (await chrome.storage.local.get(BATCH_KEY))[BATCH_KEY];
  if (batch?.running && batch.tabId === tabId) {
    await finishBatch("error", "Tab Amazon đã bị đóng.");
  }
});

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === ALARM_NAME) collectScheduledPage();
});
