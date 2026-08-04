"use strict";

const AMAZON_KEY = "rinbossMarketplaceAmazonProducts";
const TEMU_KEY = "rinbossMarketplaceTemuProducts";
const SETTINGS_KEY = "rinbossMarketplaceSettings";
const BATCH_KEY = "rinbossMarketplaceBatch";
const AMAZON_COLUMNS = [
  "title", "image_url", "price", "variants", "delivery_options", "keyword",
  "asin", "product_url", "currency", "rating", "review_count", "prime",
  "free_shipping", "fast_shipping", "delivery_available", "sponsored", "scraped_at",
];
const TEMU_COLUMNS = [
  "title", "image_url", "price", "original_price", "keyword", "product_id",
  "product_url", "units_sold", "sold_text", "rating", "review_count", "badge",
  "free_shipping", "scraped_at",
];
const SOURCES = {
  amazon: {
    label: "Amazon", key: AMAZON_KEY, columns: AMAZON_COLUMNS,
    urlPattern: /^https:\/\/(?:www\.)?amazon\.com\//i, contentFile: "content.js",
  },
  temu: {
    label: "Temu US", key: TEMU_KEY, columns: TEMU_COLUMNS,
    urlPattern: /^https:\/\/(?:[a-z0-9-]+\.)?temu\.com\//i, contentFile: "temu_content.js",
  },
};

const el = Object.fromEntries([
  "marketplace", "product-count", "source-count-label", "last-page-count", "status",
  "exclude-brands", "exclude-brands-row", "collect", "export-csv", "export-all-csv",
  "export-json", "clear", "txt-file", "keywords", "keyword-count", "pages-per-keyword",
  "delay-seconds", "start-batch", "stop-batch", "progress-wrap", "progress-bar",
  "batch-label", "batch-percent", "batch-detail", "filter-query", "filter-min-price",
  "filter-max-price", "filter-shipping", "filtered-count",
].map((id) => [id.replace(/-([a-z])/g, (_match, letter) => letter.toUpperCase()), document.querySelector(`#${id}`)]));

let cachedProducts = [];
const currentSource = () => SOURCES[el.marketplace.value] || SOURCES.temu;
const setStatus = (message, kind = "") => {
  el.status.textContent = message;
  el.status.className = `status ${kind}`.trim();
};
const parseKeywords = () => Array.from(new Set(
  el.keywords.value.split(/\r?\n/).map((value) => value.trim()).filter(Boolean)
));
const updateKeywordCount = () => {
  const count = parseKeywords().length;
  el.keywordCount.textContent = `${count} ngách hợp lệ${count > 50 ? "; chỉ chạy 50 ngách đầu" : ""}`;
};
const getStored = async () => {
  const values = await chrome.storage.local.get([AMAZON_KEY, TEMU_KEY, SETTINGS_KEY, BATCH_KEY]);
  return {
    amazon: Array.isArray(values[AMAZON_KEY]) ? values[AMAZON_KEY] : [],
    temu: Array.isArray(values[TEMU_KEY]) ? values[TEMU_KEY] : [],
    settings: values[SETTINGS_KEY] || {},
    batch: values[BATCH_KEY] || null,
  };
};

