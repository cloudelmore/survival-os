# search

Library import, text extraction, the FTS5 index and the background indexer.

Files live in `$SURVIVAL_STATE_DIR/library/<category>/`, and the first folder sets the category.
Anything outside a category folder counts as `personal`. The index is
`$SURVIVAL_STATE_DIR/index/library.db`.

    survival-library import /path/to/folder --category radio
    survival-library status
    survival-library rescan

`survival-indexer` scans every five minutes or on request. It indexes in batches that commit with
their progress, so a kill or power cut resumes at the last batch. OCR is off by default: set
`SURVIVAL_OCR=1` and install `tesseract-ocr` to read scanned PDF pages.
