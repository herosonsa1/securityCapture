from masking_core import BIRTH_PATTERN, RRN_PATTERN, PHONE_PATTERN, verify_rrn_checksum

# 생년월일 패턴 검증 (오탐 방지)
tests = [
    ('1979-07-22', True),
    ('79/07/22', True),
    ('2001.03.15', True),
    ('3.5.2', False),   # 버전번호 - 오탐 아니어야 함
    ('13.5.2', False),  # 버전번호
    ('192.168.1.1', False),  # IP주소
]
print('=== 생년월일 패턴 테스트 ===')
for text, expected in tests:
    matched = bool(BIRTH_PATTERN.search(text))
    status = 'OK' if matched == expected else 'FAIL'
    print(f'  {status}: "{text}" -> matched={matched} (expected={expected})')

# 주민번호 패턴 검증
print()
print('=== 주민번호 패턴 테스트 ===')
rrn_tests = [
    ('950101-1234567', True),
    ('19790722-1234567', True),
    ('1234567-1234567', False),  # 7자리 앞자리 - 오탐 아니어야 함
]
for text, expected in rrn_tests:
    matched = bool(RRN_PATTERN.search(text))
    status = 'OK' if matched == expected else 'FAIL'
    print(f'  {status}: "{text}" -> matched={matched} (expected={expected})')

print()
print('모든 테스트 완료')
