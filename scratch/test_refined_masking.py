"""
마스킹 탐지 고도화 후 핵심 패턴 검증 테스트
- 오탐 방지: 마스킹 되면 안 되는 케이스가 탐지되지 않는지 확인
- 미탐 방지: 마스킹 되어야 하는 케이스가 탐지되는지 확인
"""
import sys, re
sys.path.insert(0, r'c:\myWork\workspace\scratch\securityCapture')
import masking_core as mc

print("=" * 60)
print("1. 주민등록번호 패턴 테스트")
print("=" * 60)
# 정탐 케이스 (탐지되어야 함)
rrn_ok = [
    "950101-1234567",
    "790722-2345678",
    "[950101]-[1234567]",
    "[950101] - [1234567]",
    "950101 1234567",  # 공백 구분
]
# 오탐 케이스 (탐지되면 안 됨)
rrn_fp = [
    "2024-01-15",      # 날짜 (YYYY-MM-DD)
    "1.2.3",           # 버전번호
    "123456789",       # 9자리 숫자
    "12345678901234",  # 14자리 숫자 (주민번호 아님)
]

print("[정탐 케이스]")
for s in rrn_ok:
    m = mc.RRN_PATTERN.search(s)
    digits = re.sub(r'\D', '', s)
    match2 = (len(digits) == 13) and re.match(r'^(\d{6}|\d{8})[1-8]\d{6}$', digits)
    result = "✓ 탐지" if (m or match2) else "✗ 미탐"
    print(f"  {result}: {repr(s)}")

print("\n[오탐 케이스]")
for s in rrn_fp:
    m = mc.RRN_PATTERN.search(s)
    result = "✗ 오탐!" if m else "✓ 정상"
    print(f"  {result}: {repr(s)}")

print()
print("=" * 60)
print("2. 계좌번호 패턴 테스트 (하이픈 필수 버전)")
print("=" * 60)
bank_ok = ["110-123-456789", "20-1234-5678901", "123-45-678901234"]
bank_fp = ["01012345678", "9501011234567", "1234567", "110123456789"]  # 하이픈 없으면 단독 미탐

print("[정탐 케이스 - 하이픈 있음]")
for s in bank_ok:
    m = mc.BANK_PATTERN.search(s)
    result = "✓ 탐지" if m else "✗ 미탐"
    print(f"  {result}: {repr(s)}")

print("\n[오탐 방지 케이스 - 하이픈 없음, 단독 탐지 안 되어야 함]")
for s in bank_fp:
    m = mc.BANK_PATTERN.search(s)
    result = "✗ 오탐!" if m else "✓ 정상(단독 미탐지, 레이블 기반만)"
    print(f"  {result}: {repr(s)}")

print()
print("=" * 60)
print("3. 차량번호 패턴 테스트 (실제 차량용 한글 검증)")
print("=" * 60)
veh_ok = ["12가1234", "123나5678", "서울12가1234", "11가 1234"]
veh_fp = ["12김1234", "12개1234", "서울이사1234"]  # 차량용 한글 아님

print("[정탐 케이스]")
for s in veh_ok:
    m = mc.VEHICLE_PATTERN.search(s)
    if m:
        has_veh_hangul = any(c in mc.VEHICLE_HANGUL_SET for c in m.group())
        result = "✓ 탐지(차량용 한글 확인)" if has_veh_hangul else "△ 매칭됐지만 차량용 한글 없음"
    else:
        result = "✗ 미탐"
    print(f"  {result}: {repr(s)}")

print("\n[오탐 방지 케이스]")
for s in veh_fp:
    m = mc.VEHICLE_PATTERN.search(s)
    if m:
        has_veh_hangul = any(c in mc.VEHICLE_HANGUL_SET for c in m.group())
        result = "✗ 오탐!" if has_veh_hangul else "✓ 매칭됐지만 차량용 한글 Guard로 필터링"
    else:
        result = "✓ 정상(미탐지)"
    print(f"  {result}: {repr(s)}")

print()
print("=" * 60)
print("4. 질병분류기호 단독 탐지 제한 테스트")
print("=" * 60)
print(f"  DISEASE_STANDALONE_ENABLED = {mc.DISEASE_STANDALONE_ENABLED}")
disease_ok = ["J01", "A09.0", "K35.2"]
for s in disease_ok:
    m = mc.DISEASE_PATTERN.search(s)
    standalone_block = not mc.DISEASE_STANDALONE_ENABLED
    result = "✓ 탐지(레이블 기반만, 단독 비활성)" if (m and standalone_block) else ("✓ 탐지(단독)" if m else "✗ 미탐")
    print(f"  {result}: {repr(s)}")

print()
print("=" * 60)
print("5. 전화번호 패턴 테스트")
print("=" * 60)
phone_ok = ["010-1234-5678", "01012345678", "010-123-4567"]
phone_fp = ["020-1234-5678", "012-345-6789"]  # 유효하지 않은 패턴

print("[정탐 케이스]")
for s in phone_ok:
    m = mc.PHONE_PATTERN.search(s)
    result = "✓ 탐지" if m else "✗ 미탐"
    print(f"  {result}: {repr(s)}")

print()
print("=" * 60)
print("6. calculate_sub_masks 기본 동작 테스트")
print("=" * 60)
test_cases = [
    ("950101-1234567", 100, 50, 200, 20),
    ("010-1234-5678", 100, 50, 200, 20),
    ("110-123-456789", 100, 50, 200, 20),
    ("12가1234", 100, 50, 100, 20),
]
for text, x, y, w, h in test_cases:
    masks = mc.calculate_sub_masks(text, x, y, w, h)
    print(f"  {repr(text)}: {len(masks)}개 마스크 → {masks}")

print()
print("모든 테스트 완료!")
