# -*- coding: utf-8 -*-
import sys, os
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from masking_core import run_ocr
import json

img_path = r"C:\Users\Herosonsa\.gemini\antigravity-ide\brain\829cf393-9a0a-40a4-b7e7-8c5b2a02b8bb\media__1781574143570.png"
result = run_ocr(img_path)
print(json.dumps(result, ensure_ascii=False, indent=2))
