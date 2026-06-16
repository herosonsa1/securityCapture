# -*- coding: utf-8 -*-
import sys, os
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from PIL import Image, ImageOps, ImageFilter, ImageDraw
import json
import subprocess
import tempfile

img_path = r"C:\Users\Herosonsa\.gemini\antigravity-ide\brain\829cf393-9a0a-40a4-b7e7-8c5b2a02b8bb\media__1781574143570.png"

def call_ps_ocr(ocr_img_path):
    script_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "ocr_engine.ps1")
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = subprocess.SW_HIDE
    cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script_path, "-ImagePath", ocr_img_path]
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, startupinfo=startupinfo, text=True, encoding="utf-8-sig", errors="replace")
    output_str = result.stdout.strip()
    json_start = output_str.find('{"status"')
    if json_start != -1:
        output_str = output_str[json_start:]
    return json.loads(output_str)

def run_test(name, preprocess_fn):
    with Image.open(img_path) as img:
        proc_img = preprocess_fn(img)
        temp_dir = tempfile.gettempdir()
        tmp_path = os.path.join(temp_dir, f"temp_ocr_test_{name}.png")
        proc_img.save(tmp_path)
        
        try:
            ocr_res = call_ps_ocr(tmp_path)
            words = ocr_res.get("words", [])
            print(f"[{name}] 인식 단어 수: {len(words)}")
            # Y=214(보정 후 좌표 기준) 근처의 인식된 단어들만 필터링해서 출력
            # border_crop이 4px이고 scale_factor가 4.0이므로 보정되지 않은 원본 좌표계 기준
            # 원본 Y=218 근처의 단어 검색 (확대 이미지 기준 Y는 대략 (218 - 4) * 4 = 856 부근)
            y_218_words = []
            for w in words:
                orig_y = (w['y'] / 4.0) + 4
                if 205 <= orig_y <= 230:
                    y_218_words.append(f"{w['text']}(x={int(w['x']/4)+4})")
            print(f"  * Y=218 부근 단어들: {', '.join(y_218_words)}")
        except Exception as e:
            print(f"[{name}] 실패: {e}")
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

# ── 1. 기존 run_ocr 전처리 로직 (LANCZOS 4배 + autocontrast + UnsharpMask)
def prep_original(img_pil):
    border_crop = 4
    scale_factor = 4.0
    if img_pil.width > border_crop * 2 and img_pil.height > border_crop * 2:
        img_pil = img_pil.crop((border_crop, border_crop, img_pil.width - border_crop, img_pil.height - border_crop))
    new_w = int(img_pil.width * scale_factor)
    new_h = int(img_pil.height * scale_factor)
    scaled_img = img_pil.resize((new_w, new_h), Image.Resampling.LANCZOS)
    gray_img = scaled_img.convert("L")
    contrast_img = ImageOps.autocontrast(gray_img, cutoff=2)
    sharp_img = contrast_img.filter(ImageFilter.UnsharpMask(radius=2, percent=200, threshold=3))
    return sharp_img

# ── 2. 파란색 테두리 색상 필터링 후 기존 전처리
# 하늘색/파란색 계열의 픽셀(테두리선)을 흰색으로 교체하여 글자만 강조
def prep_color_filter(img_pil):
    # RGB 채널 분리
    r, g, b = img_pil.convert("RGB").split()
    r_data = r.load()
    g_data = g.load()
    b_data = b.load()
    
    # 테두리 색상(하늘색 계열): R이 작고 G, B가 큰 특성 활용
    # R < 160 이고 G > 160 이며 B > 180 인 픽셀을 흰색(255, 255, 255)으로 채움
    img_rgb = img_pil.convert("RGB")
    pixels = img_rgb.load()
    for y in range(img_rgb.height):
        for x in range(img_rgb.width):
            pr, pg, pb = pixels[x, y]
            # 하늘색/파란색 테두리 조건
            # 특히 R과 B의 차이가 크고 B가 높은 경우 (예: 드롭다운 보더 색상 #78C5E7 등)
            if pb > 150 and pg > 150 and pr < 180 and pb > pr + 30:
                pixels[x, y] = (255, 255, 255)
            # 회색 테두리선 대응
            elif 180 <= pr <= 220 and 180 <= pg <= 220 and 180 <= pb <= 220 and abs(pr-pb) < 10:
                # 콤보박스나 텍스트 박스의 옅은 회색 외곽선도 지워버림
                pixels[x, y] = (255, 255, 255)

    # 이후 기존 전처리 동일 적용
    return prep_original(img_rgb)

# ── 3. 이진화(Thresholding) 추가 전처리
def prep_binary(img_pil):
    sharp = prep_original(img_pil)
    # 이진화 threshold 적용 (임계값 140)
    binary = sharp.point(lambda p: 255 if p > 130 else 0)
    return binary

print("OCR 전처리 실험 시작...")
run_test("Original (기존)", prep_original)
run_test("Color Filter (테두리 제거)", prep_color_filter)
run_test("Binary (이진화)", prep_binary)
