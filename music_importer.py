import sqlite3
import os
from tinytag import TinyTag
import requests

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

def scan_and_add_musics_to_db(conn: sqlite3.Connection):
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
            try:
                response = requests.get(
                    'https://tools.rangotec.com/api/anon/lrc',
                    params={'title': title, 'artist': artist}
                )
            except requests.RequestException as e:
                print(f"警告:获取{title}的歌词时发生错误: {e}")
                continue
            if response.status_code != 200:
                print(f"警告:获取{title}的歌词失败, 状态码: {response.status_code}")
                continue
            try:
                lrc = response.json()['data'][0]['lrc']
            except (KeyError, IndexError, ValueError) as e:
                print(f"警告:解析{title} - {artist}的歌词时发生错误: {e}")
                continue
            lines = lrc.split('\r\n')
            song_id = cursor.lastrowid

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
    cursor.close()

if __name__ == '__main__':
    # 使用示例
    with sqlite3.connect('music copy.db') as conn:
        scan_and_add_musics_to_db(conn)
