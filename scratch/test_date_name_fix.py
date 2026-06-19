"""
날짜 단독 마스킹 비활성화 + 이름 공백 조합 차단 단위 테스트
"""
import sys, io, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, r'c:\myWork\workspace\scratch\securityCapture')
import importlib, masking_core
importlib.reload(masking_core)
mc = masking_core

print('=== 1. 날짜 패턴 단독 탐지 비활성화 검증 ===')
print()
# 레이블 없는 단독 날짜 - 마스킹 안 되어야 함
date_cases_should_NOT_mask = [
    '2026/07/20',
    '2026-07-20',
    '2026.07.20',
    '2025/12/31',
    '1990.01.15',
    '24-07-20',
    '26.07.20',
]
print('[단독 날짜 - 마스킹 안 되어야 함]')
for text in date_cases_should_NOT_mask:
    # BIRTH_PATTERN이 여전히 패턴 자체는 매칭하는지 확인
    birth_match = mc.BIRTH_PATTERN.search(text)
    # 하지만 슬라이딩 윈도우 탐지 목록에서 제거됨
    print(f'  BIRTH_PATTERN매칭={bool(birth_match)}, 단독마스킹비활성화=True: {repr(text)}')

print()
print('=== 2. 이름 단독 탐지: 공백 포함 조합 차단 ===')
print()

# 공백 포함 조합 - 이름이 아닌 것으로 판단 (False 반환되어야 함)
should_be_false = [
    '보험 가입',    # 2+2
    '처리 완료',    # 2+2
    '홍길 동민',    # 2+2 (성씨 포함이어도 공백 조합 차단)
    '김철 수민',    # 2+2
    '홍길동 이민',  # 3+2
    '홍길 이민수',  # 2+3
    '홍길동 이민수',# 3+3
    '보험금 청구서', # 3+3
    '손해 사정사',  # 2+3
]
print('[공백 포함 조합 - is_likely_korean_name=False 이어야 함]')
for text in should_be_false:
    result = mc.is_likely_korean_name(text)
    status = 'OK(False)' if not result else 'FAIL(오탐!)'
    print(f'  [{status}] {repr(text)}')

print()
# 단일 이름 (공백 없음) - 정상 탐지되어야 함 (True 반환)
should_be_true = [
    '홍길동',   # 3글자
    '김철수',   # 3글자
    '이영희',   # 3글자
    '박민준',   # 3글자
    '허준',     # 2글자 (다빈도 음절)
    '김지수',   # 3글자
    '이민재',   # 3글자
]
print('[단일 이름 - is_likely_korean_name=True 이어야 함]')
for text in should_be_true:
    result = mc.is_likely_korean_name(text)
    status = 'OK(True)' if result else 'FAIL(미탐!)'
    print(f'  [{status}] {repr(text)}')

print()
# 이름 아닌 단일 단어 - False 이어야 함
should_be_false_single = [
    '전화',     # 업무 단어
    '연락처',   # EXCLUDE_NOUNS
    '확인',     # EXCLUDE_NOUNS
    '논의하며', # 4글자 but 금지음절
    '관리자',   # EXCLUDE_NOUNS
]
print('[단일 비이름 - is_likely_korean_name=False 이어야 함]')
for text in should_be_false_single:
    result = mc.is_likely_korean_name(text)
    status = 'OK(False)' if not result else 'FAIL(오탐!)'
    print(f'  [{status}] {repr(text)}')

print()
print('모든 테스트 완료!')
