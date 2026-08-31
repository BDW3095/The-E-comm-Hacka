# [团队自建] tests/test_catalog.py —— A 负责维护
"""覆盖 src/catalog.py 与 src/retrieval.py（按契约文档 3.A 节要求，两者共用这一个测试文件）。

只用 temporary 小 JSONL fixture，不使用 public labels，不读取 catalog.jsonl / public_set.jsonl。
"""
from __future__ import annotations
from src.types import Candidate
import json

import pytest

from src.catalog import CatalogIndex, extract_attributes, flatten_text, normalize_token
from src.retrieval import (
    ConstraintRanker,
    LexicalRetriever,
    compile_positive_query,
    validate_recommendations,
)


class FakeState:
    def __init__(self, positive_slots=None, negative_slots=None, last_query=""):
        self.positive_slots = positive_slots or {}
        self.negative_slots = negative_slots or {}
        self.last_query = last_query


PRODUCTS = [
    {
        "parent_asin": "A0001",
        "title": "Men's Black Cotton Hiking Shirt",
        "features": ["100% Cotton", "Breathable"],
        "description": ["Great for hiking trips."],
        "price": 25.0,
        "categories": ["Clothing, Shoes & Jewelry", "Men", "Shirts"],
        "details": {"Department": "Mens"},
        "average_rating": 4.5,
        "rating_number": 100,
        "store": "TrailCo",
    },
    {
        "parent_asin": "A0002",
        "title": "Women's Red Leather Jacket",
        "features": ["Genuine leather"],
        "description": [],
        "price": 120.0,
        "categories": ["Clothing, Shoes & Jewelry", "Women", "Jackets"],
        "details": {},
        "average_rating": 4.0,
        "rating_number": 50,
        "store": "UrbanFit",
    },
    {
        "parent_asin": "A0003",
        # 空 title / 空 features / 空 details
        "title": "",
        "features": [],
        "description": ["A versatile piece, mentions red somewhere in the description only."],
        "price": None,  # null price 必须保留资格
        "categories": ["Clothing, Shoes & Jewelry", "Accessories"],
        "details": {},
        "average_rating": None,
        "rating_number": None,
        "store": None,
    },
    {
        "parent_asin": "A0001",  # 重复 ID：应被安全忽略，不崩溃
        "title": "Duplicate product should be ignored",
        "features": [],
        "description": [],
        "price": 9.0,
        "categories": [],
        "details": {},
        "average_rating": 5.0,
        "rating_number": 1,
        "store": "Dup",
    },
    {
        "parent_asin": "A0004",
        "title": "Cotton Hiking Socks Multicolor",
        "features": ["Cotton blend", "multiple colors available"],
        "description": [],
        "price": 15.0,
        "categories": ["Clothing, Shoes & Jewelry", "Socks"],
        "details": {},
        "average_rating": 4.2,
        "rating_number": 30,
        "store": "TrailCo",
    },
    {
        "parent_asin": "A0005",
        "title": "Waterproof Packable Rain Jacket",
        "features": ["Fully waterproof shell", "Packable design"],
        "description": [],
        "price": 60.0,
        "categories": ["Clothing, Shoes & Jewelry", "Men", "Jackets"],
        "details": {},
        "average_rating": 4.3,
        "rating_number": 80,
        "store": "TrailCo",
    },
    {
        "parent_asin": "A0006",
        "title": "Classic Striped T Shirt",
        "features": ["Cotton"],
        "description": [],
        "price": 19.99,
        "categories": ["Clothing", "Shirts"],
        "details": {"Color": "Red/White", "Material": "Cotton"},
        "average_rating": 4.0,
        "rating_number": 10,
        "store": "StripeStore",
    },
    {
        "parent_asin": "A0007",
        "title": "Running Shoes",
        "features": ["Cushioned sole"],
        "description": [],
        "price": 80.0,
        "categories": ["Shoes", "Running"],
        "details": {},
        "average_rating": 4.1,
        "rating_number": 12,
        "store": "ShoeStore",
    },
    {
        "parent_asin": "A0008",
        "title": "Gray Wool Sweater",
        "features": ["Warm wool knit"],
        "description": [],
        "price": 45.0,
        "categories": ["Clothing", "Sweaters"],
        "details": {},
        "average_rating": 4.1,
        "rating_number": 12,
        "store": "KnitStore",
    },
]


