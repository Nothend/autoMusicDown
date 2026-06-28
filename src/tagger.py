"""音频标签写入与封面压缩：把下载好的文件写入元信息（标题/艺术家/专辑/年份/歌词/封面）。

依赖 mutagen（标签）与 Pillow（封面压缩），与下载编排逻辑解耦。
"""

import io
import logging
from pathlib import Path

import requests
from PIL import Image
from mutagen.flac import FLAC, Picture
from mutagen.mp3 import MP3
from mutagen.id3 import ID3, TIT2, TPE1, TALB, TDRC, TRCK, APIC, TYER, USLT
from mutagen.mp4 import MP4, MP4Cover

from models import MusicInfo

logger = logging.getLogger(__name__)

_MAX_COVER_SIZE = 5 * 1024 * 1024  # 封面超过 5MB 自动压缩


def _cover_mime(data: bytes) -> str:
    """按字节魔数判断封面 MIME（JPEG/PNG），默认 PNG。"""
    return 'image/jpeg' if data[:2] == b'\xff\xd8' else 'image/png'


def _fetch_cover(pic_url: str) -> bytes | None:
    """下载封面并按需压缩到 _MAX_COVER_SIZE 以内；下载/压缩失败均返回 None。"""
    try:
        resp = requests.get(pic_url, timeout=10)
        resp.raise_for_status()
        data = resp.content
        if len(data) > _MAX_COVER_SIZE:
            logger.debug(f"封面过大（{len(data)} 字节），开始压缩...")
            data = compress_image(data, _MAX_COVER_SIZE)
            if not data:
                logger.warning("压缩后仍超过上限，跳过封面")
                return None
            logger.debug(f"压缩后大小: {len(data)} 字节")
        return data
    except Exception as e:
        logger.warning(f"封面下载失败: {e}")
        return None


def write_tags(file_path: Path, music_info: MusicInfo) -> None:
    """按文件扩展名分派到对应的标签写入实现。"""
    try:
        file_ext = file_path.suffix.lower()
        if file_ext == '.mp3':
            _write_mp3_tags(file_path, music_info)
        elif file_ext == '.flac':
            _write_flac_tags(file_path, music_info)
        elif file_ext == '.m4a':
            _write_m4a_tags(file_path, music_info)
    except Exception as e:
        logger.error(f"写入音乐标签失败: {e}")


def _write_mp3_tags(file_path: Path, music_info: MusicInfo) -> None:
    """写入MP3标签（图片>5MB自动压缩，失败不影响其他标签）"""
    try:
        audio = MP3(str(file_path), ID3=ID3)
        if not audio.tags:
            audio.add_tags()

        # ---------------------- 1. 保存基础标签 ----------------------
        audio.tags.setall('TIT2', [TIT2(encoding=3, text=music_info.name)])
        audio.tags.setall('TPE1', [TPE1(encoding=3, text=music_info.artists)])
        audio.tags.setall('TALB', [TALB(encoding=3, text=music_info.album)])

        if music_info.track_number > 0:
            audio.tags.setall('TRCK', [TRCK(encoding=3, text=str(music_info.track_number))])

        # 发行时间
        if hasattr(music_info, 'publishTime') and music_info.publishTime:
            full_date = music_info.publishTime.strip()
            try:
                year = full_date.split('-')[0] if '-' in full_date else full_date
                audio.tags.setall('TYER', [TYER(encoding=3, text=year)])
                audio.tags.setall('TDRC', [TDRC(encoding=3, text=full_date)])
            except Exception as e:
                logger.warning(f"发行时间处理失败: {str(e)}")

        # 歌词
        if music_info.lyric:
            audio.tags.setall('USLT', [USLT(
                encoding=3, lang='XXX', desc='Lyrics', text=music_info.lyric.strip()
            )])
        if music_info.tlyric:
            audio.tags.setall('USLT:Translated', [USLT(
                encoding=3, lang='XXX', desc='Translated Lyrics', text=music_info.tlyric.strip()
            )])

        audio.save()
        logger.debug(f"已保存MP3基础标签: {file_path.name}")

        # ---------------------- 2. 处理封面（>5MB 自动压缩） ----------------------
        if music_info.pic_url:
            cover = _fetch_cover(music_info.pic_url)
            if cover:
                audio.tags.setall('APIC', [APIC(
                    encoding=3, mime=_cover_mime(cover), type=3, desc='Cover', data=cover
                )])
                audio.save()
                logger.debug("已添加MP3封面并保存")

    except Exception as e:
        logger.error(f"MP3基础标签处理失败: {str(e)}")


