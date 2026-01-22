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

## Database Schema

```sql
CREATE TABLE images (
    id INTEGER PRIMARY KEY,
    path TEXT UNIQUE NOT NULL,
    filename TEXT NOT NULL,
    width INTEGER,
    height INTEGER,
    aspect_ratio REAL,  -- pre-calculated
    mtime REAL,
    is_video BOOLEAN,

    -- Video metadata
    video_fps REAL,
    video_duration REAL,
    video_frame_count INTEGER,

    -- Indexing
    indexed_at REAL
);

-- Separate tags table for efficient querying
CREATE TABLE image_tags (
    image_id INTEGER,
    tag TEXT,
    PRIMARY KEY (image_id, tag),
    FOREIGN KEY (image_id) REFERENCES images(id)
);

-- Indexes for fast queries
CREATE INDEX idx_images_mtime ON images(mtime);
CREATE INDEX idx_images_filename ON images(filename);
CREATE INDEX idx_images_path ON images(path);
CREATE INDEX idx_tags_tag ON image_tags(tag);
```

---

## Page Loading Flow

### Initial Load
```python
def load_directory(self, path):
    # 1. Index into database (first time or incremental)
    #    Shows progress: "Indexing: X / 1,000,000"
    self.db.index_directory(path)

    # 2. Get total count (instant - cached or COUNT(*))
    self.total_count = self.db.count()

    # 3. Load first page only
    self.pages = {}
    self.load_page(0)

    # 4. Estimate scroll height from page 1 data
    self.update_scroll_estimate()
```

### Scroll Handler
```python
def on_scroll(self, position):
    current_page = self.get_page_at_position(position)

    # Pre-load next page when near boundary
    if self.near_page_end(position):
        next_page = current_page + 1
        if next_page not in self.pages:
            self.load_page_async(next_page)

    # Unload distant pages (keep 3-5 in memory)
    self.unload_distant_pages(current_page)
```

### Page Query
```python
def load_page(self, page_num):
    offset = page_num * PAGE_SIZE

    images = self.db.query(f"""
        SELECT * FROM images
        {self.current_filter_sql}
        ORDER BY {self.sort_field} {self.sort_dir}
        LIMIT {PAGE_SIZE} OFFSET {offset}
    """)

    self.pages[page_num] = images
    self.calculate_masonry_for_page(page_num)
```

---

## Filtering & Sorting

### Sorting (Database handles it)
```python
def change_sort(self, field, direction):
    self.sort_field = field  # mtime, filename, etc
    self.sort_dir = direction

    # Clear and reload from page 1
    self.pages = {}
    self.load_page(0)
```

### Filtering
```python
def apply_filter(self, filter_text):
    # Build SQL WHERE clause
    self.current_filter_sql = self.build_filter_sql(filter_text)

    # Get new filtered count
    self.total_count = self.db.count_with_filter(self.current_filter_sql)

    # Reload from page 1
    self.pages = {}
    self.load_page(0)
```

---

## Masonry Layout

### Per-Page Calculation
- Each page calculates its own masonry layout
- Optional visual break between pages (simpler)
- Or seamless continuation (track column heights across pages)

### Scroll Height Estimation
```python
def update_scroll_estimate(self):
    if not self.pages:
        return

    # Average row height from loaded pages
    loaded_images = sum(len(p) for p in self.pages.values())
    loaded_height = sum(self.page_heights.values())
    avg_height_per_image = loaded_height / loaded_images

    # Estimate total
    self.estimated_total_height = avg_height_per_image * self.total_count
```

---

## Tag Display

**Decision: Load tags for visible items only (Option B)**

```python
def on_items_visible(self, image_ids):
    # Batch query tags for visible images
    tags = self.db.get_tags_for_images(image_ids)

    # Update UI
    for img_id, tag_list in tags.items():
        self.update_tag_display(img_id, tag_list)
```

---

## Memory Usage

| Dataset Size | Pages Loaded | RAM Usage |
|--------------|--------------|-----------|
| 1,000 | 1 | ~5 MB |
| 100,000 | 3-5 | ~25 MB |
| 1,000,000 | 3-5 | ~25 MB |

**Constant memory regardless of dataset size.**

---

## Implementation Phases

### Phase 1: Database Backend
- [ ] Extend ImageIndexDB schema (tags table, more indexes)
- [ ] Add paginated query methods
- [ ] Add filter/sort SQL builder

### Phase 2: Paginated Model
- [ ] Create new `PaginatedImageListModel`
- [ ] Implement page loading/unloading
- [ ] Wire scroll events to page loader

### Phase 3: Masonry Adaptation
- [ ] Modify masonry to work per-page
- [ ] Add scroll height estimation
- [ ] Handle page breaks or seamless stitching

### Phase 4: UI Integration
- [ ] Tag loading on demand
- [ ] Progress bar for initial indexing
- [ ] Filter/sort triggering page reload

---

## Reference Projects Analyzed

### DiffusionToolkit (C#)
- Full database-first approach
- 30+ indexes on Image table
- Separate read-only connection with 1GB cache
- SQL pagination throughout

### Image-MetaHub (React/Electron)
- In-memory approach (doesn't scale past 50K)
- Good patterns: Web Workers, batched updates, debouncing

**Conclusion**: DiffusionToolkit's database approach is correct for 1M+ scale, but our paginated loading is simpler and preserves masonry UX better.

---

## Trade-offs Accepted

| Feature | Behavior |
|---------|----------|
| Initial load (first time) | Shows indexing progress |
| Subsequent loads | Near-instant from database |
| Scrollbar accuracy | Estimated (refines as pages load) |
| Tag display | Loads on demand, slight delay |
| Complex filters | SQL query delay acceptable |
| Page boundaries | Optional visual break OK |