const filtered = () => {
  const query = el.filterQuery.value.trim().toLowerCase();
  const minimum = Math.max(0, Number(el.filterMinPrice.value) || 0);
  const maximum = Math.max(0, Number(el.filterMaxPrice.value) || 0);
  const shipping = el.filterShipping.value;
  return cachedProducts.filter((product) => {
    const text = `${product.title || ""} ${product.keyword || ""} ${product.asin || ""} ${product.product_id || ""}`.toLowerCase();
    const price = Number(product.price);
    if (query && !text.includes(query)) return false;
    if (minimum && (!Number.isFinite(price) || price < minimum)) return false;
    if (maximum && (!Number.isFinite(price) || price > maximum)) return false;
    if (shipping === "free" && !product.free_shipping) return false;
    if (shipping === "prime" && !product.prime) return false;
    if (shipping === "fast" && !product.fast_shipping) return false;
    if (shipping === "not-fresh" && /fresh/i.test(String(product.delivery_options || ""))) return false;
    return true;
  });
};
const renderFilter = () => {
  const count = filtered().length;
  el.filteredCount.textContent = `${count}/${cachedProducts.length} phù hợp`;
  el.exportCsv.disabled = count === 0;
};
const renderBatch = (batch) => {
  const running = Boolean(batch?.running);
  el.startBatch.disabled = running;
  el.stopBatch.disabled = !running || Boolean(batch?.stopRequested);
  el.collect.disabled = running;
  el.marketplace.disabled = running;
  if (!batch) { el.progressWrap.hidden = true; return; }
  el.progressWrap.hidden = false;
  const total = Math.max(0, Number(batch.totalPages) || 0);
  const completed = Math.min(total, Math.max(0, Number(batch.completedPages) || 0));
  const percent = total ? Math.round(completed / total * 100) : 0;
  el.progressBar.style.width = `${percent}%`;
  el.batchPercent.textContent = `${percent}%`;
  const labels = {
    starting: "Đang bắt đầu", navigating: "Đang mở trang", waiting: "Đang chờ",
    collecting: "Đang đọc", completed: "Hoàn tất", stopped: "Đã dừng",
    error: "Có lỗi", blocked: "Yêu cầu xác minh",
  };
  el.batchLabel.textContent = labels[batch.status] || "Chờ";
  el.batchDetail.textContent = `${batch.currentKeyword || ""}${running ? ` — lượt ${batch.pageNumber}/${batch.pagesPerKeyword}` : ""}. ${batch.message || ""}`.trim();
  if (batch.message) setStatus(batch.message, ["error", "blocked"].includes(batch.status) ? "error" : batch.status === "completed" ? "success" : "");
};
const render = async () => {
  const stored = await getStored();
  const config = currentSource();
  cachedProducts = stored[el.marketplace.value];
  el.productCount.textContent = String(cachedProducts.length);
  el.sourceCountLabel.textContent = `Sản phẩm ${config.label}`;
  el.excludeBrandsRow.hidden = el.marketplace.value !== "amazon";
  if (el.marketplace.value === "temu" && !["all", "free"].includes(el.filterShipping.value)) el.filterShipping.value = "all";
  el.lastPageCount.textContent = String(stored.batch?.marketplace === el.marketplace.value ? stored.batch.lastPageCount || 0 : 0);
  el.exportAllCsv.disabled = cachedProducts.length === 0;
  el.clear.disabled = cachedProducts.length === 0 || Boolean(stored.batch?.running);
  el.exportJson.disabled = stored.amazon.length + stored.temu.length === 0;
  renderBatch(stored.batch);
  renderFilter();
};

const csvValue = (value) => value === null || value === undefined ? "" : `"${String(value).replace(/"/g, '""')}"`;
const timestamp = () => new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
const download = (content, filename, type) => {
  const url = URL.createObjectURL(new Blob([content], { type }));
  const anchor = document.createElement("a");
  anchor.href = url; anchor.download = filename; anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 1500);
};
const downloadCsv = (products, config, filteredName) => {
  const rows = [config.columns.map(csvValue).join(",")];
  products.forEach((product) => rows.push(config.columns.map((column) => csvValue(product[column])).join(",")));
  download(`\uFEFF${rows.join("\r\n")}`, `${el.marketplace.value}_extension_${filteredName}_${timestamp()}.csv`, "text/csv;charset=utf-8");
};
const mergeManual = async (result) => {
  const stored = await getStored();
  const sourceName = el.marketplace.value;
  const config = currentSource();
  const incoming = (result.products || []).filter(
    (product) => !(sourceName === "amazon" && el.excludeBrands.checked && product._excluded_brand)
  );
  const identity = (product) => sourceName === "amazon"
    ? product.asin : (product.product_id || product.product_url || `${product.keyword}|${product.title}`);
  const merged = new Map(stored[sourceName].map((product) => [identity(product), product]));
  incoming.forEach((product) => {
    const cleaned = { ...product };
    delete cleaned._excluded_brand; delete cleaned._fresh;
    merged.set(identity(cleaned), cleaned);
  });
  await chrome.storage.local.set({ [config.key]: Array.from(merged.values()) });
  return { incoming: incoming.length, total: merged.size };
};

el.keywords.addEventListener("input", updateKeywordCount);
[el.filterQuery, el.filterMinPrice, el.filterMaxPrice].forEach((node) => node.addEventListener("input", renderFilter));
el.filterShipping.addEventListener("change", renderFilter);
el.txtFile.addEventListener("change", async () => {
  const file = el.txtFile.files?.[0];
  if (!file) return;
  try { el.keywords.value = await file.text(); updateKeywordCount(); setStatus(`Đã nhập ${file.name}.`, "success"); }
  catch (error) { setStatus(`Không đọc được TXT: ${error?.message || error}`, "error"); }
});
el.marketplace.addEventListener("change", async () => {
  const stored = await getStored();
  await chrome.storage.local.set({ [SETTINGS_KEY]: { ...stored.settings, marketplace: el.marketplace.value } });
  await render();
  setStatus(`Đã chuyển sang ${currentSource().label}.`, "success");
});
el.excludeBrands.addEventListener("change", async () => {
  const stored = await getStored();
  await chrome.storage.local.set({ [SETTINGS_KEY]: { ...stored.settings, excludeBrands: el.excludeBrands.checked } });
});

