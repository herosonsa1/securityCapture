# -*- coding: utf-8 -*-
"""
개선된 마스킹 기능 단위 테스트 스크립트
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from masking_core import (
    detect_layout_based_info_and_indices,
    detect_personal_info,
    is_likely_korean_name,
    BIRTH_PATTERN,
    PHONE_PATTERN,
    RRN_PATTERN,
    PASSPORT_PATTERN,
)

print("=" * 60)
print("1. 생년월일/주민번호/이름/전화번호 레이아웃 기반 탐지 테스트")
print("=" * 60)

words_test = [
    {'text': '생년월일', 'x': 10, 'y': 50, 'width': 80, 'height': 20},
    {'text': '1990.07.22', 'x': 120, 'y': 52, 'width': 100, 'height': 20},
    {'text': '주민등록번호', 'x': 10, 'y': 90, 'width': 120, 'height': 20},
    {'text': '900722-1234567', 'x': 160, 'y': 92, 'width': 140, 'height': 20},
    {'text': '성명', 'x': 10, 'y': 130, 'width': 40, 'height': 20},
    {'text': '홍길동', 'x': 80, 'y': 132, 'width': 60, 'height': 20},
    {'text': '전화번호', 'x': 10, 'y': 170, 'width': 80, 'height': 20},
    {'text': '010-1234-5678', 'x': 120, 'y': 172, 'width': 130, 'height': 20},
    {'text': '주소', 'x': 10, 'y': 210, 'width': 40, 'height': 20},
    {'text': '서울시', 'x': 80, 'y': 212, 'width': 50, 'height': 20},
    {'text': '강남구', 'x': 140, 'y': 212, 'width': 50, 'height': 20},
    {'text': '역삼동', 'x': 200, 'y': 212, 'width': 50, 'height': 20},
    {'text': '123-45', 'x': 260, 'y': 212, 'width': 60, 'height': 20},
]

mask_regions, used_indices, label_regions = detect_layout_based_info_and_indices(words_test)
print(f"마스킹 영역 수: {len(mask_regions)}")
print(f"레이블 강조 영역 수: {len(label_regions)}")
for r in label_regions:
    print(f"  레이블 박스: x={r['x']}, y={r['y']}, w={r['width']}, h={r['height']}")

print()
print("=" * 60)
print("2. 다중 단어 레이블 합산 테스트 ('주민 등록 번호' 분리 인식)")
print("=" * 60)
words_multi = [
    {'text': '주민', 'x': 10, 'y': 50, 'width': 30, 'height': 20},
    {'text': '등록', 'x': 45, 'y': 50, 'width': 30, 'height': 20},
    {'text': '번호', 'x': 80, 'y': 50, 'width': 30, 'height': 20},
    {'text': '900722-1234567', 'x': 140, 'y': 52, 'width': 140, 'height': 20},
]
_, _, label_regions2 = detect_layout_based_info_and_indices(words_multi)
print(f"레이블 영역 수: {len(label_regions2)}")
for r in label_regions2:
    print(f"  합산 레이블 박스: x={r['x']}, y={r['y']}, w={r['width']}, h={r['height']}")
print("  (기대값: x=10, 전체 '주민 등록 번호' 폭 약 100px)")

print()
print("=" * 60)
print("3. 생년월일 패턴 오탐/정탐 검증")
print("=" * 60)
test_dates = [
    ('1990.07.22', True),
    ('1979-07-22', True),
    ('90.07.22', True),
    ('3.5.2', False),       # 버전번호 - 오탐 방지
    ('13.5.2', False),      # 버전번호 - 오탐 방지
    ('2024-13-01', False),  # 월 범위 초과 - 오탐 방지
    ('2024-01-32', False),  # 일 범위 초과 - 오탐 방지
    ('20240722', False),    # 구분자 없음 (주민번호 스타일)
    ('1990/07/22', True),
]
all_passed = True
for date_str, expected in test_dates:
    m = bool(BIRTH_PATTERN.search(date_str))
    status = "OK" if m == expected else "FAIL"
    if status == "FAIL":
        all_passed = False
    print(f"  [{status}] '{date_str}' => 매치={m} (기대={expected})")
print(f"  => 생년월일 패턴 테스트 {'전체 통과' if all_passed else '일부 실패'}")

print()
print("=" * 60)
print("4. 이름 탐지 정확도 검증")
print("=" * 60)
name_tests = [
    ('홍길동', True),
    ('김선기', True),
    ('이름', False),
    ('조회', False),
    ('허준', True),
    ('사용자', False),
    ('박민수', True),
    ('수정', False),
    ('안내', False),
    ('이현우', True),
]
all_names_ok = True
for name, expected in name_tests:
    result = is_likely_korean_name(name)
    status = "OK" if result == expected else "FAIL"
    if status == "FAIL":
        all_names_ok = False
    print(f"  [{status}] '{name}' => 이름={result} (기대={expected})")
print(f"  => 이름 탐지 테스트 {'전체 통과' if all_names_ok else '일부 실패'}")

print()
print("=" * 60)
print("5. 주민번호 패턴 테스트")
print("=" * 60)
rrn_tests = [
    ('900722-1234567', True),
    ('19900722-1234567', True),
    ('900722-9234567', False),  # 성별코드 9는 무효
    ('900722-1234567', True),
    ('12345-1234567', False),   # 앞자리 5자리 (정상 아님)
]
for rrn, expected in rrn_tests:
    m = bool(RRN_PATTERN.search(rrn))
    status = "OK" if m == expected else "FAIL"
    print(f"  [{status}] '{rrn}' => 매치={m} (기대={expected})")

print()
print("=" * 60)
print("6. 여권번호 패턴 테스트")
print("=" * 60)
passport_tests = [
    ('M12345678', True),
    ('AB1234567', True),
    ('M1234567A', True),
    ('R87654321', True),
    ('12345678', False),  # 영문 없음
]
for pp, expected in passport_tests:
    m = bool(PASSPORT_PATTERN.search(pp))
    status = "OK" if m == expected else "FAIL"
    print(f"  [{status}] '{pp}' => 매치={m} (기대={expected})")

print()
print("모든 테스트 완료.")
