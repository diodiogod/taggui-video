"""
Custom QPlainTextEdit with spell/grammar checking support.

Provides real-time spell checking with red underlines and context menu
for corrections and grammar checking.
"""

from PySide6.QtCore import Qt, Slot, Signal
from PySide6.QtGui import QAction, QTextCursor, QContextMenuEvent
from PySide6.QtWidgets import QPlainTextEdit, QMenu

from utils.spell_highlighter import SpellHighlighter
from utils.grammar_checker import GrammarChecker, GrammarCheckMode, GrammarIssue, IssueType
from utils.settings import settings, DEFAULT_SETTINGS


class DescriptiveTextEdit(QPlainTextEdit):
    """
    Text editor with integrated spell/grammar checking.

    Features:
    - Real-time spell checking with red underlines
    - Right-click context menu for corrections
    - Optional on-demand grammar checking
    """

    # Signal emitted when grammar check is requested
    grammar_check_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        # Spell highlighter (enabled based on settings)
        spell_check_enabled = settings.value('spell_check_enabled', defaultValue=True, type=bool)
        self.spell_highlighter = SpellHighlighter(self.document())
        self.spell_highlighter.set_enabled(spell_check_enabled)

        # Load custom dictionary from settings (stored as list, converted to set)
        custom_dict_list = settings.value('spell_check_custom_dictionary', [], type=list)
        if custom_dict_list:
            custom_dict = set(custom_dict_list)
            self.spell_highlighter.load_custom_dictionary(custom_dict)

        # Grammar checker (optional, on-demand)
        self.grammar_checker = None
        self._init_grammar_checker()

        # Track grammar issues for highlighting
        self.grammar_issues = []

    def _init_grammar_checker(self):
        """Initialize grammar checker based on settings."""
        mode_str = settings.value('grammar_check_mode',
                                 defaultValue=GrammarCheckMode.FREE_API.value,
                                 type=str)

        try:
            mode = GrammarCheckMode(mode_str)
        except ValueError:
            mode = GrammarCheckMode.FREE_API

        if mode != GrammarCheckMode.DISABLED:
            try:
                self.grammar_checker = GrammarChecker(mode=mode)
            except Exception as e:
                print(f"Failed to initialize grammar checker: {e}")
                self.grammar_checker = None

    def contextMenuEvent(self, event: QContextMenuEvent):
        """Show custom context menu with spelling/grammar corrections."""
        cursor = self.cursorForPosition(event.pos())
        cursor.select(QTextCursor.SelectionType.WordUnderCursor)
        word = cursor.selectedText()

        menu = QMenu(self)

        # Spelling suggestions if word is misspelled
        if word and self.spell_highlighter.is_misspelled(word):
            suggestions = self.spell_highlighter.get_suggestions(word)

            if suggestions:
                # Add header for suggestions
                header_action = QAction(f'Suggestions for "{word}":', menu)
                header_action.setEnabled(False)
                menu.addAction(header_action)

                for suggestion in suggestions[:5]:  # Limit to 5 suggestions
                    action = QAction(f'  → {suggestion}', menu)
                    action.triggered.connect(
                        lambda checked, s=suggestion, c=cursor.position():
                        self._replace_word_at_position(c, word, s))
                    menu.addAction(action)
                menu.addSeparator()
            else:
                # No suggestions available
                no_suggestions_action = QAction(f'No suggestions for "{word}"', menu)
                no_suggestions_action.setEnabled(False)
                menu.addAction(no_suggestions_action)
                menu.addSeparator()

            # Add to dictionary option
            add_to_dict_action = QAction(f'Add "{word}" to dictionary', menu)
            add_to_dict_action.triggered.connect(
                lambda: self._add_to_dictionary(word))
            menu.addAction(add_to_dict_action)
            menu.addSeparator()

        # Grammar check action
        if self.grammar_checker and self.grammar_checker.is_available():
            check_grammar_action = QAction('Check Grammar...', menu)
            check_grammar_action.triggered.connect(self.check_grammar)
            menu.addAction(check_grammar_action)
            menu.addSeparator()

        # Standard text editing actions
        if menu.actions():
            menu.addSeparator()

        menu.addAction(self.createStandardContextMenu().actions()[0])  # Undo
        menu.addAction(self.createStandardContextMenu().actions()[1])  # Redo
        menu.addSeparator()
        menu.addAction(self.createStandardContextMenu().actions()[3])  # Cut
        menu.addAction(self.createStandardContextMenu().actions()[4])  # Copy
        menu.addAction(self.createStandardContextMenu().actions()[5])  # Paste
        menu.addAction(self.createStandardContextMenu().actions()[6])  # Delete
        menu.addSeparator()
        menu.addAction(self.createStandardContextMenu().actions()[8])  # Select All

        menu.exec(event.globalPos())

    def _replace_word_at_position(self, position: int, old_word: str, replacement: str):
        """Replace word at given position with replacement."""
        cursor = self.textCursor()
        cursor.setPosition(position)
        cursor.select(QTextCursor.SelectionType.WordUnderCursor)

        # Verify we're replacing the right word
        if cursor.selectedText() == old_word:
            cursor.beginEditBlock()
            cursor.removeSelectedText()
            cursor.insertText(replacement)
            cursor.endEditBlock()

    def _add_to_dictionary(self, word: str):
        """Add word to custom dictionary."""
        self.spell_highlighter.add_to_dictionary(word)

        # Save to settings (convert set to list for Qt settings)
        custom_dict = self.spell_highlighter.save_custom_dictionary()
        settings.setValue('spell_check_custom_dictionary', list(custom_dict))

    @Slot()
    def check_grammar(self):
        """Check grammar using LanguageTool and display issues."""
        from PySide6.QtWidgets import QMessageBox

        if not self.grammar_checker or not self.grammar_checker.is_available():
            QMessageBox.warning(
                self, "Grammar Check Unavailable",
                "Grammar checking is not available.\n\n"
                "Make sure 'language-tool-python' is installed:\n"
                "pip install language-tool-python\n\n"
                "Or check Settings to configure the grammar check mode."
            )
            return

        text = self.toPlainText()

        if not text.strip():
            return

        # Show loading cursor
        self.setCursor(Qt.CursorShape.WaitCursor)

        try:
            # Check grammar
            issues = self.grammar_checker.check(text)
            self.grammar_issues = issues

            # TODO: Highlight grammar issues (would need a more sophisticated highlighter)
            # For now, just show a summary
            if issues:
                self._show_grammar_results(issues)
            else:
                # No issues found
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.information(self, "Grammar Check",
                                      "No grammar or style issues found!")

        finally:
            # Restore cursor
            self.unsetCursor()

    def _show_grammar_results(self, issues: list[GrammarIssue]):
        """Show grammar check results dialog."""
        from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QListWidget, QPushButton, QListWidgetItem

        dialog = QDialog(self)
        dialog.setWindowTitle("Grammar Check Results")
        dialog.setMinimumWidth(500)
        dialog.setMinimumHeight(400)

        layout = QVBoxLayout(dialog)

        # Summary
        issue_counts = {}
        for issue in issues:
            issue_counts[issue.issue_type] = issue_counts.get(issue.issue_type, 0) + 1

        summary = f"Found {len(issues)} issue(s):"
        for issue_type, count in issue_counts.items():
            summary += f"\n  • {issue_type.value}: {count}"

        summary_label = QLabel(summary)
        layout.addWidget(summary_label)

        # Issue list
        issue_list = QListWidget()

        for issue in issues:
            # Get the problematic text
            text = self.toPlainText()
            problem_text = text[issue.offset:issue.offset + issue.length]

            # Create item text
            item_text = f"[{issue.issue_type.value.upper()}] {problem_text}\n"
            item_text += f"  → {issue.message}"

            if issue.suggestions:
                item_text += f"\n  Suggestions: {', '.join(issue.suggestions[:3])}"

            item = QListWidgetItem(item_text)
            item.setData(Qt.ItemDataRole.UserRole, issue)
            issue_list.addItem(item)

        # Double-click to navigate to issue
        issue_list.itemDoubleClicked.connect(self._navigate_to_issue)

        layout.addWidget(issue_list)

        # Close button
        close_button = QPushButton("Close")
        close_button.clicked.connect(dialog.close)
        layout.addWidget(close_button)

        dialog.exec()

    def _navigate_to_issue(self, item):
        """Navigate to the position of a grammar issue in the text."""
        issue = item.data(Qt.ItemDataRole.UserRole)

        if not issue:
            return

        # Move cursor to issue position
        cursor = self.textCursor()
        cursor.setPosition(issue.offset)
        cursor.setPosition(issue.offset + issue.length, QTextCursor.MoveMode.KeepAnchor)

        self.setTextCursor(cursor)
        self.setFocus()

        # Close the results dialog
        if self.sender() and self.sender().parent():
            self.sender().parent().close()

    def set_spell_check_enabled(self, enabled: bool):
        """Enable or disable spell checking."""
        self.spell_highlighter.set_enabled(enabled)

    def cleanup(self):
        """Clean up resources before deletion."""
        if self.grammar_checker:
            self.grammar_checker.close()
