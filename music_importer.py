import sqlite3
import os
from tinytag import TinyTag
import requests
import shutil
from dataclasses import dataclass
from enum import Enum

class Color(Enum):
    RED = '\033[91m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    MAGENTA = '\033[95m'
    CYAN = '\033[96m'
    WHITE = '\033[97m'
    RESET = '\033[0m'

def color_print(text: str, color: Color):
    print(f"{color.value}{text}{Color.RESET.value}")

@dataclass
class LyricsStats:
    direct_success: int = 0
    backup_success: int = 0
    main_no_artist_success: int = 0
    backup_no_artist_success: int = 0
    failed: int = 0

def recopy_db():
    shutil.copy("template_db.db", "music.db")
    

def convert_timestamp_into_seconds(timestamp):
    # timestamp格式通常为"mm:ss:xxxx"
    # 也可能是mm:ss.xxx
    try:
        timestamp = timestamp.replace('.', ':')
        split_timestamp = timestamp.split(':')
        minutes, seconds, milliseconds = map(float, split_timestamp)
        return minutes * 60 + seconds + milliseconds / 1000
    except (ValueError, IndexError):
        # 处理格式错误的情况
        print(f"Invalid timestamp format: {timestamp}")
        return None

def fetch_lyrics_from_lrclib(title: str, artist: str, album: str | None = None, duration: float | None = None) -> str | None:
    """从LRCLIB API获取歌词"""
    try:
        # 首先尝试使用 /api/get 端点
        params: dict[str, str] = {
            'track_name': title,
            'artist_name': artist
        }
        if album:
            params['album_name'] = album
        if duration:
            params['duration'] = str(int(duration))
        
        response = requests.get(
            'https://lrclib.net/api/get',
            params=params,
            timeout=10
        )
        
        if response.status_code == 200:
            data = response.json()
            synced_lyrics = data.get('syncedLyrics')
            if synced_lyrics:
                return synced_lyrics
            plain_lyrics = data.get('plainLyrics')
            if plain_lyrics:
                return plain_lyrics
        
        # 如果 /api/get 失败，尝试 /api/search
        search_params = {'q': f"{title} {artist}"}
        response = requests.get(
            'https://lrclib.net/api/search',
            params=search_params,
            timeout=10
        )
        
        if response.status_code == 200:
            results = response.json()
            if results and len(results) > 0:
                synced_lyrics = results[0].get('syncedLyrics')
                if synced_lyrics:
                    return synced_lyrics
                plain_lyrics = results[0].get('plainLyrics')
                if plain_lyrics:
                    return plain_lyrics
        
        return None
    except Exception as e:
        print(f"LRCLIB API请求失败: {e}")
        return None

def convert_lrclib_to_custom_format(lrc_content: str) -> str:
    """将LRCLIB的LRC格式转换为自定义格式 [mm:ss:xxx,mm:ss:xxx]歌词"""
    lines = lrc_content.split('\n')
    result_lines = []
    last_end_time = None
    
    for i, line in enumerate(lines):
        line = line.strip()
        if not line or not line.startswith('['):
            continue
        
        # 解析时间戳 [mm:ss.xx] 或 [mm:ss.xxx]
        try:
            # 找到时间戳结束位置
            time_end_idx = line.find(']')
            if time_end_idx == -1:
                continue
            
            time_str = line[1:time_end_idx]  # mm:ss.xx
            lyric_text = line[time_end_idx + 1:].strip()
            
            if not lyric_text:
                continue
            
            # 解析开始时间
            time_parts = time_str.split(':')
            if len(time_parts) != 2:
                continue
            
            minutes = int(time_parts[0])
            seconds_parts = time_parts[1].split('.')
            seconds = int(seconds_parts[0])
            milliseconds = int(seconds_parts[1].ljust(3, '0')[:3]) if len(seconds_parts) > 1 else 0
            
            start_time_str = f"{minutes:02d}:{seconds:02d}:{milliseconds:03d}"
            
            # 估算结束时间：使用下一行的开始时间，如果没有则加5秒
            if i + 1 < len(lines):
                next_line = lines[i + 1].strip()
                if next_line.startswith('['):
                    next_time_end_idx = next_line.find(']')
                    if next_time_end_idx != -1:
                        next_time_str = next_line[1:next_time_end_idx]
                        next_parts = next_time_str.split(':')
                        if len(next_parts) == 2:
                            next_minutes = int(next_parts[0])
                            next_seconds_parts = next_parts[1].split('.')
                            next_seconds = int(next_seconds_parts[0])
                            next_milliseconds = int(next_seconds_parts[1].ljust(3, '0')[:3]) if len(next_seconds_parts) > 1 else 0
                            end_time_str = f"{next_minutes:02d}:{next_seconds:02d}:{next_milliseconds:03d}"
                        else:
                            end_time_str = f"{minutes:02d}:{seconds + 5:02d}:{milliseconds:03d}"
                    else:
                        end_time_str = f"{minutes:02d}:{seconds + 5:02d}:{milliseconds:03d}"
                else:
                    end_time_str = f"{minutes:02d}:{seconds + 5:02d}:{milliseconds:03d}"
            else:
                end_time_str = f"{minutes:02d}:{seconds + 5:02d}:{milliseconds:03d}"
            
            result_lines.append(f"[{start_time_str},{end_time_str}]{lyric_text}")
            
        except (ValueError, IndexError) as e:
            continue
    
    return '\r\n'.join(result_lines)

def scan_and_add_musics_to_db(conn: sqlite3.Connection, stats: LyricsStats | None = None):
    cursor = conn.cursor()
    # 我们来梳理一下
    # 使用增量更新
    # 第一步是扫描歌曲文件, 看看有没有文件路径相同的 有结果->continue 无结果 -> add
    # add: 先加songs基础数据(到时候拖拽自动填充可指定歌名(与歌手)), 再用歌词API获取歌词(可指定歌词) 利用它获取start_time, end_time, line 最后for循环添加到word_index中
    # 我们先写一个基础逻辑:添加Love Story. 使用备份后的数据库: music_copy.db
    folder_path = 'music' 
    for root, dirs, files in os.walk(folder_path):
        for file in files:
            file_path = os.path.join(root, file)
            # 查询数据库是否已存在相同文件路径
            cursor.execute("SELECT file_path FROM songs WHERE file_path = ?", (file_path,))
            if cursor.fetchall():
                continue
            #else
            tag = TinyTag.get(file_path)
            title = tag.title
            artist = tag.artist
            duration = tag.duration
            # 插入新的歌曲数据
            cursor.execute("INSERT INTO songs (file_path, title, artist, duration) VALUES (?, ?, ?, ?)", (file_path, title, artist, duration))
            ''' 接下来获取歌词 api:https://tools.rangotec.com/api/anon/lrc?title=Love%20Story&artist=Taylor%20Swift
            API返回JSON格式说明:
            {
            "code": 200,           // HTTP状态码,200表示成功
            "msg": "成功",         // 响应消息
            "data": [              // 歌曲数据数组
                {
                "id": 6590734,     // 歌曲唯一标识符
                "artist": "xxx",   // 艺术家名称
                "title": "xxx",    // 歌曲标题
                "album": "",       // 专辑名称(可能为空)
                "lrc": "[00:00:000,00:16:310]...", // 歌词内容(LRC格式,带时间戳)
                "trc": null,       // 翻译歌词(当前为null)
                "createDate": "2025-11-28T08:44:24.274+08:00", // 创建时间(ISO 8601)
                "updateDate": "2025-11-28T08:44:24.274+08:00", // 更新时间(ISO 8601)
                "status": 1        // 状态码
                }
            ]
            }
            LRC歌词格式说明: [开始时间,结束时间]歌词内容
            示例: [00:16:317,00:19:917]We were both young when I first saw you\r\n<and repeat> '''
            
            if stats is None:
                stats = LyricsStats()
            
            def try_get_lyrics(title: str, artist: str | None = None, album: str | None = None, duration: float | None = None) -> tuple[str | None, str]:
                """尝试获取歌词，返回(歌词内容, API来源)"""
                # 尝试主API
                try:
                    params = {'title': title}
                    if artist:
                        params['artist'] = artist
                    response = requests.get(
                        'https://tools.rangotec.com/api/anon/lrc',
                        params=params,
                        timeout=10
                    )
                    if response.status_code == 200:
                        try:
                            lrc = response.json()['data'][0]['lrc']
                            return lrc, "主API"
                        except (TypeError, KeyError):
                            pass
                except requests.RequestException:
                    pass
                
                # 尝试备用API
                lrclib_lyrics = fetch_lyrics_from_lrclib(
                    title,
                    artist or "",
                    album,
                    duration
                )
                if lrclib_lyrics:
                    return convert_lrclib_to_custom_format(lrclib_lyrics), "备用API"
                
                return None, ""
            
            def validate_lyrics(lrc_content: str, duration: float | None) -> bool:
                """验证歌词时长是否匹配"""
                if not duration:
                    return True
                lines = lrc_content.split('\r\n')
                for line in lines:
                    if not line.startswith('['):
                        continue
                    if ',' not in line or ']' not in line:
                        continue
                    try:
                        end_time_str = line.split(',')[1].split(']')[0]
                        end_time = convert_timestamp_into_seconds(end_time_str)
                        if end_time and end_time > duration:
                            return False
                    except (ValueError, IndexError):
                        continue
                return True
            
            lrc = None
            api_source = None
            
            # 尝试1: 主API和备用API（带artist）
            lrc, api_source = try_get_lyrics(title or "", artist, tag.album, duration)
            if lrc and validate_lyrics(lrc, duration):
                if api_source == "主API":
                    stats.direct_success += 1
                else:
                    stats.backup_success += 1
            else:
                # 尝试2: 主API和备用API（不带artist）
                lrc, api_source = try_get_lyrics(title or "", None, tag.album, duration)
                if lrc and validate_lyrics(lrc, duration):
                    if api_source == "主API":
                        stats.main_no_artist_success += 1
                    else:
                        stats.backup_no_artist_success += 1
                else:
                    stats.failed += 1
                    color_print(f"失败:无法获取{title} - {artist}的歌词", Color.RED)
                    continue
            
            if api_source == "主API":
                color_print(f"成功从主API获取{title} - {artist}的歌词", Color.GREEN)
            else:
                color_print(f"成功从备用API获取{title} - {artist}的歌词", Color.CYAN)
            
            lines = lrc.split('\r\n')
            song_id = cursor.lastrowid
            color_print(f"开始处理{title} - {artist}的歌词, 共{len(lines)}行", Color.BLUE)
            for line in lines:
                if not line.startswith('['):
                    continue
                # 确保行包含逗号和右方括号
                if ',' not in line or ']' not in line:
                    continue
                # 提取开始时间和结束时间
                start_time_str = line.split(',')[0].replace('[', '')
                end_time_str = line.split(',')[1].split(']')[0]
                # 转换时间戳
                start_time = convert_timestamp_into_seconds(start_time_str)
                end_time = convert_timestamp_into_seconds(end_time_str)
                # 检查时间戳是否有效
                if start_time is None or end_time is None:
                    continue
                lyric_line: str = line.split(']')[1].strip()
                # 有些歌曲第一句"歌词"可能是"[00:00:000,00:03:000] 曲名: xxx 演唱者: xxx" 这显然不是歌词, 排除. 
                # TODO: 考虑个性化设置 详见上一句注释
                if start_time == 0:
                    continue
                # 插入新的歌词行数据
                cursor.execute("INSERT INTO lyric_lines (song_id, start_time, end_time, line) VALUES (?, ?, ?, ?)", (song_id, start_time, end_time, lyric_line))
                # 随后for循环添加word
                line_id = cursor.lastrowid
                for word in lyric_line.split(' '):
                    # 插入新的单词数据
                    if not word:
                        continue # 跳过空单词
                    cursor.execute("INSERT INTO word_index (word, line_id) VALUES (?, ?)", (word.lower(), line_id))
            # 呼, 终于搞定了.
            conn.commit() # 注意: 即使不提交也能获取cursor.lastrowid, 因为它在事务中
            color_print(f"成功导入{title} - {artist}的歌词", Color.GREEN)
    cursor.close()
    return stats

if __name__ == '__main__':
    # 使用示例
    if not os.path.exists('music.db'):
        recopy_db()
    stats = LyricsStats()
    with sqlite3.connect('music.db') as conn:
        scan_and_add_musics_to_db(conn, stats)
    
    # 打印统计信息
    print("\n" + "=" * 50)
    color_print("歌词导入统计", Color.YELLOW)
    print("=" * 50)
    color_print(f"主API直接成功: {stats.direct_success} 首", Color.GREEN)
    color_print(f"备用API成功: {stats.backup_success} 首", Color.CYAN)
    color_print(f"主API去Artist成功: {stats.main_no_artist_success} 首", Color.BLUE)
    color_print(f"备用API去Artist成功: {stats.backup_no_artist_success} 首", Color.MAGENTA)
    color_print(f"失败: {stats.failed} 首", Color.RED)
    total = stats.direct_success + stats.backup_success + stats.main_no_artist_success + stats.backup_no_artist_success + stats.failed
    print("=" * 50)
    print(f"总计: {total} 首歌曲")
    success_rate = (total - stats.failed) / total * 100 if total > 0 else 0
    color_print(f"成功率: {success_rate:.1f}%", Color.GREEN)
