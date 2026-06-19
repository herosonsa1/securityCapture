import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import re
from masking_core import (
    BIRTH_PATTERN, RRN_PATTERN, PHONE_PATTERN, 
    CARD_PATTERN, BANK_PATTERN, VEHICLE_PATTERN, DISEASE_PATTERN,
    verify_rrn_checksum
)

def test_pattern(pattern, name, cases):
    print(f'=== {name} 패턴 테스트 ===')
    success_count = 0
    for text, expected in cases:
        # 대괄호 제거 정규화 시뮬레이션
        norm_text = re.sub(r'[\[\]]', '', text)
        # 띄어쓰기가 있는 경우도 제거한 버전과 제거 안 한 버전 둘 다 매칭 시도 (실제 코드와 유사하게)
        norm_text_no_space = re.sub(r'\s+', '', norm_text)
        matched = bool(pattern.search(norm_text) or pattern.search(norm_text_no_space))
        status = 'OK' if matched == expected else 'FAIL'
        if status == 'OK':
            success_count += 1
        print(f'  {status}: "{text}" -> matched={matched} (expected={expected})')
    print(f'결과: {success_count}/{len(cases)} 성공')
    print()

# 1. 주민등록번호
rrn_cases = [
    ('950101-1234567', True),
    ('19790722-1234567', True),
    ('9501011234567', True),       # 하이픈 없음
    ('197907221234567', True),     # 하이픈 없음
    ('[950101]-[1234567]', True),  # 대괄호 포함
    ('[950101] - [1234567]', True),# 대괄호 + 공백
    ('1234567-1234567', False),    # 앞자리 유효하지 않음
    ('950132-1234567', False),     # 32일 (유효하지 않은 날짜)
]

# 2. 휴대전화번호
phone_cases = [
    ('010-1234-5678', True),
    ('01012345678', True),         # 하이픈 없음
    ('[010]-[1234]-[5678]', True), # 대괄호 포함
    ('[010] [1234] [5678]', True), # 대괄호 + 공백
    ('02-123-4567', True),         # 유선전화번호 (기존 호환성)
    ('010-123-4567', True),
    ('0101234567', True),
]

# 3. 신용카드 번호
card_cases = [
    ('1234-5678-1234-5678', True),
    ('1234567812345678', True),    # 하이픈 없음
    ('1234 5678 1234 5678', True),  # 공백 구분
    ('[1234]-[5678]-[1234]-[5678]', True),
]

# 4. 계좌번호
bank_cases = [
    ('110-123-456789', True),
    ('110123456789', True),        # 하이픈 없음 (고도화 핵심)
    ('123-4567-8901-23', True),    # 다양한 포맷
    ('[110]-[123]-[456789]', True),
    ('12345', False),              # 너무 짧은 숫자
]

# 5. 차량번호
vehicle_cases = [
    ('12가1234', True),
    ('123가1234', True),
    ('서울12가1234', True),
    ('서울 12 가 1234', True),
    ('12나3456', True),
    ('12하3456', True),            # 렌터카
    ('123합4567', True),           # 확장된 한글 범위 ('합'도 매칭)
    ('12가345', False),            # 뒷자리 3자리 (차량번호 아님)
]

# 6. 질병분류기호
disease_cases = [
    ('J01', True),
    ('A09.0', True),
    ('Z99.99', True),
    ('C12', True),
    ('K21.0', True),
    ('ABC', False),
    ('123', False),
]

test_pattern(RRN_PATTERN, "주민등록번호", rrn_cases)
test_pattern(PHONE_PATTERN, "휴대전화번호", phone_cases)
test_pattern(CARD_PATTERN, "신용카드 번호", card_cases)
test_pattern(BANK_PATTERN, "계좌번호", bank_cases)
test_pattern(VEHICLE_PATTERN, "차량번호", vehicle_cases)
test_pattern(DISEASE_PATTERN, "질병분류기호", disease_cases)

print("모든 테스트 스크립트 실행 완료")
