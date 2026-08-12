"use strict";

const STATE_KEY = "rinbossImageCollectorState";
const MAX_DIRECT_LINKS = 100;
const URL_ALIASES = ["product url", "amazon url", "temu url", "product link", "url", "link"];
const el = Object.fromEntries([
  "csv-file", "file-name", "direct-links", "load-links", "row-count", "valid-count", "done-count", "max-images",
  "delay-seconds", "start", "stop", "progress-wrap", "progress-status", "progress-percent",
  "progress-bar", "progress-detail", "status", "export", "clear",
].map((id) => [id.replace(/-([a-z])/g, (_match, letter) => letter.toUpperCase()), document.querySelector(`#${id}`)]));

const normalizeHeader = (value) => String(value || "")
  .replace(/^\uFEFF/, "")
  .trim()
  .toLowerCase()
  .replace(/[^a-z0-9]+/g, " ")
  .trim();

const parseCsv = (text) => {
  const records = [];
  let record = [];
  let value = "";
  let quoted = false;
  for (let index = 0; index < text.length; index += 1) {
    const char = text[index];
    if (char === '"') {
      if (quoted && text[index + 1] === '"') { value += '"'; index += 1; }
      else quoted = !quoted;
    } else if (char === "," && !quoted) {
      record.push(value); value = "";
    } else if ((char === "\n" || char === "\r") && !quoted) {
      if (char === "\r" && text[index + 1] === "\n") index += 1;
      record.push(value); value = "";
      if (record.some((part) => String(part).trim())) records.push(record);
      record = [];
    } else value += char;
  }
  record.push(value);
  if (record.some((part) => String(part).trim())) records.push(record);
  if (records.length < 2) throw new Error("CSV không có dòng sản phẩm.");

  const used = new Set();
  const headers = records[0].map((raw, index) => {
    let name = String(raw || "").replace(/^\uFEFF/, "").trim() || `column_${index + 1}`;
    const base = name;
    let suffix = 2;
    while (used.has(name)) name = `${base}_${suffix++}`;
    used.add(name);
    return name;
  });
  const rows = records.slice(1).map((parts) => Object.fromEntries(
    headers.map((header, index) => [header, String(parts[index] ?? "")])
  ));
  return { headers, rows };
};