def _build_index(tmp_path, products) -> CatalogIndex:
    path = tmp_path / "catalog.jsonl"
    with path.open("w", encoding="utf-8") as handle:
        for product in products:
            handle.write(json.dumps(product) + "\n")
    return CatalogIndex(path)


@pytest.fixture()
def catalog_path(tmp_path):
    path = tmp_path / "catalog.jsonl"
    with path.open("w", encoding="utf-8") as handle:
        for product in PRODUCTS:
            handle.write(json.dumps(product) + "\n")
    return path


@pytest.fixture()
def index(catalog_path) -> CatalogIndex:
    return CatalogIndex(catalog_path)


# ---------- catalog.py ----------

def test_flatten_text_handles_none_list_dict():
    assert flatten_text(None) == ""
    assert flatten_text(["a", "", None, "b"]) == "a b"
    assert flatten_text({"Department": "Mens", "empty": ""}) == "Department Mens"


def test_normalize_token_synonyms():
    assert normalize_token("Grey") == "gray"
    assert normalize_token(" COLOUR ") == "color"
    assert normalize_token("Black") == "black"

@pytest.mark.parametrize(
    ("raw_value", "expected"),
    [
        ("quick-dry", "quick dry"),
        ("quick_dry", "quick dry"),
        ("Quick Dry", "quick dry"),
        ("  quick   dry  ", "quick dry"),
    ],
)
def test_normalize_token_handles_separator_variants(raw_value, expected):
    assert normalize_token(raw_value) == expected




def test_index_loads_with_empty_fields_null_price_and_duplicate_ids(index):
    assert len(index.documents) == 8  # 9 条输入，1 条重复 ID 被忽略
    assert "A0001" in index.valid_ids
    doc3 = index.documents["A0003"]
    assert doc3.price is None
    assert doc3.search_text is not None  # 全空字段也不会崩

    # 重复 ID 保留第一条（TrailCo），不是后来的 Dup
    assert index.documents["A0001"].product["store"] == "TrailCo"


def test_extract_attributes_ignores_description_only_hits():
    product = PRODUCTS[2]
    attrs = extract_attributes(product)
    # "red" 只出现在 description 里，不应该被当作正向 color 证据
    assert "red" not in attrs["color"]


def test_extract_attributes_material_and_brand():
    attrs = extract_attributes(PRODUCTS[0])
    assert "cotton" in attrs["material"]
    assert "black" in attrs["color"]
    assert "trailco" in attrs["brand"]


def test_extract_attributes_includes_feature_key():
    """回归测试：ranking 声明支持 feature slot，但此前 attrs 字典里根本没有 'feature' 这个 key，
    导致 ConstraintRanker.rerank 里 attrs.get('feature', []) 永远拿到空 list，feature 永远不会加分。
    """
    product = next(p for p in PRODUCTS if p["parent_asin"] == "A0005")
    attrs = extract_attributes(product)
    assert "feature" in attrs
    assert "waterproof" in attrs["feature"]
    assert "packable" in attrs["feature"]


def test_extract_attributes_maps_details_keys_without_department_brand_pollution():
    product = {
        "parent_asin": "B003",
        "title": "Shoes",
        "features": [],
        "description": "",
        "categories": [],
        "details": {
            "Brand": "Nike",
            "Brand Name": "Nike Inc",
            "Color": "Navy",
            "Material": "Leather",
            "Size": "Large",
            "Style": "Casual",
            "Special Feature": "Waterproof",
            "Department": "Mens",
            "Suggested Users": "Adult",
        },
        "store": "OfficialStore",
    }
    attrs = extract_attributes(product)
    assert {"nike", "nike inc", "officialstore"} <= set(attrs["brand"])
    assert "navy" in attrs["color"]
    assert "leather" in attrs["material"]
    assert "large" in attrs["size"]
    assert "casual" in attrs["style"]
    assert "waterproof" in attrs["feature"]
    assert "mens" not in attrs["brand"]
    assert "adult" not in attrs["brand"]
    assert attrs["brand"] == sorted(attrs["brand"])



