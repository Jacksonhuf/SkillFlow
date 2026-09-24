from __future__ import annotations

from browser_skill.acquire.label_value import find_label_value, parse_label_values


def test_colon_pairs_same_line_and_next_line() -> None:
    text = "订单详情\n订单号：ORD-2024-0917\n客户名称:\n张三贸易\n金额： ¥1,200.00\n"

    pairs = parse_label_values(text)

    assert [(p.label, p.value) for p in pairs] == [
        ("订单号", "ORD-2024-0917"),
        ("客户名称", "张三贸易"),
        ("金额", "¥1,200.00"),
    ]
    assert all(p.confidence == 0.9 for p in pairs)


def test_tab_separated_rows_yield_pairs_for_each_label_value_couple() -> None:
    text = "客户\t张三贸易\t状态\t已完成\n备注\t无\n"

    pairs = parse_label_values(text)

    assert [(p.label, p.value) for p in pairs] == [
        ("客户", "张三贸易"),
        ("状态", "已完成"),
        ("备注", "无"),
    ]
    assert all(p.confidence == 0.8 for p in pairs)


def test_bare_label_needs_a_data_bearing_value_line() -> None:
    text = "首页\n订单管理\n创建时间\n2024-09-17 10:21\n"

    pairs = parse_label_values(text)

    assert [(p.label, p.value, p.confidence) for p in pairs] == [
        ("创建时间", "2024-09-17 10:21", 0.5)
    ]


def test_noisy_labels_are_rejected() -> None:
    text = (
        "价格 ¥12: 3\nhttps://example.internal: x\n"
        "这是一段很长的说明文字，肯定不是标签而是段落。: 值\n"
    )

    assert parse_label_values(text) == []


def test_find_label_value_prefers_exact_match_then_containment() -> None:
    pairs = parse_label_values("金额：1\n含税金额：2\n客户名称：ACME\n")

    assert find_label_value(pairs, ["金额"]) == "1"
    assert find_label_value(pairs, ["含税"]) == "2"
    assert find_label_value(pairs, ["客户"]) == "ACME"
    assert find_label_value(pairs, ["不存在"]) is None
