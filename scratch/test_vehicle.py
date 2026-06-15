# -*- coding: utf-8 -*-
"""차량번호 패턴 및 마스킹 로직 검증"""
import sys
sys.stdout.reconfigure(encoding='utf-8')
import os; os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from masking_core import VEHICLE_PATTERN, calculate_sub_masks

test_cases = [
    ('12가1234',        True,  '신형 2자리'),
    ('123나5678',       True,  '신형 3자리'),
    ('서울12가1234',    True,  '구형 지역명'),
    ('경기12가1234',    True,  '구형 공백 없이'),
    ('34다5678',        True,  '2자리+한글+4자리'),
    ('010-1234-5678',  False, '전화번호 (오탐X)'),
    ('950101-1234567', False, '주민번호 (오탐X)'),
    ('1234567',        False, '단순 숫자 (오탐X)'),
]

ok = True
print('=== 차량번호 패턴 탐지 테스트 ===')
for text, expected, desc in test_cases:
    m = VEHICLE_PATTERN.search(text)
    matched = m is not None
    if matched:
        sub = calculate_sub_masks(text, 0, 0, len(text)*10, 20)
        result = f'매치: "{m.group()}", 마스킹: {len(sub)}개'
    else:
        sub = []
        result = '미매칭'
    
    status = 'OK' if matched == expected else 'FAIL'
    if status == 'FAIL':
        ok = False
    print(f'  [{status}] {desc}: [{text}] -> {result}')

print()
print('전체 결과:', 'PASS' if ok else 'FAIL')
