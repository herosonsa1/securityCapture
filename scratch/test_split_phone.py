# -*- coding: utf-8 -*-
"""분리된 전화번호 입력 필드 OCR 테스트"""
import sys, os
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from masking_core import run_ocr, detect_personal_info

result = run_ocr('test_split_phone.png')
print('OCR 상태:', result.get('status'))
words = result.get('words', [])
print('인식된 단어 수:', len(words))

# 전화번호 관련 단어만 필터링해서 출력
phone_related = [w for w in words if any(
    kw in w['text'] for kw in ['010', '011', '016', '017', '018', '019', '-', '번호', '휴대', '전화', '폰']
) or (w['text'].strip().isdigit() and 3 <= len(w['text'].strip()) <= 4)]

print('\n전화번호 관련 단어:')
for w in sorted(phone_related, key=lambda x: (x['y'], x['x'])):
    print(f"  [{w['text']}]  x={w['x']}, y={w['y']}, w={w['width']}, h={w['height']}")

print('\n전체 단어 (Y=100~150 범위):')
for w in sorted([w for w in words if 80 <= w['y'] <= 160], key=lambda x: x['x']):
    print(f"  [{w['text']}]  x={w['x']}, y={w['y']}, w={w['width']}, h={w['height']}")

print()
mask_boxes, label_boxes = detect_personal_info(result)
print(f'마스킹 영역: {len(mask_boxes)}개')
for i, r in enumerate(mask_boxes):
    print(f'  [{i+1}] x={r["x"]}, y={r["y"]}, w={r["width"]}, h={r["height"]}')
print(f'레이블 강조: {len(label_boxes)}개')
