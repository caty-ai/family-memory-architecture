"""Fail-closed parser for the small YAML subset used by FMA lint configs.

This is deliberately not a general YAML implementation. It accepts mapping
documents with two-space indentation, nested mappings, block lists, lists of
mappings, and inline lists of scalar values. Unsupported YAML features are
rejected instead of being guessed at.
"""

import json
import re


KEY_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_.-]*")
INTEGER_RE = re.compile(r"-?(?:0|[1-9]\d*)")
DECIMAL_RE = re.compile(r"-?(?:0|[1-9]\d*)\.\d+")
ISO_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
SPECIAL_FLOAT_RE = re.compile(r"[+-]?\.(?:inf|nan)", re.IGNORECASE)
NUMERIC_LIKE_RE = re.compile(
    r"[+-]?(?:"
    r"0[xX][0-9A-Fa-f_]+|"
    r"0[oO][0-7_]+|"
    r"0[bB][01_]+|"
    r"(?:\d[\d_]*(?:\.\d[\d_]*)?|\.\d[\d_]*|\d[\d_]*\.)(?:[eE][+-]?\d[\d_]*)?"
    r")"
)
SPECIAL_TOKEN_RE = re.compile(r"(?:^|\s)[&*!]")
AMBIGUOUS_WORDS = {"yes", "no", "on", "off", "true", "false", "null"}


class YamlSubsetError(ValueError):
    """Raised when text is outside the supported YAML subset."""


class _Line:
    def __init__(self, number, indent, content):
        self.number = number
        self.indent = indent
        self.content = content


def _error(line_number, message):
    raise YamlSubsetError(f"line {line_number}: {message}")


def _strip_comment(raw_line):
    in_single = False
    in_double = False
    escaped = False
    for index, char in enumerate(raw_line):
        if escaped:
            escaped = False
            continue
        if char == "\\" and in_double:
            escaped = True
            continue
        if char == "'" and not in_double:
            in_single = not in_single
            continue
        if char == '"' and not in_single:
            in_double = not in_double
            continue
        if char == "#" and not in_single and not in_double:
            return raw_line[:index].rstrip()
    return raw_line.rstrip()


def _validate_characters(text):
    line_number = 1
    for index, char in enumerate(text):
        codepoint = ord(char)
        if char == "\t":
            _error(line_number, "tabs are not allowed")
        if (codepoint < 0x20 and char not in "\r\n") or 0x7F <= codepoint <= 0x9F:
            _error(line_number, f"forbidden control character U+{codepoint:04X}")
        if char == "\n" or (char == "\r" and (index + 1 == len(text) or text[index + 1] != "\n")):
            line_number += 1


def _tokenize(text):
    _validate_characters(text)
    lines = []
    for line_number, raw_line in enumerate(text.splitlines(), 1):
        line = _strip_comment(raw_line)
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" "))
        if indent % 2:
            _error(line_number, "indentation must use multiples of two spaces")
        content = line[indent:]
        if content in ("---", "..."):
            _error(line_number, "multi-document markers are not supported")
        if content.startswith("%"):
            _error(line_number, "YAML directives are not supported")
        lines.append(_Line(line_number, indent, content))
    return lines


def _parse_quoted(value, line_number):
    quote = value[0]
    if len(value) < 2 or value[-1] != quote:
        _error(line_number, "unterminated quoted string")
    if quote == '"':
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as exc:
            _error(line_number, f"malformed double-quoted string: {exc.msg}")
        if not isinstance(parsed, str):
            _error(line_number, "expected a quoted string")
        return parsed

    inner = value[1:-1]
    index = 0
    output = []
    while index < len(inner):
        if inner[index] != "'":
            output.append(inner[index])
            index += 1
            continue
        if index + 1 >= len(inner) or inner[index + 1] != "'":
            _error(line_number, "single quotes inside a single-quoted string must be doubled")
        output.append("'")
        index += 2
    return "".join(output)


def _split_inline_list(value, line_number):
    if not value.endswith("]"):
        _error(line_number, "unterminated inline list")
    inner = value[1:-1]
    if not inner.strip():
        return []

    items = []
    start = 0
    in_single = False
    in_double = False
    escaped = False
    for index, char in enumerate(inner):
        if escaped:
            escaped = False
            continue
        if char == "\\" and in_double:
            escaped = True
            continue
        if char == "'" and not in_double:
            in_single = not in_single
            continue
        if char == '"' and not in_single:
            in_double = not in_double
            continue
        if not in_single and not in_double and char in "[]{}":
            _error(line_number, "nested flow collections are not supported")
        if char == "," and not in_single and not in_double:
            item = inner[start:index].strip()
            if not item:
                _error(line_number, "inline list contains an empty item")
            items.append(item)
            start = index + 1
    if in_single or in_double:
        _error(line_number, "unterminated quoted string in inline list")
    item = inner[start:].strip()
    if not item:
        _error(line_number, "inline list must not end with a comma")
    items.append(item)
    return items


