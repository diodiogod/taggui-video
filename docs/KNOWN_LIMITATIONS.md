# Known Limitations

[Back to Documentation Hub](HUB.md)

Current known constraints in TagGUI Video 1M.

## Filtering and Metadata

- Tags and star ratings have DB-backed support in the current large-folder path.
- Markings are still stored in sidecar JSON metadata as the source of truth.
- Basic marking filters such as `marking:` and `marking_type:` are now implemented in the DB-backed paginated SQL path.
- Geometry-aware marking filters such as `crops:` and `visible:` are still not implemented in the DB-backed paginated SQL path.

## Video Captioning

- Video behavior depends on the selected model family.
- Image-first models caption one representative frame.
- Qwen-VL and Gemma 4 support native temporal video input with configurable sampling.
- The remote backend sends an ordered sequence of sampled frames; quality and context limits depend on the remote model and server.

## Ideogram Structured Captions

- JSON-schema structured output is optional because not every remote model or OpenAI-compatible server supports it.
- Schema enforcement guarantees structural validity, not accurate descriptions, text recognition, colors, or bounding boxes.
- `.ideogram.json` sidecars remain the source of truth even though their searchable text and palette terms are indexed in the folder database.

## Video and Playback

- Backend behavior can differ.
- The project currently prefers the MPV path, but backend-specific behavior still needs clearer dedicated documentation.

## Skin Designer

- The skin system works, but the skin designer is still experimental.
- Designer parity, polish, and edge-case behavior still need work.

## Large-Folder UX

- First-open behavior on very large folders can still involve noticeable scanning, DB build, or thumbnail work before the folder settles into a faster cached path.

## Continue Reading

- [Troubleshooting](TROUBLESHOOTING.md)
- [Video Backends](VIDEO_BACKENDS.md)
- [Export Guide](EXPORT_GUIDE.md)
- [Ideogram 4 Structured Caption Guide](IDEOGRAM4_GUIDE.md)
