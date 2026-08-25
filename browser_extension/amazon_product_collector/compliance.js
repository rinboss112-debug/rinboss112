(() => {
  "use strict";

  const DEFAULT_RISK_TERMS = [
    "usda", "fda", "dietary supplement", "supplement", "vitamin", "multivitamin",
    "probiotic", "prebiotic", "melatonin", "collagen", "creatine", "protein powder",
    "weight loss", "detox", "gummy supplement", "edible", "snack pack", "candy",
    "chocolate", "cookies", "beverage", "drink mix", "ground coffee", "coffee beans",
    "instant coffee", "coffee pods", "tea bags", "herbal tea", "sauce", "seasoning",
    "beef jerky", "pork jerky", "chicken jerky", "turkey jerky", "meat snack",
    "canned meat", "sausage", "bacon", "poultry", "egg powder", "pet food",
    "dog treat", "cat treat", "veterinary",
    "medical device", "diagnostic", "blood pressure monitor", "glucose meter",
    "pulse oximeter", "hearing aid", "contact lens", "syringe", "needle",
    "first aid kit", "bandage", "pain relief", "acne treatment", "antifungal",
    "antiseptic", "sunscreen", "spf", "whitening cream", "skin serum",
    "eyelash serum", "hair growth", "nail polish", "hair dye", "perfume", "shampoo",
    "deodorant", "antiperspirant", "toothpaste",
    "pesticide", "insecticide", "herbicide", "fungicide", "rodenticide",
    "insect repellent", "mosquito repellent", "disinfectant", "sanitizer",
    "antibacterial", "antimicrobial", "kills germs", "mold remover",
    "baby product", "infant", "toddler", "pacifier", "teether", "crib", "stroller",
    "car seat", "kids toy", "children's toy", "child safety", "helmet",
    "bluetooth", "wi-fi", "wifi", "wireless transmitter", "walkie talkie",
    "two way radio", "drone", "laser pointer", "lithium battery", "power bank",
    "battery charger",
    "vape", "e-cigarette", "tobacco", "nicotine", "cigar", "hookah", "cbd", "thc",
    "cannabis", "hemp extract", "alcohol", "wine", "beer", "ammunition", "firearm",
    "switchblade", "tactical knife",
  ];

  const normalizeForMatch = (value) => ` ${String(value || "")
    .normalize("NFKD")
    .toLocaleLowerCase()
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[^a-z0-9]+/g, " ")
    .replace(/\s+/g, " ")
    .trim()} `;

  const normalizeRiskTerms = (value) => {
    const source = Array.isArray(value) ? value : String(value || "").split(/\r?\n/);
    const seen = new Set();
    const terms = [];
    source.forEach((item) => {
      const term = String(item || "").trim();
      const normalized = normalizeForMatch(term).trim();
      if (!normalized || seen.has(normalized)) return;
      seen.add(normalized);
      terms.push(term);
    });
    return terms;
  };

  const matchedRiskTerms = (title, terms = DEFAULT_RISK_TERMS) => {
    const haystack = normalizeForMatch(title);
    const matches = normalizeRiskTerms(terms).filter((term) =>
      haystack.includes(normalizeForMatch(term))
    );
    return matches.filter((term) => {
      const normalized = normalizeForMatch(term);
      return !matches.some((other) => {
        const otherNormalized = normalizeForMatch(other);
        return otherNormalized.length > normalized.length && otherNormalized.includes(normalized);
      });
    });
  };

  globalThis.RinBossTemuCompliance = Object.freeze({
    DEFAULT_RISK_TERMS: Object.freeze([...DEFAULT_RISK_TERMS]),
    normalizeRiskTerms,
    matchedRiskTerms,
  });
})();
