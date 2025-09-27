import re

def escape_markdown(text: str) -> str:
    """
    Екранує спеціальні символи для старого Markdown, який використовується в боті.
    """
    if not isinstance(text, str):
        text = str(text)
    # Для parse_mode="Markdown" потрібно екранувати лише ці символи
    escape_chars = r"([*_`\[])"
    return re.sub(escape_chars, r"\\\1", text)