import os
import re
from notion_client import Client
from dotenv import load_dotenv
# Вставь свои данные сюда
load_dotenv()

NOTION_TOKEN = os.getenv("NOTION_TOKEN")
if not NOTION_TOKEN:
    raise ValueError("Ошибка: нету NOTION_TOKEN")
PAGE_ID = "376c21eeae7880f5bbbff2b2c2c2ff85"

FILE_PATH = "notes.md" 

notion = Client(auth=NOTION_TOKEN)

def parse_text_to_rich_text(text):
    """Токенизатор: чисто режет строку на текст, формулы и жирный шрифт"""
    tokens = re.split(r'(\$\$.*?\$\$|\$.*?\$|\*\*.*?\*\*)', text)
    rich_text = []
    
    for token in tokens:
        if not token:
            continue
            
        if token.startswith('$') and token.endswith('$'):
            if token.startswith('$$') and token.endswith('$$') and len(token) > 4:
                formula = token[2:-2].strip()
            else:
                formula = token[1:-1].strip()
                
            if formula:
                rich_text.append({
                    "type": "equation",
                    "equation": {"expression": formula}
                })
            continue
            
        if token.startswith('**') and token.endswith('**') and len(token) > 4:
            bold_content = token[2:-2]
            if bold_content:
                rich_text.append({
                    "type": "text",
                    "text": {"content": bold_content},
                    "annotations": {"bold": True}
                })
            continue
            
        rich_text.append({
            "type": "text",
            "text": {"content": token}
        })
        
    return rich_text

def upload_content():
    if not os.path.exists(FILE_PATH):
        print(f"Ошибка: Файл '{FILE_PATH}' не найден!")
        return

    print(f"Читаю файл {FILE_PATH}...")
    with open(FILE_PATH, "r", encoding="utf-8") as f:
        raw_text = f.read()

    # Точечно чиним всратую строчку Клода в определении, убирая "shadow" и "еслидлялюбогох"
    raw_text = raw_text.replace("shadow", "")
    raw_text = raw_text.replace(
        r"F(x, y) = \mathbf{0}_m, еслидлялюбогох \in X$",
        r"$F(x, y) = \mathbf{0}_m$, если для любого $x \in X$"
    )

    lines = raw_text.split('\n')
    blocks = []
    
    in_display_formula = False
    current_formula_lines = []
    
    for line in lines:
        clean_line = line.strip()
        
        # Если строка пустая — это явный маркер конца абзаца
        if not clean_line:
            # Добавим пустой блок для визуального отступа, если прошлый блок не был пустым
            if blocks and blocks[-1]["type"] != "paragraph" or (blocks and blocks[-1]["paragraph"]["rich_text"]):
                blocks.append({
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {"rich_text": []}
                })
            continue

        # Обработка многострочных формул $$
        if clean_line.startswith('$$') and clean_line.endswith('$$') and len(clean_line) > 4:
            formula = clean_line[2:-2].strip()
            if formula:
                blocks.append({"object": "block", "type": "equation", "equation": {"expression": formula}})
            continue
            
        if clean_line.startswith('$$') and not in_display_formula:
            in_display_formula = True
            current_formula_lines.append(clean_line[2:])
            continue
            
        if clean_line.endswith('$$') and in_display_formula:
            in_display_formula = False
            current_formula_lines.append(clean_line[:-2])
            full_formula = "\n".join(current_formula_lines).strip()
            if full_formula:
                blocks.append({"object": "block", "type": "equation", "equation": {"expression": full_formula}})
            current_formula_lines = []
            continue
            
        if in_display_formula:
            current_formula_lines.append(clean_line)
            continue

        # Определяем тип текущей строки
        if clean_line.startswith('# '):
            blocks.append({
                "object": "block",
                "type": "heading_1",
                "heading_1": {"rich_text": parse_text_to_rich_text(clean_line[2:].strip())}
            })
        elif clean_line.startswith('## '):
            blocks.append({
                "object": "block",
                "type": "heading_2",
                "heading_2": {"rich_text": parse_text_to_rich_text(clean_line[3:].strip())}
            })
        elif clean_line.startswith('### '):
            blocks.append({
                "object": "block",
                "type": "heading_3",
                "heading_3": {"rich_text": parse_text_to_rich_text(clean_line[4:].strip())}
            })
        elif clean_line.startswith('* '):
            blocks.append({
                "object": "block",
                "type": "bulleted_list_item",
                "bulleted_list_item": {"rich_text": parse_text_to_rich_text(clean_line[2:].strip())}
            })
        elif clean_line.startswith('1. ') or clean_line.startswith('2. '):
            # Бонус: поддержка нумерованных списков
            blocks.append({
                "object": "block",
                "type": "numbered_list_item",
                "numbered_list_item": {"rich_text": parse_text_to_rich_text(clean_line[3:].strip())}
            })
        else:
            # ЭТО ОБЫЧНЫЙ ТЕКСТ
            # Умная склейка: если предыдущий блок ТОЖЕ был обычным параграфом (и не пустым), 
            # мы дописываем текст туда, а не плодим новые блоки ("колбасу")
            current_rich_text = parse_text_to_rich_text(clean_line)
            
            if blocks and blocks[-1]["type"] == "paragraph" and blocks[-1]["paragraph"]["rich_text"]:
                # Добавляем пробел между склеиваемыми строками
                blocks[-1]["paragraph"]["rich_text"].append({"type": "text", "text": {"content": " "}})
                blocks[-1]["paragraph"]["rich_text"].extend(current_rich_text)
            else:
                blocks.append({
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {"rich_text": current_rich_text}
                })

    # Очищаем пустые параграфы в самом конце, если они остались
    blocks = [b for b in blocks if not (b["type"] == "paragraph" and not b["paragraph"]["rich_text"])]

    if blocks:
        print(f"Отправляю {len(blocks)} блоков в Notion...")
        for i in range(0, len(blocks), 50):
            notion.blocks.children.append(block_id=PAGE_ID, children=blocks[i:i+50])
        print("Заебись! Теперь всё идеально: списки отдельно, абзацы склеены, формулы рендерятся.")
    else:
        print("Нечего отправлять.")

if __name__ == "__main__":
    upload_content()



