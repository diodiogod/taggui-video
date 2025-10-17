"""
Grammar checking using LanguageTool API or local server.

Provides on-demand grammar, style, and punctuation checking.
"""

from dataclasses import dataclass
from enum import Enum
from typing import List, Optional

try:
    import language_tool_python
    LANGUAGE_TOOL_AVAILABLE = True
except ImportError:
    LANGUAGE_TOOL_AVAILABLE = False


class GrammarCheckMode(Enum):
    """Grammar checking modes."""
    DISABLED = "disabled"
    FREE_API = "free_api"
    LOCAL_SERVER = "local_server"


class IssueType(Enum):
    """Types of issues detected by grammar checker."""
    SPELLING = "misspelling"
    GRAMMAR = "grammar"
    STYLE = "style"
    PUNCTUATION = "punctuation"
    OTHER = "other"


@dataclass
class GrammarIssue:
    """Represents a grammar/style issue found in text."""
    message: str              # Human-readable description
    offset: int               # Character position in text
    length: int               # Length of the error
    issue_type: IssueType     # Type of issue
    suggestions: List[str]    # Suggested replacements
    rule_id: str              # LanguageTool rule ID (for debugging)

    @property
    def end_offset(self) -> int:
        """End position of the issue."""
        return self.offset + self.length


class GrammarChecker:
    """
    Grammar checker using LanguageTool.

    Supports three modes:
    - FREE_API: Use LanguageTool's public API (20 requests/min limit)
    - LOCAL_SERVER: Download and run local Java server (unlimited)
    - DISABLED: No grammar checking
    """

    def __init__(self, mode: GrammarCheckMode = GrammarCheckMode.FREE_API,
                 language: str = 'en-US'):
        self.mode = mode
        self.language = language
        self._tool: Optional[language_tool_python.LanguageTool] = None

        if not LANGUAGE_TOOL_AVAILABLE:
            self.mode = GrammarCheckMode.DISABLED

        self._initialize_tool()

    def _initialize_tool(self):
        """Initialize LanguageTool based on current mode."""
        if self.mode == GrammarCheckMode.DISABLED or not LANGUAGE_TOOL_AVAILABLE:
            self._tool = None
            return

        try:
            if self.mode == GrammarCheckMode.FREE_API:
                # Use public API (requires internet)
                self._tool = language_tool_python.LanguageToolPublicAPI(self.language)
            elif self.mode == GrammarCheckMode.LOCAL_SERVER:
                # Download and run local server (first run may take time)
                self._tool = language_tool_python.LanguageTool(self.language)
        except Exception as e:
            print(f"Failed to initialize LanguageTool: {e}")
            self._tool = None
            self.mode = GrammarCheckMode.DISABLED

    def check(self, text: str) -> List[GrammarIssue]:
        """
        Check text for grammar, style, and punctuation issues.

        Returns list of issues found, sorted by position.
        Returns empty list if disabled or error occurs.
        """
        if self.mode == GrammarCheckMode.DISABLED or not self._tool:
            return []

        if not text or not text.strip():
            return []

        try:
            matches = self._tool.check(text)
            issues = []

            for match in matches:
                # Determine issue type from LanguageTool category
                issue_type = self._classify_issue(match)

                # Extract suggestions
                suggestions = match.replacements[:5]  # Limit to 5 suggestions

                issue = GrammarIssue(
                    message=match.message,
                    offset=match.offset,
                    length=match.errorLength,
                    issue_type=issue_type,
                    suggestions=suggestions,
                    rule_id=match.ruleId
                )
                issues.append(issue)

            # Sort by position
            issues.sort(key=lambda x: x.offset)
            return issues

        except Exception as e:
            print(f"Grammar check failed: {e}")
            return []

    def _classify_issue(self, match) -> IssueType:
        """Classify LanguageTool match into issue type."""
        category = match.category.lower() if hasattr(match, 'category') else ""
        rule_id = match.ruleId.lower() if hasattr(match, 'ruleId') else ""

        # Check category and rule ID to determine type
        if "spell" in category or "typo" in category:
            return IssueType.SPELLING
        elif "grammar" in category or "agreement" in category:
            return IssueType.GRAMMAR
        elif "style" in category or "redundan" in category:
            return IssueType.STYLE
        elif "punctuat" in category or "comma" in category:
            return IssueType.PUNCTUATION
        else:
            return IssueType.OTHER

    def set_mode(self, mode: GrammarCheckMode):
        """Change grammar checking mode and reinitialize."""
        if mode == self.mode:
            return

        self.mode = mode

        # Close existing tool
        if self._tool:
            try:
                self._tool.close()
            except:
                pass
            self._tool = None

        # Initialize new tool
        self._initialize_tool()

    def close(self):
        """Clean up resources."""
        if self._tool:
            try:
                self._tool.close()
            except:
                pass
            self._tool = None

    def is_available(self) -> bool:
        """Check if grammar checker is available and enabled."""
        return self.mode != GrammarCheckMode.DISABLED and self._tool is not None

    def __del__(self):
        """Cleanup on deletion."""
        self.close()
