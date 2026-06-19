"""
손상된 라인 1473 (index 1472)을 올바른 코드 블록으로 교체하는 스크립트
"""
import re

with open(r'c:\myWork\workspace\scratch\securityCapture\masking_core.py', encoding='utf-8') as f:
    content = f.read()

lines = content.split('\n')

# 라인 1473 확인 (0-indexed: 1472)
print(f"현재 라인 1473 앞 80자: {repr(lines[1472][:80])}")

new_bank_code = (
    "            if val_words:\n"
    "                if matched_label_type == \"bank\":\n"
    "                    # 계좌번호 분리 입력 필드 대응\n"
    "                    # 숫자 세그먼트 단어 추출 (대괄호 제거)\n"
    "                    numeric_segs = []\n"
    "                    for vw in val_words:\n"
    r"                        digits_only = re.sub(r'\D', '', re.sub(r'[\[\]]', '', vw['text']))"
    "\n"
    "                        if digits_only:\n"
    "                            numeric_segs.append((vw, digits_only))\n"
    "\n"
    "                    total_digits = ''.join(d for _, d in numeric_segs)\n"
    "                    combined_text_bank = ''.join(w['text'] for w in val_words)\n"
    r"                    combined_norm_bank = re.sub(r'[\[\]]', '', combined_text_bank)"
    "\n"
    "\n"
    "                    if len(numeric_segs) >= 2:\n"
    "                        # 분리 필드 형태: 마지막 숫자 필드 박스 전체를 마스킹\n"
    "                        # 레이블 컨텍스트가 있으므로 마지막 세그먼트 마스킹\n"
    "                        for idx_seg, (vw, digits) in enumerate(numeric_segs):\n"
    "                            if idx_seg == len(numeric_segs) - 1:\n"
    "                                mask_regions.append({\n"
    "                                    'x': vw['x'], 'y': vw['y'],\n"
    "                                    'width': vw['width'], 'height': vw['height']\n"
    "                                })\n"
    "                    else:\n"
    "                        # 단일 토큰 형태\n"
    "                        merged = merge_boxes(val_words)\n"
    "                        if merged:\n"
    "                            # BANK_PATTERN(하이픈 필수)로 먼저 시도\n"
    "                            if BANK_PATTERN.search(combined_norm_bank):\n"
    "                                sub_masks = calculate_sub_masks(combined_norm_bank, merged['x'], merged['y'], merged['width'], merged['height'], name_mask_style)\n"
    "                                if sub_masks:\n"
    "                                    mask_regions.extend(sub_masks)\n"
    "                                else:\n"
    "                                    mask_regions.append(merged)\n"
    "                            elif BANK_PATTERN_NO_DASH.search(combined_norm_bank):\n"
    "                                # 하이픈 없는 계좌번호: 레이블 컨텍스트 있으므로 마지막 6자리 마스킹\n"
    r"                                digits_no_dash = re.sub(r'\D', '', combined_norm_bank)"
    "\n"
    "                                if len(digits_no_dash) >= 10:\n"
    "                                    mask_start_ratio = (len(digits_no_dash) - 6) / max(1, len(digits_no_dash))\n"
    "                                    mask_x = int(merged['x'] + mask_start_ratio * merged['width'])\n"
    "                                    mask_w = merged['width'] - (mask_x - merged['x'])\n"
    "                                    if mask_w > 0:\n"
    "                                        mask_regions.append({\n"
    "                                            'x': mask_x, 'y': merged['y'],\n"
    "                                            'width': mask_w, 'height': merged['height']\n"
    "                                        })\n"
    "                            else:\n"
    "                                mask_regions.append(merged)"
)

lines[1472] = new_bank_code

new_content = '\n'.join(lines)
with open(r'c:\myWork\workspace\scratch\securityCapture\masking_core.py', 'w', encoding='utf-8') as f:
    f.write(new_content)
print("교체 완료!")

# 문법 검사
import py_compile
try:
    py_compile.compile(r'c:\myWork\workspace\scratch\securityCapture\masking_core.py', doraise=True)
    print("문법 검사 통과!")
except py_compile.PyCompileError as e:
    print(f"문법 오류: {e}")
