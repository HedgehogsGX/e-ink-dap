"""Helpers shared by the card tools (build_index.py, books.py, fonts.py)."""
import os
import re
import unicodedata

INDEX_DIR = ".dap"


def ident(text):
    return unicodedata.normalize("NFKC", text).casefold().strip()


def sort_key(text):
    """Case- and width-insensitive, ignores leading punctuation, empty sorts last. Without
    sort tags, scripts sort Latin, then kana, then kanji/hanzi by code point."""
    s = ident(text)
    s = re.sub(r"^[\W_]+", "", s) or s
    return (s == "", s)


def card_path(file, root):
    """Path of a file on the card as the player sees it: from the root, NFC, '/' separators."""
    return unicodedata.normalize("NFC", "/" + file.relative_to(root).as_posix())


def write_atomic(path, data):
    """Writes to path.tmp, then renames, so an interrupted run leaves the old file in place."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def skipped_name(name):
    """Hidden files and folders (.dap, .Trashes, the ._ files macOS leaves on FAT32)."""
    return name.startswith(".") or name == "System Volume Information"


class Strings:
    """NUL-terminated UTF-8 strings, each stored once. Offset 0 is the empty string."""

    def __init__(self):
        self.data = bytearray(b"\0")
        self.offsets = {"": 0}

    def add(self, text):
        if text not in self.offsets:
            self.offsets[text] = len(self.data)
            self.data += text.replace("\0", "").encode("utf-8") + b"\0"
        return self.offsets[text]


def read_string(data, start):
    return data[start:data.index(b"\0", start)].decode("utf-8")
