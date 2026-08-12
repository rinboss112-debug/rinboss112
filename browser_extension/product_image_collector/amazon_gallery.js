(() => {
  "use strict";

  const bodyText = `${document.title}\n${document.body?.innerText || ""}`.slice(0, 20000);
  if (/(?:captcha|robot check|enter the characters you see|sorry! something went wrong|unusual activity)/i.test(bodyText)) {
    return {
      ok: true,
      blocked: true,
      images: [],
      message: "Amazon yêu cầu CAPTCHA/Robot Check; phiên đã dừng.",
    };
  }

  const images = [];
  const seen = new Set();

  const normalize = (value) => {
    let text = String(value || "")
      .trim()
      .replace(/\\\//g, "/")
      .replace(/\\u002F/gi, "/")
      .replace(/&amp;/g, "&");

    if (text.startsWith("//")) text = `https:${text}`;

    try {
      const parsed = new URL(text);
      const validHost = /(?:^|\.)(?:media-amazon\.com|ssl-images-amazon\.com|amazon\.com)$/i.test(parsed.hostname);
      const isProductImage = /^\/images\/I\//i.test(parsed.pathname);
      if (!validHost || !isProductImage) return "";

      // Amazon image modifiers such as ._AC_UL320_ or ._SL1500_ are removed
      // so the CSV receives the original product image URL.
      parsed.pathname = parsed.pathname.replace(/\._[^/]*_(?=\.[a-zA-Z0-9]+$)/, "");
      parsed.search = "";
      parsed.hash = "";
      return parsed.toString();
    } catch (_error) {
      return "";
    }
  };

  const add = (value) => {
    const url = normalize(value);
    if (!url || seen.has(url) || images.length >= 30) return;
    seen.add(url);
    images.push(url);
  };

  const addDynamic = (value) => {
    try {
      const parsed = JSON.parse(String(value || ""));
      Object.entries(parsed)
        .sort((a, b) => {
          const area = (entry) =>
            Array.isArray(entry[1]) ? Number(entry[1][0] || 0) * Number(entry[1][1] || 0) : 0;
          return area(b) - area(a);
        })
        .forEach(([url]) => add(url));
    } catch (_error) {
      // The attribute is optional and is not always JSON.
    }
  };

  const addImage = (image) => {
    if (!image) return;
    const description = `${image.getAttribute("alt") || ""} ${image.currentSrc || image.src || ""}`;
    if (/(?:product video|play-icon|video-player)/i.test(description)) return;

    add(image.getAttribute("data-old-hires"));
    addDynamic(image.getAttribute("data-a-dynamic-image"));
    add(image.currentSrc);
    add(image.src);
    String(image.srcset || "")
      .split(",")
      .forEach((part) => add(part.trim().split(/\s+/)[0]));
  };

  // Main image first so image_url_1 always matches the selected product.
  document
    .querySelectorAll("#landingImage, #imgBlkFront, #imgTagWrapperId img, #main-image-container img")
    .forEach(addImage);

  // Amazon keeps the original gallery URLs inside scripts in the image block.
  // Restricting the scan to this block prevents Prime logos, banners and
  // recommendation carousels elsewhere on the page from leaking into results.
  const galleryRoot = document.querySelector("#imageBlock_feature_div, #imageBlock");
  if (galleryRoot) {
    const scripts = Array.from(galleryRoot.querySelectorAll("script"));
    for (const property of ["hiRes", "large", "mainUrl"]) {
      const pattern = new RegExp(`"${property}"\\s*:\\s*"([^"]+)"`, "gi");
      scripts.forEach((script) => {
        const text = script.textContent || "";
        for (const match of text.matchAll(pattern)) add(match[1]);
      });
    }
  }

  // Thumbnail URLs are a safe fallback for layouts that omit gallery JSON.
  document
    .querySelectorAll(
      "#altImages li.imageThumbnail img, #altImages .a-button-thumbnail img, #imageBlock li.imageThumbnail img"
    )
    .forEach(addImage);

  // Open Graph is kept as the final fallback and still must be a product URL.
  add(document.querySelector("meta[property='og:image']")?.content);

  return {
    ok: true,
    blocked: false,
    images,
    page_url: location.href,
    source: galleryRoot ? "amazon_product_gallery" : "amazon_main_image",
  };
})();
