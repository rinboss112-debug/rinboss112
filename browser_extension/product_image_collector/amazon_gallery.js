(() => {
  "use strict";
  const bodyText = `${document.title}\n${document.body?.innerText || ""}`.slice(0, 20000);
  if (/(?:captcha|robot check|enter the characters you see|sorry! something went wrong|unusual activity)/i.test(bodyText)) {
    return { ok: true, blocked: true, images: [], message: "Amazon yêu cầu CAPTCHA/Robot Check; phiên đã dừng." };
  }

  const images = [];
  const normalize = (value) => {
    let text = String(value || "").trim().replace(/\\\//g, "/").replace(/\\u002F/gi, "/").replace(/&amp;/g, "&");
    if (text.startsWith("//")) text = `https:${text}`;
    if (!/^https?:\/\//i.test(text) || !/(?:media-)?amazon\.com\/images\//i.test(text)) return "";
    return text.replace(/\._[^/?]+_(?=\.[a-zA-Z0-9]+(?:[?#]|$))/, "");
  };
  const add = (value) => {
    const url = normalize(value);
    const key = url.split(/[?#]/)[0];
    if (url && !images.some((item) => item.split(/[?#]/)[0] === key) && images.length < 30) images.push(url);
  };
  const addDynamic = (value) => {
    try {
      const parsed = JSON.parse(String(value || ""));
      Object.entries(parsed).sort((a, b) => {
        const area = (entry) => Array.isArray(entry[1]) ? Number(entry[1][0] || 0) * Number(entry[1][1] || 0) : 0;
        return area(b) - area(a);
      }).forEach(([url]) => add(url));
    } catch (_error) { /* not JSON */ }
  };
  const addImage = (image) => {
    add(image?.getAttribute("data-old-hires"));
    addDynamic(image?.getAttribute("data-a-dynamic-image"));
    add(image?.currentSrc);
    add(image?.src);
    String(image?.srcset || "").split(",").forEach((part) => add(part.trim().split(/\s+/)[0]));
  };

  document.querySelectorAll("#landingImage, #imgTagWrapperId img, #altImages img, #imageBlock img, img[data-a-dynamic-image]").forEach(addImage);
  add(document.querySelector("meta[property='og:image']")?.content);
  document.querySelectorAll("script").forEach((script) => {
    const text = script.textContent || "";
    for (const pattern of [/"hiRes"\s*:\s*"([^"]+)"/gi, /"large"\s*:\s*"([^"]+)"/gi, /"mainUrl"\s*:\s*"([^"]+)"/gi]) {
      for (const match of text.matchAll(pattern)) add(match[1]);
    }
  });
  return { ok: true, blocked: false, images, page_url: location.href };
})();
