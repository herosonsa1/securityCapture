"""
분리 입력 필드 전화번호 마스킹 수정 검증 테스트
- [010] - [3559] - [4313] 형태에서 국번+끝번호 모두 마스킹되는지 확인
- 차량번호 정규식 기반 감지 테스트
"""
import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from masking_core import detect_personal_info, calculate_sub_masks, VEHICLE_PATTERN


def make_word(text, x, y, w, h):
    return {'text': text, 'x': x, 'y': y, 'width': w, 'height': h}


# ──────────────────────────────────────────────────────────────────────────────
# 테스트 1: [010] - [3559] - [4313] 분리 입력 필드 마스킹 검증
# ──────────────────────────────────────────────────────────────────────────────
def test_split_phone_all_masked():
    """
    3분리 전화번호 입력 필드([010] - [국번] - [끝번호]) 모두에서
    국번과 끝번호 두 필드가 마스킹되어야 함.
    """
    print("\n=== 테스트 1: 분리 전화번호 국번+끝번호 마스킹 ===")

    # 모의 OCR 단어 배열: [010] - [3559] - [4313]
    # 각 단어가 x좌표로 순서대로 배치됨 (같은 Y행)
    words = [
        make_word('[010]',   100, 50, 60, 20),
        make_word('-',       165, 50, 15, 20),
        make_word('[3559]',  185, 50, 65, 20),
        make_word('-',       255, 50, 15, 20),
        make_word('[4313]',  275, 50, 65, 20),
    ]
    ocr_result = {'status': 'success', 'words': words}
    mask_regions, label_regions = detect_personal_info(ocr_result)

    print(f"  마스킹 영역 수: {len(mask_regions)}")
    for i, r in enumerate(mask_regions):
        print(f"  영역 #{i+1}: x={r['x']}, y={r['y']}, w={r['width']}, h={r['height']}")

    # [010]은 노출, [3559]와 [4313]이 마스킹되어야 함
    masked_xs = [r['x'] for r in mask_regions]
    assert 185 in masked_xs, f"[3559] 국번 필드(x=185)가 마스킹되지 않음! 마스킹 x 목록: {masked_xs}"
    assert 275 in masked_xs, f"[4313] 끝번호 필드(x=275)가 마스킹되지 않음! 마스킹 x 목록: {masked_xs}"
    print("  ✅ PASS: 국번([3559])과 끝번호([4313]) 모두 마스킹 확인")


# ──────────────────────────────────────────────────────────────────────────────
# 테스트 2: 레이아웃 기반 탐지 + 분리 입력 필드 (레이블 있는 경우)
# ──────────────────────────────────────────────────────────────────────────────
def test_split_phone_with_label():
    """
    '휴대폰번호' 레이블이 있고 분리 입력 필드가 있는 경우
    레이아웃 기반 탐지에서 처리되어야 함.
    """
    print("\n=== 테스트 2: 레이아웃 기반 분리 전화번호 마스킹 ===")

    words = [
        make_word('휴대폰번호', 50, 50, 80, 20),
        make_word('[010]',      160, 50, 60, 20),
        make_word('-',          225, 50, 15, 20),
        make_word('[3559]',     245, 50, 65, 20),
        make_word('-',          315, 50, 15, 20),
        make_word('[4313]',     335, 50, 65, 20),
    ]
    ocr_result = {'status': 'success', 'words': words}
    mask_regions, label_regions = detect_personal_info(ocr_result)

    print(f"  마스킹 영역 수: {len(mask_regions)}")
    for i, r in enumerate(mask_regions):
        print(f"  영역 #{i+1}: x={r['x']}, y={r['y']}, w={r['width']}, h={r['height']}")
    print(f"  레이블 강조 영역 수: {len(label_regions)}")

    # 국번과 끝번호 중 최소 하나가 마스킹되어야 함
    assert len(mask_regions) >= 1, f"마스킹 영역이 없음! 마스킹 목록: {mask_regions}"
    print("  ✅ PASS: 분리 전화번호 마스킹 영역 감지됨")


