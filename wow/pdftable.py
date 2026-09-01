# -*- coding: utf-8 -*-
"""PDF 表格解析：处罚名单 PDF（2~4 列）→ 行列表。

解析策略（按坐标，抗乱序/挤压）：
- get_text('words') 取词坐标，按 y 聚类成行、行内按 x 分列 → 无视 PDF 内容流的
  绘制顺序（有的 PDF 文本流乱序）
- 表头行：整行能切出 >= 2 个表头词即为表头，列数 = 拆开后的表头词数。有的 PDF
  表头字距不足会把「服务器名 违规次数」并成一格，必须先按词表切开，否则列数
  定不下来、整表被丢（20251204 PVE 就是这样转出空表的）
- 数据行列数不足时，按「次数词后缀」和「服务器名词库」逐轮拆分粘连单元格
"""

from __future__ import annotations

import logging

logger = logging.getLogger("astrbot_plugin_wow.pdftable")

_HEADER_WORDS = {
    "角色名", "角色昵称", "服务器名", "违规次数", "次数", "账号", "昵称", "区服", "服务器",
    "游戏名", "时间", "日期", "原因", "处罚", "处罚类型", "处罚措施", "处罚原因", "处罚内容",
    "违规", "是否二次违规", "备注", "说明", "编号", "序号", "等级", "标题", "内容",
}
_COUNT_WORDS = ("首次违规", "多次违规", "首次", "多次")
_ROW_GAP = 10   # 行聚类：y/10 取整
_CELL_GAP = 8   # 同列词间距阈值：超过则视为新列（pt）


def _page_rows(page) -> list[list[str]]:
    """坐标解析：返回该页所有行（每行 = 按 x 分列后的单元格列表）。"""
    words = page.get_text("words")
    lines: dict[int, list] = {}
    for w in words:
        lines.setdefault(round(w[1] / _ROW_GAP), []).append(w)
    rows = []
    for key in sorted(lines):
        ws = sorted(lines[key], key=lambda w: w[0])
        cells: list[str] = []
        cur, cur_x1 = [ws[0][4]], ws[0][2]
        for w in ws[1:]:
            if w[0] - cur_x1 > _CELL_GAP:
                cells.append("".join(cur))
                cur = [w[4]]
            else:
                cur.append(w[4])
            cur_x1 = max(cur_x1, w[2])
        cells.append("".join(cur))
        rows.append(cells)
    return rows


def _segment_header(cell: str) -> list[str] | None:
    """把一个（可能粘连的）表头单元格切成表头词序列；含非表头内容返回 None。"""
    out: list[str] = []
    i = 0
    while i < len(cell):
        for w in sorted(_HEADER_WORDS, key=len, reverse=True):
            if cell.startswith(w, i):
                out.append(w)
                i += len(w)
                break
        else:
            return None
    return out or None


def _header_cells(cells: list[str]) -> list[str] | None:
    """是表头行则返回拆开后的表头词列表，否则 None。"""
    out: list[str] = []
    for c in cells:
        seg = _segment_header(c)
        out.extend(seg) if seg else out.append(c)
    return out if sum(1 for c in out if c in _HEADER_WORDS) >= 2 else None


def _split_by_count(cell: str) -> list[str] | None:
    """按次数词后缀拆分（服务器名+违规次数粘连，无需词库）。长词优先。"""
    for cw in _COUNT_WORDS:
        if cell.endswith(cw) and len(cell) > len(cw):
            return [cell[: -len(cw)], cw]
    return None


def _split_by_realm(cell: str, realms: set[str]) -> list[str] | None:
    """把粘连单元格按服务器名拆开；服务器名取最长匹配。"""
    for r in sorted(realms, key=len, reverse=True):
        if cell.startswith(r) and len(cell) > len(r):
            return [r, cell[len(r):]]
        if cell.endswith(r) and len(cell) > len(r):
            return [cell[: -len(r)], r]
    return None


def _fix_short_rows(
    short: list[list[str]], n: int, realms: set[str]
) -> tuple[list[list[str]], list[list[str]]]:
    """多轮修复列数不足的行：次数词优先，再按服务器名词库拆。拆不动的一并返回。"""
    fixed: list[list[str]] = []
    pending = list(short)
    while pending:
        progressed = False
        remain: list[list[str]] = []
        for cells in pending:
            grown = None
            for i, c in enumerate(cells):
                parts = _split_by_count(c) or _split_by_realm(c, realms)
                if parts and len(cells) + len(parts) - 1 <= n:
                    grown = cells[:i] + parts + cells[i + 1:]
                    if len(parts) == 2:
                        realms.add(parts[0])
                    break
            if grown is None:
                remain.append(cells)
                continue
            progressed = True
            (fixed if len(grown) == n else remain).append(grown)
        if not progressed:
            return fixed, remain
        pending = remain
    return fixed, pending


def extract_rows(
    pdf_path, seed_realms: set[str] | None = None
) -> tuple[list[list[str]], list[str], list[str]]:
    """解析 PDF 表格，返回 (数据行, 表头, 警告)。列数由表头行确定。

    seed_realms：外部提供的服务器名词库（如从已有 xlsx 学到的）。单份 PDF 里若某个
    服务器的行全部粘连，本份内学不到，只能靠它补。
    """
    import pymupdf  # 局部导入：没装 pymupdf 时插件其余功能照常

    doc = pymupdf.open(str(pdf_path))
    header: list[str] | None = None
    n: int | None = None
    good: list[list[str]] = []
    short: list[list[str]] = []
    warns: list[str] = []
    try:
        for pi, page in enumerate(doc):
            for cells in _page_rows(page):
                hdr = _header_cells(cells)
                if hdr is not None:
                    if header is None:
                        header, n = hdr, len(hdr)
                    elif len(hdr) != n:
                        warns.append(
                            f"第 {pi + 1} 页表头列数({len(hdr)})与首页({n})不一致，按 {n} 列解析")
                    continue
                if n is None:
                    continue  # 未遇到表头前（封面/水印）跳过
                if len(cells) == n:
                    good.append(cells)
                elif len(cells) < n:
                    short.append(cells)
                else:
                    warns.append(f"第 {pi + 1} 页某行列数({len(cells)})异常，已丢弃：{cells}")
    finally:
        doc.close()
    if header is None:
        return [], ["列1", "列2"], warns

    realms = set(seed_realms or ())
    realms.update(r[1] for r in good if len(r) >= 2)
    rows = list(good)
    fixed, remain = _fix_short_rows(short, n, realms)
    rows.extend(fixed)
    for cells in remain:
        warns.append(f"某行列数不足且无法拆分，已丢弃：{cells}")
    return rows, header, warns
