# TagGUI 1M+ Images Architecture Plan

## Goal

Support 1 million+ images while maintaining the masonry view, smooth scrolling, and current UX.

## Key Insight

**Don't load all images into memory. Use paginated loading with database-backed queries.**

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│ SQLite Database (on disk)                               │
│ - All images indexed with metadata                      │
│ - Indexed columns for fast filtering/sorting            │
│ - Persisted between sessions (instant reload)           │
└─────────────────────────────────────────────────────────┘
                    │
                    │ LIMIT/OFFSET queries
                    ▼
┌─────────────────────────────────────────────────────────┐
│ In Memory: Current Pages Only (3-5 pages max)           │
│ - Page size: ~1000 images                               │
│ - LRU eviction for distant pages                        │
│ - ~25MB RAM regardless of dataset size                  │
└─────────────────────────────────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────────────────┐
│ Masonry Layout                                          │
│ - Calculate per-page (not full dataset)                 │
│ - Estimate total height from loaded pages               │
│ - Page breaks OK (simpler implementation)               │
└─────────────────────────────────────────────────────────┘
```

---

---

## Masonry Layout

### Per-Page Calculation

- Each page calculates its own masonry layout
- Optional visual break between pages (simpler)
- Or seamless continuation (track column heights across pages)

### ---

## Memory Usage

| Dataset Size | Pages Loaded | RAM Usage |
| ------------ | ------------ | --------- |
| 1,000        | 1            | ~5 MB     |
| 100,000      | 3-5          | ~25 MB    |
| 1,000,000    | 3-5          | ~25 MB    |

**Constant memory regardless of dataset size.**

---

## 

---

## Trade-offs Accepted

| Feature                   | Behavior                          |
| ------------------------- | --------------------------------- |
| Initial load (first time) | Shows indexing progress           |
| Subsequent loads          | Near-instant from database        |
| Scrollbar accuracy        | Estimated (refines as pages load) |
| Tag display               | Loads on demand, slight delay     |
| Complex filters           | SQL query delay acceptable        |
| Page boundaries           | Optional visual break OK          |