def test_details_values_do_not_cross_attribute_boundaries():
    product = {
        "parent_asin": "V1001",
        "title": "Product",
        "features": [],
        "description": [],
        "categories": [],
        "details": {
            "Style": "Black",
            "Color": "Cotton",
        },
        "store": "",
    }

    attrs = extract_attributes(product)

    assert "black" not in attrs["color"]
    assert "cotton" not in attrs["material"]


def test_store_name_does_not_pollute_structured_attributes():
    product = {
        "parent_asin": "V1002",
        "title": "Hiking Boots",
        "features": [],
        "description": [],
        "categories": ["Shoes"],
        "details": {},
        "store": "Black Diamond",
    }

    attrs = extract_attributes(product)

    assert "black diamond" in attrs["brand"]
    assert "black" not in attrs["color"]


def test_brand_aliases_keep_phrases_and_remove_only_suffixes():
    product = {
        "parent_asin": "V1003",
        "title": "Product",
        "features": [],
        "description": [],
        "categories": [],
        "details": {
            "Brand Name": "Nike Inc",
            "Manufacturer": "The North Face",
        },
        "store": "Plain Store",
    }

    brands = set(extract_attributes(product)["brand"])

    assert {"nike inc", "nike", "the north face", "north face", "plain store"} <= brands
    assert {"north", "face", "plain", "store"}.isdisjoint(brands)

@pytest.mark.parametrize(
    "feature_value",
    ["quick-dry", "quick_dry", "Quick Dry"],
)
def test_feature_separator_variants_extract_canonically(feature_value):
    product = {
        "parent_asin": "V1004",
        "title": "Running Shirt",
        "features": [feature_value],
        "description": [],
        "categories": ["Clothing"],
        "details": {},
        "store": "",
    }

    assert "quick dry" in extract_attributes(product)["feature"]




def test_extract_attributes_keeps_store_brand_when_details_missing():
    attrs = extract_attributes({"title": "Socks", "details": None, "store": "TrailCo"})
    assert "trailco" in attrs["brand"]


def test_catalog_index_get_document_and_raw_product(index):
    document = index.get_document("A0001")
    assert document is not None
    assert document.parent_asin == "A0001"
    assert index.get_product("A0001") == document.product
    assert index.get_document("UNKNOWN") is None


# ---------- retrieval.py: query compilation ----------

def test_compile_positive_query_dedup_and_stopwords():
    expr = compile_positive_query("I want a black cotton cotton shirt please")
    assert "black" in expr and "cotton" in expr and "shirt" in expr
    assert expr.count('"cotton"') == 1  # 去重
    assert "want" not in expr and "please" not in expr  # stopwords 去掉


def test_compile_positive_query_empty_and_unsafe_input():
    assert compile_positive_query("") == ""
    assert compile_positive_query("   ") == ""
    # 危险字符不应让构造出的表达式非法（不测试内部转义细节，只测不抛异常且能被 FTS 安全使用）
    expr = compile_positive_query('"; DROP TABLE products; --')
    assert isinstance(expr, str)


# ---------- retrieval.py: LexicalRetriever ----------

def test_lexical_retriever_bm25_direction_and_relevance(index):
    retriever = LexicalRetriever(index)
    results = retriever.retrieve("black cotton hiking shirt", limit=10)
    assert results, "应该召回至少一个候选"
    asins = [c.parent_asin for c in results]
    assert "A0001" in asins
    # 分数越大越相关：结果应已按 score 降序（LexicalRetriever 内部靠 SQL ORDER BY 保证）
    scores = [c.score for c in results]
    assert scores == sorted(scores, reverse=True)


def test_lexical_retriever_empty_query_returns_empty(index):
    retriever = LexicalRetriever(index)
    assert retriever.retrieve("", limit=10) == []
    assert retriever.retrieve("the a an", limit=10) == []  # 全是 stopwords


def test_lexical_retriever_fts_exception_returns_empty_not_raise(index, monkeypatch):
    retriever = LexicalRetriever(index)

    class Boom:
        def execute(self, *a, **k):
            raise RuntimeError("simulated FTS failure")

    monkeypatch.setattr(index, "_conn", Boom())
    assert retriever.retrieve("cotton shirt", limit=10) == []


