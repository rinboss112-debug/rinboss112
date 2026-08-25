"use strict";

const STORAGE_KEY = "rinbossAmazonProducts";
const SETTINGS_KEY = "rinbossAmazonSettings";
const BATCH_KEY = "rinbossAmazonBatch";
const TEMU_COMPLIANCE = globalThis.RinBossTemuCompliance;
const CSV_COLUMNS = [
  "title", "image_url", "price", "variants", "delivery_options", "keyword",
  "asin", "product_url", "currency", "rating", "review_count", "prime",
  "free_shipping", "fast_shipping", "delivery_available", "sponsored", "scraped_at",
];

const elements = {
  count: document.querySelector("#product-count"),
  lastPageCount: document.querySelector("#last-page-count"),
  status: document.querySelector("#status"),
  excludeBrands: document.querySelector("#exclude-brands"),
  collect: document.querySelector("#collect"),
  exportCsv: document.querySelector("#export-csv"),
  exportAllCsv: document.querySelector("#export-all-csv"),
  exportJson: document.querySelector("#export-json"),
  clear: document.querySelector("#clear"),
  txtFile: document.querySelector("#txt-file"),
  keywords: document.querySelector("#keywords"),
  keywordCount: document.querySelector("#keyword-count"),
  pages: document.querySelector("#pages-per-keyword"),
  delay: document.querySelector("#delay-seconds"),
  startBatch: document.querySelector("#start-batch"),
  stopBatch: document.querySelector("#stop-batch"),
  progressWrap: document.querySelector("#progress-wrap"),
  progressBar: document.querySelector("#progress-bar"),
  batchLabel: document.querySelector("#batch-label"),
  batchPercent: document.querySelector("#batch-percent"),
  batchDetail: document.querySelector("#batch-detail"),
  filterQuery: document.querySelector("#filter-query"),
  filterMinPrice: document.querySelector("#filter-min-price"),
  filterMaxPrice: document.querySelector("#filter-max-price"),
  filterShipping: document.querySelector("#filter-shipping"),
  filterTemuRisk: document.querySelector("#filter-temu-risk"),
  filterTemuRiskTerms: document.querySelector("#filter-temu-risk-terms"),
  temuRiskCount: document.querySelector("#temu-risk-count"),
  filteredCount: document.querySelector("#filtered-count"),
};

let cachedProducts = [];

const setStatus = (message, kind = "") => {
  elements.status.textContent = message;
  elements.status.className = `status ${kind}`.trim();
};

const parseKeywords = () => Array.from(new Set(
  elements.keywords.value.split(/\r?\n/).map((value) => value.trim()).filter(Boolean)
));

const updateKeywordCount = () => {
  const keywords = parseKeywords();
  elements.keywordCount.textContent = `${keywords.length} ngách hợp lệ${keywords.length > 50 ? "; chỉ chạy 50 ngách đầu" : ""}`;
};

const getStored = async () => {
  const values = await chrome.storage.local.get([STORAGE_KEY, SETTINGS_KEY, BATCH_KEY]);
  return {
    products: Array.isArray(values[STORAGE_KEY]) ? values[STORAGE_KEY] : [],
    settings: values[SETTINGS_KEY] || {},
    batch: values[BATCH_KEY] || null,
  };
};

const productRiskMatches = (product, terms) => TEMU_COMPLIANCE.matchedRiskTerms(
  `${product.title || ""} ${product.keyword || ""}`,
  terms,
);

