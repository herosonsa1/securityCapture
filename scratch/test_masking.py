import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from masking_core import run_ocr, detect_personal_info, apply_mask
from PIL import Image

def main():
    image_path = os.path.abspath("test_target.png")
    if not os.path.exists(image_path):
        print(f"테스트 타겟 이미지가 없습니다: {image_path}")
        return

    print("1. OCR 구동 중...")
    ocr_res = run_ocr(image_path)
    print("OCR 결과 상태:", ocr_res.get("status"))

    if ocr_res.get("status") == "success":
        print(f"인식된 총 단어 개수: {len(ocr_res.get('words', []))}")
        
        print("\n2. 개인정보 영역 감지 중...")
        regions = detect_personal_info(ocr_res)
        print(f"감지된 개인정보 영역 개수: {len(regions)}")
        
        for idx, reg in enumerate(regions):
            print(f"영역 #{idx+1}: {reg}")
            
        print("\n3. 이미지 마스킹 필터 적용...")
        img = Image.open(image_path)
        
        # 모자이크 이미지 저장
        img_mosaic = apply_mask(img, regions, mask_type="mosaic", mosaic_size=8)
        mosaic_out = os.path.abspath("test_target_masked_mosaic.png")
        img_mosaic.save(mosaic_out)
        print(f"모자이크 마스킹 이미지 저장 완료: {mosaic_out}")
        
        # 블랙 단색 이미지 저장
        img_black = apply_mask(img, regions, mask_type="black")
        black_out = os.path.abspath("test_target_masked_black.png")
        img_black.save(black_out)
        print(f"블랙박스 마스킹 이미지 저장 완료: {black_out}")
    else:
        print("에러:", ocr_res.get("message"))

if __name__ == "__main__":
    main()
