"use strict";

const assert = require("assert");
const path = require("path");

require(path.resolve(__dirname, "../../browser_extension/amazon_product_collector/compliance.js"));
const compliance = globalThis.RinBossTemuCompliance;

assert.ok(compliance.DEFAULT_RISK_TERMS.length >= 80);
assert.deepStrictEqual(
  compliance.matchedRiskTerms("Vitamin C Gummies Dietary Supplement"),
  ["dietary supplement", "vitamin"],
);
assert.deepStrictEqual(
  compliance.matchedRiskTerms("Bluetooth Walkie Talkie Two Way Radio"),
  ["bluetooth", "walkie talkie", "two way radio"],
);
assert.deepStrictEqual(
  compliance.matchedRiskTerms("Kitchen Drawer Organizer Bamboo", ["vitamin", "pesticide"]),
  [],
);
assert.deepStrictEqual(
  compliance.normalizeRiskTerms(" Vitamin \nvitamin\nUSDA\n"),
  ["Vitamin", "USDA"],
);
assert.deepStrictEqual(
  compliance.matchedRiskTerms("Thực phẩm bổ sung cho người lớn", ["thuc pham bo sung"]),
  ["thuc pham bo sung"],
);
console.log("Temu US compliance keyword filter fixture passed.");
