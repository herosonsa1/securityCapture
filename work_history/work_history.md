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
---

## 2026-06-15 (추가) — 캡쳐방지 우회 후 운영서버 마스킹 실패 근본 원인 수정

### 문제 제보
> "캡쳐방지 우회 작업 이전에는 휴대폰번호 마스킹이 잘 됐는데, 이후 운영서버에서 잘 안 됨"

### 근본 원인: Windows DPI Awareness 미설정으로 인한 좌표계 불일치

운영서버 PC가 **고DPI(125%, 150%)** 설정인 경우, DPI Awareness가 없으면:

| 구분 | 로컬(100% DPI) | 운영서버(125% DPI) |
|------|--------------|-------------------|
| Tkinter 창 좌표 | 논리px = 물리px | 논리px (작음) |
| `mss`/`dxcam` 캡쳐 이미지 | 물리px = 논리px | **물리px (1.25배 큰 이미지)** |
| OCR word.height | 예) 18px | 예) 22~27px |
| 분리필드 gap 허용치 | 18×8=144px ✅ | **22×8=176px → 실제 gap 초과로 탐지 실패** |

**흐름:**
1. `screen_grab.py`의 `mss`가 물리픽셀(큰 이미지)로 캡쳐
2. `capture_window.py`의 Tkinter 창은 논리픽셀 크기
3. 이미지가 창보다 커서 마우스 선택 영역이 오프셋됨
4. OCR 좌표도 물리픽셀 기준으로 나와 마스킹 영역이 실제 텍스트 위치와 어긋남

### 수정 내용 (`capture_window.py`)

```python
# 1. 모듈 임포트 시 즉시 DPI Awareness 설정 (Tkinter 창 생성 전)
_set_dpi_awareness()   # Per-Monitor V2 → V1 → 레거시 순 폴백

# 2. 캡쳐 이미지 크기 ≠ Tkinter 창 크기일 때 자동 리사이즈
img_w, img_h = self.screenshot.size
if img_w != width or img_h != height:
    print(f"[DPI보정] 캡쳐이미지({img_w}×{img_h}) → Tkinter창({width}×{height})으로 리사이즈")
    self.screenshot = self.screenshot.resize((width, height), Image.Resampling.LANCZOS)
```

**적용 우선순위:**
1. `SetProcessDpiAwareness(2)` — Per-Monitor DPI V2 (Windows 10 Anniversary+)
2. `SetProcessDpiAwareness(1)` — Per-Monitor DPI V1 (Windows 8.1+)  
3. `SetProcessDPIAware()` — 시스템 DPI (레거시 폴백)

### 수정 파일
- `capture_window.py` — DPI Awareness 설정 + 이미지 크기 보정

---
