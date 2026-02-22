from typing import Generator
from fastapi import Depends, Body
import sqlite3
from fastapi import FastAPI
from pydantic import BaseModel, Field
from pydub import AudioSegment
from fastapi.responses import Response

class LyricResult(BaseModel):
    file_path: str = Field(..., description="歌词文件路径")
    line_id: int = Field(..., description="歌词行ID")
    line: str = Field(..., description="歌词行内容")
    start_time: float = Field(..., description="开始时间（秒）")
    end_time: float = Field(..., description="结束时间（秒）")
    title: str = Field(..., description="歌曲名")
    artist: str = Field(..., description="歌手")

# 新增：请求体模型
class LineIdsRequest(BaseModel):
    line_ids: list[int] = Field(..., description="歌词行ID数组")

app = FastAPI()
DB_PATH = "music.db"

def get_conn() -> Generator[sqlite3.Connection, None, None]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()

@app.get("/search/{word}")
def get_word(word: str, conn: sqlite3.Connection = Depends(get_conn)) -> list[LyricResult]:
    return search_word(word, conn)

def search_word(word: str, conn: sqlite3.Connection) -> list[LyricResult]:
    # 如果有非字母字符，直接返回空列表
    if not word.isalpha():
        return []
    cursor = conn.cursor()
    cursor.execute("""SELECT
	file_path,
	line,
	start_time,
	end_time,
	title,
	artist,
	line_id
FROM
	( word_index JOIN lyric_lines ON word_index.line_id = lyric_lines.id JOIN songs ON lyric_lines.song_id = songs.id ) 
WHERE
	word = ?;""", (word,))
    rows = cursor.fetchall()
    return [LyricResult(**dict(row)) for row in rows]


@app.post("/get_lines")
def get_lines_by_ids(
    request: LineIdsRequest, 
    conn: sqlite3.Connection = Depends(get_conn)
) -> list[LyricResult]:
    """
    通过line_id数组批量获取歌词行详情
    返回格式与 /search/{word} 完全相同
    """
    if not request.line_ids:
        return []
    
    cursor = conn.cursor()
    placeholders = ','.join('?' * len(request.line_ids))
    
    cursor.execute(f"""SELECT
        file_path,
        line,
        start_time,
        end_time,
        title,
        artist,
        lyric_lines.id as line_id
    FROM
        lyric_lines 
    JOIN songs ON lyric_lines.song_id = songs.id
    WHERE lyric_lines.id IN ({placeholders});""", tuple(request.line_ids))
    
    rows = cursor.fetchall()
    return [LyricResult(**dict(row)) for row in rows]

@app.get("/get_line_ogg/{line_id}")
def get_line_ogg(line_id: int, start_offset: int = 300, end_offset: int = 200, conn: sqlite3.Connection = Depends(get_conn)) -> Response:
    cursor = conn.cursor()
    cursor.execute("""
                   SELECT
                        file_path,
                        start_time,
                        end_time 
                    FROM
                        ( lyric_lines JOIN songs ON lyric_lines.song_id = songs.id )
                    WHERE lyric_lines.id = ?;
                   """, (line_id,))
    file_path, start_time, end_time = cursor.fetchone()
    audio = AudioSegment.from_file(file_path)
    # TODO: 更智能的剪切逻辑: 如 自动剪切到下一句开始, 但不超过 audio.duration_seconds*1000且不超过自定义 max_end_offset
    clip = audio[max(start_time*1000-start_offset, 0):min(end_time*1000+end_offset, audio.duration_seconds*1000)]  # pydub 用毫秒
    ogg_bytes = clip.export(format="ogg").read()
    return Response(content=ogg_bytes, media_type="audio/ogg")

if __name__ == "__main__":
    import os
    if not os.path.exists(DB_PATH):
        import music_importer
        music_importer.recopy_db()
        with sqlite3.connect(DB_PATH) as conn:
            music_importer.scan_and_add_musics_to_db(conn)
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)