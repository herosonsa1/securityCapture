# -*- coding: utf-8 -*-
"""생년월일 패턴 정확도 테스트"""
import re

# 개선된 BIRTH_PATTERN (masking_core.py와 동일)
BIRTH_PATTERN = re.compile(
    r'\b(?:(19|20)\d{2}|\d{2})'
    r'[-./]'
    r'(0[1-9]|1[0-2])'
    r'[-./]'
    r'(0[1-9]|[12]\d|3[01])\b'
)

# 정상 케이스 (감지되어야 함)
ok_cases = ['1979-07-22', '1979.07.22', '79/07/22', '2001-01-01', '95-06-15', '2023-12-31']
# 오탐 케이스 (감지되면 안 됨)
bad_cases = ['3.5.2', '13.5.2', '1.2.3', '2023.13.01', '2023.01.32', '192.168.1.1']

print("=== 정상 케이스 (감지 O) ===")
for t in ok_cases:
    m = BIRTH_PATTERN.search(t)
    mark = "OK 감지됨" if m else "누락(문제!)"
    print(f"  {t}: {mark}")

print("")
print("=== 오탐 케이스 (감지 X) ===")
for t in bad_cases:
    m = BIRTH_PATTERN.search(t)
    mark = "오탐(문제!)" if m else "OK 미감지"
    print(f"  {t}: {mark}")

# RRN 패턴 테스트
print("")
print("=== RRN 패턴 테스트 ===")
RRN_PATTERN = re.compile(r'\b(\d{6}|\d{8})-[1-8]\d{6}\b')
rrn_cases = [
    ('950101-1234567', True),
    ('19790722-1234567', True),
    ('1234567-1234567', False),   # 7자리 앞자리 - 불허
    ('123456-1234567', True),     # 6자리 - 허용
    ('12345-1234567', False),     # 5자리 - 불허
]
for text, should_match in rrn_cases:
    m = bool(RRN_PATTERN.search(text))
    result = "OK" if m == should_match else "오류(문제!)"
    expected = "감지O" if should_match else "감지X"
    print(f"  {text}: {result} (예상:{expected}, 실제:{'감지O' if m else '감지X'})")