def test_lexical_retriever_bm25_tie_breaks_by_parent_asin(tmp_path):
    """内容完全相同的商品在 BM25 同分时按 parent_asin 升序返回。"""
    products = [
        {
            "parent_asin": parent_asin,
            "title": "identical tie break product",
            "features": ["same"],
            "description": "same",
            "categories": ["SameCategory"],
            "details": {},
            "store": "SameStore",
            "price": 10.0,
            "average_rating": 4.0,
            "rating_number": 1,
        }
        for parent_asin in ("B001", "A999", "B002")
    ]
    retriever = LexicalRetriever(_build_index(tmp_path, products))

    candidates = retriever.retrieve("identical tie break product", limit=10)
    assert [c.parent_asin for c in candidates] == ["A999", "B001", "B002"]


# ---------- retrieval.py: ConstraintRanker ----------

def test_constraint_ranker_negative_material_penalized(index):
    retriever = LexicalRetriever(index)
    ranker = ConstraintRanker(index)
    # 用 "leather jacket" 而不是 "cotton" —— 后者根本召不回 A0002，会让下面的断言永远跳过、
    # 测试看起来 PASS 但其实什么都没验证到。这里先硬性确认 A0002 确实在候选池里，召回失败要报错。
    candidates = retriever.retrieve("leather jacket", limit=10)
    original = {c.parent_asin: c.score for c in candidates}
    assert "A0002" in original, "precondition failed: A0002 (leather) 没有被召回，无法验证 negative 惩罚"

    state = FakeState(negative_slots={"material": ["leather"]})
    ranked = ranker.rerank(candidates, state)
    by_asin = {c.parent_asin: c.score for c in ranked}
    assert by_asin["A0002"] < original["A0002"]


def test_constraint_ranker_color_match_gets_bonus(index):
    retriever = LexicalRetriever(index)
    ranker = ConstraintRanker(index)
    candidates = retriever.retrieve("black cotton shirt", limit=10)
    original = {c.parent_asin: c.score for c in candidates}
    assert "A0001" in original, "precondition failed: A0001 (black) 没有被召回"

    ranked = ranker.rerank(candidates, FakeState(positive_slots={"color": ["black"]}))
    by_asin = {c.parent_asin: c.score for c in ranked}
    assert by_asin["A0001"] > original["A0001"]


def test_constraint_ranker_negative_color_does_not_penalize(index):
    """negative color 被忽略；color 不能作为 parent product 的负向证据。"""
    retriever = LexicalRetriever(index)
    ranker = ConstraintRanker(index)
    candidates = retriever.retrieve("red leather jacket", limit=10)
    original = {c.parent_asin: c.score for c in candidates}
    assert "A0002" in original, "precondition failed: A0002 (red) 没有被召回"

    ranked = ranker.rerank(candidates, FakeState(negative_slots={"color": ["red"]}))
    by_asin = {c.parent_asin: c.score for c in ranked}
    assert by_asin["A0002"] == pytest.approx(original["A0002"])


def test_constraint_ranker_negative_category_reads_raw_product_categories(index):
    """category 不在 extracted attrs 中时仍须读取 raw product categories。"""
    retriever = LexicalRetriever(index)
    ranker = ConstraintRanker(index)
    candidates = retriever.retrieve("running shoes", limit=10)
    original = {c.parent_asin: c.score for c in candidates}
    assert "A0007" in original, "precondition failed: A0007 (Shoes) 没有被召回"

    ranked = ranker.rerank(candidates, FakeState(negative_slots={"category": ["shoes"]}))
    by_asin = {c.parent_asin: c.score for c in ranked}
    assert by_asin["A0007"] < original["A0007"]


def test_constraint_ranker_grey_slot_matches_gray_catalog_attribute(index):
    """B 的 grey slot 与 catalog 规范化后的 gray attribute 必须匹配。"""
    retriever = LexicalRetriever(index)
    ranker = ConstraintRanker(index)
    candidates = retriever.retrieve("gray sweater", limit=10)
    original = {c.parent_asin: c.score for c in candidates}
    assert "A0008" in original, "precondition failed: A0008 (gray) 没有被召回"
    assert "gray" in index.get_document("A0008").attributes["color"]

    ranked = ranker.rerank(candidates, FakeState(positive_slots={"color": ["grey"]}))
    by_asin = {c.parent_asin: c.score for c in ranked}
    assert by_asin["A0008"] > original["A0008"]


