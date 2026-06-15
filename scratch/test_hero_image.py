# -*- coding: utf-8 -*-
"""
첨부된 실제 이미지(HERO Biz Platform 캡처)로 OCR + 마스킹 탐지 전체 파이프라인 테스트
결과 이미지(노란 강조 + 마스킹)를 저장하여 시각적으로 확인
"""
import sys, os
sys.stdout.reconfigure(encoding='utf-8')

# 프로젝트 루트에서 실행한다고 가정
from masking_core import run_ocr, detect_personal_info, apply_mask
from PIL import Image, ImageDraw

# ── 설정 ──────────────────────────────────────────────────────────────────
TEST_IMAGE = "test_hero_input.png"       # 사용자 제공 이미지 경로
OUT_HIGHLIGHTED = "test_hero_highlighted.png"   # 노란 강조 결과
OUT_MASKED_BLACK = "test_hero_masked_black.png"  # 블랙박스 마스킹
OUT_MASKED_MOSAIC = "test_hero_masked_mosaic.png" # 모자이크 마스킹

if not os.path.exists(TEST_IMAGE):
    print(f"[오류] 테스트 이미지가 없습니다: {TEST_IMAGE}")
    sys.exit(1)

print("=" * 70)
print(f"테스트 이미지: {TEST_IMAGE}")
print("=" * 70)

# ── 1. OCR 실행 ───────────────────────────────────────────────────────────
print("\n[1단계] OCR 인식 중...")
result = run_ocr(TEST_IMAGE)
print(f"OCR 상태: {result.get('status')}")

words = result.get('words', [])
print(f"인식된 단어 수: {len(words)}")
print("\n인식된 단어 목록:")
for w in words:
    print(f"  [{w['text']}]  x={w['x']}, y={w['y']}, w={w['width']}, h={w['height']}")

# ── 2. 개인정보 탐지 ──────────────────────────────────────────────────────
print("\n[2단계] 개인정보 탐지 중...")
mask_boxes, label_boxes = detect_personal_info(result, name_mask_style="middle")
print(f"\n마스킹 영역: {len(mask_boxes)}개")
for i, r in enumerate(mask_boxes):
    print(f"  [{i+1}] x={r['x']}, y={r['y']}, w={r['width']}, h={r['height']}")

print(f"\n레이블 강조 영역: {len(label_boxes)}개")
for i, r in enumerate(label_boxes):
    print(f"  [{i+1}] x={r['x']}, y={r['y']}, w={r['width']}, h={r['height']}")

# ── 3. 노란색 강조 + 마스킹 이미지 생성 ─────────────────────────────────
print("\n[3단계] 결과 이미지 생성 중...")
original = Image.open(TEST_IMAGE)

# 노란 강조 오버레이
base_rgba = original.copy().convert("RGBA")
overlay = Image.new("RGBA", base_rgba.size, (0, 0, 0, 0))
draw_ov = ImageDraw.Draw(overlay)

for box in label_boxes:
    x, y, w, h = box['x'], box['y'], box['width'], box['height']
    draw_ov.rectangle(
        [x, y, x + w - 1, y + h - 1],
        fill=(255, 215, 0, 110),      # 황금빛 반투명
        outline=(255, 165, 0, 240),   # 주황빛 테두리
        width=2
    )

highlighted = Image.alpha_composite(base_rgba, overlay).convert("RGB")
highlighted.save(OUT_HIGHLIGHTED)
print(f"  → 노란 강조 이미지 저장: {OUT_HIGHLIGHTED}")

# 블랙박스 마스킹
masked_black = apply_mask(highlighted, mask_boxes, mask_type="black")
masked_black.save(OUT_MASKED_BLACK)
print(f"  → 블랙박스 마스킹 이미지 저장: {OUT_MASKED_BLACK}")

# 모자이크 마스킹
masked_mosaic = apply_mask(highlighted, mask_boxes, mask_type="mosaic", mosaic_size=10)
masked_mosaic.save(OUT_MASKED_MOSAIC)
print(f"  → 모자이크 마스킹 이미지 저장: {OUT_MASKED_MOSAIC}")

print("\n[완료] 모든 테스트 결과 이미지가 생성되었습니다.")
