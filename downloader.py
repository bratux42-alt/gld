import yt_dlp
import os
import asyncio
import logging

logger = logging.getLogger(__name__)

class Downloader:
    def __init__(self, download_path="downloads"):
        self.download_path = download_path
        if not os.path.exists(download_path):
            os.makedirs(download_path)

    async def download(self, url: str, mode: str = "video") -> str:
        """
        Downloads media from URL.
        mode: 'video' or 'audio'
        Returns the path to the downloaded file.
        """
        # Workaround for platforms with DRM or limited support (Spotify, Yandex Music)
        # Search on YouTube instead
        music_platforms = ["spotify.com", "music.yandex", "yandex.ru/music"]
        if any(platform in url for platform in music_platforms):
            mode = "audio" # These are always audio
            url = f"ytsearch1:{url} audio"
            logger.info(f"Music platform detected, searching on YouTube: {url}")

        loop = asyncio.get_event_loop()
        
        ydl_opts = {
            # Выбираем лучший формат, где видео и аудио уже вместе (progressive), предпочтительно mp4
            'format': 'best[ext=mp4]/best',
            'outtmpl': f'{self.download_path}/%(title).50s_%(id)s.%(ext)s',
            'noplaylist': True,
            'quiet': True,
            'no_warnings': True,
            'nocheckcertificate': True,
            'ignoreerrors': False,
            'logtostderr': False,
            'add_header': [
                'User-Agent:Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            ]
        }

        # Postprocessors removed for local testing without FFmpeg
        # They will be needed on the server, but for now we comment them out or disable
        """
        if mode == 'audio':
            ydl_opts.update({
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }],
            })
        elif mode == 'video':
             ydl_opts.update({
                'postprocessors': [{
                    'key': 'FFmpegVideoConvertor',
                    'preferedformat': 'mp4',
                }],
            })
        """

        try:
            # We use run_in_executor because yt_dlp is synchronous
            info = await loop.run_in_executor(None, lambda: self._extract_info(url, ydl_opts))
            if not info:
                return None
            
            filename = self._get_filename(info, mode)
            return filename
        except Exception as e:
            logger.error(f"Error downloading {url}: {e}")
            return None

    def _extract_info(self, url, opts):
        with yt_dlp.YoutubeDL(opts) as ydl:
            return ydl.extract_info(url, download=True)

    def _get_filename(self, info, mode):
        # If it was a search, info will contain 'entries'
        if 'entries' in info and len(info['entries']) > 0:
            info = info['entries'][0]

        # yt-dlp might change extension after post-processing
        ext = 'mp3' if mode == 'audio' else 'mp4'
        
        # If it's a playlist or something else, it might be different, but noplaylist is True
        # The outtmpl uses title and id
        base_path = f"{self.download_path}/{info['title'][:50]}_{info['id']}"
        
        # Check if the file exists with the expected extension or the one from info
        possible_file = f"{base_path}.{ext}"
        if os.path.exists(possible_file):
            return possible_file
        
        # Fallback: check what yt-dlp actually saved
        for f in os.listdir(self.download_path):
            if info['id'] in f:
                return os.path.join(self.download_path, f)
        
        return None

downloader = Downloader()
