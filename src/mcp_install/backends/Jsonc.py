"""Minimal JSONC object editor that preserves unrelated configuration and comments."""

from __future__ import annotations

import json
import re

from dataclasses import dataclass
from typing import Any, Optional


@dataclass(frozen=True)
class _Member:
    key: str
    start: int
    valueStart: int
    valueEnd: int
    commaPosition: Optional[int]


class JsoncDocument:
    """Read and edit nested JSONC object keys without reformatting the entire file."""

    def __init__(self, text: str):
        self.text = text or "{}\n"
        self._validate()

    @classmethod
    def _readString(cls, text: str, position: int) -> tuple[str, int]:
        if text[position] != '"':
            raise ValueError("JSONC object keys must be quoted")

        return json.JSONDecoder().raw_decode(text, position)

    @classmethod
    def _skipIgnored(cls, text: str, position: int) -> int:
        while position < len(text):
            if text[position].isspace():
                position += 1
            elif text.startswith("//", position):
                end = text.find("\n", position + 2)
                position = len(text) if end < 0 else end
            elif text.startswith("/*", position):
                end = text.find("*/", position + 2)
                if end < 0:
                    raise ValueError("Unterminated JSONC block comment")

                position = end + 2
            else:
                break

        return position

    @classmethod
    def _stripComments(cls, text: str) -> str:
        chars = list(text)
        position = 0

        while position < len(text):
            if text[position] == '"':
                _, position = cls._readString(text, position)
                continue

            start = position
            if text.startswith("//", position):
                end = text.find("\n", position + 2)
                position = len(text) if end < 0 else end
            elif text.startswith("/*", position):
                end = text.find("*/", position + 2)
                if end < 0:
                    raise ValueError("Unterminated JSONC block comment")

                position = end + 2
            else:
                position += 1
                continue

            for index in range(start, position):
                if chars[index] != "\n":
                    chars[index] = " "

        cleaned = "".join(chars)
        chars = list(cleaned)
        position = 0

        while position < len(cleaned):
            if cleaned[position] == '"':
                _, position = cls._readString(cleaned, position)
                continue

            if cleaned[position] == ",":
                nextPosition = position + 1
                while nextPosition < len(cleaned) and cleaned[nextPosition].isspace():
                    nextPosition += 1

                if nextPosition < len(cleaned) and cleaned[nextPosition] in "}]":
                    chars[position] = " "

            position += 1

        return "".join(chars)

    def _validate(self) -> dict:
        data = json.loads(self._stripComments(self.text))
        if not isinstance(data, dict):
            raise ValueError("OpenCode config must contain a JSON object")

        return data

    @classmethod
    def _valueEnd(cls, text: str, position: int) -> int:
        if text[position] == '"':
            _, end = cls._readString(text, position)
            return end

        if text[position] not in "{[":
            end = position
            while end < len(text) and text[end] not in ",}] \r\n\t":
                end += 1

            return end

        stack = []
        cursor = position
        while cursor < len(text):
            if text[cursor] == '"':
                _, cursor = cls._readString(text, cursor)
                continue

            if text.startswith("//", cursor) or text.startswith("/*", cursor):
                cursor = cls._skipIgnored(text, cursor)
                continue

            if text[cursor] in "{[":
                stack.append(text[cursor])
            elif text[cursor] in "}]":
                if not stack:
                    raise ValueError("Unexpected JSONC closing delimiter")

                expected = "}" if stack.pop() == "{" else "]"
                if text[cursor] != expected:
                    raise ValueError("Unbalanced JSONC delimiters")

                if not stack:
                    return cursor + 1

            cursor += 1

        raise ValueError("Unterminated JSONC value")

    def _members(self, objectStart: int) -> tuple[list[_Member], int]:
        text = self.text
        if text[objectStart] != "{":
            raise ValueError("Expected a JSONC object")

        members = []
        cursor = self._skipIgnored(text, objectStart + 1)

        while text[cursor] != "}":
            memberStart = cursor
            key, cursor = self._readString(text, cursor)
            cursor = self._skipIgnored(text, cursor)
            if text[cursor] != ":":
                raise ValueError("Expected ':' after JSONC key")

            valueStart = self._skipIgnored(text, cursor + 1)
            valueEnd = self._valueEnd(text, valueStart)
            cursor = self._skipIgnored(text, valueEnd)
            commaPosition = cursor if text[cursor] == "," else None

            members.append(
                _Member(key, memberStart, valueStart, valueEnd, commaPosition)
            )

            if commaPosition is not None:
                cursor = self._skipIgnored(text, cursor + 1)
            elif text[cursor] != "}":
                raise ValueError("Expected ',' or '}' after JSONC value")

        return members, cursor

    def _renderValue(self, value: Any, indent: str) -> str:
        serialized = json.dumps(value, ensure_ascii=True, indent=2)
        return serialized.replace("\n", "\n" + indent)

    def _addMember(self, objectStart: int, key: str, value: Any) -> None:
        members, closePosition = self._members(objectStart)
        prefix = self.text[:closePosition]
        suffix = self.text[closePosition:]
        closeLineStart = self.text.rfind("\n", objectStart, closePosition) + 1
        closingIndent = self.text[closeLineStart:closePosition]
        multiline = "\n" in self.text[objectStart:closePosition]

        if multiline and closingIndent.isspace() or multiline and not closingIndent:
            itemIndent = closingIndent + "  "
            item = (
                f"{itemIndent}{json.dumps(key)}: "
                f"{self._renderValue(value, itemIndent)}\n"
            )

            if members and members[-1].commaPosition is None:
                commaAt = members[-1].valueEnd
                prefix = self.text[:commaAt] + "," + self.text[commaAt:closeLineStart]
            else:
                prefix = self.text[:closeLineStart]

            self.text = prefix + item + self.text[closeLineStart:]
            return

        separator = ", " if members and members[-1].commaPosition is None else " "
        if not members:
            separator = ""

        item = f"{separator}{json.dumps(key)}: {json.dumps(value, ensure_ascii=True)}"
        self.text = prefix + item + suffix

    def set(self, path: tuple[str, ...], value: Any) -> None:
        if not path:
            raise ValueError("JSONC key path cannot be empty")

        objectStart = self._skipIgnored(self.text, 0)
        for index, key in enumerate(path):
            members, _ = self._members(objectStart)
            member = next((item for item in members if item.key == key), None)
            last = index == len(path) - 1

            if member is None:
                nestedValue = value
                for parentKey in reversed(path[index + 1:]):
                    nestedValue = {parentKey: nestedValue}

                self._addMember(objectStart, key, nestedValue)
                break

            if last:
                keyLineStart = self.text.rfind("\n", 0, member.start) + 1
                keyIndent = self.text[keyLineStart:member.start]
                if not re.fullmatch(r"[ \t]*", keyIndent):
                    keyIndent = ""

                replacement = self._renderValue(value, keyIndent)
                self.text = (
                    self.text[:member.valueStart]
                    + replacement
                    + self.text[member.valueEnd:]
                )
                break

            if self.text[member.valueStart] != "{":
                raise ValueError(f"JSONC key {key!r} must contain an object")

            objectStart = member.valueStart

        self._validate()

    def remove(self, path: tuple[str, ...]) -> bool:
        if not path:
            raise ValueError("JSONC key path cannot be empty")

        objectStart = self._skipIgnored(self.text, 0)
        for index, key in enumerate(path):
            members, _ = self._members(objectStart)
            memberIndex = next(
                (position for position, item in enumerate(members) if item.key == key),
                None,
            )
            if memberIndex is None:
                return False

            member = members[memberIndex]
            if index < len(path) - 1:
                if self.text[member.valueStart] != "{":
                    raise ValueError(f"JSONC key {key!r} must contain an object")

                objectStart = member.valueStart
                continue

            if memberIndex < len(members) - 1:
                start = member.start
                end = member.commaPosition + 1
            elif memberIndex > 0:
                start = members[memberIndex - 1].commaPosition
                end = member.valueEnd
                if member.commaPosition is not None:
                    end = member.commaPosition + 1
            else:
                start = member.start
                end = (
                    member.commaPosition + 1
                    if member.commaPosition is not None
                    else member.valueEnd
                )

            self.text = self.text[:start] + self.text[end:]
            self._validate()
            return True

        return False
