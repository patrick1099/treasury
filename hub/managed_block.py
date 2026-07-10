BEGIN = "<!-- hub:begin -->"
END = "<!-- hub:end -->"

def extract_block(text: str) -> str | None:
    i = text.find(BEGIN)
    j = text.find(END)
    if i == -1 or j == -1 or j < i:
        return None
    inner = text[i + len(BEGIN):j]
    return inner.strip("\n")

def replace_block(text: str, new_inner: str) -> str:
    block = f"{BEGIN}\n{new_inner}\n{END}"
    i = text.find(BEGIN)
    j = text.find(END)
    if i != -1 and j != -1 and j >= i:
        return text[:i] + block + text[j + len(END):]
    prefix = text if text.endswith("\n") or text == "" else text + "\n"
    if prefix and not prefix.endswith("\n\n") and prefix != "":
        prefix = prefix + "\n"
    return prefix + block + "\n"