def test_constraint_ranker_single_red_color_stays_neutral_for_black_request(index):
    retriever = LexicalRetriever(index)
    ranker = ConstraintRanker(index)
    candidates = retriever.retrieve("red leather jacket", limit=10)
    original = {c.parent_asin: c.score for c in candidates}
    assert "A0002" in original, "precondition failed: A0002 (red) 没有被召回"

    ranked = ranker.rerank(candidates, FakeState(positive_slots={"color": ["black"]}))
    by_asin = {c.parent_asin: c.score for c in ranked}
    assert by_asin["A0002"] == pytest.approx(original["A0002"])
    assert "A0002" in by_asin


def test_constraint_ranker_red_white_detail_stays_neutral_for_black_request(index):
    retriever = LexicalRetriever(index)
    ranker = ConstraintRanker(index)
    candidates = retriever.retrieve("striped t shirt", limit=10)
    original = {c.parent_asin: c.score for c in candidates}
    assert "A0006" in original, "precondition failed: A0006 (red/white) 没有被召回"
    assert {"red", "white"} <= set(index.get_document("A0006").attributes["color"])

    ranked = ranker.rerank(candidates, FakeState(positive_slots={"color": ["black"]}))
    by_asin = {c.parent_asin: c.score for c in ranked}
    assert by_asin["A0006"] == pytest.approx(original["A0006"])


def test_constraint_ranker_multicolor_stays_neutral(index):
    retriever = LexicalRetriever(index)
    ranker = ConstraintRanker(index)
    candidates = retriever.retrieve("cotton hiking socks", limit=10)
    original = {c.parent_asin: c.score for c in candidates}
    assert "A0004" in original, "precondition failed: A0004 (multicolor) 没有被召回"

    ranked = ranker.rerank(candidates, FakeState(positive_slots={"color": ["black"]}))
    by_asin = {c.parent_asin: c.score for c in ranked}
    # A0004 是 multicolor，缺乏可靠单一颜色证据——不该因为不是 black 被扣分，保持中性
    assert by_asin["A0004"] == pytest.approx(original["A0004"])


def test_constraint_ranker_description_only_color_stays_neutral(index):
    retriever = LexicalRetriever(index)
    ranker = ConstraintRanker(index)
    candidates = retriever.retrieve("versatile piece", limit=10)
    original = {c.parent_asin: c.score for c in candidates}
    assert "A0003" in original, "precondition failed: A0003 没有被召回"

    ranked = ranker.rerank(candidates, FakeState(positive_slots={"color": ["black"]}))
    by_asin = {c.parent_asin: c.score for c in ranked}
    # A0003 的 "red" 只出现在 description 里，不是正向证据；不是 black 也不该被扣分
    assert by_asin["A0003"] == pytest.approx(original["A0003"])


def test_constraint_ranker_null_price_not_penalized(index):
    retriever = LexicalRetriever(index)
    ranker = ConstraintRanker(index)
    candidates = retriever.retrieve("versatile piece", limit=10)
    original = {c.parent_asin: c.score for c in candidates}
    assert "A0003" in original, "precondition failed: A0003 (price=None) 没有被召回"

    ranked = ranker.rerank(candidates, FakeState(positive_slots={"budget": ["under $10"]}))
    by_asin = {c.parent_asin: c.score for c in ranked}
    # A0003 price=None，即使远超预算的表述存在也不能被扣分
    assert by_asin["A0003"] == pytest.approx(original["A0003"])


