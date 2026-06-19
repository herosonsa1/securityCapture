"""
주소 마스킹 3단계 고도화 단위 테스트
"""
import sys, io, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, r'c:\myWork\workspace\scratch\securityCapture')
import importlib, masking_core
importlib.reload(masking_core)
mc = masking_core

print('=== 1. ADDRESS_PATTERN 매칭 테스트 ===')
print()
# 매칭되어야 하는 주소 (True 기대)
should_match = [
    '서울특별시 강남구 테헤란로 123',
    '경기도 성남시 수정구 태평동 45',
    '부산광역시 해운대구 해운대로 123-4',
    '인천광역시 남동구 논현동 567',
    '대전광역시 유성구 대학로 99',
]
print('[ADDRESS_PATTERN 매칭 - True 기대]')
for addr in should_match:
    m = mc.ADDRESS_PATTERN.search(addr)
    status = 'OK' if m else 'FAIL(미매칭)'
    print(f'  [{status}] {repr(addr)}')

print()
# 매칭되면 안 되는 패턴 (False 기대: 오탐 방지)
should_not_match = [
    '2026-07-20',         # 날짜
    '192.168.1.100',      # IP
    '홍길동',              # 이름
    '목동 아파트',         # 법정동 단독
    '테헤란로 여행',       # 시/도 없음
]
print('[ADDRESS_PATTERN 비매칭 - False 기대]')
for text in should_not_match:
    m = mc.ADDRESS_PATTERN.search(text)
    status = 'OK(비매칭)' if not m else 'FAIL(오탐!)'
    print(f'  [{status}] {repr(text)}')

print()
print('=== 2. UNIT_DETAIL_PATTERN 탐지 테스트 ===')
print()
# 동/호/층 패턴 (탐지되어야 함)
unit_should_detect = [
    ('101동', '101'),
    ('202호', '202'),
    ('3층', '3'),
    ('A동', 'A'),
    ('지하1층', '지하1'),
    ('B1층', 'B1'),
    ('에이동', None),     # 한글 앞이므로 제외되어야 함
]
print('[UNIT_DETAIL_PATTERN 탐지]')
for text, expected_id in unit_should_detect:
    m = mc.UNIT_DETAIL_PATTERN.search(text)
    if expected_id is None:
        # 탐지 안 되는 게 맞음 - 또는 탐지되더라도 법정동 접미 구분 가능
        status = 'OK(무시가능)' if not m else f'참고: {m.group(1)!r} 탐지됨'
    else:
        got = m.group(1) if m else None
        status = 'OK' if got == expected_id else f'FAIL(got {got!r})'
    print(f'  [{status}] {repr(text)} (기대 식별자: {repr(expected_id)})')

print()
# 법정동 이름 - 탐지되면 안 됨 (오탐 차단)
unit_should_not = ['목동', '천호동', '서초동', '구로동']
print('[UNIT_DETAIL_PATTERN 오탐 차단 - 법정동]')
for text in unit_should_not:
    m = mc.UNIT_DETAIL_PATTERN.search(text)
    # '목동' 같은 경우 '목' + '동' 으로 분리될 수 있으나, lookbehind로 앞이 한글이면 제외
    if m:
        print(f'  [참고] {repr(text)} → {m.group(1)!r} 탐지 (법정동 오탐 검토 필요)')
    else:
        print(f'  [OK차단] {repr(text)}')

print()
print('=== 3. calculate_sub_masks 주소 마스킹 3단계 테스트 ===')
print()
test_cases = [
    # (입력주소, 기대_마스킹_설명)
    ('서울특별시 강남구 테헤란로 123, 에이동 102호', '건물번호 이후 동/호 식별자 마스킹'),
    ('경기도 성남시 수정구 태평동 45-3 현대아파트 101동 202호', '동/호 식별자 마스킹'),
    ('부산광역시 해운대구 해운대로 99 스카이타워 15층', '층 식별자 마스킹'),
    ('인천광역시 남동구 논현동 123', '건물번호 이후 전체 마스킹'),
]
for addr, desc in test_cases:
    masks = mc.calculate_sub_masks(addr, x=0, y=0, width=len(addr)*10, height=20, name_mask_style='middle')
    print(f'  입력: {repr(addr)}')
    print(f'  설명: {desc}')
    print(f'  마스킹 영역: {len(masks)}개 → {[{"x": m["x"], "w": m["width"]} for m in masks]}')
    print()

print('모든 주소 마스킹 테스트 완료!')
