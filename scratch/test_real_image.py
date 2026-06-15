# -*- coding: utf-8 -*-
"""실제 테스트 이미지로 OCR + 개인정보 탐지 검증"""
import sys, os
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from masking_core import run_ocr, detect_personal_info

result = run_ocr('test_target.png')
print('OCR 상태:', result.get('status'))
words = result.get('words', [])
print('인식된 단어 수:', len(words))
for w in words[:20]:
    txt = w['text']
    print(f'  [{txt}] x={w["x"]}, y={w["y"]}')

print()
mask_boxes, label_boxes = detect_personal_info(result)
print('마스킹 영역 수:', len(mask_boxes))
print('레이블 강조 영역 수:', len(label_boxes))
for lb in label_boxes:
    print(f'  레이블박스: x={lb["x"]}, y={lb["y"]}, w={lb["width"]}, h={lb["height"]}')
