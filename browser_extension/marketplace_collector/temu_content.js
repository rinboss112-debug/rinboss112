(async () => {
  "use strict";

  const normalize = (value) => String(value || "").replace(/\s+/g, " ").trim();
  const pageText = normalize(document.body?.innerText).slice(0, 15000);
  const blocked = /(?:captcha|verify you are human|unusual activity|security check|access denied)/i.test(
    `${document.title}\n${pageText}`
  );
  if (blocked) {
    return {
      ok: true,
      blocked: true,
      message: "Temu đang yêu cầu xác minh. Hãy xử lý thủ công; extension không vượt CAPTCHA.",
      url: location.href,
      keyword: "",
      card_count: 0,
      products: [],
    };
  }

  window.scrollBy({ top: Math.max(window.innerHeight * 1.6, 900), behavior: "smooth" });
  await new Promise((resolve) => setTimeout(resolve, 1800));

  const cleanUrl = (value) => {
    try {
      const url = new URL(String(value || ""), location.origin);
      ["refer_page_el_sn", "refer_page_name", "refer_page_id", "_x_sessn_id", "_x_vst_scene"].forEach(
        (name) => url.searchParams.delete(name)
      );
      return url.href;
    } catch (_error) {
      return "";
    }
  };

  const cleanImage = (value) => normalize(value).split(/\s+/)[0];
  const parseNumber = (value) => {
    const match = normalize(value).replace(/,/g, "").match(/(\d+(?:\.\d+)?)\s*([KM])?/i);
    if (!match) return null;
    let number = Number(match[1]);
    if (match[2]?.toLowerCase() === "k") number *= 1000;
    if (match[2]?.toLowerCase() === "m") number *= 1000000;
    return number;
  };
  const parsePrice = (text) => {
    const match = normalize(text).replace(/,/g, "").match(/(?:US\s*)?\$\s*(\d+(?:\.\d{1,2})?)/i);
    return match ? Number(match[1]) : null;
  };
  const keyword = normalize(new URL(location.href).searchParams.get("search_key"));
  const productId = (url) => {
    const match = String(url || "").match(/(?:goods_id=|-g-)(\d{6,})/i);
    return match?.[1] || "";
  };
  const closestCard = (anchor) => {
    let node = anchor;
    for (let depth = 0; node && depth < 7; depth += 1, node = node.parentElement) {
      const text = normalize(node.innerText);
      if (node.querySelector?.("img") && /\$\s*\d/.test(text) && text.length > 20 && text.length < 1800) return node;
    }
    return anchor.parentElement;
  };
  const titleFor = (anchor, card) => {
    const candidates = [
      anchor.getAttribute("aria-label"),
      anchor.getAttribute("title"),
      card?.querySelector?.("[title]")?.getAttribute("title"),
      card?.querySelector?.("h2, h3, [class*='title'], [data-testid*='title']")?.textContent,
      anchor.textContent,
    ].map(normalize).filter(Boolean);
    return candidates.find((value) => value.length >= 12 && !/^\$/.test(value)) || "";
  };

  const anchors = Array.from(document.querySelectorAll("a[href*='goods.html'], a[href*='-g-']"));
  const products = [];
  const seen = new Set();
  for (const anchor of anchors) {
    const url = cleanUrl(anchor.href);
    const id = productId(url);
    const card = closestCard(anchor);
    const cardText = normalize(card?.innerText);
    const title = titleFor(anchor, card);
    const price = parsePrice(cardText);
    const identity = id || url;
    if (!identity || seen.has(identity) || !title || !price) continue;
    seen.add(identity);
    const image = card?.querySelector?.("img");
    const soldMatch = cardText.match(/(?:^|\s)([\d,.]+\s*[KM]?\+?)\s*(?:sold|bought)/i);
    const reviewMatch = cardText.match(/\(([\d,.]+\s*[KM]?)\)/i);
    const ratingMatch = cardText.match(/(?:^|\s)([0-5](?:\.\d)?)\s*(?:stars?|\u2605)/i);
    const originalMatches = Array.from(cardText.matchAll(/\$\s*(\d+(?:\.\d{1,2})?)/g)).map((match) => Number(match[1]));
    const originalPrice = originalMatches.find((value) => value > price) || null;
    const badge = (cardText.match(/(?:best seller|top rated|popular|almost sold out|limited time deal)/i) || [""])[0];
    products.push({
      source: "temu",
      title,
      image_url: cleanImage(image?.currentSrc || image?.src || image?.getAttribute("data-src")),
      price,
      original_price: originalPrice,
      keyword,
      product_id: id,
      product_url: url,
      units_sold: parseNumber(soldMatch?.[1]),
      sold_text: normalize(soldMatch?.[0]),
      rating: parseNumber(ratingMatch?.[1]),
      review_count: parseNumber(reviewMatch?.[1]),
      badge: normalize(badge),
      free_shipping: /free shipping/i.test(cardText),
      scraped_at: new Date().toISOString(),
    });
  }

  return {
    ok: true,
    blocked: false,
    url: location.href,
    keyword,
    card_count: anchors.length,
    products,
  };
})();