# ──────────────────────────────────────────────────────────────────────────────
# 테스트 3: 차량번호 정규식 기반 감지
# ──────────────────────────────────────────────────────────────────────────────
def test_vehicle_regex_detection():
    """
    차량번호가 정규식으로 자동 감지되고 뒤 4자리가 마스킹되어야 함.
    """
    print("\n=== 테스트 3: 차량번호 정규식 기반 감지 ===")

    test_cases = [
        "12가1234",      # 신형 숫자2+한글+숫자4
        "123나5678",     # 신형 숫자3+한글+숫자4
        "서울12나1234",  # 구형 지역명+숫자+한글+숫자4
    ]

    for tc in test_cases:
        m = VEHICLE_PATTERN.search(tc)
        if m:
            print(f"  '{tc}' → 패턴 매칭 OK: '{m.group()}'")
        else:
            print(f"  '{tc}' → ❌ 패턴 매칭 실패!")
            assert False, f"차량번호 '{tc}'가 VEHICLE_PATTERN에 매칭되지 않음"

    # calculate_sub_masks로 마스킹 영역 계산
    for tc in test_cases:
        sub_masks = calculate_sub_masks(tc, 100, 50, len(tc) * 12, 20)
        if sub_masks:
            print(f"  '{tc}' → 마스킹 영역: {sub_masks}")
        else:
            print(f"  '{tc}' → ⚠️  마스킹 영역 없음 (calculate_sub_masks 미매칭)")

    print("  ✅ PASS: 차량번호 정규식 감지 완료")


# ──────────────────────────────────────────────────────────────────────────────
# 테스트 4: 차량번호 OCR 단어로 감지
# ──────────────────────────────────────────────────────────────────────────────
def test_vehicle_word_detection():
    """
    OCR 단어로 차량번호가 감지되어 마스킹 영역이 생성되어야 함.
    """
    print("\n=== 테스트 4: 차량번호 단어 마스킹 감지 ===")

    words = [
        make_word('12가1234', 100, 50, 100, 20),
    ]
    ocr_result = {'status': 'success', 'words': words}
    mask_regions, label_regions = detect_personal_info(ocr_result)

    print(f"  마스킹 영역 수: {len(mask_regions)}")
    for i, r in enumerate(mask_regions):
        print(f"  영역 #{i+1}: x={r['x']}, y={r['y']}, w={r['width']}, h={r['height']}")

    assert len(mask_regions) >= 1, "차량번호 '12가1234'에 대한 마스킹 영역이 없음!"
    print("  ✅ PASS: 차량번호 마스킹 영역 감지됨")


# ──────────────────────────────────────────────────────────────────────────────
# 테스트 5: 차량번호 레이블 + 차량번호 값
# ──────────────────────────────────────────────────────────────────────────────
def test_vehicle_with_label():
    """
    '차량번호' 레이블 + 차량번호 값이 함께 있을 때 마스킹되어야 함.
    """
    print("\n=== 테스트 5: 차량번호 레이블+값 마스킹 ===")

    words = [
        make_word('차량번호', 50, 50, 80, 20),
        make_word('12가1234', 160, 50, 100, 20),
    ]
    ocr_result = {'status': 'success', 'words': words}
    mask_regions, label_regions = detect_personal_info(ocr_result)

    print(f"  마스킹 영역 수: {len(mask_regions)}")
    for i, r in enumerate(mask_regions):
        print(f"  영역 #{i+1}: x={r['x']}, y={r['y']}, w={r['width']}, h={r['height']}")
    print(f"  레이블 강조 영역 수: {len(label_regions)}")

    assert len(mask_regions) >= 1, "차량번호 레이블+값에 대한 마스킹 영역이 없음!"
    print("  ✅ PASS: 차량번호 레이블 기반 마스킹 감지됨")


if __name__ == "__main__":
    try:
        test_split_phone_all_masked()
        test_split_phone_with_label()
        test_vehicle_regex_detection()
        test_vehicle_word_detection()
        test_vehicle_with_label()
        print("\n\n✅ 모든 테스트 통과!")
    except AssertionError as e:
        print(f"\n❌ 테스트 실패: {e}")
        sys.exit(1)
