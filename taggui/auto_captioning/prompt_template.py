"""Template expansion for per-image auto-captioning prompts."""

import re

from utils.image import Image


_CONDITIONAL_TOKEN_RE = re.compile(
    r"##IF(?P<condition>.*?)##|##ELSE##|##ENDIF##",
    re.IGNORECASE | re.DOTALL,
)
_VARIABLE_RE = re.compile(r"(?<!\\){[^{}]+(?<!\\)}")


def _template_variable_value(
    variable_name: str,
    image: Image,
    skip_hash: bool,
) -> str | None:
    """Return a variable's rendered value, or None for an unknown variable."""
    key = variable_name.strip().strip('{}').lower()
    if key == 'tags':
        tags = [
            tag for tag in (getattr(image, 'tags', None) or [])
            if tag and tag != '__no_tags__'
        ]
        if skip_hash:
            tags = [tag for tag in tags if not tag.startswith('#')]
        return ', '.join(tags)
    if key == 'name':
        return image.path.stem
    if key in ('directory', 'folder'):
        return image.path.parent.name
    return None


def _condition_is_true(condition: str, image: Image, skip_hash: bool) -> bool:
    """Evaluate a simple non-empty placeholder condition."""
    expression = condition.strip()
    if expression.lower().endswith('then'):
        expression = expression[:-4].rstrip()

    negated = False
    if expression.startswith('!'):
        negated = True
        expression = expression[1:].lstrip()
    elif expression.lower().startswith('not '):
        negated = True
        expression = expression[4:].lstrip()

    value = _template_variable_value(expression, image, skip_hash)
    result = bool(value and value.strip())
    return not result if negated else result


def _render_conditionals(text: str, image: Image, skip_hash: bool) -> str:
    """Render IF/ELSE/ENDIF blocks, including nested blocks.

    An IF block without an explicit ENDIF consumes the remainder of the
    prompt. This supports the compact trailing form ``##IF{tags} THEN##``.
    """

    def parse_from(
        start: int,
        stop_at_branch: bool,
    ) -> tuple[str, int, str | None]:
        chunks: list[str] = []
        cursor = start
        while True:
            match = _CONDITIONAL_TOKEN_RE.search(text, cursor)
            if match is None:
                # A conditional at the end of a prompt is an implicit block.
                return ''.join(chunks) + text[cursor:], len(text), 'EOF'

            chunks.append(text[cursor:match.start()])
            token = match.group(0).upper()
            if token.startswith('##IF'):
                true_text, next_cursor, terminator = parse_from(
                    match.end(), True
                )
                false_text = ''
                if terminator == '##ELSE##':
                    false_text, next_cursor, terminator = parse_from(
                        next_cursor, True
                    )
                if terminator not in ('##ENDIF##', 'EOF'):
                    # Preserve malformed template text rather than silently
                    # dropping part of a user's prompt.
                    return text[start:], len(text), 'MALFORMED'
                condition = match.group('condition') or ''
                selected = (
                    true_text
                    if _condition_is_true(condition, image, skip_hash)
                    else false_text
                )
                chunks.append(selected)
                cursor = next_cursor
                if terminator == 'EOF':
                    return ''.join(chunks), len(text), 'EOF'
                continue

            if token in ('##ELSE##', '##ENDIF##'):
                if stop_at_branch:
                    return ''.join(chunks), match.end(), token
                # Stray closing markers remain visible so a normal prompt is
                # not unexpectedly changed by an unmatched marker.
                chunks.append(match.group(0))
                cursor = match.end()

    rendered, _position, status = parse_from(0, False)
    if status == 'MALFORMED':
        return text
    return rendered


def replace_template_variable(match: re.Match, image: Image, skip_hash: bool) -> str:
    """Replace one ``{variable}`` placeholder."""
    variable_name = match.group(0)[1:-1]
    value = _template_variable_value(variable_name, image, skip_hash)
    return match.group(0) if value is None else value


def replace_template_variables(text: str, image: Image, skip_hash: bool) -> str:
    """Expand placeholders and conditional prompt sections for one image."""
    text = _render_conditionals(text, image, skip_hash)
    text = _VARIABLE_RE.sub(
        lambda match: replace_template_variable(match, image, skip_hash),
        text,
    )
    return re.sub(r'\\([{}])', r'\1', text)
