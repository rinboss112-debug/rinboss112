(() => {
  "use strict";

  const pageText = String(document.body?.innerText || "");
  const pageTitle = String(document.title || "");
  const blocked = /(?:robot check|enter the characters you see below|sorry, we just need to make sure you're not a robot|captcha)/i.test(
    `${pageTitle}\n${pageText.slice(0, 8000)}`
  );
  if (blocked) {
    return {
      ok: true,
      blocked: true,
      message: "Amazon đang hiện CAPTCHA/Robot Check. Hãy xử lý thủ công và chạy lại sau.",
      url: location.href,
      keyword: "",
      card_count: 0,
      products: [],
    };
  }

  const normalize = (value) => String(value || "").replace(/\s+/g, " ").trim();

  const firstText = (root, selectors) => {
    for (const selector of selectors) {
      const node = root.querySelector(selector);
      const value = normalize(node?.textContent);
      if (value) return value;
    }
    return "";
  };

  const cleanImageUrl = (value) => {
    let url = normalize(value).split(" ")[0];
    if (!url) return "";
    url = url.replace(/\._(?:AC|SL|SX|SY|UL|UX|UY)[^.]*(?=\.(?:jpe?g|png|webp)(?:\?|$))/i, "");
    return url;
  };

  const imageUrl = (card) => {
    const image = card.querySelector("img.s-image, img[data-image-latency], img");
    if (!image) return "";
    const dynamic = image.getAttribute("data-a-dynamic-image");
    if (dynamic) {
      try {
        const candidates = Object.entries(JSON.parse(dynamic));
        candidates.sort((left, right) => {
          const leftSize = Number(left[1]?.[0] || 0) * Number(left[1]?.[1] || 0);
          const rightSize = Number(right[1]?.[0] || 0) * Number(right[1]?.[1] || 0);
          return rightSize - leftSize;
        });
        if (candidates[0]?.[0]) return cleanImageUrl(candidates[0][0]);
      } catch (_error) {
        // Continue with the visible src when Amazon changes this attribute.
      }
    }
    return cleanImageUrl(
      image.getAttribute("data-old-hires") ||
      image.currentSrc ||
      image.getAttribute("srcset") ||
      image.src
    );
  };

  const parsePrice = (card) => {
    const raw = firstText(card, [
      ".a-price:not([data-a-strike]) .a-offscreen",
      ".a-price .a-offscreen",
      "[data-a-color='price'] .a-offscreen",
    ]);
    const match = raw.replace(/,/g, "").match(/(?:US\$|\$)?\s*(\d+(?:\.\d{1,2})?)/i);
    return match ? Number(match[1]) : null;
  };

  const searchKeyword = () => {
    const field = document.querySelector("#twotabsearchtextbox, input[name='field-keywords']");
    const value = normalize(field?.value);
    if (value) return value;
    const url = new URL(location.href);
    return normalize(url.searchParams.get("k") || url.searchParams.get("field-keywords"));
  };

  const shippingText = (card) => {
    const lines = String(card.innerText || "")
      .split(/\r?\n/)
      .map(normalize)
      .filter(Boolean);
    const startPattern = /(?:join\s+prime|prime\s+members?|free\s+(?:delivery|shipping)|fastest\s+delivery|fresh|ships\s+from|sold\s+by)/i;
    const stopPattern = /^(?:add to cart|see all buying options|currently unavailable|only \d+ left|more buying choices)$/i;
    const continuationPattern = /(?:today|tomorrow|overnight|\b(?:mon|tue|wed|thu|fri|sat|sun)\b|\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\b|\d{1,2}\s*(?:am|pm)|eligible orders?|orders? over|items shipped by amazon|order within|amazonfresh|prime)/i;
    const start = lines.findIndex((line) => startPattern.test(line));
    if (start < 0) return "";
    const selected = [];
    for (let index = start; index < lines.length && selected.length < 10; index += 1) {
      const line = lines[index];
      if (selected.length && stopPattern.test(line)) break;
      if (startPattern.test(line) || continuationPattern.test(line) || selected.length < 2) {
        selected.push(line);
      } else if (selected.length >= 2) {
        break;
      }
    }
    return normalize(selected.join(" | "));
  };

  const selectedVariant = (card, title) => {
    const candidates = Array.from(
      card.querySelectorAll(
        "[data-csa-c-item-type*='variation'], .s-product-image-container + div .a-size-base.a-color-base"
      )
    )
      .map((node) => normalize(node.textContent))
      .filter((value) => value && value.length <= 100 && value !== title);
    const explicit = candidates.find((value) =>
      /(?:flavou?r|size|ounce|\boz\b|count|pack of|variety)/i.test(value)
    );
    if (explicit) return explicit;
    const size = title.match(
      /\b\d+(?:\.\d+)?\s*(?:fl\.?\s*oz|oz|ounce|ounces|lb|lbs|pound|pounds|g|kg|ml|l)\b(?:\s*\(pack of \d+\))?/i
    );
    return normalize(size?.[0]);
  };

  const excludedBrand = (title) => {
    const value = normalize(title).toLowerCase().replace(/^amazon brand\s*[-:]?\s*/, "amazon brand ");
    return [
      "amazon fresh",
      "amazon saver",
      "amazon grocery",
      "amazon brand",
      "365 everyday value",
      "365 food",
      "365 whole foods",
      "365 by whole foods",
    ].some((prefix) => value.startsWith(prefix));
  };

  const titleTextFromScope = (scope) => {
    if (!scope) return "";
    const isNoise = (value) => /^(?:sponsored|best seller|overall pick|amazon'?s choice)$/i.test(value);
    const fullText = normalize(scope.textContent);
    const spanTexts = Array.from(scope.querySelectorAll("span"))
      .map((node) => normalize(node.textContent))
      .filter((value) => value && !isNoise(value));

    // The current Amazon card can place the brand in the first h2 span and
    // the real product title in a second span. Prefer the descriptive span
    // instead of blindly accepting the first one.
    if (spanTexts.length > 1) {
      return spanTexts.sort((left, right) => right.length - left.length)[0];
    }
    if (spanTexts.length === 1) {
      const onlySpan = spanTexts[0];
      if (fullText.length > onlySpan.length && fullText.startsWith(onlySpan)) {
        const remainder = normalize(fullText.slice(onlySpan.length));
        if (remainder.length > onlySpan.length) return remainder;
      }
      return onlySpan;
    }

    const ariaLabel = normalize(scope.getAttribute("aria-label"));
    if (ariaLabel && !isNoise(ariaLabel)) return ariaLabel;
    return isNoise(fullText) ? "" : fullText;
  };

  const titleFromCard = (card, asin) => {
    const asinPattern = new RegExp(`/(?:dp|gp/product)/${asin}(?:[/?]|$)`, "i");
    const productLinks = Array.from(card.querySelectorAll("a[href]")).filter((anchor) => {
      let href = anchor.getAttribute("href") || "";
      try {
        href = decodeURIComponent(href);
      } catch (_error) {
        // Use the original href when Amazon returns malformed escaping.
      }
      return asinPattern.test(href);
    });
    const productLink = productLinks.find((anchor) =>
      anchor.querySelector("h2") || anchor.closest("h2") || anchor.closest("[data-cy='title-recipe']")
    ) || productLinks.find((anchor) => normalize(anchor.textContent).length >= 12);
    const exactScope = productLink?.querySelector("h2") || productLink?.closest("h2") || productLink;
    const exactTitle = titleTextFromScope(exactScope);
    if (exactTitle) return exactTitle;

    for (const selector of [
      "[data-cy='title-recipe'] h2",
      "h2",
      "a.a-link-normal.s-line-clamp-2",
    ]) {
      const title = titleTextFromScope(card.querySelector(selector));
      if (title) return title;
    }
    return normalize(card.querySelector("img.s-image")?.getAttribute("alt"));
  };

  const collectCard = (card, keyword) => {
    const asin = normalize(card.getAttribute("data-asin")).toUpperCase();
    const title = titleFromCard(card, asin);
    if (!/^[A-Z0-9]{10}$/.test(asin) || !title) return null;
    const delivery = shippingText(card);
    const lowerDelivery = delivery.toLowerCase();
    return {
      title,
      image_url: imageUrl(card),
      price: parsePrice(card),
      variants: selectedVariant(card, title),
      delivery_options: delivery || "Không thấy thông tin ship trên thẻ kết quả",
      keyword,
      asin,
      product_url: `https://www.amazon.com/dp/${asin}`,
      currency: "USD",
      rating: null,
      review_count: null,
      prime: /(?:join\s+prime|prime\s+members?)/i.test(delivery),
      free_shipping: /free\s+(?:delivery|shipping)/i.test(delivery),
      fast_shipping: /(?:today|tomorrow|overnight|fastest\s+delivery)/i.test(delivery),
      delivery_available: Boolean(delivery),
      sponsored: /\bsponsored\b/i.test(String(card.innerText || "")),
      scraped_at: new Date().toISOString(),
      _excluded_brand: excludedBrand(title),
      _fresh: /(?:\bfresh\b|amazonfresh)/i.test(lowerDelivery),
    };
  };

  const keyword = searchKeyword();
  const cards = Array.from(
    document.querySelectorAll("[data-component-type='s-search-result'][data-asin]")
  );
  const knownErrorPage = /(?:sorry! something went wrong|automated access|api-services-support@amazon\.com|dogs of amazon|service unavailable)/i.test(
    `${pageTitle}\n${pageText.slice(0, 12000)}`
  );
  if (knownErrorPage || (location.pathname === "/s" && cards.length === 0 && pageText.length < 12000)) {
    return {
      ok: true,
      blocked: true,
      message: "Amazon không trả trang kết quả chuẩn. Có thể kết nối đang bị giới hạn; phiên đã tự dừng để tránh tạo dữ liệu rỗng.",
      url: location.href,
      keyword,
      card_count: 0,
      products: [],
    };
  }
  const products = cards.map((card) => collectCard(card, keyword)).filter(Boolean);
  return {
    ok: true,
    blocked: false,
    url: location.href,
    keyword,
    card_count: cards.length,
    products,
  };
})();
