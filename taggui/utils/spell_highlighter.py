"""
Real-time spell checking using QSyntaxHighlighter.

Provides red underlines for misspelled words with context menu suggestions.
"""

import re
from typing import Set

from PySide6.QtCore import Qt
from PySide6.QtGui import QSyntaxHighlighter, QTextCharFormat, QColor

try:
    from spellchecker import SpellChecker
    SPELL_CHECKER_AVAILABLE = True
except ImportError:
    SPELL_CHECKER_AVAILABLE = False


class SpellHighlighter(QSyntaxHighlighter):
    """
    Highlights misspelled words in real-time with red underlines.

    Uses pyspellchecker for spell checking and supports custom dictionaries
    for whitelisting common terms (character names, technical terms, etc.).
    """

    # Word pattern: letters, numbers, apostrophes, hyphens
    WORD_PATTERN = re.compile(r"\b[a-zA-Z][a-zA-Z0-9'\-]*\b")

    def __init__(self, parent=None, language='en', custom_words: Set[str] = None):
        super().__init__(parent)

        if not SPELL_CHECKER_AVAILABLE:
            # Graceful degradation if spell checker not installed
            self.enabled = False
            return

        self.enabled = True
        self.spell_checker = SpellChecker(language=language)

        # Custom dictionary for whitelisted words
        self.custom_words = set(custom_words) if custom_words else set()

        # Format for misspelled words (red wavy underline)
        self.error_format = QTextCharFormat()
        self.error_format.setUnderlineColor(QColor(Qt.red))
        self.error_format.setUnderlineStyle(QTextCharFormat.UnderlineStyle.WaveUnderline)

    def highlightBlock(self, text):
        """Highlight misspelled words in the given text block."""
        if not self.enabled:
            return

        # Find all words in the text
        for match in self.WORD_PATTERN.finditer(text):
            word = match.group()

            # Skip very short words (1-2 chars) and numbers
            if len(word) <= 2 or word.isdigit():
                continue

            # Check if word is in custom dictionary
            if word.lower() in self.custom_words:
                continue

            # For hyphenated words, check each component separately
            if '-' in word:
                parts = word.split('-')
                # Skip if all parts are valid words
                all_valid = True
                for part in parts:
                    if len(part) <= 2:  # Skip short parts
                        continue
                    if part.lower() not in self.custom_words and self.spell_checker.unknown([part.lower()]):
                        all_valid = False
                        break
                if all_valid:
                    continue

            # Check spelling (case-insensitive)
            if self.spell_checker.unknown([word.lower()]):
                # Mark as misspelled
                self.setFormat(match.start(), match.end() - match.start(),
                             self.error_format)

    def add_to_dictionary(self, word: str):
        """Add a word to the custom dictionary (whitelist)."""
        self.custom_words.add(word.lower())
        # Re-highlight all text
        self.rehighlight()

    def remove_from_dictionary(self, word: str):
        """Remove a word from the custom dictionary."""
        self.custom_words.discard(word.lower())
        self.rehighlight()

    def get_suggestions(self, word: str) -> list[str]:
        """Get spelling suggestions for a misspelled word."""
        if not self.enabled:
            return []

        # Get candidates from spell checker
        candidates = self.spell_checker.candidates(word.lower())

        if not candidates:
            return []

        # Preserve original capitalization if word was capitalized
        if word and word[0].isupper():
            return [c.capitalize() for c in candidates]
        else:
            return list(candidates)

    def is_misspelled(self, word: str) -> bool:
        """Check if a word is misspelled."""
        if not self.enabled:
            return False

        # Check custom dictionary first
        if word.lower() in self.custom_words:
            return False

        # Check with spell checker
        return bool(self.spell_checker.unknown([word.lower()]))

    def set_enabled(self, enabled: bool):
        """Enable or disable spell checking."""
        self.enabled = enabled
        self.rehighlight()

    def save_custom_dictionary(self) -> Set[str]:
        """Return the custom dictionary for saving to settings."""
        return self.custom_words.copy()

    def load_custom_dictionary(self, words: Set[str]):
        """Load custom dictionary from settings."""
        self.custom_words = set(words)
        self.rehighlight()
