"""
앵커 키워드 기반 이름 탐지 단위 테스트
"""
import sys, io, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import importlib, masking_core
importlib.reload(masking_core)
mc = masking_core

print('=== 앵커 패턴 단위 테스트 ===')
print()
print('[선행 앵커 패턴 - 단일 단어 내]')
cases_leading = [
    ('성명:홍길동', '홍길동'),
    ('피보험자김철수', '김철수'),
    ('청구인:이영희', '이영희'),
    ('예금주박민준', '박민준'),
    ('환자명이수진', '이수진'),
]
for text, expected in cases_leading:
    m = mc.NAME_ANCHOR_LEADING_PATTERN.search(text)
    got = m.group(1) if m else None
    status = 'OK' if got == expected else 'FAIL'
    print(f'  [{status}] {repr(text)} -> {repr(got)} (기대: {repr(expected)})')

print()
print('[후행 앵커 패턴 - 단일 단어 내]')
cases_trailing = [
    ('홍길동님', '홍길동'),
    ('김철수씨', '김철수'),
    ('이영희귀하', '이영희'),
    ('박민준선생님', '박민준'),
]
for text, expected in cases_trailing:
    m = mc.NAME_ANCHOR_TRAILING_PATTERN.search(text)
    got = m.group(1) if m else None
    status = 'OK' if got == expected else 'FAIL'
    print(f'  [{status}] {repr(text)} -> {repr(got)} (기대: {repr(expected)})')

print()
print('[오탐 방지 - EXCLUDE_NOUNS 포함]')
cases_fp = ['관리자님', '시스템귀하', '담당자씨']
for text in cases_fp:
    m = mc.NAME_ANCHOR_TRAILING_PATTERN.search(text)
    if m:
        name = m.group(1)
        blocked = name in mc.EXCLUDE_NOUNS
        status = 'OK차단' if blocked else 'FAIL오탐'
        print(f'  [{status}] {repr(text)} -> 이름후보={repr(name)}, EXCLUDE_NOUNS={blocked}')
    else:
        print(f'  [OK미탐지] {repr(text)}')

print()
print('[선행 앵커 단어 패턴 - 인접 단어용]')
anchor_words = ['성명', '성명:', '피보험자', '환자명', '청구인']
for w in anchor_words:
    m = mc.NAME_LEADING_ANCHOR_WORD_PATTERN.match(w)
    result = 'OK앵커' if m else '미매칭'
    print(f'  [{result}]: {repr(w)}')

print()
print('[후행 앵커 단어 패턴 - 인접 단어용]')
trailing_words = ['님', '귀하', '씨', '선생님', '입니다', '홍길동']
for w in trailing_words:
    m = mc.NAME_TRAILING_ANCHOR_WORD_PATTERN.match(w)
    result = 'OK앵커' if m else '미매칭'
    print(f'  [{result}]: {repr(w)}')

print()
print('=== detect_name_by_anchor 통합 테스트 ===')

def make_words(word_list):
    """테스트용 OCR 단어 목록 생성"""
    words = []
    x_offset = 10
    for i, text in enumerate(word_list):
        words.append({
            'text': text,
            'x': x_offset,
            'y': 50,
            'width': len(text) * 12,
            'height': 20,
            '_idx': i
        })
        x_offset += len(text) * 12 + 5
    return words

test_cases = [
    # (단어목록, 기대 마스킹 이름)
    (['성명', '홍길동'], '홍길동'),
    (['피보험자', ':', '김철수'], '김철수'),
    (['환자명', '이수진'], '이수진'),
    (['홍길동', '님'], '홍길동'),
    (['박민준', '귀하'], '박민준'),
    (['청구인', '이영희', '님'], '이영희'),
    (['시스템', '님'], None),  # 오탐 방지
    (['관리자', '님'], None),  # 오탐 방지
]

for word_list, expected_name in test_cases:
    words = make_words(word_list)
    masks, used = mc.detect_name_by_anchor(words)
    found = len(masks) > 0
    if expected_name is None:
        status = 'OK(미탐지)' if not found else 'FAIL(오탐!)'
    else:
        status = 'OK' if found else 'FAIL(미탐!)'
    print(f'  [{status}] {word_list} -> 마스킹={len(masks)}개, used={used}')

print()
print('모든 앵커 이름 탐지 테스트 완료!')
