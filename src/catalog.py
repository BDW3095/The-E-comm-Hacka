# [团队自建] catalog.py —— A 负责维护
"""
把 5万商品的 JSONL catalog 变成内存可检索结构。

  - flatten_text / normalize_token：安全拍平任意字段，统一大小写与同义词
  - ProductDocument：每个商品的标准化视图（search_text、结构化属性、价格、人气先验）
  - extract_attributes：从 title/features/details/categories/store 里正则+词典抽取
    material/color/size/style/brand/use_case（description 不参与正向抽取——避免"仅
    description 命中"被误当作正向证据，这条边界在 retrieval.py 的 color 处理里同样遵守）
  - CatalogIndex：一次性建索引（parent_asin 映射 + SQLite FTS5），供 retrieval.py 反复查询

只依赖标准库；无网络、无第三方模型时同样可用。
"""
from __future__ import annotations

import json
import math
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

SEARCH_FIELDS = ("title", "features", "description", "categories", "details", "store")

# ---------- 通用拍平 / 归一化 ----------


def flatten_text(value: object) -> str:
    """None -> ""；list 合并非空元素；dict 变成 "key value" 拼接文本。空字段永不 crash。"""
    if value is None:
        return ""
    if isinstance(value, dict):
        return " ".join(f"{k} {v}" for k, v in value.items() if v not in (None, "", []))
    if isinstance(value, list):
        return " ".join(str(v) for v in value if v not in (None, ""))
    return str(value)


_SYNONYMS = {
    "grey": "gray",
    "colour": "color",
    "sz": "size",
}


def normalize_token(text: object) -> str:
    t = str(text).strip().lower()
    return _SYNONYMS.get(t, t)


# ---------- 属性抽取词典（确定性正则，不依赖模型） ----------

_MATERIALS = (
    "cotton", "polyester", "nylon", "leather", "wool", "spandex", "silk",
    "rayon", "denim", "linen", "suede", "cashmere", "fleece", "canvas", "mesh",
)
_COLORS = (
    "black", "white", "blue", "red", "pink", "green", "brown", "gray", "grey",
    "purple", "yellow", "orange", "beige", "navy", "gold", "silver", "tan",
)
_SIZES = (
    "xs", "small", "medium", "large", "xl", "xxl", "xxxl",
    "petite", "plus size", "tall", "regular", "wide", "narrow",
)
_STYLES = (
    "casual", "formal", "athletic", "vintage", "classic", "bohemian",
    "sporty", "slim fit", "relaxed fit", "crew neck", "v-neck",
)
_USE_CASES = (
    "hiking", "running", "gym", "winter", "summer", "outdoor", "work",
    "travel", "wedding", "party", "yoga", "swimming", "everyday",
)
# "feature" 在契约里是开放词表的兜底分类（ask_attribute 十个枚举值之一），不像 material/color
# 那样能穷举，所以这里只收录高频功能性描述词做正向抽取；ConstraintRanker 里对 feature 还会
# 额外做一次 search_text 子串匹配兜底，两边配合覆盖没进词典的说法（比如具体的 "quick-dry" 变体）。
_FEATURES = (
    "waterproof", "water resistant", "water-resistant", "windproof",
    "breathable", "moisture wicking", "moisture-wicking", "quick dry",
    "quick-dry", "wrinkle resistant", "wrinkle-resistant", "stretch",
    "adjustable", "reversible", "reinforced", "insulated", "lightweight",
    "packable", "machine washable", "anti slip", "anti-slip", "non slip",
    "non-slip", "uv protection", "odor resistant", "odor-resistant",
)

# details 是半结构化 metadata。只有字段语义明确的 value 才进入 structured
# attribute extraction；其余 details 仍会进入 FTS5 search_text，不会丢失 lexical recall。
_DETAIL_KEYS_BY_ATTRIBUTE = {
    "color": {"color"},
    "material": {"material"},
    "size": {"size"},
    "style": {"style"},
    "feature": {"special feature", "special features"},
}
_BRAND_DETAIL_KEYS = {"brand", "brand name", "manufacturer"}
_BRAND_ALIAS_STOPWORDS = {
    "and", "co", "company", "corp", "corporation", "inc", "incorporated",
    "ltd", "llc", "limited", "of", "the",
}

_MATERIAL_RE = re.compile(r"\b(" + "|".join(_MATERIALS) + r")\b", re.I)
_COLOR_RE = re.compile(r"\b(" + "|".join(_COLORS) + r")\b", re.I)
_SIZE_RE = re.compile(r"\b(" + "|".join(re.escape(s) for s in _SIZES) + r")\b", re.I)
_STYLE_RE = re.compile(r"\b(" + "|".join(re.escape(s) for s in _STYLES) + r")\b", re.I)
_USE_CASE_RE = re.compile(r"\b(" + "|".join(_USE_CASES) + r")\b", re.I)
_FEATURE_RE = re.compile(r"\b(" + "|".join(re.escape(f) for f in _FEATURES) + r")\b", re.I)


