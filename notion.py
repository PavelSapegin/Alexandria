import os
import re
from notion_client import Client
from dotenv import load_dotenv

load_dotenv()

# Configuration setup
NOTION_TOKEN = os.getenv("NOTION_TOKEN")
if not NOTION_TOKEN:
    raise ValueError("Error: NOTION_TOKEN is missing from environment variables.")

# Fallback values if not specified in .env
PAGE_ID = os.getenv("NOTION_PAGE_ID", "page_id")
FILE_PATH = os.getenv("NOTION_FILE_PATH", "notes.md")

notion = Client(auth=NOTION_TOKEN)


def parse_text_to_rich_text(text):
    """
    Tokenizer: splits a string into text, equations, and bold styles
    for the Notion Rich Text structure.
    """
    tokens = re.split(r'(\$\$.*?\$\$|\$.*?\$|\*\*.*?\*\*)', text)
    rich_text = []
    
    for token in tokens:
        if not token:
            continue
            
        # Inline and block equation processing within text strings
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
            
        # Bold text processing
        if token.startswith('**') and token.endswith('**') and len(token) > 4:
            bold_content = token[2:-2]
            if bold_content:
                rich_text.append({
                    "type": "text",
                    "text": {"content": bold_content},
                    "annotations": {"bold": True}
                })
            continue
            
        # Plain text processing
        rich_text.append({
            "type": "text",
            "text": {"content": token}
        })
        
    return rich_text


def upload_content():
    if not os.path.exists(FILE_PATH):
        print(f"Error: File '{FILE_PATH}' not found!")
        return

    print(f"Reading file: {FILE_PATH}...")
    with open(FILE_PATH, "r", encoding="utf-8") as f:
        raw_text = f.read()

    # Pre-processing: patching legacy formatting or specific text edge cases
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
        
        # Empty line handling (paragraph boundaries)
        if not clean_line:
            # Append empty block for visual padding if the last block wasn't empty
            if blocks and (blocks[-1]["type"] != "paragraph" or blocks[-1]["paragraph"]["rich_text"]):
                blocks.append({
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {"rich_text": []}
                })
            continue

        # Multiline block equation processing ($$)
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

        # Block type parsing based on Markdown syntax
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
            # Support for numbered lists
            blocks.append({
                "object": "block",
                "type": "numbered_list_item",
                "numbered_list_item": {"rich_text": parse_text_to_rich_text(clean_line[3:].strip())}
            })
        else:
            # Standard paragraph handling with smart line joining
            current_rich_text = parse_text_to_rich_text(clean_line)
            
            # If the previous block is also a non-empty paragraph, append to it instead of making a new block
            if blocks and blocks[-1]["type"] == "paragraph" and blocks[-1]["paragraph"]["rich_text"]:
                blocks[-1]["paragraph"]["rich_text"].append({"type": "text", "text": {"content": " "}})
                blocks[-1]["paragraph"]["rich_text"].extend(current_rich_text)
            else:
                blocks.append({
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {"rich_text": current_rich_text}
                })

    # Clear dangling empty paragraphs at the end of the content structure
    blocks = [b for b in blocks if not (b["type"] == "paragraph" and not b["paragraph"]["rich_text"])]

    # Batch upload to Notion API (50 blocks per request limit)
    if blocks:
        print(f"Sending {len(blocks)} blocks to Notion...")
        for i in range(0, len(blocks), 50):
            notion.blocks.children.append(block_id=PAGE_ID, children=blocks[i:i+50])
        print("Success! Content successfully synchronized, paragraphs joined, and formulas rendered.")
    else:
        print("No content changes to upload.")


if __name__ == "__main__":
    upload_content()
