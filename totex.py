import os
import re
import logging
import time
import json
import argparse
from typing import List, Dict, Optional

import yt_dlp
from pydub import AudioSegment
from faster_whisper import WhisperModel
from openai import OpenAI
from tqdm import tqdm

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class LectureArchivist:
    def __init__(self, api_key: str, base_url: Optional[str] = None, model_name: str = "google/gemma-4-31b-it:free"):
        self.api_key = api_key
        self.base_url = base_url
        self.model_name = model_name
        self.client = OpenAI(api_key=self.api_key, base_url=self.base_url)
        
        self.metadata: Dict[str, str] = {}
        self.transcriptions: List[str] = []
        self.latex_sections: List[str] = []
        self.cache_file = "lecture_session_cache.json"
        
        self._load_cache()

    def _save_cache(self) -> None:
        """Записывает текущий прогресс в файл."""
        data = {
            'metadata': self.metadata,
            'transcriptions': self.transcriptions,
            'latex_sections': self.latex_sections
        }
        with open(self.cache_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)

    def _load_cache(self) -> None:
        """Загружает прогресс, если файл существует."""
        if os.path.exists(self.cache_file):
            try:
                with open(self.cache_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.metadata = data.get('metadata', {})
                    self.transcriptions = data.get('transcriptions', [])
                    self.latex_sections = data.get('latex_sections', [])
                logging.info(f"Найден прогресс: {len(self.transcriptions)} чанков транскрибировано, {len(self.latex_sections)} обработано LLM.")
            except Exception as e:
                logging.warning(f"Не удалось прочитать кэш: {e}")

    def download(self, url: str, output_path: str = "lecture_audio") -> Optional[str]:
        expected_audio_path = f"{output_path}.mp3"
        
        # Если транскрибация полностью завершена, аудио нам больше не нужно
        if self.metadata.get('transcription_done'):
            logging.info("Транскрибация для этого видео уже завершена. Загрузка аудио не требуется.")
            return None
            
        # Если аудиофайл уже скачан в прошлую сессию, просто используем его
        if os.path.exists(expected_audio_path):
            logging.info(f"Аудиофайл '{expected_audio_path}' уже есть на диске. Пропускаем загрузку.")
            return expected_audio_path

        logging.info(f"Начало загрузки: {url}")
        ydl_opts = {
            'format': 'bestaudio/best',
            'noplaylist': True, # ИСПРАВЛЕНИЕ 1: Запрещаем бесконечное скачивание плейлистов
            'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '192'}],
            'outtmpl': f'{output_path}.%(ext)s',
            'quiet': True,
            'source_address': '0.0.0.0',
            'extractor_args': {'youtube': ['player_client=tv', 'player_client=default']},
            'nocheckcertificate': True,
            'match_filter': yt_dlp.utils.match_filter_func("!is_live") # ИСПРАВЛЕНИЕ 2: Игнорируем стримы
        }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                self.metadata['title'] = info.get('title', 'Unknown Title')
                self.metadata['author'] = info.get('uploader', 'Unknown Author')
                self._save_cache()
                logging.info(f"Загрузка завершена: {self.metadata['title']}")
                return expected_audio_path
        except Exception as e:
            logging.error(f"Ошибка загрузки: {e}")
            raise

    def transcribe(self, audio_path: Optional[str]) -> List[str]:
        # Если уже все распознано - возвращаем результат
        if self.metadata.get('transcription_done'):
            return self.transcriptions

        if not audio_path or not os.path.exists(audio_path):
            raise FileNotFoundError("Для продолжения транскрибации требуется аудиофайл, но он не найден на диске!")

        chunk_paths = self._chunk_audio(audio_path)
        start_from = len(self.transcriptions)
        
        if start_from > 0:
            logging.info(f"Пропускаем {start_from} уже транскрибированных чанков...")

        if start_from < len(chunk_paths):
            logging.info("Инициализация Whisper...")
            model = WhisperModel("small", device="cpu", compute_type="int8")

            for i in tqdm(range(start_from, len(chunk_paths)), desc="Транскрибация", unit="чанк"):
                chunk_path = chunk_paths[i]
                segments, _ = model.transcribe(chunk_path, beam_size=5, language="ru")
                text = " ".join([s.text for s in segments]).strip()
                
                self.transcriptions.append(text)
                self._save_cache()
                
                if os.path.exists(chunk_path):
                    os.remove(chunk_path)

        # Отмечаем, что транскрибация завершена (чтобы безопасно удалить исходный аудиофайл)
        self.metadata['transcription_done'] = True
        self._save_cache()

        if os.path.exists("temp_chunks"):
            try: os.rmdir("temp_chunks")
            except Exception: pass
            
        return self.transcriptions

    def _chunk_audio(self, audio_path: Optional[str]) -> List[str]:
        if not audio_path: 
            return []
            
        logging.info("Подготовка аудиофайла (разбиение на чанки)...")
        audio = AudioSegment.from_file(audio_path)
        chunk_ms = 10 * 60 * 1000
        step_ms = chunk_ms - (30 * 1000)
        
        chunk_paths = []
        os.makedirs("temp_chunks", exist_ok=True)
        
        ranges = list(range(0, len(audio), step_ms))
        
        for i, start in enumerate(tqdm(ranges, desc="Нарезка аудио", unit="чанк")):
            path = f"temp_chunks/chunk_{i}.mp3"
            if not os.path.exists(path):
                chunk = audio[start : start + chunk_ms]
                chunk.export(path, format="mp3")
            chunk_paths.append(path)
            if start + chunk_ms >= len(audio): 
                break
                
        return chunk_paths

    def format_to_latex(self) -> None:
        if not self.transcriptions:
            raise ValueError("Нет текста для обработки.")

        start_idx = len(self.latex_sections)
        if start_idx > 0:
            logging.info(f"Продолжаем оформление в LaTeX с чанка {start_idx + 1}...")

        sys_prompt = (
            "Ты — профессиональный LaTeX-наборщик. Твоя задача — продолжать оформление конспекта лекции.\n"
            "ВАЖНЫЕ ПРАВИЛА:\n"
            "1. Тебе будет дан КОНТЕКСТ (конец предыдущей части) и НОВЫЙ ТЕКСТ.\n"
            "2. Твоя задача — обработать ТОЛЬКО НОВЫЙ ТЕКСТ.\n"
            "3. КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО повторять информацию, которая уже есть в КОНТЕКСТЕ.\n"
            "4. Начни свой ответ сразу с продолжения, чтобы при склейке с контекстом текст был бесшовным.\n"
            "5. Если НОВЫЙ ТЕКСТ начинается с того же, чем закончился КОНТЕКСТ — просто проигнорируй это дублирование.\n"
            "6. Выводи ТОЛЬКО чистый код LaTeX."
        )

        if start_idx < len(self.transcriptions):
            for i in tqdm(range(start_idx, len(self.transcriptions)), desc="Генерация LaTeX", unit="чанк"):
                text = self.transcriptions[i]
                context = ""
                if i > 0:
                    context = f"Предыдущий контекст: {self.latex_sections[i-1][:500]}...\n\n"

                try:
                    res = self._call_llm_with_retry([
                        {"role": "system", "content": sys_prompt},
                        {"role": "user", "content": context + text}
                    ])
                    res = re.sub(r'```latex|```', '', res).strip()
                    
                    self.latex_sections.append(res)
                    self._save_cache()
                    
                    time.sleep(10) # Защита от 429
                except Exception as e:
                    logging.error(f"Ошибка на чанке {i}: {e}")
                    break

    def _call_llm_with_retry(self, messages: list) -> str:
        for attempt in range(5):
            try:
                response = self.client.chat.completions.create(
                    model=self.model_name, messages=messages, temperature=0.2
                )
                return response.choices[0].message.content
            except Exception as e:
                if "429" in str(e):
                    wait = (attempt + 1) * 30
                    tqdm.write(f"Rate Limit. Ждем {wait} сек...") 
                    time.sleep(wait)
                else: 
                    raise e
        raise Exception("API недоступно после нескольких попыток.")

    def save_final_tex(self, filename: str = "lecture_notes.tex") -> None:
        if not self.latex_sections: 
            return
            
        title = self.metadata.get('title', 'Lecture').replace('_', '\\_')
        doc = (
            f"\\documentclass[12pt]{{article}}\n"
            f"\\usepackage[utf8]{{inputenc}}\n"
            f"\\usepackage[russian]{{babel}}\n"
            f"\\usepackage{{amsmath,amssymb,geometry}}\n"
            f"\\geometry{{a4paper,margin=2cm}}\n"
            f"\\title{{{title}}}\n"
            f"\\begin{{document}}\n"
            f"\\maketitle\n\n"
        )
        doc += "\n\n".join(self.latex_sections)
        doc += "\n\\end{document}"
        
        with open(filename, "w", encoding="utf-8") as f:
            f.write(doc)
        logging.info(f"Файл {filename} сохранен!")


def main():
    parser = argparse.ArgumentParser(description="Конвертация видеолекции в LaTeX конспект")
    parser.add_argument("url", type=str, help="Ссылка на видео (YouTube и др.)")
    parser.add_argument(
        "--api-key", 
        type=str, 
        default=os.getenv("OPENROUTER_API_KEY"),
        help="API ключ. Можно передать через переменную окружения OPENROUTER_API_KEY"
    )
    parser.add_argument(
        "--model", 
        type=str, 
        default="minimax/minimax-m2.5:free",
        help="Название модели LLM"
    )

    args = parser.parse_args()

    if not args.api_key:
        logging.error("Не указан API ключ! Используйте аргумент --api-key или задайте переменную окружения OPENROUTER_API_KEY")
        return

    archivist = LectureArchivist(
        api_key=args.api_key, 
        base_url="https://openrouter.ai/api/v1",
        model_name=args.model
    )
    
    try:
        audio = archivist.download(args.url)
        archivist.transcribe(audio)
        archivist.format_to_latex()
        archivist.save_final_tex()
    except KeyboardInterrupt:
        logging.info("\nПроцесс прерван пользователем. Прогресс сохранен в кэш.")
    finally:
        # ИСПРАВЛЕНИЕ 3: Удаляем аудио только тогда, когда весь текст успешно транскрибирован
        if archivist.metadata.get('transcription_done') and 'audio' in locals() and audio and os.path.exists(audio):
            os.remove(audio)
            logging.info("Временный аудиофайл удален, так как он больше не нужен.")

if __name__ == "__main__":
    main()
