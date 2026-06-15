# securityCapture 작업 이력

---

## 2026-06-15 — 분리 입력 필드 전화번호 마스킹 버그 수정 및 차량번호 감지 추가

### 작업 배경
- 로컬 환경에서는 3분리 입력 필드 휴대폰번호(`[010]`-`[국번]`-`[끝번호]`) 마스킹이 정상 동작했으나, **운영서버 배포 후 마스킹이 되지 않는 문제** 발생
- OCR 판독 시 대괄호로 감싸진 형태(`[010]`, `[3559]`, `[4313]`)로 인식되는 분리 입력 필드의 실제 값이 마스킹 처리되지 않음
- 마스킹 항목에 **차량번호** 추가 요청

---

### 수정 파일
- `masking_core.py`
- `scratch/test_split_phone_masking.py` (신규 테스트 파일)

---

### 버그 1: 분리 입력 필드 전화번호 마스킹 미동작 (운영서버)

#### 원인 분석

**원인 1 — 끝번호 필드 마스킹 누락 (핵심 버그)**
- 기존 코드(`detect_personal_info` 내 "2-a. 분리된 전화번호 입력 필드 탐지" 섹션)는
  `[010]` - `[국번]` - `[끝번호]` 중에서 **국번(`seg2_word`)만 마스킹하고 끝번호(`seg3_word`)를 마스킹하지 않는 버그**가 존재
- 이로 인해 끝 4자리 실제 번호가 그대로 노출됨

**원인 2 — 세그먼트 간 간격 허용치 부족**
- 대괄호(`[ ]`) 포함 입력 필드는 일반 텍스트보다 단어 간격이 넓을 수 있음
- 기존 허용치: `height × 8.0` (최소 120px) → 운영서버 레이아웃에서 간격 초과로 탐지 실패

#### 수정 내용 (`masking_core.py` L1307~L1337)

```python
# 수정 전: 국번만 마스킹
mask_regions.append({
    'x': seg2_word['x'], 'y': seg2_word['y'],
    'width': seg2_word['width'], 'height': seg2_word['height']
})

# 수정 후: 국번 + 끝번호 모두 마스킹
mask_regions.append({
    'x': seg2_word['x'], 'y': seg2_word['y'],
    'width': seg2_word['width'], 'height': seg2_word['height']
})
mask_regions.append({
    'x': seg3_word['x'], 'y': seg3_word['y'],
    'width': seg3_word['width'], 'height': seg3_word['height']
})
```

- 세그먼트 간 간격 허용치 변경:  
  `height × 8.0 (min 120px)` → **`height × 15.0 (min 200px)`**

---

### 버그 2: 차량번호 마스킹 미동작

#### 원인 분석
- `VEHICLE_PATTERN` 정규식과 레이아웃 기반 `VEHICLE_LABELS` 처리는 이미 구현되어 있었음
- 그러나 **`detect_personal_info`의 정규식 기반 자동 탐지 패턴 목록에 `VEHICLE_PATTERN`이 누락**
- 레이블("차량번호" 등) 없이 차량번호만 독립적으로 존재하는 경우 전혀 감지되지 않음

#### 수정 내용 (`masking_core.py` L1406~L1413)

```python
# 수정 전
for pattern, p_type in [
    (RRN_PATTERN, "rrn"), (PHONE_PATTERN, "phone"),
    ...
    (IP_PATTERN, "ip"), (ADDRESS_PATTERN, "address")
]:

# 수정 후 — VEHICLE_PATTERN 추가
for pattern, p_type in [
    (RRN_PATTERN, "rrn"), (PHONE_PATTERN, "phone"),
    ...
    (IP_PATTERN, "ip"), (ADDRESS_PATTERN, "address"),
    (VEHICLE_PATTERN, "vehicle"),  # 차량번호 정규식 기반 감지 추가
]:
```

- 지원 차량번호 형식:
  - 신형(2019+): `12가1234`, `123나5678` (숫자 2~3자리 + 허용 한글 1자 + 숫자 4자리)
  - 구형: `서울12나1234` (지역명 + 숫자 + 한글 + 숫자 4자리)
- 마스킹 방식: 뒤 4자리 숫자만 가림 (앞 번호와 한글 문자는 노출)

---

### 단위 테스트 결과 (`scratch/test_split_phone_masking.py`)

| # | 테스트 항목 | 결과 |
|---|------------|------|
| 1 | 분리 전화번호 국번+끝번호 모두 마스킹 | ✅ PASS |
| 2 | 레이아웃 기반 분리 전화번호 마스킹 | ✅ PASS |
| 3 | 차량번호 정규식 감지 (신형 2종, 구형 1종) | ✅ PASS |
| 4 | 차량번호 단어 단독 마스킹 감지 | ✅ PASS |
| 5 | 차량번호 레이블+값 마스킹 | ✅ PASS |

---
