# -*- coding: utf-8 -*-
"""실제 및 가상 시나리오 검증용 테스트 스크립트"""
import sys, os
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from masking_core import detect_personal_info

def run_simulated_tests():
    print("=== 가상 레이아웃 테스트 시작 ===")

    # 시나리오 1: 피보험자 이름 뒤에 주민등록번호가 바로 위치한 경우
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

    # 시나리오 4: 상세주소가 분리 입력필드로 인식된 경우
    # [주소] [부산 남구 대연3동] [54-1 경성대 부근]
    # 예상 결과: "부산 남구 대연3동" 단어는 노출, "54-1 경성대 부근" 단어는 마스킹
    print("\n[시나리오 4] 주소 및 상세주소 분리 입력필드")
    words_4 = [
        {"text": "주소", "x": 10, "y": 300, "width": 30, "height": 20},
        {"text": "[부산 남구 대연3동]", "x": 50, "y": 300, "width": 150, "height": 20},
        {"text": "[54-1 경성대 부근]", "x": 210, "y": 300, "width": 150, "height": 20}
    ]
    ocr_res_4 = {"status": "success", "words": words_4}
    mask_4, label_4 = detect_personal_info(ocr_res_4)
    
    print("  * 감지된 마스킹 영역 수:", len(mask_4))
    for m in mask_4:
        print(f"    마스킹: x={m['x']}, y={m['y']}, w={m['width']}, h={m['height']}")

    # 시나리오 5: 계좌번호가 분리 입력필드로 인식된 경우
    # [계좌번호] [110] [-] [123] [-] [456789]
    # 예상 결과: 마지막 세그먼트인 "456789" 필드만 마스킹
    print("\n[시나리오 5] 계좌번호 분리 입력필드")
    words_5 = [
        {"text": "계좌번호", "x": 10, "y": 400, "width": 60, "height": 20},
        {"text": "[110]", "x": 80, "y": 400, "width": 40, "height": 20},
        {"text": "[-]", "x": 125, "y": 400, "width": 15, "height": 20},
        {"text": "[123]", "x": 145, "y": 400, "width": 40, "height": 20},
        {"text": "[-]", "x": 190, "y": 400, "width": 15, "height": 20},
        {"text": "[456789]", "x": 210, "y": 400, "width": 60, "height": 20}
    ]
    ocr_res_5 = {"status": "success", "words": words_5}
    mask_5, label_5 = detect_personal_info(ocr_res_5)
    
    print("  * 감지된 마스킹 영역 수:", len(mask_5))
    for m in mask_5:
        print(f"    마스킹: x={m['x']}, y={m['y']}, w={m['width']}, h={m['height']}")

    # 시나리오 6: 운전자 이름 및 사고장소 마스킹 검증
    # [운전자] [본인] [이준희] / [사고장소] [부산 남구 대연3동] [54-1 경성대 부근]
    print("\n[시나리오 6] 운전자 및 사고장소 레이블 감지")
    words_6 = [
        {"text": "운전자", "x": 10, "y": 500, "width": 40, "height": 20},
        {"text": "본인", "x": 60, "y": 500, "width": 30, "height": 20},
        {"text": "이준희", "x": 100, "y": 500, "width": 45, "height": 20},
        {"text": "사고장소", "x": 10, "y": 530, "width": 50, "height": 20},
        {"text": "부산 남구 대연3동", "x": 70, "y": 530, "width": 120, "height": 20},
        {"text": "54-1 경성대 부근", "x": 200, "y": 530, "width": 100, "height": 20}
    ]
    ocr_res_6 = {"status": "success", "words": words_6}
    mask_6, label_6 = detect_personal_info(ocr_res_6)
    
    print("  * 감지된 마스킹 영역 수:", len(mask_6))
    for m in mask_6:
        print(f"    마스킹: x={m['x']}, y={m['y']}, w={m['width']}, h={m['height']}")

    # 시나리오 7: 주소가 레이블보다 한 줄 밑(아래 행)에 있고 레이블 시작점보다 약간 왼쪽에서 시작하는 수직 레이아웃
    # [사고장소] 
    # [부산 남구 대연3동] [54-1 경성대 부근]
    print("\n[시나리오 7] 사고장소 수직 레이아웃 (아래 행 주소 시작)")
    words_7 = [
        {"text": "사고장소", "x": 100, "y": 600, "width": 50, "height": 20},
        {"text": "부산 남구 대연3동", "x": 20, "y": 630, "width": 120, "height": 20},
        {"text": "54-1 경성대 부근", "x": 150, "y": 630, "width": 100, "height": 20}
    ]
    ocr_res_7 = {"status": "success", "words": words_7}
    mask_7, label_7 = detect_personal_info(ocr_res_7)
    
    print("  * 감지된 마스킹 영역 수:", len(mask_7))
    for m in mask_7:
        print(f"    마스킹: x={m['x']}, y={m['y']}, w={m['width']}, h={m['height']}")

    # 시나리오 8: 증권번호 오탐 차단 검증
    # [증권번호] [CA0023456000000] [통합상품 개인용]
    # 예상 결과: 주민번호로 오인식되더라도 자릿수 검증에 의해 마스킹 영역 0개 (무마스킹)
    print("\n[시나리오 8] 증권번호 오탐 차단 검증")
    words_8 = [
        {"text": "증권번호", "x": 10, "y": 700, "width": 50, "height": 20},
        {"text": "CA0023456000000", "x": 70, "y": 700, "width": 120, "height": 20},
        {"text": "통합상품 개인용", "x": 200, "y": 700, "width": 100, "height": 20}
    ]
    ocr_res_8 = {"status": "success", "words": words_8}
    mask_8, label_8 = detect_personal_info(ocr_res_8)
    print("  * 감지된 마스킹 영역 수:", len(mask_8))
    for m in mask_8:
        print(f"    마스킹: x={m['x']}, y={m['y']}, w={m['width']}, h={m['height']}")

    # 시나리오 9: 연락처 010 노출 및 뒷번호 마스킹 검증
    # [연락처] [핸드폰] [010] [-] [4355] [-] [4613]
    # 예상 결과: 010은 노출되고 4355와 4613만 마스킹 처리됨
    print("\n[시나리오 9] 연락처 010 노출 및 뒷번호 마스킹")
    words_9 = [
        {"text": "연락처", "x": 10, "y": 800, "width": 40, "height": 20},
        {"text": "핸드폰", "x": 60, "y": 800, "width": 40, "height": 20},
        {"text": "[010]", "x": 110, "y": 800, "width": 35, "height": 20},
        {"text": "[-]", "x": 150, "y": 800, "width": 10, "height": 20},
        {"text": "[4355]", "x": 165, "y": 800, "width": 35, "height": 20},
        {"text": "[-]", "x": 205, "y": 800, "width": 10, "height": 20},
        {"text": "[4613]", "x": 220, "y": 800, "width": 35, "height": 20}
    ]
    ocr_res_9 = {"status": "success", "words": words_9}
    mask_9, label_9 = detect_personal_info(ocr_res_9)
    print("  * 감지된 마스킹 영역 수:", len(mask_9))
    for m in mask_9:
        print(f"    마스킹: x={m['x']}, y={m['y']}, w={m['width']}, h={m['height']}")

    # 시나리오 10: 도로명 주소 고도화 검증
    # [주소] [중앙대로 123번길] [54-1]
    # 예상 결과: "중앙대로 "는 노출, "123번길"은 "123"부터 마스킹, "54-1"은 전체 마스킹
    print("\n[시나리오 10] 도로명 주소 및 상세 지번 고도화")
    words_10 = [
        {"text": "주소", "x": 10, "y": 900, "width": 30, "height": 20},
        {"text": "중앙대로 123번길", "x": 50, "y": 900, "width": 110, "height": 20},
        {"text": "54-1", "x": 170, "y": 900, "width": 40, "height": 20}
    ]
    ocr_res_10 = {"status": "success", "words": words_10}
    mask_10, label_10 = detect_personal_info(ocr_res_10)
    print("  * 감지된 마스킹 영역 수:", len(mask_10))
    for m in mask_10:
        print(f"    마스킹: x={m['x']}, y={m['y']}, w={m['width']}, h={m['height']}")

if __name__ == "__main__":
    run_simulated_tests()
