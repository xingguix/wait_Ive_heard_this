CREATE DATABASE IF NOT EXISTS `music`;

PRAGMA foreign_keys = ON;

CREATE TABLE songs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT,
    artist TEXT,
    file_path TEXT UNIQUE, --From /music
    duration INTEGER
    );

CREATE TABLE lyrics_lines(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    song_id INTEGER,
    start_time REAL,
    end_time REAL,
    line TEXT,
    FOREIGN KEY (song_id) REFERENCES songs(id) ON DELETE CASCADE
    );
CREATE TABLE word_index(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    word TEXT,
    line_id INTEGER,
    FOREIGN KEY (line_id) REFERENCES lyrics_lines(id) ON DELETE CASCADE
    );

.open music.db
DROP TABLE `songs`;

SELECT file_path, line, start_time, end_time, title, artist FROM (
	word_index
	JOIN lyric_lines ON word_index.line_id = lyric_lines.id
	JOIN songs ON lyric_lines.song_id = songs.id
) WHERE word = 'hello';