def _write_flac_tags(file_path: Path, music_info: MusicInfo) -> None:
    """写入FLAC标签（图片>5MB自动压缩，失败不影响其他标签）"""
    try:
        audio = FLAC(str(file_path))

        # ---------------------- 1. 保存基础标签 ----------------------
        audio['TITLE'] = music_info.name
        audio['ARTIST'] = music_info.artists
        audio['ALBUM'] = music_info.album
        if music_info.track_number > 0:
            audio['TRACKNUMBER'] = str(music_info.track_number)

        # 发行时间
        if hasattr(music_info, 'publishTime') and music_info.publishTime:
            full_date = music_info.publishTime
            audio['YEAR'] = full_date.split('-')[0] if '-' in full_date else full_date
            audio['DATE'] = full_date
        else:
            logger.debug("publishTime为空，跳过日期标签")

        # 歌词
        if music_info.lyric:
            audio['LYRICS'] = music_info.lyric.strip()
        if music_info.tlyric:
            audio['TRANSLATEDLYRICS'] = music_info.tlyric.strip()

        audio.save()
        logger.debug(f"已保存FLAC基础标签: {file_path.name}")

        # ---------------------- 2. 处理封面（>5MB 自动压缩） ----------------------
        if music_info.pic_url:
            cover = _fetch_cover(music_info.pic_url)
            if cover:
                picture = Picture()
                picture.type = 3
                picture.mime = _cover_mime(cover)
                picture.desc = 'Cover'
                picture.data = cover
                audio.add_picture(picture)
                audio.save()
                logger.debug("已添加FLAC封面并保存")

    except Exception as e:
        logger.error(f"FLAC基础标签处理失败: {str(e)}")


def _write_m4a_tags(file_path: Path, music_info: MusicInfo) -> None:
    """写入M4A标签"""
    try:
        audio = MP4(str(file_path))

        audio['\xa9nam'] = music_info.name
        audio['\xa9ART'] = music_info.artists
        audio['\xa9alb'] = music_info.album

        if music_info.track_number > 0:
            audio['trkn'] = [(music_info.track_number, 0)]

        # 下载并添加封面（统一走压缩，避免超大封面）
        if music_info.pic_url:
            cover = _fetch_cover(music_info.pic_url)
            if cover:
                fmt = MP4Cover.FORMAT_JPEG if _cover_mime(cover) == 'image/jpeg' else MP4Cover.FORMAT_PNG
                audio['covr'] = [MP4Cover(cover, imageformat=fmt)]

        audio.save()
    except Exception as e:
        logger.error(f"写入M4A标签失败: {e}")


def compress_image(image_data: bytes, max_size: int = _MAX_COVER_SIZE, max_dimension: int = 2000) -> bytes:
    """压缩图片至指定大小，处理DecompressionBombWarning。压缩不下来返回 None。"""
    original_max_pixels = Image.MAX_IMAGE_PIXELS
    try:
        # 在打开图片前先放宽像素限制（覆盖超大封面），避免触发 DecompressionBombWarning
        Image.MAX_IMAGE_PIXELS = 160000000  # 1.6亿像素

        if len(image_data) <= max_size:
            return image_data

        with Image.open(io.BytesIO(image_data)) as img:
            original_width, original_height = img.size
            total_pixels = original_width * original_height
            logger.debug(f"图片像素: {total_pixels}（{original_width}x{original_height}）")

            # 主动防护：像素过大疑似恶意文件，拒绝处理
            if total_pixels > 200000000:  # 2亿像素阈值
                logger.error(f"图片像素过大（{total_pixels}），可能是恶意文件，拒绝处理")
                return None

            img_format = img.format if img.format in ['JPEG', 'PNG'] else 'JPEG'
            is_png = img_format == 'PNG'

            # 缩放尺寸
            if original_width > max_dimension or original_height > max_dimension:
                scale = min(max_dimension / original_width, max_dimension / original_height)
                new_width, new_height = int(original_width * scale), int(original_height * scale)
                img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
                logger.debug(f"缩放到 {new_width}x{new_height}")

            # 检查缩放后大小
            buffer = io.BytesIO()
            img.save(buffer, format=img_format, quality=95 if not is_png else None, optimize=True)
            scaled_data = buffer.getvalue()
            if len(scaled_data) <= max_size:
                return scaled_data

            # PNG 转 JPEG
            if is_png:
                logger.debug("PNG转JPEG尝试压缩")
                if img.mode in ('RGBA', 'LA') or (img.mode == 'P' and 'transparency' in img.info):
                    background = Image.new(img.mode[:-1], img.size, (255, 255, 255))
                    background.paste(img, img.split()[-1])
                    img = background.convert('RGB')
                else:
                    img = img.convert('RGB')
                img_format = 'JPEG'

                buffer = io.BytesIO()
                img.save(buffer, format='JPEG', quality=95, optimize=True)
                converted_data = buffer.getvalue()
                if len(converted_data) <= max_size:
                    return converted_data

            # 逐步降低 JPEG 质量
            quality = 90
            min_quality = 70
            quality_step = 2
            while quality >= min_quality:
                buffer = io.BytesIO()
                img.save(buffer, format='JPEG', quality=quality, optimize=True, progressive=True)
                compressed_data = buffer.getvalue()
                if len(compressed_data) <= max_size:
                    logger.debug(f"压缩完成（质量{quality}）")
                    return compressed_data
                quality -= quality_step

            logger.warning("压缩至最低质量仍超标")
            return None

    except Exception as e:
        logger.warning(f"压缩失败: {str(e)}")
        return None
    finally:
        # 恢复全局像素限制
        Image.MAX_IMAGE_PIXELS = original_max_pixels
