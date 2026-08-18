"use strict";

const assert = require("assert");
const fs = require("fs");
const vm = require("vm");
const path = require("path");

const asin = "B0FFFSP74N";
const title = "Halloween Horror Mask Scary Halloween Latex Full Head Masks";
const textNode = (textContent) => ({ textContent });
const heading = {
  textContent: `LAMZZP ${title}`,
  querySelectorAll: (selector) => selector === "span"
    ? [textNode("LAMZZP"), textNode(title)]
    : [],
  getAttribute: (name) => name === "aria-label" ? `LAMZZP ${title}` : "",
};
const productLink = {
  textContent: heading.textContent,
  getAttribute: (name) => name === "href" ? `/LAMZZP-Halloween-Mask/dp/${asin}` : "",
  querySelector: (selector) => selector === "h2" ? heading : null,
  closest: () => null,
};
const imageLink = {
  textContent: "",
  getAttribute: (name) => name === "href" ? `/LAMZZP-Halloween-Mask/dp/${asin}` : "",
  querySelector: () => null,
  closest: () => null,
};
const image = {
  currentSrc: "https://m.media-amazon.com/images/I/example._AC_UL320_.jpg",
  src: "https://m.media-amazon.com/images/I/example._AC_UL320_.jpg",
  getAttribute: () => "",
};
const price = { textContent: "$19.99" };
const card = {
  innerText: `${title}\n$19.99\nJoin Prime to get FREE delivery Overnight 7 AM - 11 AM`,
  getAttribute: (name) => name === "data-asin" ? asin : "",
  querySelector: (selector) => {
    if (selector.includes("img")) return image;
    if (selector.includes("a-offscreen")) return price;
    if (selector === "[data-cy='title-recipe'] h2" || selector === "h2") return heading;
    return null;
  },
  querySelectorAll: (selector) => {
    if (selector === "a[href]") return [imageLink, productLink];
    return [];
  },
};

global.location = {
  href: "https://www.amazon.com/s?k=halloween+mask",
  pathname: "/s",
};
global.document = {
  title: "Amazon.com : halloween mask",
  body: { innerText: "Amazon search results" },
  querySelector: () => null,
  querySelectorAll: (selector) => selector.includes("s-search-result") ? [card] : [],
};

const contentPath = path.resolve(__dirname, "../../browser_extension/amazon_product_collector/content.js");
const result = vm.runInThisContext(fs.readFileSync(contentPath, "utf8"), { filename: contentPath });

assert.strictEqual(result.ok, true);
assert.strictEqual(result.products.length, 1);
assert.strictEqual(result.products[0].title, title);
assert.strictEqual(result.products[0].asin, asin);
assert.strictEqual(result.products[0].product_url, `https://www.amazon.com/dp/${asin}`);
console.log("Amazon title extraction fixture passed.");