el.startBatch.addEventListener("click", async () => {
  const keywords = parseKeywords().slice(0, 50);
  const pagesPerKeyword = Math.min(10, Math.max(1, Number(el.pagesPerKeyword.value) || 1));
  const delaySeconds = Math.min(120, Math.max(8, Number(el.delaySeconds.value) || 10));
  const config = currentSource();
  try {
    if (!keywords.length) throw new Error("Hãy nhập ít nhất một ngách.");
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab?.id || !config.urlPattern.test(String(tab.url || ""))) throw new Error(`Hãy mở ${config.label} trong tab hiện tại.`);
    const stored = await getStored();
    await chrome.storage.local.set({
      [SETTINGS_KEY]: { ...stored.settings, marketplace: el.marketplace.value, excludeBrands: el.excludeBrands.checked, pagesPerKeyword, delaySeconds },
    });
    const response = await chrome.runtime.sendMessage({
      type: "START_BATCH", tabId: tab.id, marketplace: el.marketplace.value,
      keywords, pagesPerKeyword, delaySeconds,
    });
    if (!response?.ok) throw new Error(response?.message || "Không bắt đầu được.");
    renderBatch(response.batch);
    setStatus(`Đã bắt đầu ${config.label}: ${keywords.length} ngách × ${pagesPerKeyword} lượt.`, "success");
  } catch (error) { setStatus(error?.message || String(error), "error"); }
});
el.stopBatch.addEventListener("click", async () => {
  const response = await chrome.runtime.sendMessage({ type: "STOP_BATCH" });
  if (!response?.ok) setStatus(response?.message || "Không gửi được yêu cầu dừng.", "error");
  else renderBatch(response.batch);
});
el.collect.addEventListener("click", async () => {
  const config = currentSource();
  el.collect.disabled = true;
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab?.id || !config.urlPattern.test(String(tab.url || ""))) throw new Error(`Hãy mở ${config.label}.`);
    const injection = await chrome.scripting.executeScript({ target: { tabId: tab.id }, files: [config.contentFile] });
    const result = injection?.[0]?.result;
    if (!result?.ok || result.blocked) throw new Error(result?.message || `Không đọc được ${config.label}.`);
    if (!result.card_count) throw new Error("Trang chưa có thẻ sản phẩm đang hiển thị.");
    const merged = await mergeManual(result);
    el.lastPageCount.textContent = String(merged.incoming);
    setStatus(`Đã đọc ${merged.incoming}/${result.card_count}; tổng kho ${merged.total}.`, "success");
    await render();
  } catch (error) { setStatus(error?.message || String(error), "error"); }
  finally { el.collect.disabled = Boolean((await getStored()).batch?.running); }
});

el.exportCsv.addEventListener("click", () => downloadCsv(filtered(), currentSource(), "filtered"));
el.exportAllCsv.addEventListener("click", () => downloadCsv(cachedProducts, currentSource(), "all"));
el.exportJson.addEventListener("click", async () => {
  const stored = await getStored();
  download(JSON.stringify({ version: 2, exported_at: new Date().toISOString(), amazon_products: stored.amazon, temu_products: stored.temu }, null, 2), `marketplace_extension_${timestamp()}.json`, "application/json;charset=utf-8");
});
el.clear.addEventListener("click", async () => {
  const config = currentSource();
  if (!confirm(`Xóa toàn bộ dữ liệu ${config.label}?`)) return;
  await chrome.storage.local.remove(config.key);
  await render();
});

chrome.storage.onChanged.addListener((changes, area) => {
  if (area === "local" && (changes[AMAZON_KEY] || changes[TEMU_KEY] || changes[BATCH_KEY])) render();
});

(async () => {
  const stored = await getStored();
  if (stored.settings.marketplace && SOURCES[stored.settings.marketplace]) el.marketplace.value = stored.settings.marketplace;
  el.excludeBrands.checked = stored.settings.excludeBrands !== false;
  el.pagesPerKeyword.value = String(stored.settings.pagesPerKeyword || 2);
  el.delaySeconds.value = String(stored.settings.delaySeconds || 10);
  updateKeywordCount();
  await render();
})().catch((error) => setStatus(error?.message || String(error), "error"));