const filteredProducts = (products = cachedProducts) => {
  const query = elements.filterQuery.value.trim().toLocaleLowerCase();
  const minimum = Math.max(0, Number(elements.filterMinPrice.value) || 0);
  const maximum = Math.max(0, Number(elements.filterMaxPrice.value) || 0);
  const shipping = elements.filterShipping.value;
  const riskTerms = TEMU_COMPLIANCE.normalizeRiskTerms(elements.filterTemuRiskTerms.value);
  const excludeTemuRisk = elements.filterTemuRisk.checked;
  return products.filter((product) => {
    const haystack = `${product.title || ""} ${product.keyword || ""} ${product.asin || ""}`.toLocaleLowerCase();
    if (query && !haystack.includes(query)) return false;
    const price = Number(product.price);
    if (minimum > 0 && (!Number.isFinite(price) || price < minimum)) return false;
    if (maximum > 0 && (!Number.isFinite(price) || price > maximum)) return false;
    if (shipping === "prime" && !product.prime) return false;
    if (shipping === "free" && !product.free_shipping) return false;
    if (shipping === "fast" && !product.fast_shipping) return false;
    if (shipping === "not-fresh" && /fresh/i.test(String(product.delivery_options || ""))) return false;
    if (excludeTemuRisk && productRiskMatches(product, riskTerms).length) return false;
    return true;
  });
};

const renderFilterCount = () => {
  const riskTerms = TEMU_COMPLIANCE.normalizeRiskTerms(elements.filterTemuRiskTerms.value);
  const riskCount = cachedProducts.filter((product) =>
    productRiskMatches(product, riskTerms).length
  ).length;
  const count = filteredProducts().length;
  elements.filteredCount.textContent = `${count}/${cachedProducts.length} phù hợp`;
  elements.temuRiskCount.textContent = `${riskCount} sản phẩm được cảnh báo giấy tờ.`;
  elements.exportCsv.disabled = count === 0;
};

const renderBatch = (batch) => {
  const running = Boolean(batch?.running);
  elements.startBatch.disabled = running;
  elements.stopBatch.disabled = !running || Boolean(batch?.stopRequested);
  elements.collect.disabled = running;
  if (!batch) {
    elements.progressWrap.hidden = true;
    return;
  }
  elements.progressWrap.hidden = false;
  const total = Math.max(0, Number(batch.totalPages) || 0);
  const completed = Math.min(total, Math.max(0, Number(batch.completedPages) || 0));
  const percent = total ? Math.round((completed / total) * 100) : 0;
  elements.progressBar.style.width = `${percent}%`;
  elements.batchPercent.textContent = `${percent}%`;
  const labels = {
    starting: "Đang bắt đầu", navigating: "Đang mở trang", waiting: "Đang chờ trang",
    collecting: "Đang đọc", completed: "Hoàn tất", stopped: "Đã dừng",
    error: "Có lỗi", blocked: "Amazon yêu cầu xác minh",
  };
  elements.batchLabel.textContent = labels[batch.status] || "Chờ";
  elements.batchDetail.textContent = `${batch.currentKeyword || ""}${batch.running ? ` — trang ${batch.pageNumber}/${batch.pagesPerKeyword}` : ""}. ${batch.message || ""}`.trim();
  if (batch.message) {
    setStatus(batch.message, ["error", "blocked"].includes(batch.status) ? "error" : batch.status === "completed" ? "success" : "");
  }
};

const refresh = async () => {
  const { products, settings, batch } = await getStored();
  cachedProducts = products;
  elements.count.textContent = String(products.length);
  elements.lastPageCount.textContent = String(batch?.lastPageCount || 0);
  elements.excludeBrands.checked = settings.excludeBrands !== false;
  elements.pages.value = String(settings.pagesPerKeyword || elements.pages.value || 2);
  elements.delay.value = String(settings.delaySeconds || elements.delay.value || 10);
  elements.filterTemuRisk.checked = settings.excludeTemuComplianceRisk !== false;
  if (!elements.filterTemuRiskTerms.dataset.ready) {
    const terms = Array.isArray(settings.temuComplianceRiskTerms)
      ? settings.temuComplianceRiskTerms
      : TEMU_COMPLIANCE.DEFAULT_RISK_TERMS;
    elements.filterTemuRiskTerms.value = terms.join("\n");
    elements.filterTemuRiskTerms.dataset.ready = "true";
  }
  const disabled = products.length === 0;
  elements.exportAllCsv.disabled = disabled;
  elements.exportJson.disabled = disabled;
  elements.clear.disabled = disabled || Boolean(batch?.running);
  renderBatch(batch);
  renderFilterCount();
};

