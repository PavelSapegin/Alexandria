#!/usr/bin/env python3
import os
import sys
import argparse
from pathlib import Path

# Расширенный список игнорируемых папок
DEFAULT_IGNORE = {
    '.git', '.idea', '.vscode', '.gradle', 'build', 'node_modules', 
    'venv', '.venv', 'bin', 'obj', '__pycache__', 'target', 'dist'
}

# Карта расширений для подсветки синтаксиса в Markdown
LANG_MAP = {
    '.py': 'python',
    '.kt': 'kotlin',
    '.kts': 'kotlin',
    '.java': 'java',
    '.js': 'javascript',
    '.ts': 'typescript',
    '.cpp': 'cpp',
    '.c': 'c',
    '.h': 'cpp',
    '.cs': 'csharp',
    '.go': 'go',
    '.rs': 'rust',
    '.rb': 'ruby',
    '.php': 'php',
    '.html': 'html',
    '.css': 'css',
    '.sh': 'bash',
    '.yaml': 'yaml',
    '.yml': 'yaml',
    '.json': 'json',
    '.sql': 'sql'
}

def is_binary(file_path):
    """Проверяет, является ли файл бинарным."""
    try:
        with open(file_path, 'rb') as f:
            chunk = f.read(1024)
            return b'\0' in chunk
    except Exception:
        return True

def get_markdown_lang(file_path):
    """Определяет язык для блока кода Markdown."""
    return LANG_MAP.get(file_path.suffix.lower(), '')

def collect_project(target_dir, output_file=None, extra_ignore=None):
    target_path = Path(target_dir).resolve()
    if not target_path.exists():
        print(f"![ERR] Path not found: {target_path}")
        return

    if not output_file:
        output_file = f"{target_path.name}_code.md"
    
    output_path = Path.cwd() / output_file
    ignore_set = DEFAULT_IGNORE.copy()
    if extra_ignore:
        ignore_set.update(extra_ignore)

    print(f"--- Scanning: {target_path.name} ---")
    print(f" Ignoring: {', '.join(sorted(ignore_set))}")

    files_count = 0
    
    try:
        with open(output_path, 'w', encoding='utf-8') as md_file:
            md_file.write(f"# Project Archive: {target_path.name}\n")
            md_file.write(f"**Path:** `{target_path}`\n\n---\n\n")

            for root, dirs, files in os.walk(target_path):
                # Фильтруем папки "на лету"
                dirs[:] = [d for d in dirs if d not in ignore_set and not d.startswith('.')]

                for file_name in files:
                    file_path = Path(root) / file_name
                    
                    # Пропускаем сам файл результата и скрытые файлы
                    if file_path.resolve() == output_path.resolve() or file_name.startswith('.'):
                        continue

                    if not is_binary(file_path):
                        relative_path = file_path.relative_to(target_path)
                        lang = get_markdown_lang(file_path)
                        
                        print(f"[NEW] Add: {relative_path}")
                        
                        md_file.write(f"### File: {relative_path}\n")
                        md_file.write(f"```{lang}\n")
                        
                        try:
                            with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                                md_file.write(f.read())
                        except Exception as e:
                            md_file.write(f"// Ошибка чтения файла: {e}")
                        
                        md_file.write("\n```\n\n---\n\n")
                        files_count += 1

            print("---")
            print(f"Done: {files_count} files -> {output_file}")

    except PermissionError:
        print(f"![ERR] Permission denied: {output_path}")

def main():
    parser = argparse.ArgumentParser(description="Сборщик кода проекта в один Markdown файл.")
    parser.add_argument("path", nargs="?", default=".", help="Путь к папке проекта (по умолчанию текущая)")
    parser.add_argument("-o", "--output", help="Имя выходного файла")
    parser.add_argument("-i", "--ignore", nargs="+", help="Дополнительные папки для игнорирования")

    args = parser.parse_args()
    collect_project(args.path, args.output, args.ignore)


if __name__ == "__main__":
    main()
    
