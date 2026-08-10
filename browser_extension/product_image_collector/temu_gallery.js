(() => {
  "use strict";
  const bodyText = `${document.title}\n${document.body?.innerText || ""}`.slice(0, 20000);
  if (/(?:captcha|verify you are human|unusual activity|security check|access denied|check your network connection)/i.test(bodyText)) {
    return { ok: true, blocked: true, images: [], message: "Temu yêu cầu xác minh hoặc không trả trang sản phẩm; phiên đã dừng." };
  }

  const images = [];
  const normalize = (value) => {
    let text = String(value || "").trim().replace(/\\\//g, "/").replace(/\\u002F/gi, "/").replace(/&amp;/g, "&");
    if (text.startsWith("//")) text = `https:${text}`;
    if (!/^https?:\/\//i.test(text)) return "";
    try {
      const url = new URL(text);
      if (!/(?:kwcdn\.com|temu\.com)$/i.test(url.hostname) && !/(?:kwcdn\.com|temu\.com)/i.test(url.hostname)) return "";
      if (/(?:logo|icon|avatar|flag|payment|sprite)/i.test(url.pathname)) return "";
      ["imageMogr2", "imageView2", "thumbnail", "width", "height", "w", "h"].forEach((name) => url.searchParams.delete(name));
      return url.href;
    } catch (_error) { return ""; }
  };
  const add = (value) => {
    const url = normalize(value);
    const key = url.split(/[?#]/)[0];
    if (url && !images.some((item) => item.split(/[?#]/)[0] === key) && images.length < 40) images.push(url);
  };
  const addImage = (image) => {
    add(image?.getAttribute("data-src"));
    add(image?.getAttribute("data-original"));
    add(image?.currentSrc);
    add(image?.src);
    String(image?.srcset || "").split(",").forEach((part) => add(part.trim().split(/\s+/)[0]));
  };
  const walkImages = (value, depth = 0) => {
    if (depth > 7 || value == null) return;
    if (typeof value === "string") { add(value); return; }
    if (Array.isArray(value)) { value.forEach((item) => walkImages(item, depth + 1)); return; }
    if (typeof value === "object") {
      Object.entries(value).forEach(([key, item]) => {
        if (/^(?:image|images|imageUrl|image_url|contentUrl|thumbnailUrl)$/i.test(key)) walkImages(item, depth + 1);
        else if (depth < 3 && /product/i.test(key)) walkImages(item, depth + 1);
      });
    }
  };

  document.querySelectorAll("script[type='application/ld+json']").forEach((script) => {
    try { walkImages(JSON.parse(script.textContent || "null")); } catch (_error) { /* invalid JSON-LD */ }
  });
  add(document.querySelector("meta[property='og:image']")?.content);
  add(document.querySelector("meta[name='twitter:image']")?.content);
  document.querySelectorAll("[class*='gallery' i] img, [class*='thumb' i] img, [class*='carousel' i] img, main img").forEach((image, index) => {
    if (index < 80 && (image.naturalWidth >= 180 || image.width >= 180 || /product|item|goods/i.test(image.alt || ""))) addImage(image);
  });
  document.querySelectorAll("script:not([src])").forEach((script) => {
    const text = script.textContent || "";
    if (!/(?:kwcdn\.com|product_image|goods_image)/i.test(text)) return;
    for (const match of text.matchAll(/https?:\\?\/\\?\/[^"'\s<>]+/gi)) add(match[0]);
  });
  return { ok: true, blocked: false, images, page_url: location.href };
})();
