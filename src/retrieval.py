# [团队自建] retrieval.py —— A 负责维护
"""
从 CatalogIndex 缩小到候选集：

  1) compile_positive_query：只用正向 token 构造安全的 FTS OR expression
  2) LexicalRetriever：SQLite FTS5 BM25 召回 Top-N Candidate（转换后分数越大越相关）
  3) ConstraintRanker：按 state 的 positive_slots / negative_slots 重新排序；
     color 严格 positive-evidence-only —— 只有命中用户要的颜色才加分，
     不匹配/多色/缺失/仅 description 命中一律中性，绝不 penalty 或 hard filter
     （官方已确认 parent_asin 是可能含多个 SKU variant 的 parent product）
  4) validate_recommendations：去重、剔除非法ID、稳定排序，不足 top_k 时用
     CatalogIndex.stable_fallback_ids() 补齐，保证每轮恰好 top_k 个合法 ID

只读取 state，不修改 state；不读取 ground_truth / sample_id / scenario 标签。
"""
from __future__ import annotations

import re

from typing import Any

from src.catalog import CatalogIndex, normalize_token

from src.types import Candidate


TOKEN_RE = re.compile(r"[a-z0-9]+", re.IGNORECASE)
STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "but", "by", "for", "from",
    "i", "in", "is", "it", "me", "my", "of", "on", "or", "please", "some",
    "that", "the", "this", "to", "want", "with", "would", "you", "looking",
    "need", "like", "prefer", "actually", "ignore", "earlier", "preference",
    "requirement", "requirements", "key", "specific", "attribute", "one",
    "still", "exploring", "options", "not", "quite", "right", "yet", "ask",
    "about", "have", "don", "additional", "matters", "what", "those",
}

_ATTR_KEYS_FOR_RANKING = ("category", "material", "color", "brand", "size", "style", "feature", "use_case")
# feature 是开放词表兜底分类，extract_attributes 的固定词典必然覆盖不全（比如没收录进词典的
# 具体功能描述），所以命中判断额外做一次 search_text 子串匹配兜底，不完全依赖词典命中。
_SUBSTRING_FALLBACK_KEYS = {"feature"}
_POSITIVE_BONUS = 2.0
_NEGATIVE_PENALTY = 6.0
_COLOR_BONUS = 1.5
_BUDGET_PENALTY = 0.5
_BUDGET_TOLERANCE = 1.15  # 超预算 15% 以内不惩罚，避免把合适商品挤掉


def _terms(text: str) -> list[str]:
    return [
        tok.lower() for tok in TOKEN_RE.findall(text)
        if len(tok) > 1 and tok.lower() not in STOPWORDS
    ]


def compile_positive_query(query: str) -> str:
    """只用正向 token 构造 FTS OR expression；negative token 永远不会传进这里
    （B 的 build_query 只应该吐出正向 query；这里再做一层防御性去重/截断/转义）。
    """
    terms = list(dict.fromkeys(_terms(query or "")))[:40]
    if not terms:
        return ""
    return " OR ".join(f'"{t}"' for t in terms)


def _budget_ceiling(values: list) -> float | None:
    """Return only an explicit upper bound from B's budget representation.

    ``min:`` and ``target:`` carry different semantics and must never be
    reinterpreted as a maximum.  Natural-language strings are accepted only
    when they contain an unambiguous upper-bound phrase such as ``under`` or
    ``at most``.
    """
    ceiling: float | None = None
    for v in values:
        if isinstance(v, dict):
            hi = v.get("max")
            if isinstance(hi, (int, float)) and not isinstance(hi, bool):
                numeric_hi = float(hi)
                ceiling = numeric_hi if ceiling is None else min(ceiling, numeric_hi)
            continue

        text = str(v).strip().lower()
        kind, separator, _amount = text.partition(":")
        if separator and kind in {"min", "target"}:
            continue
        has_upper_semantics = kind == "max" or bool(
            re.search(
                r"(?:<=|\bunder\b|\bbelow\b|\bless\s+than\b|\bup\s+to\b|"
                r"\bat\s+most\b|\bno\s+more\s+than\b|\bmax(?:imum)?\b)",
                text,
            )
        )
        if not has_upper_semantics:
            continue
        numbers = [float(n) for n in re.findall(r"\d+(?:\.\d+)?", text)]
        if numbers:
            hi = max(numbers)
            ceiling = hi if ceiling is None else min(ceiling, hi)
    return ceiling


