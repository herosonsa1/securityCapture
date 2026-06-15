# -*- coding: utf-8 -*-
"""실제 및 가상 시나리오 검증용 테스트 스크립트"""
import sys, os
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from masking_core import detect_personal_info

def run_simulated_tests():
    print("=== 가상 레이아웃 테스트 시작 ===")

    # 시나리오 1: 피보험자 이름 뒤에 주민등록번호가 바로 위치한 경우
    # [피보험자] [이준희] [731225-1542622] [사업자조회]
    print("\n[시나리오 1] 피보험자 + 이름 + 주민번호")
    words_1 = [
        {"text": "피보험자", "x": 10, "y": 100, "width": 50, "height": 20},
        {"text": "이준희", "x": 70, "y": 100, "width": 45, "height": 20},
        {"text": "731225-1542622", "x": 130, "y": 100, "width": 100, "height": 20},
        {"text": "사업자조회", "x": 240, "y": 100, "width": 60, "height": 20}
    ]
    ocr_res_1 = {"status": "success", "words": words_1}
    mask_1, label_1 = detect_personal_info(ocr_res_1)
    
    print("  * 감지된 마스킹 영역 수:", len(mask_1))
    for m in mask_1:
        print(f"    마스킹: x={m['x']}, y={m['y']}, w={m['width']}, h={m['height']}")
    
    # 731225-1542622 에서 성별 뒷자리 6자리가 마스킹 영역으로 잡혔는지 검증
    # 731225-1542622 의 글자 수 = 14자, char_w = 100 / 14 = 7.14
    # 뒤 6자리는 8번째 글자부터 시작하므로 x 오프셋은 130 + 8 * 7.14 = 187
    # 731225-1542622와 이준희 모두 마스킹되어야 함
    has_name_mask = any(m['x'] == 70 for m in mask_1)
    has_rrn_mask = any(m['x'] > 130 for m in mask_1)
    print(f"  * 이름 마스킹 감지 여부: {has_name_mask}")
    print(f"  * 주민번호 마스킹 감지 여부: {has_rrn_mask}")


    # 시나리오 2: 면허번호가 92-692533 와 74 로 분리되어 인식된 경우
    print("\n[시나리오 2] 면허번호 쪼개짐 (92-692533 과 74)")
    words_2 = [
        {"text": "면허번호", "x": 10, "y": 200, "width": 50, "height": 20},
        {"text": "부산(12)", "x": 70, "y": 200, "width": 50, "height": 20},
        {"text": "92-692533", "x": 130, "y": 200, "width": 75, "height": 20},
        {"text": "-74", "x": 210, "y": 200, "width": 25, "height": 20}
    ]
    ocr_res_2 = {"status": "success", "words": words_2}
    mask_2, label_2 = detect_personal_info(ocr_res_2)
    
    print("  * 감지된 마스킹 영역 수:", len(mask_2))
    for m in mask_2:
        print(f"    마스킹: x={m['x']}, y={m['y']}, w={m['width']}, h={m['height']}")
    
    # 92-692533와 -74 중, 앞 2자리(지역코드)를 제외한 영역이 마스킹 영역으로 잡혔는지 검증
    # numeric_dr_segs 에 92692533 (8자리)와 74 (2자리)가 수집되어, dr_idx=1인 두번째 세그먼트(-74 및 692533 부분)가 가려져야 함
    # (원래 세그먼트가 쪼개지면 두번째 숫자 세그먼트 전체가 마스킹 박스로 덮임)
    has_driver_mask = len(mask_2) > 0
    print(f"  * 면허번호 마스킹 감지 여부: {has_driver_mask}")

    # 시나리오 3: 면허번호가 92-692533-74 단일 토큰으로 정상 인식된 경우
    print("\n[시나리오 3] 면허번호 단일 토큰 (92-692533-74)")
    words_3 = [
        {"text": "면허번호", "x": 10, "y": 200, "width": 50, "height": 20},
        {"text": "부산(12)", "x": 70, "y": 200, "width": 50, "height": 20},
        {"text": "92-692533-74", "x": 130, "y": 200, "width": 100, "height": 20}
    ]
    ocr_res_3 = {"status": "success", "words": words_3}
    mask_3, label_3 = detect_personal_info(ocr_res_3)
    
    print("  * 감지된 마스킹 영역 수:", len(mask_3))
    for m in mask_3:
        print(f"    마스킹: x={m['x']}, y={m['y']}, w={m['width']}, h={m['height']}")

if __name__ == "__main__":
    run_simulated_tests()
