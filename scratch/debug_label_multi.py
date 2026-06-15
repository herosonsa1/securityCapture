# -*- coding: utf-8 -*-
"""
다중 단어 레이블 매칭 디버그 테스트
"""
import sys, os, re
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from masking_core import EXCLUDE_NOUNS

# 각 단어가 어떤 레이블 조건에 매치되는지 확인
words_multi = [
    {'text': '주민', 'x': 10, 'y': 50, 'width': 30, 'height': 20},
    {'text': '등록', 'x': 45, 'y': 50, 'width': 30, 'height': 20},
    {'text': '번호', 'x': 80, 'y': 50, 'width': 30, 'height': 20},
    {'text': '900722-1234567', 'x': 140, 'y': 52, 'width': 140, 'height': 20},
]

RRN_LABELS = {
    "주민등록번호", "주민번호", "실명번호", "외국인등록번호", "등록번호", "주민등록 번호",
    "주원들릨ä호", "주원들", "릨ä호", "들릨ä", "주원", "주민등록", "등록번호", "주원들릨", "릨ä",
    "주인등록변호", "주인등록", "등록변호", "변호", "주인등록변"
}

for word in words_multi:
    text_clean = re.sub(r'\s+', '', word['text'])
    cond1 = any(lbl in text_clean for lbl in RRN_LABELS)
    cond2 = "주민" in text_clean and "번호" in text_clean
    cond3 = "등록" in text_clean and "번호" in text_clean
    cond4 = "주원" in text_clean
    cond5 = "들릨" in text_clean
    cond6 = "릨ä" in text_clean
    cond7 = "주인" in text_clean and "변호" in text_clean
    cond8 = "주" in text_clean and ("번호" in text_clean or "변호" in text_clean or "호" in text_clean)
    cond9 = "등록" in text_clean and ("번호" in text_clean or "변호" in text_clean or "호" in text_clean)
    ex1 = "접수" in text_clean
    ex2 = "제휴" in text_clean

    any_rrn = any([cond1, cond2, cond3, cond4, cond5, cond6, cond7, cond8, cond9]) and not (ex1 or ex2)
    print(f"단어='{text_clean}': RRN레이블매치={any_rrn} (cond1={cond1}, c2={cond2}, c3={cond3}, c8={cond8}, c9={cond9})")

print()
print("=> '주민' 단어: 주=True, '번호' 없음 -> cond8 조건 ('주' + '호'는 True!)")
print("   '등록' 단어: '등록' + '호'없음 -> cond9 조건 ('등록' alone)...")