class LexicalRetriever:
    def __init__(self, catalog_index: CatalogIndex) -> None:
        self._catalog = catalog_index

    def retrieve(self, query: str, limit: int = 200) -> list[Candidate]:
        expression = compile_positive_query(query)
        if not expression:
            return []
        try:
            rows = self._catalog.connection.execute(
                "SELECT parent_asin, bm25(products, 0.0, 6.0, 4.0, 2.5, 2.5, 1.5, 1.0) "
                "FROM products WHERE products MATCH ? "
                "ORDER BY bm25(products, 0.0, 6.0, 4.0, 2.5, 2.5, 1.5, 1.0), "
                "parent_asin ASC LIMIT ?",
                (expression, limit),
            ).fetchall()
        except Exception:
            return []
        candidates: list[Candidate] = []
        for rank, (asin, raw_bm25) in enumerate(rows, start=1):
            doc = self._catalog.documents.get(str(asin))
            if doc is None:
                continue
            candidates.append(
                Candidate(
                    parent_asin=doc.parent_asin,
                    score=-float(raw_bm25),  # sqlite bm25 越小越相关 -> 取负号，全项目统一越大越相关
                    search_text=doc.search_text,
                    product=doc.product,
                    route_ranks={"lexical": rank},
                )
            )
        return candidates


