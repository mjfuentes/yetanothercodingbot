"""
Response formatter for Telegram messages
Enhances plain text responses with HTML formatting for better display
"""

import re
from typing import Optional


class ResponseFormatter:
    """Format agent responses for better Telegram display using HTML"""

    def __init__(self, workspace_path: Optional[str] = None):
        self.workspace_path = workspace_path

    def format_response(self, text: str) -> str:
        """
        Apply HTML formatting to response text

        Enhancements:
        - Highlight file paths with <code>
        - Highlight repository names with <b>
        - Format code blocks with <pre>
        - Format lists properly
        """
        if not text:
            return text

        # Apply formatters in order
        formatted = text
        formatted = self._strip_existing_markdown(formatted)
        formatted = self._format_code_blocks(formatted)
        formatted = self._format_paths(formatted)
        formatted = self._format_repositories(formatted)
        formatted = self._format_lists(formatted)

        return formatted

    def _strip_existing_markdown(self, text: str) -> str:
        """Remove markdown asterisks and underscores for plain text"""
        # Remove bold/italic markdown syntax but keep the text
        # Only remove if they're markdown formatting, not literal asterisks

        # Remove bold: **text** or __text__
        text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
        text = re.sub(r'__(.+?)__', r'\1', text)

        # Remove italic: *text* or _text_ (but be careful not to break paths)
        text = re.sub(r'(?<!\w)\*(.+?)\*(?!\w)', r'\1', text)
        text = re.sub(r'(?<!\w)_(.+?)_(?!\w)', r'\1', text)

        return text

    def _format_code_blocks(self, text: str) -> str:
        """Convert markdown code blocks to HTML <pre>"""
        # Match triple backtick code blocks
        def replace_code_block(match):
            code = match.group(1)
            # Escape HTML in code
            code = code.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            return f'<pre>{code}</pre>'

        # Replace ```code``` blocks
        text = re.sub(r'```(?:\w+)?\n?(.*?)```', replace_code_block, text, flags=re.DOTALL)

        # Replace inline `code`
        def replace_inline_code(match):
            code = match.group(1)
            code = code.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            return f'<code>{code}</code>'

        text = re.sub(r'`([^`]+)`', replace_inline_code, text)

        return text

    def _format_paths(self, text: str) -> str:
        """Detect and format file/directory paths with <code>"""
        # Match common path patterns (order matters - more specific first)
        patterns = [
            # Home directory paths: ~/path/to/file
            r'(~(?:/[\w\-./]+)+)',
            # Absolute paths: /Users/path/to/file
            r'(/(?:[\w\-./]+/)+[\w\-.]+)',
            # Relative paths with extensions: src/file.py
            r'([\w\-]+/[\w\-./]+\.\w+)',
        ]

        for pattern in patterns:
            # Find all matches
            matches = list(re.finditer(pattern, text))
            replacements = []

            for match in matches:
                path = match.group(1)
                start = match.start()
                end = match.end()

                # Skip if already in HTML tags
                if start > 0 and text[start - 1] == '>':
                    continue
                if '<code>' in text[max(0, start-10):start]:
                    continue

                # Skip URLs
                if 'http://' in path or 'https://' in path:
                    continue

                # Remove trailing punctuation from path
                clean_path = path.rstrip('.,;:!?')
                if len(clean_path) < len(path):
                    # Adjust end position to exclude punctuation
                    end = start + len(clean_path)
                    path = clean_path

                replacements.append((start, end, f'<code>{path}</code>'))

            # Apply replacements in reverse order to maintain indices
            for start, end, replacement in reversed(replacements):
                text = text[:start] + replacement + text[end:]

        return text

    def _format_repositories(self, text: str) -> str:
        """Highlight repository/project names with bold"""
        # Match repository references like "groovetherapy repository"
        patterns = [
            (r'\b([\w\-]+)\s+(repository|repo|project)\b', lambda m: f'<b>{m.group(1)}</b> {m.group(2)}'),
            (r'\b(repository|repo|project)\s+([\w\-]+)\b', lambda m: f'{m.group(1)} <b>{m.group(2)}</b>'),
        ]

        for pattern, replacement in patterns:
            text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)

        return text

    def _format_lists(self, text: str) -> str:
        """Format bullet lists and numbered lists"""
        lines = text.split('\n')
        formatted_lines = []
        in_list = False

        for i, line in enumerate(lines):
            stripped = line.strip()

            # Check if line is a list item
            is_bullet = stripped.startswith('- ') or stripped.startswith('* ') or stripped.startswith('• ')
            is_numbered = bool(re.match(r'^\d+\.\s', stripped))
            is_list_item = is_bullet or is_numbered

            # Add spacing before list if needed
            if is_list_item and not in_list and i > 0 and formatted_lines and formatted_lines[-1].strip():
                formatted_lines.append('')

            # Convert bullets to consistent format
            if is_bullet:
                content = re.sub(r'^[*\-•]\s+', '', stripped)
                formatted_lines.append(f'  • {content}')
            else:
                formatted_lines.append(line)

            in_list = is_list_item

        return '\n'.join(formatted_lines)


def format_telegram_response(
    text: str,
    workspace_path: Optional[str] = None,
    max_length: int = 4096
) -> list[str]:
    """
    Format response and split into Telegram-compatible chunks

    Args:
        text: Raw response text
        workspace_path: Workspace path for context
        max_length: Maximum message length (Telegram limit is 4096)

    Returns:
        List of formatted message chunks
    """
    formatter = ResponseFormatter(workspace_path)
    formatted = formatter.format_response(text)

    # Split into chunks if needed
    if len(formatted) <= max_length:
        return [formatted]

    # Smart chunking: try to split on paragraphs/sections
    chunks = []
    current_chunk = ""

    for line in formatted.split('\n'):
        # If adding this line exceeds limit, save current chunk
        if len(current_chunk) + len(line) + 1 > max_length:
            if current_chunk:
                chunks.append(current_chunk.strip())
                current_chunk = line + '\n'
            else:
                # Line itself is too long, force split
                chunks.append(line[:max_length])
                current_chunk = line[max_length:] + '\n'
        else:
            current_chunk += line + '\n'

    if current_chunk.strip():
        chunks.append(current_chunk.strip())

    return chunks