const rowUrl = (row, headers) => {
  const mapped = new Map(headers.map((header) => [normalizeHeader(header), header]));
  for (const alias of URL_ALIASES) {
    const column = mapped.get(alias);
    const value = String(column ? row[column] : "").trim();
    if (/^https:\/\/(?:www\.)?amazon\.com\//i.test(value) || /^https:\/\/(?:[a-z0-9-]+\.)?temu\.com\//i.test(value)) return value;
  }
  const asinColumn = mapped.get("asin");
  const asin = String(asinColumn ? row[asinColumn] : "").trim();
  return /^[A-Z0-9]{10}$/i.test(asin) ? `https://www.amazon.com/dp/${asin}` : "";
};

const parseDirectLinks = (text) => {
  const rawLinks = String(text || "").split(/\r?\n/).map((value) => value.trim()).filter(Boolean);
  if (!rawLinks.length) throw new Error("Hãy dán ít nhất một link sản phẩm.");
  if (rawLinks.length > MAX_DIRECT_LINKS) {
    throw new Error(`Mỗi lượt dán tối đa ${MAX_DIRECT_LINKS} link. Nên đặt thời gian nghỉ 10–15 giây khi chạy danh sách lớn.`);
  }
  const headers = ["product_url"];
  const seen = new Set();
  const rows = [];
  const invalidLines = [];
  let duplicateCount = 0;
  rawLinks.forEach((value, index) => {
    const row = { product_url: value };
    const url = rowUrl(row, headers);
    if (!url) {
      invalidLines.push(index + 1);
      return;
    }
    const key = url.toLowerCase();
    if (seen.has(key)) {
      duplicateCount += 1;
      return;
    }
    seen.add(key);
    rows.push(row);
  });
  if (invalidLines.length) {
    throw new Error(`Link không hợp lệ ở dòng ${invalidLines.join(", ")}. Chỉ nhận link Amazon.com hoặc Temu.com.`);
  }
  if (!rows.length) throw new Error("Không còn link hợp lệ sau khi bỏ dòng trùng.");
  return { headers, rows, duplicateCount };
};

const csvValue = (value) => `"${String(value ?? "").replace(/"/g, '""')}"`;
const timestamp = () => new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
const setStatus = (message, kind = "") => {
  el.status.textContent = message;
  el.status.className = `status ${kind}`.trim();
};
const getState = async () => (await chrome.storage.local.get(STATE_KEY))[STATE_KEY] || null;

const loadRows = async ({ sourceName, headers, rows, message }) => {
  const previous = await getState();
  if (previous?.running) throw new Error("Hãy dừng phiên đang chạy trước khi nạp danh sách mới.");
  const preparedRows = rows.map((row) => rowUrl(row, headers)
    ? { ...row, image_gallery_count: 0, image_gallery_status: "" }
    : { ...row, image_gallery_count: 0, image_gallery_status: "missing_url" });
  const validCount = preparedRows.filter((row) => rowUrl(row, headers)).length;
  if (!validCount) throw new Error("Không tìm thấy link Amazon/Temu hoặc ASIN hợp lệ.");
  await chrome.storage.local.set({
    [STATE_KEY]: {
      version: 3,
      sourceName,
      headers,
      rows: preparedRows,
      running: false,
      stopRequested: false,
      status: "ready",
      processed: 0,
      total: validCount,
      maxImages: Math.min(10, Math.max(1, Number(el.maxImages.value) || 5)),
      delaySeconds: Math.min(120, Math.max(5, Number(el.delaySeconds.value) || 8)),
      message: message || `Đã nạp ${rows.length} dòng; có ${validCount} link hợp lệ.`,
    },
  });
  await render();
};

const render = async () => {
  const state = await getState();
  const rows = Array.isArray(state?.rows) ? state.rows : [];
  const valid = rows.filter((row) => rowUrl(row, state?.headers || [])).length;
  const done = rows.filter((row) => ["complete", "partial", "no_images", "error", "missing_url"].includes(row.image_gallery_status)).length;
  el.fileName.textContent = state?.sourceName || "Chưa chọn file.";
  el.rowCount.textContent = String(rows.length);
  el.validCount.textContent = String(valid);
  el.doneCount.textContent = String(done);
  el.start.disabled = Boolean(state?.running) || valid === 0;
  el.loadLinks.disabled = Boolean(state?.running);
  el.stop.disabled = !state?.running || Boolean(state?.stopRequested);
  el.export.disabled = rows.length === 0 || done === 0;
  el.clear.disabled = rows.length === 0 || Boolean(state?.running);
  if (state?.maxImages) el.maxImages.value = String(state.maxImages);
  if (state?.delaySeconds) el.delaySeconds.value = String(state.delaySeconds);

  if (!state || !state.total) {
    el.progressWrap.hidden = true;
  } else {
    el.progressWrap.hidden = false;
    const percent = Math.round(Math.min(state.total, state.processed || 0) / state.total * 100);
    el.progressBar.style.width = `${percent}%`;
    el.progressPercent.textContent = `${percent}%`;
    const labels = {
      ready: "Sẵn sàng", starting: "Đang bắt đầu", navigating: "Đang mở sản phẩm",
      waiting: "Đang chờ trang", collecting: "Đang đọc gallery", completed: "Hoàn tất",
      stopped: "Đã dừng", blocked: "Yêu cầu xác minh", error: "Có lỗi",
    };
    el.progressStatus.textContent = labels[state.status] || "Chờ";
    el.progressDetail.textContent = `${state.processed || 0}/${state.total} sản phẩm. ${state.message || ""}`;
  }
  if (state?.message) {
    setStatus(state.message, ["blocked", "error"].includes(state.status) ? "error" : state.status === "completed" ? "success" : "");
  }
};

el.csvFile.addEventListener("change", async () => {
  const file = el.csvFile.files?.[0];
  if (!file) return;
  try {
    const parsed = parseCsv(await file.text());
    await loadRows({
      sourceName: file.name,
      headers: parsed.headers,
      rows: parsed.rows,
      message: `Đã nhập ${parsed.rows.length} dòng từ CSV.`,
    });
    setStatus(`Đã nhập ${file.name}.`, "success");
  } catch (error) {
    setStatus(error?.message || String(error), "error");
  }
});

el.loadLinks.addEventListener("click", async () => {
  try {
    const parsed = parseDirectLinks(el.directLinks.value);
    const duplicateNote = parsed.duplicateCount ? `; đã bỏ ${parsed.duplicateCount} link trùng` : "";
    await loadRows({
      sourceName: "direct_product_links.csv",
      headers: parsed.headers,
      rows: parsed.rows,
      message: `Đã nạp ${parsed.rows.length} link trực tiếp${duplicateNote}.`,
    });
    setStatus(`Đã nạp ${parsed.rows.length} link. Chọn 5 ảnh rồi bấm bắt đầu.`, "success");
  } catch (error) {
    setStatus(error?.message || String(error), "error");
  }
});

el.start.addEventListener("click", async () => {
  try {
    const response = await chrome.runtime.sendMessage({
      type: "START_IMAGE_BATCH",
      maxImages: Math.min(10, Math.max(1, Number(el.maxImages.value) || 5)),
      delaySeconds: Math.min(120, Math.max(5, Number(el.delaySeconds.value) || 8)),
    });
    if (!response?.ok) throw new Error(response?.message || "Không bắt đầu được.");
    await render();
  } catch (error) { setStatus(error?.message || String(error), "error"); }
});

el.stop.addEventListener("click", async () => {
  const response = await chrome.runtime.sendMessage({ type: "STOP_IMAGE_BATCH" });
  if (!response?.ok) setStatus(response?.message || "Không gửi được yêu cầu dừng.", "error");
  await render();
});

el.export.addEventListener("click", async () => {
  const state = await getState();
  if (!state?.rows?.length) return;
  const imageColumns = Array.from({ length: state.maxImages || 5 }, (_value, index) => `image_url_${index + 1}`);
  const headers = Array.from(new Set([
    ...(state.headers || []), ...imageColumns, "image_gallery_count", "image_gallery_status",
  ]));
  const lines = [headers.map(csvValue).join(",")];
  state.rows.forEach((row) => lines.push(headers.map((header) => csvValue(row[header])).join(",")));
  const blobUrl = URL.createObjectURL(new Blob([`\uFEFF${lines.join("\r\n")}`], { type: "text/csv;charset=utf-8" }));
  const anchor = document.createElement("a");
  anchor.href = blobUrl;
  anchor.download = `${String(state.sourceName || "products").replace(/\.csv$/i, "")}_gallery_${timestamp()}.csv`;
  anchor.click();
  setTimeout(() => URL.revokeObjectURL(blobUrl), 1500);
});

el.clear.addEventListener("click", async () => {
  if (!confirm("Xóa file và toàn bộ tiến độ ảnh của phiên hiện tại?")) return;
  await chrome.runtime.sendMessage({ type: "CLEAR_IMAGE_BATCH" });
  el.csvFile.value = "";
  el.directLinks.value = "";
  await render();
  setStatus("Đã xóa phiên hiện tại.", "success");
});

chrome.storage.onChanged.addListener((changes, area) => {
  if (area === "local" && changes[STATE_KEY]) render();
});

render().catch((error) => setStatus(error?.message || String(error), "error"));
