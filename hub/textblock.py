"""通用受管块编辑：<!-- hub:begin --> … <!-- hub:end -->。

无标记→在末尾追加块；正好一对合法标记→只替换块内、保留块外用户文本；
重复/缺半边/错序/嵌套→抛 BlockError（校验失败，调用方据此零写入，旧文件不动）。
块内用户手改的内容下次会被覆盖——块头已写"自动生成，勿手改"。
"""
BEGIN = "<!-- hub:begin -->"
END = "<!-- hub:end -->"

class BlockError(RuntimeError):
    pass

def _positions(text: str, marker: str) -> list[int]:
    out, i = [], text.find(marker)
    while i != -1:
        out.append(i)
        i = text.find(marker, i + len(marker))
    return out

def upsert_block(text: str, body: str) -> str:
    begins, ends = _positions(text, BEGIN), _positions(text, END)
    if not begins and not ends:
        sep = "" if text == "" or text.endswith("\n") else "\n"
        return f"{text}{sep}{BEGIN}\n{body.rstrip(chr(10))}\n{END}\n"
    if len(begins) != 1 or len(ends) != 1:
        raise BlockError(f"受管块标记不成对/重复（begin×{len(begins)}, end×{len(ends)}），拒绝写入")
    b, e = begins[0], ends[0]
    if b > e:
        raise BlockError("受管块标记顺序颠倒（end 在 begin 之前），拒绝写入")
    before, after = text[:b], text[e + len(END):]
    return f"{before}{BEGIN}\n{body.rstrip(chr(10))}\n{END}{after}"

def has_one_valid_block(text: str) -> bool:
    """恰好一对、顺序正确的受管块 → True；缺失/重复/缺半边/颠倒 → False。
    status --check 用它判受管块良构（不能只 `"hub:begin" in text` 就算 ok）。"""
    b, e = _positions(text, BEGIN), _positions(text, END)
    return len(b) == 1 and len(e) == 1 and b[0] < e[0]
