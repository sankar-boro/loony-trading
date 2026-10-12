-- The Loony Trading Handbook: table definitions (no data).
-- Generated from db/models.py by `python scripts/migrate_docs.py --write-sql`.
-- Schema-neutral: the tables are created in the first schema of the
-- search_path. scripts/migrate_docs.py sets it to DB_SCHEMA and then
-- loads docs/ into the tables.

CREATE TABLE IF NOT EXISTS doc_chapters (
	id SERIAL NOT NULL,
	path VARCHAR(255) NOT NULL,
	part VARCHAR(128) NOT NULL,
	part_number INTEGER NOT NULL,
	number INTEGER NOT NULL,
	title VARCHAR(255) NOT NULL,
	content TEXT NOT NULL,
	content_sha256 VARCHAR(64) NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (path)
);
CREATE INDEX IF NOT EXISTS ix_doc_chapters_number ON doc_chapters (number);

CREATE TABLE IF NOT EXISTS doc_sections (
	id SERIAL NOT NULL,
	chapter_id INTEGER NOT NULL,
	position INTEGER NOT NULL,
	anchor VARCHAR(255) NOT NULL,
	title VARCHAR(255) NOT NULL,
	content TEXT NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_docsection_chapter_position UNIQUE (chapter_id, position),
	FOREIGN KEY(chapter_id) REFERENCES doc_chapters (id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS ix_doc_sections_chapter_id ON doc_sections (chapter_id);