@pytest.mark.parametrize("budget", [["min:25"], ["target:50"]])
def test_constraint_ranker_does_not_treat_non_max_budget_as_ceiling(index, budget):
    """B preserves min/target semantics; A must not reinterpret either as max."""
    retriever = LexicalRetriever(index)
    ranker = ConstraintRanker(index)
    candidates = retriever.retrieve("red leather jacket", limit=10)
    original = {c.parent_asin: c.score for c in candidates}
    assert "A0002" in original, "precondition failed: A0002 没有被召回"

    ranked = ranker.rerank(candidates, FakeState(positive_slots={"budget": budget}))
    by_asin = {c.parent_asin: c.score for c in ranked}
    assert by_asin["A0002"] == pytest.approx(original["A0002"])


@pytest.mark.parametrize("budget", [["max:40"], ["under $40"]])
def test_constraint_ranker_penalizes_only_explicit_upper_budget(index, budget):
    retriever = LexicalRetriever(index)
    ranker = ConstraintRanker(index)
    candidates = retriever.retrieve("red leather jacket", limit=10)
    original = {c.parent_asin: c.score for c in candidates}
    assert "A0002" in original, "precondition failed: A0002 没有被召回"

    ranked = ranker.rerank(candidates, FakeState(positive_slots={"budget": budget}))
    by_asin = {c.parent_asin: c.score for c in ranked}
    assert by_asin["A0002"] < original["A0002"]


def test_feature_separator_variants_receive_rerank_bonus(tmp_path):
    product = {
        "parent_asin": "Q0001",
        "title": "Quick-Dry Running Jacket",
        "features": ["Quick-Dry fabric"],
        "description": [],
        "price": 40.0,
        "categories": ["Clothing", "Jackets"],
        "details": {},
        "average_rating": 4.0,
        "rating_number": 5,
        "store": "Runner Brand",
    }

    separator_index = _build_index(tmp_path, [product])
    retriever = LexicalRetriever(separator_index)
    ranker = ConstraintRanker(separator_index)

    candidates = retriever.retrieve("quick dry jacket", limit=10)
    original = {candidate.parent_asin: candidate.score for candidate in candidates}

    assert "Q0001" in original

    ranked = ranker.rerank(
        candidates,
        FakeState(positive_slots={"feature": ["quick_dry"]}),
    )
    updated = {candidate.parent_asin: candidate.score for candidate in ranked}

    assert updated["Q0001"] > original["Q0001"]


def test_constraint_ranker_feature_positive_bonus(index):
    """回归测试：修复前 attrs 字典里没有 'feature' key，这个测试之前会失败（现在应该通过）。"""
    retriever = LexicalRetriever(index)
    ranker = ConstraintRanker(index)
    candidates = retriever.retrieve("waterproof packable rain jacket", limit=10)
    original = {c.parent_asin: c.score for c in candidates}
    assert "A0005" in original, "precondition failed: A0005 (waterproof) 没有被召回"

    ranked = ranker.rerank(candidates, FakeState(positive_slots={"feature": ["waterproof"]}))
    by_asin = {c.parent_asin: c.score for c in ranked}
    assert by_asin["A0005"] > original["A0005"]


def test_constraint_ranker_no_slots_returns_stable_sort(index):
    retriever = LexicalRetriever(index)
    ranker = ConstraintRanker(index)
    candidates = retriever.retrieve("cotton", limit=10)
    ranked = ranker.rerank(candidates, FakeState())
    scores = [c.score for c in ranked]
    assert scores == sorted(scores, reverse=True)


def test_constraint_ranker_rewards_cumulative_query_coverage(index):
    ranker = ConstraintRanker(index)
    weak = Candidate(
        parent_asin="A0003",
        score=5.0,
        search_text="cotton accessory",
        product=index.get_product("A0003"),
    )
    strong = Candidate(
        parent_asin="A0001",
        score=1.0,
        search_text="black cotton hiking shirt",
        product=index.get_product("A0001"),
    )

    ranked = ranker.rerank(
        [weak, strong],
        FakeState(last_query="black cotton hiking shirt"),
    )

    assert ranked[0].parent_asin == "A0001"


def test_constraint_ranker_ignores_unknown_slot_keys(index):
    """B 未来词典扩展出未知 key 时，不能让 retrieval 崩溃。"""
    retriever = LexicalRetriever(index)
    ranker = ConstraintRanker(index)
    candidates = retriever.retrieve("cotton", limit=10)
    state = FakeState(positive_slots={"totally_unknown_attribute": ["whatever"]})
    ranked = ranker.rerank(candidates, state)  # 不应抛异常
    assert len(ranked) == len(candidates)


