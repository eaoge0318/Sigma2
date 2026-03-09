"""
knowledge_utils.py
──────────────────
current_knowledge 結構化管理工具。

current_knowledge 以三個段落儲存:
  [ROUTING]    → 模式路由標籤 (系統寫入, 不可被覆蓋)
  [SUMMARY]    → 精煉歷史摘要 (Synthesizer 管理, JSON 事件字典)
  [DASHBOARD]  → 每 Turn 追加的報告更新
"""

from __future__ import annotations

# ── section 分隔標記 ──
_SEC_ROUTING = "=== [ROUTING] ==="
_SEC_SUMMARY = "=== [SUMMARY] ==="
_SEC_DASHBOARD = "=== [DASHBOARD] ==="


def build_initial_knowledge(routing_text: str) -> str:
    """
    初始化 current_knowledge, 帶 [ROUTING] 段落。
    後續 [SUMMARY] 和 [DASHBOARD] 會在分析過程中自動追加。
    """
    return f"{_SEC_ROUTING}\n{routing_text}\n{_SEC_SUMMARY}\n\n{_SEC_DASHBOARD}\n"


def get_section(knowledge: str, section: str) -> str:
    """
    從 current_knowledge 中擷取指定段落的內容。
    section: "ROUTING" | "SUMMARY" | "DASHBOARD"
    """
    markers = {
        "ROUTING": (_SEC_ROUTING, _SEC_SUMMARY),
        "SUMMARY": (_SEC_SUMMARY, _SEC_DASHBOARD),
        "DASHBOARD": (_SEC_DASHBOARD, None),
    }
    if section not in markers:
        raise ValueError(f"Unknown section: {section}")

    start_mark, end_mark = markers[section]
    start_idx = knowledge.find(start_mark)
    if start_idx == -1:
        # 向後兼容: 沒有段落標記的舊格式, 整段當作 ROUTING
        return knowledge if section == "ROUTING" else ""

    content_start = start_idx + len(start_mark)
    if end_mark:
        end_idx = knowledge.find(end_mark, content_start)
        if end_idx == -1:
            return knowledge[content_start:].strip()
        return knowledge[content_start:end_idx].strip()
    else:
        return knowledge[content_start:].strip()


def set_section(knowledge: str, section: str, content: str) -> str:
    """
    替換指定段落的內容, 其他段落不變。
    """
    markers = {
        "ROUTING": (_SEC_ROUTING, _SEC_SUMMARY),
        "SUMMARY": (_SEC_SUMMARY, _SEC_DASHBOARD),
        "DASHBOARD": (_SEC_DASHBOARD, None),
    }
    if section not in markers:
        raise ValueError(f"Unknown section: {section}")

    start_mark, end_mark = markers[section]
    start_idx = knowledge.find(start_mark)

    if start_idx == -1:
        # 沒有段落標記 → 用 build_initial_knowledge 重建再 set
        knowledge = build_initial_knowledge(knowledge)
        return set_section(knowledge, section, content)

    content_start = start_idx + len(start_mark)
    if end_mark:
        end_idx = knowledge.find(end_mark, content_start)
        if end_idx == -1:
            # end marker 遺失, 追加
            return knowledge[:content_start] + f"\n{content}\n" + f"{end_mark}\n"
        return knowledge[:content_start] + f"\n{content}\n" + knowledge[end_idx:]
    else:
        return knowledge[:content_start] + f"\n{content}\n"


def append_to_section(knowledge: str, section: str, text: str) -> str:
    """
    在指定段落尾部追加文字。
    """
    current = get_section(knowledge, section)
    new_content = current + "\n" + text if current else text
    return set_section(knowledge, section, new_content)


def append_routing(knowledge: str, text: str) -> str:
    """快捷: 在 ROUTING 段落追加。"""
    return append_to_section(knowledge, "ROUTING", text)


def get_summary(knowledge: str) -> str:
    """快捷: 取得 SUMMARY 段落 (JSON 事件字典)。"""
    return get_section(knowledge, "SUMMARY")


def set_summary(knowledge: str, summary_json: str) -> str:
    """快捷: 設定 SUMMARY 段落。"""
    return set_section(knowledge, "SUMMARY", summary_json)


def append_dashboard(knowledge: str, text: str) -> str:
    """快捷: 在 DASHBOARD 段落追加。"""
    return append_to_section(knowledge, "DASHBOARD", text)


def inject_to_section(
    knowledge: str,
    section: str,
    label: str,
    text: str,
    module: str = "",
) -> str:
    """
    向指定 section 注入帶標籤的資訊塊。
    取代原本 synthesizer.inject_to_rolling_summary。
    """
    tag = f"[{module}]" if module else ""
    block = f"\n[{label}] {tag}\n{text}\n"
    return append_to_section(knowledge, section, block)