class ConstraintRanker:
    """只读 state 的 positive_slots / negative_slots；从不修改 state。

    需要 catalog_index 是为了用 CatalogIndex 在建索引时就算好的 ProductDocument.attributes，
    避免每轮、每个候选都重新跑一遍正则抽取（50k 商品规模下这个差别是几十毫秒 vs 几百毫秒）。
    """

    def __init__(self, catalog_index: CatalogIndex) -> None:
        self._catalog = catalog_index

    def rerank(self, candidates: list[Candidate], state: Any) -> list[Candidate]:
        positive = getattr(state, "positive_slots", None) or {}
        negative = getattr(state, "negative_slots", None) or {}
        if not positive and not negative:
            return sorted(candidates, key=lambda c: (-c.score, c.parent_asin))

        budget_values = positive.get("budget") or []
        if not isinstance(budget_values, list):
            budget_values = [budget_values]
        budget_hi = _budget_ceiling(budget_values)

        adjusted: list[Candidate] = []
        for cand in candidates:
            attrs = self._attrs_of(cand)
            bonus = 0.0
            penalty = 0.0

            surface = (cand.search_text or "").lower()

            for key in _ATTR_KEYS_FOR_RANKING:
                pos_values = positive.get(key)
                if not pos_values:
                    continue
                pos_norm = {self._norm(v) for v in self._flat(pos_values)}
                cand_norm = set(attrs.get(key, []))
                #取出候选商品在该属性上的值
                if key == "category":
                    cand_norm |= {self._norm(c) for c in (cand.product.get("categories") or [])}#如果是 category，还要把 product["categories"] 原始品类纳入匹配。
                hit = bool(pos_norm & cand_norm)
                #判断是否有交集
                if not hit and key in _SUBSTRING_FALLBACK_KEYS:
                    hit = any(v in surface for v in pos_norm if len(v) >= 3)
                if key == "color":
                    if hit:
                        bonus += _COLOR_BONUS
                    # 不匹配 / 多色 / 缺失一律中性：不扣分、不过滤
                    continue
                    #color 命中加 1.5 分；无论是否命中都 continue，不进入通用加分，也不扣分
                if hit:
                    bonus += _POSITIVE_BONUS

            for key in _ATTR_KEYS_FOR_RANKING:
                neg_values = negative.get(key)
                if not neg_values:
                    continue
                # A parent product can contain several color variants.  Color is
                # positive evidence only, so a negative color can never filter
                # or penalize a candidate.
                if key == "color":
                    continue
                neg_norm = {self._norm(v) for v in self._flat(neg_values)}
                cand_norm = set(attrs.get(key, []))
                if key == "category":
                    cand_norm |= {
                        self._norm(category)
                        for category in (cand.product.get("categories") or [])
                    }
                neg_hit = bool(neg_norm & cand_norm)
                if not neg_hit and key in _SUBSTRING_FALLBACK_KEYS:
                    neg_hit = any(v in surface for v in neg_norm if len(v) >= 3)
                if neg_hit:
                    penalty += _NEGATIVE_PENALTY

            price = cand.product.get("price")
            if isinstance(price, (int, float)) and budget_hi is not None:
                if price > budget_hi * _BUDGET_TOLERANCE:
                    penalty += _BUDGET_PENALTY
            # price is None -> 完全不参与预算判断，资格保留

            adjusted.append(
                Candidate(
                    parent_asin=cand.parent_asin,
                    score=cand.score + bonus - penalty,
                    search_text=cand.search_text,
                    product=cand.product,
                    route_ranks=cand.route_ranks,
                )
            )
            #用新分数构造新 Candidate，其他字段保留

        adjusted.sort(key=lambda c: (-c.score, c.parent_asin))
        #按新分数降序、parent_asin 升序排序。
        return adjusted

    @staticmethod
    def _norm(value: object) -> str:
        return normalize_token(value)

    @staticmethod
    def _flat(values: Any) -> list[str]:
        if values is None:
            return []
        if isinstance(values, (list, tuple, set)):
            out: list[str] = []
            for v in values:
                out.extend(ConstraintRanker._flat(v))
            return out
        if isinstance(values, dict):
            return []  # budget 结构化 dict 已单独处理；其它 slot 不应出现 dict
        return [str(values)]

    def _attrs_of(self, candidate: Candidate) -> dict[str, list[str]]:
        doc = self._catalog.documents.get(candidate.parent_asin)
        return doc.attributes if doc else {}


def validate_recommendations(
    candidates: list[Candidate],
    valid_ids: set[str],
    fallback_ids: list[str],
    top_k: int = 10,
) -> list[dict]:
    """去重、剔除非法 ID、按 score desc + parent_asin asc 稳定排序；
    候选不足 top_k 时用必传的 fallback_ids（CatalogIndex.stable_fallback_ids()）补齐未出现过的合法 ID。

    对官方 50k catalog，fallback_ids 必须足以补齐 top_k；否则说明 catalog 或调用 contract
    已损坏，显式抛错而不是静默返回不足的 recommendation。
    """
    if top_k < 1:
        raise ValueError("top_k must be at least 1")
    seen: set[str] = set()
    out: list[dict] = []
    ordered = sorted(candidates, key=lambda c: (-c.score, c.parent_asin))
    for cand in ordered:
        asin = str(cand.parent_asin)
        if not asin or asin in seen or asin not in valid_ids:
            continue
        seen.add(asin)
        out.append({"parent_asin": asin, "score": round(float(cand.score), 6)})
        if len(out) >= top_k:
            return out
    for asin in fallback_ids:
        if len(out) >= top_k:
            break
        if asin in seen or asin not in valid_ids:
            continue
        seen.add(asin)
        out.append({"parent_asin": asin})
    if len(out) != top_k:
        raise RuntimeError(
            f"catalog integrity error: unable to produce {top_k} unique valid recommendations"
        )
    return out
