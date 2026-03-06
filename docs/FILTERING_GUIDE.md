# Filtering Guide

Filtering is one of the core workflows in TagGUI Video 1M.

It is what turns the app from a simple browser into a practical tool for large collections: you can search by tags, caption text, ratings, file properties, media type, and sort order.

## Where Filtering Happens

Use the `Filter Images` box at the top of the `Images` pane.

You can:

- click tags in the `All Tags` pane for quick filtering
- type direct filter expressions
- switch between `All`, `Images`, and `Videos`
- change sort order
- combine multiple rules with logical operators

## Media Type Filter

The image list UI includes a media-type selector with:

- `All`
- `Images`
- `Videos`

This is not typed into the filter box. It is a separate UI filter that works alongside the text filter.

This is especially important in TagGUI Video 1M because mixed folders often contain both still images and video files.

## Sorting

The image list UI also includes a sort selector.

Current sort options in the code are:

- `Default`
- `Name`
- `Modified`
- `Created`
- `Size`
- `Type`
- `Random`

### What These Mean

- `Default`: project default ordering
- `Name`: natural sort by filename
- `Modified`: newest modified files first
- `Created`: newest created files first
- `Size`: largest files first
- `Type`: grouped by file type or extension
- `Random`: randomized ordering

### DB-Backed Sort Support

In the current DB-backed Video 1M path, sorting is connected to database fields such as:

- `file_name`
- `mtime`
- `ctime`
- `file_size`
- `file_type`
- `rating`
- `aspect_ratio`

This is one of the reasons sorting remains practical even on very large folders.

## Basic Search

If you type a plain term with no prefix, TagGUI searches for it in:

- the caption text
- the file path

Example:

```text
cat
```

This matches files containing `cat` in caption text or path.

## String Filters

These prefixes are used for text-based filtering.

### `tag:`

Matches files that contain a tag.

Example:

```text
tag:cat
```

### `caption:`

Matches files whose caption text contains the term.

Example:

```text
caption:cat
```

### `marking:`

Matches files containing a marking label.

Example:

```text
marking:face
```

Confidence-aware form:

```text
marking:face:>0.789
```

### `crops:`

Matches files where a marking with the given label is partially cropped by the current crop area.

Example:

```text
crops:hand
```

### `visible:`

Matches files where a marking with the given label is at least partly visible in the exported area.

Example:

```text
visible:face
```

### `name:`

Matches the file name.

Example:

```text
name:cat
```

### `path:`

Matches the full file path.

Example:

```text
path:cat
```

### `size:`

Matches exact dimensions.

Example:

```text
size:512:512
```

### `target:`

Matches target dimensions used by the app’s target-dimension logic.

Example:

```text
target:1024:1024
```

## Numeric Filters

These filters accept comparison operators:

- `=`
- `==`
- `!=`
- `<`
- `>`
- `<=`
- `>=`

### `tags:`

Number of tags.

Example:

```text
tags:=13
```

### `chars:`

Number of characters in the caption text.

Example:

```text
chars:<100
```

### `tokens:`

Approximate token count of the caption text.

Example:

```text
tokens:>75
```

### `stars:`

Star rating filter.

Example:

```text
stars:>=4
```

### Star Rating UI Shortcuts

TagGUI also supports star filtering directly from the rating UI.

- Click a star to rate the current file
- `Ctrl` + click a star to set an exact star filter
- `Ctrl` + `Shift` + click a star to set a minimum-star filter

Examples:

- `Ctrl` + click on 4 stars sets `stars:=4`
- `Ctrl` + `Shift` + click on 4 stars sets `stars:>=4`

This is one of the quickest ways to turn ratings into an active filter.

### `width:` / `height:`

Dimension-based filtering.

Examples:

```text
width:>512
height:=1024
```

### `area:`

Image area in pixels.

Example:

```text
area:<1048576
```

## Quotes and Spaces

If the filter term contains spaces, wrap it in single or double quotes.

Examples:

```text
tag:"orange cat"
tag:'orange cat'
```

If the term itself contains quotes, escape them or alternate quote styles.

Examples:

```text
tag:"orange \\\"cat\\\""
tag:'orange "cat"'
```

## Wildcards

You can use wildcard matching in text filters:

- `*` matches any number of characters
- `?` matches a single character

Example:

```text
tag:*cat
```

## Combining Filters

You can combine expressions with:

- `NOT`
- `AND`
- `OR`

Lowercase versions also work.

Examples:

```text
NOT tag:cat
tag:cat AND tag:orange
tag:cat OR tag:dog
tag:cat AND (tag:orange OR tag:white)
```

Operator precedence is:

1. `NOT`
2. `AND`
3. `OR`

Parentheses override the default order.

## Practical Examples

```text
tag:cat AND tag:orange
chars:<100
stars:>=4
width:>1024 AND tag:cat
tag:"orange cat"
```

## Current Limitations in Video 1M

> [!WARNING]
> In the current paginated and DB-backed Video 1M path, not every filter type is implemented in SQL yet. Tags and star ratings have DB-backed support, but marking-related predicates such as `marking:`, `crops:`, and `visible:` are still tied to in-memory or sidecar metadata behavior rather than a full SQL-backed filter path.

> [!NOTE]
> The parser supports more filter syntax than the current DB-backed paginated path accelerates. If a filter feels inconsistent in very large paginated datasets, this implementation gap is one of the first things to check.

## Notes

- Filtering is especially important in large datasets where visual browsing alone is not enough.
- Marking-aware filtering connects directly to the markings workflow.
- Rating-aware filtering connects directly to the DB-backed star-rating support already present in Video 1M.
- Media-type filtering and DB-backed sorting are part of the same large-collection workflow, even though they are controlled through separate UI widgets instead of the text filter box.