def _parse_scalar(value, line_number):
    value = value.strip()
    if not value:
        _error(line_number, "empty scalar value")
    if value[0] in ("'", '"'):
        return _parse_quoted(value, line_number)
    if value.startswith("["):
        return [_parse_scalar(item, line_number) for item in _split_inline_list(value, line_number)]
    if "]" in value or "[" in value:
        _error(line_number, "malformed inline list")
    if "'" in value or '"' in value:
        _error(line_number, "quotes must enclose the entire scalar")
    if value == "{}":
        return {}
    if "{" in value or "}" in value:
        _error(line_number, "non-empty flow mappings are not supported")
    if SPECIAL_TOKEN_RE.search(value):
        _error(line_number, "anchors, aliases, and tags are not supported")
    if value.startswith(("|", ">")):
        _error(line_number, "block scalars are not supported")
    if value == "~" or value.casefold() in AMBIGUOUS_WORDS:
        if value not in ("null", "true", "false"):
            _error(line_number, f"ambiguous implicit YAML scalar {value!r} is not supported")
    if value == "null":
        return None
    if value == "true":
        return True
    if value == "false":
        return False
    if INTEGER_RE.fullmatch(value):
        return int(value)
    if DECIMAL_RE.fullmatch(value):
        return float(value)
    if ISO_DATE_RE.fullmatch(value):
        _error(line_number, "unquoted ISO dates are not supported")
    if SPECIAL_FLOAT_RE.fullmatch(value) or NUMERIC_LIKE_RE.fullmatch(value):
        _error(line_number, f"unsupported numeric scalar {value!r}")
    if ":" in value or "," in value:
        _error(line_number, "plain strings containing ':' or ',' must be quoted")
    if value[0] in "-?:@`":
        _error(line_number, f"unsupported plain scalar {value!r}")
    return value


def _parse_key_value(content, line_number):
    if ":" not in content:
        _error(line_number, "expected key: value")
    key, value = content.split(":", 1)
    key = key.strip()
    if not KEY_RE.fullmatch(key):
        _error(line_number, f"invalid mapping key {key!r}")
    if value and not value.startswith(" "):
        _error(line_number, "mapping values must be separated from ':' by a space")
    return key, value.strip()


def _is_list_item(content):
    return content == "-" or content.startswith("- ")


def _is_mapping_entry(content):
    return re.match(r"[A-Za-z_][A-Za-z0-9_.-]*:(?: |$)", content) is not None


class _Parser:
    def __init__(self, lines):
        self.lines = lines

    def parse(self):
        if not self.lines:
            _error(1, "document is empty")
        first = self.lines[0]
        if first.indent != 0:
            _error(first.number, "top-level content must not be indented")
        if _is_list_item(first.content):
            _error(first.number, "top-level document must be a mapping")
        data, index = self._parse_mapping(0, 0)
        if index != len(self.lines):
            line = self.lines[index]
            _error(line.number, "unexpected content")
        return data

    def _parse_child(self, index, parent_indent):
        if index >= len(self.lines) or self.lines[index].indent <= parent_indent:
            return None, index
        child = self.lines[index]
        expected = parent_indent + 2
        if child.indent != expected:
            _error(child.number, f"unexpected indentation; expected {expected} spaces")
        if _is_list_item(child.content):
            return self._parse_sequence(index, expected)
        return self._parse_mapping(index, expected)

    def _store_entry(self, mapping, key, raw_value, line_number, index, indent):
        if key in mapping:
            _error(line_number, f"duplicate mapping key {key!r}")
        if raw_value:
            mapping[key] = _parse_scalar(raw_value, line_number)
            return index
        mapping[key], index = self._parse_child(index, indent)
        return index

    def _parse_mapping(self, index, indent, initial=None):
        mapping = {}
        if initial is not None:
            initial_line, initial_content = initial
            key, raw_value = _parse_key_value(initial_content, initial_line.number)
            index = self._store_entry(mapping, key, raw_value, initial_line.number, index, indent)

        while index < len(self.lines):
            line = self.lines[index]
            if line.indent < indent:
                break
            if line.indent > indent:
                _error(line.number, f"unexpected indentation; expected {indent} spaces")
            if _is_list_item(line.content):
                _error(line.number, "cannot mix mapping entries and list items at the same indentation")
            key, raw_value = _parse_key_value(line.content, line.number)
            index += 1
            index = self._store_entry(mapping, key, raw_value, line.number, index, indent)
        return mapping, index

    def _parse_sequence(self, index, indent):
        sequence = []
        while index < len(self.lines):
            line = self.lines[index]
            if line.indent < indent:
                break
            if line.indent > indent:
                _error(line.number, f"unexpected indentation; expected {indent} spaces")
            if not _is_list_item(line.content):
                _error(line.number, "cannot mix list items and mapping entries at the same indentation")

            payload = line.content[1:].strip()
            index += 1
            if not payload:
                value, index = self._parse_child(index, indent)
                if value is None:
                    _error(line.number, "empty block-list item")
                sequence.append(value)
                continue

            if _is_mapping_entry(payload):
                value, index = self._parse_mapping(index, indent + 2, initial=(line, payload))
            else:
                value = _parse_scalar(payload, line.number)
                if index < len(self.lines) and self.lines[index].indent > indent:
                    child = self.lines[index]
                    _error(child.number, "scalar list item cannot have nested content")
            sequence.append(value)
        return sequence, index


def parse_yaml_subset(text):
    """Parse one constrained YAML mapping document.

    Supported values are nested mappings, block lists, lists of mappings,
    inline scalar lists, null, booleans, integers, decimal numbers, and quoted
    or conservative unquoted strings. All indentation is exactly two spaces per
    nesting level.
    """

    if not isinstance(text, str):
        raise TypeError("text must be a string")
    return _Parser(_tokenize(text)).parse()