const csvValue = (value) => {
  if (value === null || value === undefined) return "";
  return `"${String(value).replace(/"/g, '""')}"`;
};

const download = (content, filename, type) => {
  const blob = new Blob([content], { type });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 1500);
};

const timestamp = () => new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);

elements.keywords.addEventListener("input", updateKeywordCount);
[elements.filterQuery, elements.filterMinPrice, elements.filterMaxPrice].forEach((element) => {
  element.addEventListener("input", renderFilterCount);
});
elements.filterShipping.addEventListener("change", renderFilterCount);
elements.filterTemuRisk.addEventListener("change", async () => {
  renderFilterCount();
  const { settings } = await getStored();
  await chrome.storage.local.set({
    [SETTINGS_KEY]: { ...settings, excludeTemuComplianceRisk: elements.filterTemuRisk.checked },
  });
});
elements.filterTemuRiskTerms.addEventListener("input", renderFilterCount);
elements.filterTemuRiskTerms.addEventListener("change", async () => {
  const terms = TEMU_COMPLIANCE.normalizeRiskTerms(elements.filterTemuRiskTerms.value);
  elements.filterTemuRiskTerms.value = terms.join("\n");
  const { settings } = await getStored();
  await chrome.storage.local.set({
    [SETTINGS_KEY]: { ...settings, temuComplianceRiskTerms: terms },
  });
  renderFilterCount();
});
elements.txtFile.addEventListener("change", async () => {
  const file = elements.txtFile.files?.[0];
  if (!file) return;
  try {
    elements.keywords.value = await file.text();
    updateKeywordCount();
    setStatus(`Đã nhập danh sách từ ${file.name}.`, "success");
  } catch (error) {
    setStatus(`Không đọc được file TXT: ${error?.message || error}`, "error");
  }
});

elements.excludeBrands.addEventListener("change", async () => {
  const { settings } = await getStored();
  await chrome.storage.local.set({
    [SETTINGS_KEY]: { ...settings, excludeBrands: elements.excludeBrands.checked },
  });
});

elements.startBatch.addEventListener("click", async () => {
  const keywords = parseKeywords().slice(0, 50);
  const pagesPerKeyword = Math.min(10, Math.max(1, Number(elements.pages.value) || 1));
  const delaySeconds = Math.min(120, Math.max(8, Number(elements.delay.value) || 10));
  if (!keywords.length) {
    setStatus("Hãy nhập ít nhất một ngách hoặc chọn file TXT.", "error");
    return;
  }
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab?.id || !/^https:\/\/(?:www\.)?amazon\.com\//i.test(String(tab.url || ""))) {
      throw new Error("Hãy mở amazon.com trong tab hiện tại trước khi bắt đầu.");
    }
    const { settings } = await getStored();
    await chrome.storage.local.set({
      [SETTINGS_KEY]: { ...settings, excludeBrands: elements.excludeBrands.checked, pagesPerKeyword, delaySeconds },
    });
    const response = await chrome.runtime.sendMessage({
      type: "START_BATCH", tabId: tab.id, keywords, pagesPerKeyword, delaySeconds,
    });
    if (!response?.ok) throw new Error(response?.message || "Không bắt đầu được phiên cào.");
    renderBatch(response.batch);
    setStatus(`Đã bắt đầu ${keywords.length} ngách × ${pagesPerKeyword} trang.`, "success");
  } catch (error) {
    setStatus(error?.message || String(error), "error");
  }
});

elements.stopBatch.addEventListener("click", async () => {
  elements.stopBatch.disabled = true;
  const response = await chrome.runtime.sendMessage({ type: "STOP_BATCH" });
  if (!response?.ok) setStatus(response?.message || "Không gửi được yêu cầu dừng.", "error");
  else renderBatch(response.batch);
});

