"""Library import, text extraction and the SQLite FTS5 index."""

CATEGORIES = (
    "medical_survival", "engineering", "natural_sciences", "radio", "mechanical",
    "navigation_weather", "education", "personal",
)
DEFAULT_CATEGORY = "personal"
FORMATS = {".pdf": "pdf", ".epub": "epub", ".txt": "txt", ".md": "md", ".markdown": "md",
           ".html": "html", ".htm": "html"}
