-- Player feedback (spec §9). No IPs, user agents or other personal data: only what the
-- player typed or picked, the drive, and when the server received it.
CREATE TABLE IF NOT EXISTS feedback (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at TEXT    NOT NULL,                                   -- server time, ISO 8601 UTC
  drive      INTEGER NOT NULL CHECK (drive >= 1),
  rating     INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
  message    TEXT             CHECK (message IS NULL OR length(message) <= 500),
  device     TEXT    NOT NULL CHECK (device IN ('mobile', 'desktop'))
);
CREATE INDEX IF NOT EXISTS feedback_drive ON feedback (drive);
CREATE INDEX IF NOT EXISTS feedback_created ON feedback (created_at);