elements.collect.addEventListener("click", async () => {
  elements.collect.disabled = true;
  setStatus("Đang đọc trang Amazon hiện tại…");
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab?.id || !/^https:\/\/(?:www\.)?amazon\.com\//i.test(String(tab.url || ""))) {
      throw new Error("Hãy mở một trang amazon.com rồi thử lại.");
    }
    const injection = await chrome.scripting.executeScript({ target: { tabId: tab.id }, files: ["content.js"] });
    const result = injection?.[0]?.result;
    if (!result?.ok) throw new Error(result?.message || "Không đọc được nội dung trang Amazon.");
    if (result.blocked) throw new Error(result.message);
    if (!result.card_count) throw new Error("Trang này không có thẻ kết quả. Hãy mở trang tìm kiếm Amazon.");
    const { products: stored } = await getStored();
    const incoming = result.products.filter((product) => !(elements.excludeBrands.checked && product._excluded_brand));
    const merged = new Map(stored.map((product) => [product.asin, product]));
    incoming.forEach((product) => {
      const cleaned = { ...product };
      delete cleaned._excluded_brand;
      delete cleaned._fresh;
      merged.set(cleaned.asin, cleaned);
    });
    await chrome.storage.local.set({ [STORAGE_KEY]: Array.from(merged.values()) });
    elements.lastPageCount.textContent = String(incoming.length);
    setStatus(`Đã lấy ${incoming.length}/${result.card_count} sản phẩm. Tổng hiện có ${merged.size}.`, "success");
    await refresh();
  } catch (error) {
    setStatus(error?.message || String(error), "error");
  } finally {
    const batch = (await getStored()).batch;
    elements.collect.disabled = Boolean(batch?.running);
  }
});

elements.exportCsv.addEventListener("click", async () => {
  const products = filteredProducts();
  const rows = [CSV_COLUMNS.map(csvValue).join(",")];
  products.forEach((product) => rows.push(CSV_COLUMNS.map((column) => csvValue(product[column])).join(",")));
  download(`\uFEFF${rows.join("\r\n")}`, `amazon_extension_filtered_${timestamp()}.csv`, "text/csv;charset=utf-8");
  setStatus(`Đã xuất ${products.length} sản phẩm phù hợp bộ lọc.`, "success");
});

elements.exportAllCsv.addEventListener("click", async () => {
  const { products } = await getStored();
  const rows = [CSV_COLUMNS.map(csvValue).join(",")];
  products.forEach((product) => rows.push(CSV_COLUMNS.map((column) => csvValue(product[column])).join(",")));
  download(`\uFEFF${rows.join("\r\n")}`, `amazon_extension_all_${timestamp()}.csv`, "text/csv;charset=utf-8");
  setStatus(`Đã xuất toàn bộ ${products.length} sản phẩm.`, "success");
});

elements.exportJson.addEventListener("click", async () => {
  const { products } = await getStored();
  download(JSON.stringify({ version: 1, products }, null, 2), `amazon_extension_${timestamp()}.json`, "application/json;charset=utf-8");
  setStatus(`Đã xuất ${products.length} sản phẩm thành JSON.`, "success");
});

elements.clear.addEventListener("click", async () => {
  if (!confirm("Xóa toàn bộ sản phẩm đã lưu trong extension?")) return;
  await chrome.storage.local.remove(STORAGE_KEY);
  elements.lastPageCount.textContent = "0";
  setStatus("Đã xóa dữ liệu trong extension.", "success");
  await refresh();
});

chrome.storage.onChanged.addListener((changes, areaName) => {
  if (areaName === "local" && (changes[STORAGE_KEY] || changes[BATCH_KEY])) refresh();
});

updateKeywordCount();
refresh().catch((error) => setStatus(error?.message || String(error), "error"));
