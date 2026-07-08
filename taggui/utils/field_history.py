"""
Generic field history manager for single-line inputs.

Stores history for various fields with persistent JSON storage.
"""

import json
import os
import time
import threading
from typing import Dict, List, Any
from pathlib import Path


class FieldHistoryManager:
    """Manages history for multiple fields with persistent JSON storage."""

    def __init__(self, max_entries_per_field: int = 100):
        self.max_entries = max_entries_per_field
        self.lock = threading.Lock()

        # Store history in user's home directory
        history_dir = Path.home() / '.taggui'
        history_dir.mkdir(exist_ok=True)
        self.history_path = history_dir / 'field_history.json'

        self.history = self._load_history()

    def _load_history(self) -> Dict[str, Any]:
        """Load history from disk."""
        try:
            if self.history_path.exists():
                with open(self.history_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        return data
        except Exception as e:
            print(f"[FieldHistory] Error loading {self.history_path}: {e}")

        return {}

    def _save_history(self):
        """Save history to disk atomically."""
        try:
            temp_path = str(self.history_path) + '.tmp'
            with open(temp_path, 'w', encoding='utf-8') as f:
                json.dump(self.history, f, ensure_ascii=False, indent=2)
            os.replace(temp_path, self.history_path)
        except Exception as e:
            print(f"[FieldHistory] Error saving {self.history_path}: {e}")

    def add_value(self, field_key: str, value: str):
        """Add or update value in field history (LRU)."""
        if not value or not value.strip():
            return

        value = value.strip()
        now = int(time.time())

        with self.lock:
            if field_key not in self.history:
                self.history[field_key] = []

            items = self.history[field_key]

            # Find existing entry
            existing_idx = -1
            for i, item in enumerate(items):
                if item.get('value') == value:
                    existing_idx = i
                    break

            if existing_idx >= 0:
                # Move to front (LRU), update metadata
                item = items.pop(existing_idx)
                item['last_used'] = now
                item['hits'] = item.get('hits', 0) + 1
                items.insert(0, item)
            else:
                # New entry
                new_item = {
                    'value': value,
                    'created': now,
                    'last_used': now,
                    'hits': 1,
                }
                items.insert(0, new_item)

            # Trim to max_entries
            if len(items) > self.max_entries:
                items = items[:self.max_entries]

            self.history[field_key] = items
            self._save_history()

    def get_values(self, field_key: str, search_query: str = "") -> List[str]:
        """Get all values for a field, optionally filtered by search query."""
        with self.lock:
            items = self.history.get(field_key, [])

            if not search_query:
                return [item.get('value', '') for item in items]

            # Simple case-insensitive search
            query = search_query.lower()
            results = []

            for item in items:
                value = item.get('value', '')
                if query in value.lower():
                    results.append(value)

            return results

    def clear_field(self, field_key: str):
        """Clear history for a specific field."""
        with self.lock:
            if field_key in self.history:
                del self.history[field_key]
                self._save_history()


# Global instance
_field_history = None

def get_field_history() -> FieldHistoryManager:
    """Get or create global field history instance."""
    global _field_history
    if _field_history is None:
        _field_history = FieldHistoryManager()
    return _field_history