# ---------- retrieval.py: validate_recommendations ----------

def test_validate_recommendations_dedup_and_stable_order(index):
    

    candidates = [
        Candidate(parent_asin="A0002", score=1.0, search_text="", product={}, route_ranks={}),
        Candidate(parent_asin="A0001", score=1.0, search_text="", product={}, route_ranks={}),
        Candidate(parent_asin="A0001", score=1.0, search_text="", product={}, route_ranks={}),  # 重复
        Candidate(parent_asin="NOT_IN_CATALOG", score=99.0, search_text="", product={}, route_ranks={}),
    ]
    out = validate_recommendations(
        candidates,
        index.valid_ids,
        fallback_ids=index.stable_fallback_ids(),
        top_k=5,
    )
    asins = [item["parent_asin"] for item in out]
    assert asins.count("A0001") == 1  # 去重
    assert "NOT_IN_CATALOG" not in asins  # 非法 ID 被剔除
    assert len(asins) == 5
    # 同分时按 parent_asin 升序稳定排序
    assert asins.index("A0001") < asins.index("A0002")


def test_validate_recommendations_pads_with_fallback_to_exact_top_k(index):
    

    candidates = [Candidate(parent_asin="A0001", score=5.0, search_text="", product={}, route_ranks={})]
    fallback = index.stable_fallback_ids()
    out = validate_recommendations(candidates, index.valid_ids, fallback_ids=fallback, top_k=4)
    assert len(out) == 4  # 候选只有1个，其余3个由 fallback 补齐
    asins = [item["parent_asin"] for item in out]
    assert len(set(asins)) == len(asins)  # 补齐部分也不重复


def test_validate_recommendations_empty_candidates_still_fills_from_fallback(index):
    out = validate_recommendations([], index.valid_ids, fallback_ids=index.stable_fallback_ids(), top_k=4)
    assert len(out) == 4


def test_validate_recommendations_raises_when_catalog_cannot_fill_top_k(index):
    with pytest.raises(RuntimeError, match="catalog integrity error"):
        validate_recommendations(
            [],
            index.valid_ids,
            fallback_ids=index.stable_fallback_ids(),
            top_k=len(index.valid_ids) + 1,
        )


def test_validate_recommendations_empty_candidates_produces_exact_top_ten(tmp_path):
    products = [
        {
            "parent_asin": f"T{i:04d}",
            "title": f"Fallback Shirt {i}",
            "features": [],
            "description": [],
            "price": None,
            "categories": ["Clothing"],
            "details": {},
            "average_rating": 4.0,
            "rating_number": i,
            "store": "FallbackStore",
        }
        for i in range(10)
    ]
    ten_index = _build_index(tmp_path, products)
    out = validate_recommendations(
        [],
        ten_index.valid_ids,
        fallback_ids=ten_index.stable_fallback_ids(),
        top_k=10,
    )
    asins = [item["parent_asin"] for item in out]
    assert len(asins) == 10
    assert len(set(asins)) == 10
    assert set(asins) == ten_index.valid_ids


def test_fts_exception_then_validation_still_produces_top_ten(tmp_path, monkeypatch):
    products = [
        {
            "parent_asin": f"E{i:04d}",
            "title": f"Exception Shirt {i}",
            "features": [],
            "description": [],
            "price": None,
            "categories": ["Clothing"],
            "details": {},
            "average_rating": 4.0,
            "rating_number": i,
            "store": "FallbackStore",
        }
        for i in range(10)
    ]
    ten_index = _build_index(tmp_path, products)
    retriever = LexicalRetriever(ten_index)

    class Boom:
        def execute(self, *args, **kwargs):
            raise RuntimeError("simulated FTS failure")

    monkeypatch.setattr(ten_index, "_conn", Boom())
    out = validate_recommendations(
        retriever.retrieve("shirt", limit=10),
        ten_index.valid_ids,
        fallback_ids=ten_index.stable_fallback_ids(),
        top_k=10,
    )
    assert len(out) == 10
    assert len({item["parent_asin"] for item in out}) == 10
