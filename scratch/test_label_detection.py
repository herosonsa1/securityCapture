# -*- coding: utf-8 -*-
"""
masking_core 임포트 및 detect_personal_info 반환값 구조 검증 스크립트
"""
import sys
sys.path.insert(0, r"c:\myWork\workspace\scratch\securityCapture")

from masking_core import detect_personal_info

# OCR 결과 모의 데이터: 테이블 형태 레이아웃 (레이블 왼쪽, 값 오른쪽)
fake_ocr = {
    "status": "success",
    "words": [
        # 행 1: 성명 | 홍길동
        {"text": "성명", "x": 50, "y": 30, "width": 60, "height": 20},
        {"text": "홍길동", "x": 200, "y": 30, "width": 70, "height": 20},
        # 행 2: 주민등록번호 | 950101-1234567
        {"text": "주민등록번호", "x": 50, "y": 60, "width": 100, "height": 20},
        {"text": "950101-1234567", "x": 200, "y": 60, "width": 130, "height": 20},
        # 행 3: 전화번호 | 010-1234-5678
        {"text": "전화번호", "x": 50, "y": 90, "width": 80, "height": 20},
        {"text": "010-1234-5678", "x": 200, "y": 90, "width": 120, "height": 20},
        # 행 4: 주소 | 경기도 성남시 수정구 태평동 123
        {"text": "주소", "x": 50, "y": 120, "width": 40, "height": 20},
        {"text": "경기도", "x": 200, "y": 120, "width": 60, "height": 20},
        {"text": "성남시", "x": 270, "y": 120, "width": 60, "height": 20},
    ]
}

mask_regions, label_regions = detect_personal_info(fake_ocr, "middle")

print("[mask_regions - 실제 값 마스킹 영역]")
for r in mask_regions:
    print(f"  x={r['x']}, y={r['y']}, w={r['width']}, h={r['height']}")

print("")
print("[label_regions - 항목명 레이블 강조 영역]")
for r in label_regions:
    print(f"  x={r['x']}, y={r['y']}, w={r['width']}, h={r['height']}")

print("")
print(f"반환 타입: mask={type(mask_regions).__name__}({len(mask_regions)}개), label={type(label_regions).__name__}({len(label_regions)}개)")
print(">>> 검증 완료")
