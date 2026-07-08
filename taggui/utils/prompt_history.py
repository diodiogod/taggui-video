"""
Prompt history manager for autocaptioner prompts.

Stores prompt history to JSON file with LRU ordering, fuzzy search support,
and persistent storage.
"""

import json
import os
import hashlib
import time
import threading
from typing import List, Dict, Any, Optional
from pathlib import Path


class PromptHistoryManager:
    """Manages prompt history with persistent JSON storage."""

    def __init__(self, max_entries: int = 10000):
        self.max_entries = max_entries
        self.lock = threading.Lock()

        # Store history in user's home directory
        history_dir = Path.home() / '.taggui'
        history_dir.mkdir(exist_ok=True)
        self.history_path = history_dir / 'prompt_history.json'

        self.history = self._load_history()

    def _load_history(self) -> Dict[str, Any]:
        """Load history from disk."""
        try:
            if self.history_path.exists():
                with open(self.history_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if isinstance(data, dict) and 'items' in data:
                        return data
        except Exception as e:
            print(f"[PromptHistory] Error loading {self.history_path}: {e}")

        return {'schema_version': 1, 'items': []}

    def _save_history(self):
        """Save history to disk atomically."""
        try:
            temp_path = str(self.history_path) + '.tmp'
            with open(temp_path, 'w', encoding='utf-8') as f:
                json.dump(self.history, f, ensure_ascii=False, indent=2)
            os.replace(temp_path, self.history_path)
        except Exception as e:
            print(f"[PromptHistory] Error saving {self.history_path}: {e}")

    def _compute_hash(self, prompt: str) -> str:
        """Compute SHA1 hash of prompt text."""
        return hashlib.sha1(prompt.encode('utf-8')).hexdigest()

    def add_prompt(self, prompt: str):
        """Add or update prompt in history (LRU)."""
        if not prompt or not prompt.strip():
            return

        prompt = prompt.strip()
        prompt_hash = self._compute_hash(prompt)
        now = int(time.time())

        with self.lock:
            items = self.history.get('items', [])

            # Find existing entry
            existing_idx = -1
            for i, item in enumerate(items):
                if item.get('hash') == prompt_hash:
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
                    'hash': prompt_hash,
                    'prompt': prompt,
                    'created': now,
                    'last_used': now,
                    'hits': 1,
                }
                items.insert(0, new_item)

            # Trim to max_entries
            if len(items) > self.max_entries:
                items = items[:self.max_entries]

            self.history['items'] = items
            self._save_history()

    def get_all_prompts(self, search_query: str = "") -> List[Dict[str, Any]]:
        """
        Get all prompts, optionally filtered by search query.

        Returns list of dicts with keys: prompt, created, last_used, hits
        """
        with self.lock:
            items = self.history.get('items', [])

            if not search_query:
                return [
                    {
                        'prompt': item.get('prompt', ''),
                        'created': item.get('created', 0),
                        'last_used': item.get('last_used', 0),
                        'hits': item.get('hits', 0),
                    }
                    for item in items
                ]

            # Simple case-insensitive search
            query = search_query.lower()
            results = []

            for item in items:
                prompt = item.get('prompt', '')
                if query in prompt.lower():
                    results.append({
                        'prompt': prompt,
                        'created': item.get('created', 0),
                        'last_used': item.get('last_used', 0),
                        'hits': item.get('hits', 0),
                    })

            return results

    def clear_history(self):
        """Clear all history."""
        with self.lock:
            self.history = {'schema_version': 1, 'items': []}
            self._save_history()


# Global instance
_prompt_history = None

def get_prompt_history() -> PromptHistoryManager:
    """Get or create global prompt history instance."""
    global _prompt_history
    if _prompt_history is None:
        _prompt_history = PromptHistoryManager()
    return _prompt_history
