# -*- coding: utf-8 -*-
"""분리 전화번호 입력 필드 마스킹 결과 이미지 생성"""
import sys, os
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from masking_core import run_ocr, detect_personal_info, apply_mask
from PIL import Image, ImageDraw

TEST_IMAGE = 'test_split_phone.png'
result = run_ocr(TEST_IMAGE)
mask_boxes, label_boxes = detect_personal_info(result)

# 노란 강조 + 마스킹 이미지 생성
original = Image.open(TEST_IMAGE).convert("RGBA")
overlay = Image.new("RGBA", original.size, (0, 0, 0, 0))
draw_ov = ImageDraw.Draw(overlay)
for box in label_boxes:
    x, y, w, h = box['x'], box['y'], box['width'], box['height']
    draw_ov.rectangle([x, y, x+w-1, y+h-1], fill=(255, 215, 0, 110), outline=(255, 165, 0, 240), width=2)

highlighted = Image.alpha_composite(original, overlay).convert("RGB")
masked = apply_mask(highlighted, mask_boxes, mask_type="black")
masked.save('test_split_phone_result.png')
print(f"결과 저장 완료: {len(mask_boxes)}개 마스킹, {len(label_boxes)}개 레이블 강조")
for i, r in enumerate(mask_boxes):
    print(f"  [{i+1}] x={r['x']}, y={r['y']}, w={r['width']}, h={r['height']}")