def extract_attributes(product: dict) -> dict[str, list[str]]:
    """从可信文本和 schema-driven details fields 抽取结构化属性。

    description 故意不参与（比赛契约要求：仅 description 命中的颜色等属性不能算正向证据）。
    Department / Suggested Users 等 category-like details 不进入 brand 或 structured text。
    """
    details = product.get("details")
    normalized_details: list[tuple[str, object]] = []
    if isinstance(details, dict):
        normalized_details = [(str(key).strip().casefold(), value) for key, value in details.items()]

    structured_detail_keys = set().union(*_DETAIL_KEYS_BY_ATTRIBUTE.values())
    details_text = " ".join(
        flatten_text(value)
        for key, value in normalized_details
        if key in structured_detail_keys
    )
    strong_text = " ".join(
        flatten_text(product.get(f)) for f in ("title", "features", "categories", "store")
    )
    strong_text = f"{strong_text} {details_text}".strip()
    attrs: dict[str, list[str]] = {
        "material": sorted({normalize_token(m) for m in _MATERIAL_RE.findall(strong_text)}),
        "color": sorted({normalize_token(c) for c in _COLOR_RE.findall(strong_text)}),
        "size": sorted({normalize_token(s) for s in _SIZE_RE.findall(strong_text)}),
        "style": sorted({normalize_token(s) for s in _STYLE_RE.findall(strong_text)}),
        "use_case": sorted({normalize_token(u) for u in _USE_CASE_RE.findall(strong_text)}),
        "feature": sorted({normalize_token(ft) for ft in _FEATURE_RE.findall(strong_text)}),
        "brand": [],
    }

    def add_brand(value: object) -> None:
        phrase = normalize_token(flatten_text(value))
        if not phrase:
            return
        attrs["brand"].append(phrase)
        # Keep the complete phrase (e.g. "nike inc") and useful word aliases
        # (e.g. "nike") so B's brand slot can match either representation.
        for token in re.findall(r"[a-z0-9]+", phrase):
            if len(token) >= 3 and token not in _BRAND_ALIAS_STOPWORDS:
                attrs["brand"].append(token)

    store = product.get("store")
    if store:
        add_brand(store)
    for key, value in normalized_details:
        if key in _BRAND_DETAIL_KEYS and flatten_text(value):
            add_brand(value)

    return {key: sorted(set(values)) for key, values in attrs.items()}


@dataclass
class ProductDocument:
    parent_asin: str
    search_text: str
    category_path: list[str]
    attributes: dict[str, list[str]]
    price: float | None
    quality_prior: float
    product: dict


class CatalogIndex:
    """构造只做一次；retrieval.py 的 LexicalRetriever / ConstraintRanker 反复查询。"""

    def __init__(self, catalog_path: str | Path) -> None:
        self.catalog_path = Path(catalog_path)
        self.documents: dict[str, ProductDocument] = {}
        self.valid_ids: set[str] = set()
        self._conn = sqlite3.connect(":memory:")
        self._fallback_ids: list[str] | None = None
        self._build()

    def _build(self) -> None:
        cur = self._conn.cursor()
        cur.execute(
            "CREATE VIRTUAL TABLE products USING fts5("
            "parent_asin UNINDEXED, title, categories, features, details, store, description, "
            "tokenize='unicode61 remove_diacritics 2')"
        )
        batch: list[tuple[str, str, str, str, str, str, str]] = []
        with self.catalog_path.open(encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                product = json.loads(line)
                asin = str(product["parent_asin"])
                if asin in self.documents:
                    continue  # 重复 ID：保留第一条，不崩溃
                price = product.get("price")
                price_value = price if isinstance(price, (int, float)) else None
                rating = product.get("average_rating") or 0.0
                rating_n = product.get("rating_number") or 0
                try:
                    quality_prior = float(rating) * math.log1p(float(rating_n))
                except (TypeError, ValueError):
                    quality_prior = 0.0
                categories = product.get("categories")
                category_path = [str(c) for c in categories] if isinstance(categories, list) else []
                doc = ProductDocument(
                    parent_asin=asin,
                    search_text=" ".join(flatten_text(product.get(f)) for f in SEARCH_FIELDS),
                    category_path=category_path,
                    attributes=extract_attributes(product),
                    price=price_value,
                    quality_prior=quality_prior,
                    product=product,
                )
                self.documents[asin] = doc
                self.valid_ids.add(asin)
                batch.append((
                    asin,
                    flatten_text(product.get("title")),
                    flatten_text(product.get("categories")),
                    flatten_text(product.get("features")),
                    flatten_text(product.get("details")),
                    flatten_text(product.get("store")),
                    flatten_text(product.get("description")),
                ))
                if len(batch) >= 1000:
                    cur.executemany("INSERT INTO products VALUES (?,?,?,?,?,?,?)", batch)
                    batch.clear()
        if batch:
            #每读完 1000 条商品，就通过 executemany 一次性把这 1000 行插入 FTS5 表
            cur.executemany("INSERT INTO products VALUES (?,?,?,?,?,?,?)", batch)
        self._conn.commit()

    def get_product(self, parent_asin: str) -> dict | None:
        doc = self.documents.get(str(parent_asin))
        return doc.product if doc else None

    def get_document(self, parent_asin: str) -> ProductDocument | None:
        """返回内部标准化 document，供需要 attributes / price / prior 的调用方使用。"""
        return self.documents.get(str(parent_asin))

    def all_documents(self) -> Iterator[ProductDocument]:
        return iter(self.documents.values())

    def stable_fallback_ids(self) -> list[str]:
        """按人气先验降序、parent_asin 升序的稳定顺序，供 validate_recommendations 补齐用。"""
        if self._fallback_ids is None:
            self._fallback_ids = [
                doc.parent_asin
                for doc in sorted(
                    self.documents.values(),
                    key=lambda d: (-d.quality_prior, d.parent_asin),
                )
            ]
        return self._fallback_ids

    @property
    def connection(self) -> sqlite3.Connection:
        return self._conn
