import json
import os
import re
import subprocess
from PIL import Image, ImageDraw, ImageFilter, ImageOps

# 1. 개인정보 탐지를 위한 정규표현식 정의
# 주민등록번호/외국인등록번호 (예: 950101-1234567, 19790722-1234567, 대시 필수)
# 앞자리는 반드시 6자리(YYMMDD) 또는 8자리(YYYYMMDD)로만 허용하여 오탐 최소화
RRN_PATTERN = re.compile(r'\b(\d{6}|\d{8})-[1-8]\d{6}\b')

# 전화번호 (01x-xxxx-xxxx 및 대시 없는 형태)
# 대괄호로 감싸진 형태([010], [3559] 등 입력 필드 UI OCR 오인식 대응) 포함
PHONE_PATTERN = re.compile(
    r'\[?\b01[0-9]\]?[-\s]?\[?\d{3,4}\]?[-\s]?\[?\d{4}\]?\b'
    r'|\b01[0-9]\d{7,8}\b'
    r'|\b0[2-6]\d?-\d{3,4}-\d{4}\b'
)

# 이메일 주소
EMAIL_PATTERN = re.compile(r'\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b')

# 신용카드 번호
CARD_PATTERN = re.compile(r'\b\d{4}-\d{4}-\d{4}-\d{4}\b|\b\d{16}\b')

# 계좌번호 (은행 계좌번호 포맷: 3~6자리 - 2~6자리 - 3~6자리)
BANK_PATTERN = re.compile(r'\b\d{3,6}-\d{2,6}-\d{3,6}\b')

# 생년월일 (구분자 필수, 달/일 범위를 명시적으로 한정하여 버전번호(3.5.2)·IP 오탐 방지)
# 4자리 연도: 1900~2099, 2자리 연도: 00~99, 달: 01~12, 일: 01~31 범위 강제
BIRTH_PATTERN = re.compile(
    r'\b(?:(19|20)\d{2}|\d{2})'
    r'[-./]'
    r'(0[1-9]|1[0-2])'
    r'[-./]'
    r'(0[1-9]|[12]\d|3[01])\b'
)

# 여권번호 (한국 여권 포맷)
# - 신형: 영문 1자(M/R) + 숫자 8자리 (예: M12345678)
# - 구형: 영문 2자 + 숫자 7자리 (예: AB1234567)
# - 구형2: 영문 1자 + 숫자 7자리 + 영문 1자 (예: M1234567A)
PASSPORT_PATTERN = re.compile(r'\b[A-Z]\d{8}\b|\b[A-Z]{2}\d{7}\b|\b[A-Z]\d{7}[A-Z]\b')

# 운전면허번호 (한글 지역명 및 숫자 지역코드 대응)
DRIVER_PATTERN = re.compile(r'\b\d{2}-\d{2}-\d{6}-\d{2}\b|\b[가-힣]{2}-\d{2}-\d{6}-\d{2}\b')

# 차량번호 (자동차등록번호)
# - 신형(2019+): 12가1234 / 123가1234  (숫자2~3 + 한글1 + 숫자4)
# - 구형: 서울12가1234 / 서울 12 가 1234  (지역명 + 숫자2 + 한글1 + 숫자4)
# 허용 한글(차량용 문자): 가나다라마거너더러머버서어저고노도로모보소오조구누두루무부수우주하허호
_VEH_CH = r'[가나다라마거너더러머버서어저고노도로모보소오조구누두루무부수우주하허호]'
VEHICLE_PATTERN = re.compile(
    rf'(?<!\d)'                       # 앞에 숫자 없음
    rf'(?:[가-힣]{{2,3}}\s*)?'        # 선택적 지역명 (서울, 경기 등)
    rf'\d{{2,3}}\s*{_VEH_CH}\s*\d{{4}}'  # 숫자2~3 + 차량한글 + 숫자4
    rf'(?!\d)'                        # 뒤에 숫자 없음
)

# IP 주소 패턴 (IPv4)
IP_PATTERN = re.compile(r'\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b')

# 주소 패턴 (시/도 및 구/동/읍/면/로/길 행정구역 특징 매칭)
ADDRESS_PATTERN = re.compile(r'\b[가-힣]{2,4}[시도]\b.*\b[가-힣]+[구동읍면로길]\b')

# 한글 이름 성씨 패턴 (한국인 인구 대다수를 차지하는 주요 성씨 32종)
# 일반 명사의 접두사로 오남용되는 희귀 성씨들을 걷어내어 오탐지를 최소화합니다.
SURNAMES = "김이박최정강조윤장임한오서신권황안송전홍유고문양손배백허남심노하지"
NAME_PATTERN = re.compile(rf'^[{SURNAMES}][가-힣]{{1,3}}$')

# 2글자 단어가 한글 이름으로 인정받기 위해 필요한 이름 음절 (다빈도 인명용)
COMMON_NAME_SYLLABLES = set("준서민영지수진훈현우호재태철석성원경은선혜연윤동건창병상종규환용승아희락필엽곤혁찬솔슬비빈율설담은겸송원지윤희주은재민하율예준서윤")

# 한글 이름 부분(성씨를 제외한 글자들)에 포함될 수 없는 인명 금지 음절 목록
# 업무용 단어(예: 조회, 수정, 등록, 전체, 배치, 백업, 관리, 정보, 이력, 노드, 조직 등)에서 파생되는 글자들 차단
# ※ 주의: 장(이장훈), 화(김화진), 국(박국현), 함(함준혁) 등은 실제 인명용 음절이므로 제외함
FORBIDDEN_NAME_SYLLABLES = set("의체업치류객권법제과식품판표물별역력록학교실점비통등및것요됨할적용조회합식단")

# 한글 이름 오인식 방지를 위한 일반 업무용 및 시스템 메뉴 제외 명사 리스트 (Blacklist)
EXCLUDE_NOUNS = {
    # 기본 업무 속성 및 직급
    "이름", "사번", "직급", "부서", "연락처", "주소", "입사", "퇴사", "사원", "대리", 
    "과장", "부장", "차장", "주임", "본부", "팀장", "센터", "관리", "본부장", "센터장", 
    "일반", "개발", "지원", "보상", "기획", "재물", "팀원", "플랫폼", "직원", "담당", 
    "전사", "지점", "실장", "소장", "원장", "처장", "국장", "부서명", "직책", "직무",
    
    # IT 및 시스템 메뉴 명사
    "사용자", "그룹", "그룹관리", "사용자관리", "사용자목록", "목록", "상세", "조회", "수정", 
    "삭제", "등록", "추가", "검색", "설정", "시스템", "코드", "코드관리", "메뉴", "메뉴관리", 
    "대시보드", "운영대시보드", "대시", "보드", "서비스", "서비스요청", "서비스관리", "업무", 
    "업무관리", "보고", "주간보고", "주간보고관리", "계약", "계약관리", "알림", "알림이력", 
    "통합알림", "로그", "로그인", "접근이력", "로그이력", "변경이력", "이력", "이력조회",
    "노드", "노드관리", "조직", "조직도", "조직도관리", "계층", "계층관리", "트리", "맵",
    
    # 공통 UI 컴포넌트 및 업무 일반어
    "구분", "상태", "유형", "종류", "날짜", "일시", "시간", "수량", "금액", "가격", "비고",
    "확인", "취소", "저장", "닫기", "열기", "출력", "인쇄", "엑셀", "다운로드", "업로드",
    "전송", "복사", "붙여넣기", "이전", "다음", "완료", "실패", "성공", "오류", "에러",
    "대상", "조건", "필터", "정렬", "기본", "선택", "전체", "상세정보", "정보", "개인"
}


def is_likely_korean_name(text):
    """
    주어진 한글 텍스트가 실제 한국인 이름인지 상세 규칙을 기반으로 판별합니다.
    """
    if not text:
        return False
        
    # 불필요한 공백이나 가이드라인 기호(테두리 등)를 제거하고 순수 한글만 추출
    clean_text = re.sub(r'[^가-힣]', '', text)
    
    # 1. 2~4글자 한글만 허용
    if not (2 <= len(clean_text) <= 4):
        return False
        
    # 2. 첫 글자가 성씨 목록에 있어야 함
    surname = clean_text[0]
    if surname not in SURNAMES:
        return False
        
    name_part = clean_text[1:]
    
    # 3. 이름 부분에 인명 금지 음절이 있으면 제외
    if any(char in FORBIDDEN_NAME_SYLLABLES for char in name_part):
        return False
        
    # 4. 제외 명사 단어가 분석 텍스트 내에 포함되어 있거나 완전히 일치하는 경우 제외
    for noun in EXCLUDE_NOUNS:
        if noun in clean_text:
            return False
            
    # 5. 2글자 이름인 경우 (예: "허준", "지수", "조회")
    if len(clean_text) == 2:
        # 끝 글자(이름 부분)가 다빈도 인명용 음절 세트에 포함되어야만 인정
        if name_part[0] not in COMMON_NAME_SYLLABLES:
            return False
            
    return True

def is_valid_korean_date(yy_str, mm_str, dd_str):
    """
    앞 6자리 생년월일이 실제 달력 상 유효한 날짜인지 검증합니다. (오탐 방지 핵심)
    """
    try:
        yy = int(yy_str)
        mm = int(mm_str)
        dd = int(dd_str)
    except ValueError:
        return False
        
    if mm < 1 or mm > 12:
        return False
        
    # 각 월별 말일 계산
    # 주민번호에서는 앞 2자리만 제공되므로 4로 나누어 떨어지는 해를 대략 윤년으로 보고 2월 말일을 29일로 처리합니다.
    days_in_months = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    if (yy % 4 == 0):
        days_in_months[1] = 29
        
    if dd < 1 or dd > days_in_months[mm - 1]:
        return False
        
    return True


def verify_rrn_checksum(digits_only):
    """
    주민등록번호/외국인등록번호의 가중치 체크섬 공식을 검증합니다.
    2020년 10월 이후 발행된 주민번호는 임의 번호 부여로 체크섬이 성립하지 않을 수 있으므로,
    체크섬이 맞거나 혹은 날짜 유효성이 부합하는 경우 통과시킵니다.
    """
    if len(digits_only) != 13:
        return False
        
    # 날짜 유효성 1차 검증
    yy = digits_only[0:2]
    mm = digits_only[2:4]
    dd = digits_only[4:6]
    try:
        gender = int(digits_only[6])
    except ValueError:
        return False
    
    if gender < 1 or gender > 8:
        return False
        
    if not is_valid_korean_date(yy, mm, dd):
        return False
        
    # 체크섬 공식 계산
    # 가중치: 2,3,4,5,6,7,8,9,2,3,4,5
    nums = [int(x) for x in digits_only]
    weights = [2, 3, 4, 5, 6, 7, 8, 9, 2, 3, 4, 5]
    
    # 주민등록번호 체크섬 공식
    total = sum(n * w for n, w in zip(nums[:-1], weights))
    check_digit = (11 - (total % 11)) % 10
    
    # 외국인등록번호 체크섬 공식
    # 외국인번호의 뒷자리 성별 구분이 5, 6, 7, 8 인 경우 외국인 체크섬 공식을 따릅니다.
    if gender in [5, 6, 7, 8]:
        foreigner_digit = (13 - (total % 11)) % 10
        if nums[-1] == foreigner_digit:
            return True
            
    # 주민등록번호 체크섬이 일치하거나, 2020년 10월 이후 발행된 번호(체크섬 미적용)일 가능성을 열어둠
    # (앞 날짜와 성별 번호가 명확히 유효하면 체크섬 불일치라도 2020년 10월 이후 발행 번호로 간주하여 인정)
    if nums[-1] == check_digit:
        return True
        
    # 날짜 검증을 통과하고 성별 대역이 유효하다면 보수적으로 안전하게 마스킹 처리 (누락 방지)
    return True


def run_ocr(image_path):
    """
    Windows 내장 OCR 엔진의 인식률을 극대화하기 위해 이미지를 고품질로 4배 스케일업(Scale-up)하고,
    [autocontrast → UnsharpMask 선명화 → Otsu 근사 자동 임계값 이진화] 다단계 전처리를 거친 뒤
    PowerShell OCR을 호출합니다. 획득한 단어 좌표계를 원래 해상도에 맞춰 스케일다운 보정하여 반환합니다.
    OCR 인식 결과 단어가 5개 미만인 경우(어두운 배경 등 이진화 실패 의심), 이미지 반전 후 2단계 재시도합니다.
    """
    import tempfile
    from PIL import Image, ImageFilter, ImageOps

    scale_factor = 4.0  # 3.5 → 4.0: 소형 글자 및 저해상도 캡처 인식률 향상

    def compute_otsu_threshold(gray_image):
        """
        픽셀 히스토그램 기반 Otsu's Method 근사로 최적 이진화 임계값을 자동 계산합니다.
        numpy 없이 순수 Python + Pillow 히스토그램으로 구현하여 의존성 없이 동작합니다.
        """
        hist = gray_image.histogram()  # 256개 버킷의 픽셀 수
        total = sum(hist)
        if total == 0:
            return 127
        sum_all = sum(i * hist[i] for i in range(256))
        sum_b = 0.0
        w_b = 0
        max_var = 0.0
        threshold = 127
        for t in range(256):
            w_b += hist[t]
            if w_b == 0:
                continue
            w_f = total - w_b
            if w_f == 0:
                break
            sum_b += t * hist[t]
            mean_b = sum_b / w_b
            mean_f = (sum_all - sum_b) / w_f
            # 클래스 간 분산 극대화 (배경/글자 픽셀 군의 분리도 최대 지점)
            var_between = w_b * w_f * (mean_b - mean_f) ** 2
            if var_between > max_var:
                max_var = var_between
                threshold = t
        return threshold

    def preprocess_and_save(img_pil, invert=False):
        """
        이미지를 전처리(스케일업, autocontrast, UnsharpMask, Otsu 이진화)한 후
        임시 파일로 저장하고 경로를 반환합니다.
        invert=True이면 이진화 결과를 반전시켜 어두운 배경에 밝은 글자 환경을 보정합니다.
        """
        new_w = int(img_pil.width * scale_factor)
        new_h = int(img_pil.height * scale_factor)
        # LANCZOS 필터로 고품질 확대 (픽셀 깨짐, 계단 현상 방지)
        scaled_img = img_pil.resize((new_w, new_h), Image.Resampling.LANCZOS)
        # ── 다단계 OCR 전처리 파이프라인 ──────────────────────────────────
        # 1단계: Grayscale 변환 (컬러 채널 제거 → 명암 처리 집중)
        gray_img = scaled_img.convert("L")
        # 2단계: autocontrast로 히스토그램을 0~255 전 범위로 늘려 저대비 이미지 보정
        # cutoff=2: 양 극단 2% 픽셀 제외 → 밝은 테두리나 어두운 UI 배경에서 글자 대비 극대화
        contrast_img = ImageOps.autocontrast(gray_img, cutoff=2)
        # 3단계: UnsharpMask로 텍스트 외곽선 세밀 선명화
        # radius=2: 선명화 반경, percent=200: 선명화 강도, threshold=3: 노이즈 픽셀 보호
        sharp_img = contrast_img.filter(
            ImageFilter.UnsharpMask(radius=2, percent=200, threshold=3)
        )
        # 4단계: Otsu 근사 자동 임계값 이진화 (이미지마다 최적 분리 지점 자동 탐색)
        otsu_t = compute_otsu_threshold(sharp_img)
        if invert:
            # 반전 모드: 어두운 배경에 밝은 글자 시 Otsu 임계값을 반전하여 적용
            bin_img = sharp_img.point(lambda p: 0 if p > otsu_t else 255)
        else:
            bin_img = sharp_img.point(lambda p: 255 if p > otsu_t else 0)
        # ─────────────────────────────────────────────────────────────────
        temp_dir = tempfile.gettempdir()
        suffix = "_inv" if invert else ""
        tmp_path = os.path.join(
            temp_dir,
            f"temp_scaled_ocr{suffix}_{os.path.basename(image_path)}"
        )
        bin_img.save(tmp_path)
        return tmp_path

    def call_ps_ocr(ocr_img_path):
        """PowerShell OCR 스크립트를 호출하여 결과를 반환합니다."""
        script_path = os.path.join(os.path.dirname(__file__), "ocr_engine.ps1")
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = subprocess.SW_HIDE
        cmd = [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy", "Bypass",
            "-File", script_path,
            "-ImagePath", ocr_img_path
        ]
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            startupinfo=startupinfo,
            text=True,
            encoding="utf-8-sig",
            errors="replace"
        )
        if result.returncode != 0:
            return {"status": "error", "message": result.stderr}
        output_str = result.stdout.strip()
        json_start = output_str.find('{"status"')
        if json_start != -1:
            output_str = output_str[json_start:]
        return json.loads(output_str)

    # ── 메인 OCR 실행 흐름 ───────────────────────────────────────────────
    scaled_img_path = None
    ocr_result = {"status": "error", "message": "초기화 안 됨"}

    try:
        if os.path.exists(image_path):
            with Image.open(image_path) as img:
                # 1단계 시도: 정방향 전처리
                scaled_img_path = preprocess_and_save(img, invert=False)
                try:
                    ocr_result = call_ps_ocr(scaled_img_path)
                except Exception as e:
                    ocr_result = {"status": "error", "message": str(e)}

                # 2단계 시도: 1단계 인식 단어가 5개 미만이면 반전 이미지로 재시도
                # (어두운 배경에 밝은 글자 형태의 이미지에서 Otsu 이진화가 배경/글자를 뒤바꾸는 현상 보정)
                word_count = len(ocr_result.get("words", []))
                if ocr_result.get("status") != "success" or word_count < 5:
                    print(f"[OCR] 1단계 인식 단어수={word_count}, 반전 이미지로 2단계 재시도")
                    inv_path = None
                    try:
                        inv_path = preprocess_and_save(img, invert=True)
                        inv_result = call_ps_ocr(inv_path)
                        inv_word_count = len(inv_result.get("words", []))
                        # 반전 이미지에서 더 많은 단어가 인식되면 반전 결과 채택
                        if inv_word_count > word_count:
                            print(f"[OCR] 반전 결과({inv_word_count}개) > 정방향({word_count}개), 반전 결과 채택")
                            ocr_result = inv_result
                    except Exception as e:
                        print(f"[OCR] 2단계 반전 시도 예외: {e}")
                    finally:
                        if inv_path and os.path.exists(inv_path):
                            try:
                                os.remove(inv_path)
                            except:
                                pass

    except Exception as e:
        print(f"OCR 전처리 스케일업 및 이진화 중 예외 발생: {e}")
        # 실패 시 원본 경로로 롤백하여 OCR 시도
        scaled_img_path = image_path
        scale_factor = 1.0
        try:
            ocr_result = call_ps_ocr(scaled_img_path)
        except Exception as e2:
            ocr_result = {"status": "error", "message": str(e2)}
    finally:
        # 확대용 임시 파일 삭제 (원본 경로가 아닌 경우에만)
        if scaled_img_path and scaled_img_path != image_path:
            try:
                os.remove(scaled_img_path)
            except:
                pass

    # 확대 비율(scale_factor)에 맞춰 단어들의 좌표계를 원상 복구 (Scale-down)
    if ocr_result.get("status") == "success" and scale_factor > 1.0:
        words = ocr_result.get("words", [])
        for w in words:
            w['x'] = int(w['x'] / scale_factor)
            w['y'] = int(w['y'] / scale_factor)
            w['width'] = int(w['width'] / scale_factor)
            w['height'] = int(w['height'] / scale_factor)

    return ocr_result


def merge_boxes(boxes):
    """
    여러 단어들의 바운딩 박스를 하나의 큰 바운딩 박스로 병합합니다.
    """
    if not boxes:
        return None
    x1 = min(box['x'] for box in boxes)
    y1 = min(box['y'] for box in boxes)
    x2 = max(box['x'] + box['width'] for box in boxes)
    y2 = max(box['y'] + box['height'] for box in boxes)
    return {
        'x': x1,
        'y': y1,
        'width': x2 - x1,
        'height': y2 - y1
    }


def calculate_sub_masks(text, x, y, width, height, name_mask_style="middle"):
    """
    텍스트 종류를 분석하여 우리나라 실정에 맞는 정밀한 부분 마스킹 사각형 영역 목록을 계산합니다.
    """
    sub_masks = []
    char_w = width / max(1, len(text))
    
    # 1. 주민등록번호 / 외국인등록번호 (예: 950101-1*****)
    # 생년월일과 성별(뒷자리 첫 번호)을 제외한 뒤 6자리 마스킹
    is_rrn = False
    digits_only = re.sub(r'\D', '', text)
    if RRN_PATTERN.search(text) or ((len(digits_only) == 13 or len(digits_only) == 15) and re.match(r'^(\d{6}|\d{8})[1-8]\d{6}$', digits_only)):
        is_rrn = True
        
    if is_rrn:
        dash_idx = text.find('-')
        if dash_idx != -1:
            # 대시가 있는 경우 (예: 950101-1234567 -> 950101-1*****)
            # 앞 6자리(생년월일) + 대시 1자리 + 성별 1자리 = 8자리 노출, 9번째(index 8)부터 6글자 가림
            w_back = 6 * char_w
            sub_masks.append({
                'x': int(x + 8 * char_w),
                'y': y,
                'width': int(w_back),
                'height': height
            })
        else:
            # 대시가 없는 경우 (예: 9501011234567 -> 9501011*****)
            # 앞 6자리(생년월일) + 성별 1자리 = 7자리 노출, 8번째(index 7)부터 6글자 가림
            w_back = 6 * char_w
            sub_masks.append({
                'x': int(x + 7 * char_w),
                'y': y,
                'width': int(w_back),
                'height': height
            })
        return sub_masks
            
    # 2. 생년월일 (예: 1979.07.22 / 1979-07-22 -> 19******)
    # 연도 앞 2자리만 남기고 뒤를 전부 가림
    elif BIRTH_PATTERN.search(text):
        w_mask = (len(text) - 2) * char_w
        sub_masks.append({
            'x': int(x + 2 * char_w),
            'y': y,
            'width': int(w_mask),
            'height': height
        })
        return sub_masks
        
    # 3. 전화번호 / 휴대전화번호 (예: 010-1234-5678 -> 010-****-5678)
    # 가운데 4자리(국번) 마스킹
    elif PHONE_PATTERN.search(text):
        if '-' in text:
            # 대시 포함 포맷 (예: 010-1234-5678)
            # 첫 번째 대시 직후(index = 대시 인덱스 + 1)부터 4글자 국번 가림
            dash_idx = text.find('-')
            sub_masks.append({
                'x': int(x + (dash_idx + 1) * char_w),
                'y': y,
                'width': int(4 * char_w),
                'height': height
            })
        else:
            # 대시 미포함 포맷 (예: 01012345678)
            # 앞 3자리(010)를 제외하고 index 3부터 4글자 국번 가림
            sub_masks.append({
                'x': int(x + 3 * char_w),
                'y': y,
                'width': int(4 * char_w),
                'height': height
            })
        return sub_masks
        
    # 4. 한글 사람 이름 (예: 김선기 -> 김*기 / 허준 -> 허* / 독고영재 -> 독**재)
    elif is_likely_korean_name(text):
        clean_text = re.sub(r'[^가-힣]', '', text)
        if name_mask_style == "surname":
            # 성씨만 남김 (예: 김선기 -> 김**, 허준 -> 허*, 독고영재 -> 독***)
            if len(clean_text) >= 2:
                sub_masks.append({
                    'x': int(x + char_w),
                    'y': y,
                    'width': int((len(clean_text) - 1) * char_w),
                    'height': height
                })
        else:
            # 글자수별 표준 마스킹
            if len(clean_text) == 2:
                # 2글자 이름: 뒷글자 마스킹 (예: 허준 -> 허*)
                sub_masks.append({
                    'x': int(x + char_w),
                    'y': y,
                    'width': int(char_w),
                    'height': height
                })
            elif len(clean_text) == 3:
                # 3글자 이름: 가운데 1글자 마스킹 (예: 김선기 -> 김*기)
                sub_masks.append({
                    'x': int(x + char_w),
                    'y': y,
                    'width': int(char_w),
                    'height': height
                })
            elif len(clean_text) >= 4:
                # 4글자 이상 이름: 첫 글자와 마지막 글자를 제외한 중간 글자 모두 마스킹 (예: 독고영재 -> 독**재)
                w_mask = (len(clean_text) - 2) * char_w
                sub_masks.append({
                    'x': int(x + char_w),
                    'y': y,
                    'width': int(w_mask),
                    'height': height
                })
        return sub_masks

    # 5. 운전면허번호 (예: 11-12-123456-11 -> 11-12-******-11)
    # 지역 코드 및 앞자리 일부를 제외한 뒤 5~6자리 마스킹 (3번째 대시 그룹 가림)
    elif DRIVER_PATTERN.search(text):
        parts = text.split('-')
        if len(parts) >= 3:
            start_idx = len(parts[0]) + 1 + len(parts[1]) + 1
            w_mask = len(parts[2]) * char_w
            sub_masks.append({
                'x': int(x + start_idx * char_w),
                'y': y,
                'width': int(w_mask),
                'height': height
            })
        else:
            # 대시가 깨진 경우 중간 영역 가림
            sub_masks.append({
                'x': int(x + 4 * char_w),
                'y': y,
                'width': int(6 * char_w),
                'height': height
            })
        return sub_masks

    # 6. 여권번호 (예: M12345678 -> M123*****)
    # 영문자 뒤의 숫자 중간 또는 뒷자리 4~5자리 마스킹 (앞 4자리 노출 후 나머지 마스킹)
    elif PASSPORT_PATTERN.search(text):
        w_mask = (len(text) - 4) * char_w
        if w_mask > 0:
            sub_masks.append({
                'x': int(x + 4 * char_w),
                'y': y,
                'width': int(w_mask),
                'height': height
            })
        return sub_masks

    # 7. 이메일 주소 → 전체 마스킹 (예: kim@company.com → ███████████████)
    # 아이디+도메인 전체를 하나의 박스로 가립니다.
    elif EMAIL_PATTERN.search(text):
        sub_masks.append({
            'x': x,
            'y': y,
            'width': width,
            'height': height
        })
        return sub_masks

    # 8. 신용카드 번호 (예: 1234-1234-1234-1234 -> 1234-****-****-1234)
    # 중간 8자리(2번째, 3번째 번호군) 마스킹
    elif CARD_PATTERN.search(text):
        if '-' in text:
            # 대시 포함: 5번째 인덱스부터 9글자(대시 2개 포함) 마스킹
            sub_masks.append({
                'x': int(x + 5 * char_w),
                'y': y,
                'width': int(9 * char_w),
                'height': height
            })
        else:
            # 대시 미포함: 4번째 인덱스부터 8글자 마스킹
            sub_masks.append({
                'x': int(x + 4 * char_w),
                'y': y,
                'width': int(8 * char_w),
                'height': height
            })
        return sub_masks

    # 9. 계좌번호 (예: 110-123-456789 -> 110-123-*****)
    # 은행 코드 및 앞자리를 제외한 실 계좌번호 뒤 5~6자리 마스킹
    elif BANK_PATTERN.search(text):
        w_mask = 6 * char_w
        if len(text) > 6:
            sub_masks.append({
                'x': int(x + (len(text) - 6) * char_w),
                'y': y,
                'width': int(w_mask),
                'height': height
            })
        return sub_masks

    # 10. IP 주소 (예: 192.168.1.1 -> 192.168.*.**)
    # C클래스 또는 D클래스 영역 마스킹 (2번째 점 뒤의 모든 영역 가림)
    elif IP_PATTERN.search(text):
        dots = [i for i, char in enumerate(text) if char == '.']
        if len(dots) >= 2:
            start_idx = dots[1] + 1
            w_mask = (len(text) - start_idx) * char_w
            sub_masks.append({
                'x': int(x + start_idx * char_w),
                'y': y,
                'width': int(w_mask),
                'height': height
            })
        return sub_masks

    # 11. 주소 (예: 경기도 성남시 수정구 태평동 123 -> 경기도 성남시 수정구 ****)
    # 시·군·구(또는 읍·면·동) 등 행정구역까지만 노출하고 상세 주소 전체 마스킹
    elif ADDRESS_PATTERN.search(text):
        match = None
        for kw in ["구", "동", "읍", "면", "로", "길", "시", "도"]:
            idx = text.rfind(kw)
            if idx != -1:
                match = idx + 1
                break
        if match and match < len(text):
            sub_masks.append({
                'x': int(x + match * char_w),
                'y': y,
                'width': int((len(text) - match) * char_w),
                'height': height
            })
        return sub_masks

    # 12. 차량번호 (예: 12가1234 → 12가****  /  서옧0312나1234 → 서옧0312나****)
    # 숫자 앞자리와 한글 문자는 노출, 뒤 4자리 숫자만 마스킹
    elif VEHICLE_PATTERN.search(text):
        m = VEHICLE_PATTERN.search(text)
        if m:
            matched_str = m.group()
            # 매치된 문자열 내에서 마지막 4자리 숫자 위치 찾기
            # (12가1234 형에서 마지막 \d{4} 시작 인덱스)
            last4_match = re.search(r'\d{4}$', matched_str)
            if last4_match:
                # 원본 text 내 실제 시작 위치 계산
                offset_in_text = m.start() + last4_match.start()
                sub_masks.append({
                    'x': int(x + offset_in_text * char_w),
                    'y': y,
                    'width': int(4 * char_w),
                    'height': height
                })
        return sub_masks

    # 매칭되는 항목이 없으면 마스킹하지 않음 (단순 사번이나 숫자 시퀀스 보호)
    return []


def detect_layout_based_info_and_indices(words, name_mask_style="middle"):
    """
    레이블(성명, 주민번호, 휴대폰, 생년월일 등 11종) 텍스트의 우측 인접 영역을 탐색하여
    개인정보 영역을 강제로 식별하고 마스킹 좌표와 사용된 단어들의 인덱스 세트를 반환합니다.
    레이블이 여러 단어로 OCR 인식된 경우 동일 행의 연속된 레이블 단어들을 합산하여 전체 레이블
    바운딩박스를 label_regions에 저장하여 노란 강조 표시 영역을 정확히 반영합니다.
    """
    NAME_LABELS = {
        "성명", "민원인성명", "고객명", "이름", "대표자", "대표자명", "성 명", "민원인 성명",
        "보회자", "피보험자", "피보험자명", "인원인", "인원점수번호", "보회자Q卜", "보회云|략", "피보"
    }
    RRN_LABELS = {
        "주민등록번호", "주민번호", "실명번호", "외국인등록번호", "등록번호", "주민등록 번호",
        "주원들릨ä호", "주원들", "릨ä호", "들릨ä", "주원", "주민등록", "등록번호", "주원들릨", "릨ä",
        "주인등록변호", "주인등록", "등록변호", "변호", "주인등록변"
    }
    PHONE_LABELS = {
        "휴대폰번호", "휴대폰", "연락처", "전화번호", "핸드폰", "이동전화", "휴대폰 번호", "전화 번호",
        "폰번", "폰번호", "핸드폰번호", "폰 번"
    }
    DRIVER_LABELS = {"운전면허번호", "운전면허", "면허번호", "면허", "운전"}
    PASSPORT_LABELS = {"여권번호", "여권"}
    EMAIL_LABELS = {"이메일주소", "이메일", "E-Mail", "email", "이매일"}
    ADDRESS_LABELS = {"주소", "소재지", "주 소"}
    CARD_LABELS = {"신용카드", "카드번호", "카드"}
    BANK_LABELS = {"계좌번호", "계좌"}
    IP_LABELS = {"IP주소", "IP", "아이피"}
    # 차량번호 레이블
    VEHICLE_LABELS = {
        "차량번호", "자동차번호", "차 번호", "차량 번호", "자동차 번호",
        "차번호", "등록번호", "시고번호", "사고차량", "차량"
    }
    # 생년월일 레이블 (layout-based 탐지 추가)
    BIRTH_LABELS = {"생년월일", "생년", "생년월", "출생년월일", "생일", "출생일", "생년월일일"}
    # 주소 행정구역 키워드 (다중 단어 주소 수집 시 사용)
    ADDR_KEYWORDS = {"시", "도", "구", "군", "동", "읍", "면", "로", "길", "가", "번지", "번", "호"}

    mask_regions = []
    label_regions = []  # 개인정보 항목명(레이블) 단어들의 바운딩박스 목록
    used_indices = set()

    for idx, w in enumerate(words):
        w['_idx'] = idx

    def collect_label_box(anchor_word):
        """
        레이블 기준 단어(anchor_word)와 동일 행(Y좌표 오차 내)에서
        바로 인접(X 연속)한 단어들을 함께 수집하여 레이블 전체 박스를 반환합니다.
        OCR이 '주민 등록 번호'처럼 여러 단어로 분리하여 인식하더라도 하나의
        넓은 박스로 합산하여 노란 강조 표시가 정확히 항목명 전체를 덮도록 합니다.
        """
        y_tol = max(anchor_word['height'] * 0.8, 10)
        # 동일 행의 모든 단어를 X순으로 정렬하여 앵커 기준으로 인접 여부 확인
        same_row = sorted(
            [w for w in words if abs(w['y'] - anchor_word['y']) <= y_tol],
            key=lambda w: w['x']
        )
        # 앵커 단어 인덱스 찾기
        anchor_idx_in_row = next(
            (i for i, w in enumerate(same_row) if w.get('_idx') == anchor_word.get('_idx')),
            None
        )
        if anchor_idx_in_row is None:
            return {'x': anchor_word['x'], 'y': anchor_word['y'],
                    'width': anchor_word['width'], 'height': anchor_word['height']}

        # 앵커 기준 왼쪽/오른쪽으로 레이블 키워드에 해당하는 연속 단어 수집
        # 단, 오른쪽 수집은 candidates(값 영역) 직전까지만 포함
        label_word_group = [anchor_word]
        max_gap = max(anchor_word['height'] * 1.5, 20)

        # 왼쪽 방향 (앵커의 왼쪽에 붙어있는 레이블 선행 단어 수집)
        for i in range(anchor_idx_in_row - 1, -1, -1):
            w = same_row[i]
            gap = anchor_word['x'] - (w['x'] + w['width'])
            if gap > max_gap:
                break
            w_clean = re.sub(r'\s+', '', w['text'])
            if not w_clean or w_clean in EXCLUDE_NOUNS:
                break
            # 숫자나 특수문자만 있는 단어는 레이블 아님
            if re.match(r'^[\d\-*]+$', w_clean):
                break
            label_word_group.insert(0, w)

        # 오른쪽 방향 (앵커 바로 오른쪽에 붙어있는 레이블 후속 단어 수집)
        # 단, 앵커 단어에 콜론(:)이 이미 포함되어 있으면 레이블이 끝났으므로 오른쪽 확장 없음
        anchor_text_raw = re.sub(r'\s+', '', anchor_word['text'])
        if ':' not in anchor_text_raw and '\uff1a' not in anchor_text_raw:
            for i in range(anchor_idx_in_row + 1, len(same_row)):
                w = same_row[i]
                prev = same_row[i - 1]
                gap = w['x'] - (prev['x'] + prev['width'])
                if gap > max_gap:
                    break
                w_clean = re.sub(r'\s+', '', w['text'])
                if not w_clean or w_clean in EXCLUDE_NOUNS:
                    break
                # 콜론(:) 포함 단어가 나오면 해당 단어까지 수집 후 중단 (레이블의 마지막 토큰)
                has_colon = ':' in w_clean or '\uff1a' in w_clean
                # 숫자나 특수문자가 주를 이루면 이미 값 영역 시작으로 판단 → 중단
                pure_no_colon = w_clean.replace(':', '').replace('\uff1a', '')
                if re.match(r'^[\d\-*\.]+$', pure_no_colon) or re.search(r'\d{4}', w_clean):
                    break
                # 순수 한글 2~4자 단어는 이름/값 가능성이 높으므로 중단 (레이블 후속 단어 아님)
                hangul_only = re.sub(r'[^가-힣]', '', w_clean)
                if 2 <= len(hangul_only) <= 4 and len(w_clean) == len(hangul_only):
                    break
                label_word_group.append(w)
                if has_colon:
                    break  # 콜론이 있는 단어까지 포함하고 중단

        merged = merge_boxes(label_word_group)
        if merged:
            return merged
        return {'x': anchor_word['x'], 'y': anchor_word['y'],
                'width': anchor_word['width'], 'height': anchor_word['height']}

    # ── 사전 스캔: 동일 행의 연속 단어들을 결합하여 레이블 키워드 탐지 ────────────────────
    # OCR이 '민원인성명'→['민원','인성','명'] 처럼 분리 인식할 때를 보완합니다.
    # 동일 행(Y 오차 내)의 인접 단어들을 슬라이딩 윈도우로 결합해 레이블을 찾으면
    # 첫 번째 단어를 앵커로 레이블 탐지를 처리합니다.
    ALL_LABEL_KEYWORDS = [
        # (결합 키워드, 레이블_타입)
        ("민원인성명", "name"), ("민원인", "name"), ("인성명", "name"),
        ("고객성명", "name"), ("보험계약자", "name"), ("피보험자명", "name"),
        ("주민등록번호", "rrn"), ("주민번호", "rrn"), ("외국인등록번호", "rrn"),
        ("휴대폰번호", "phone"), ("전화번호", "phone"), ("핸드폰번호", "phone"),
        ("생년월일", "birth"), ("출생년월일", "birth"),
        ("여권번호", "passport"), ("운전면허번호", "driver"),
        ("이메일주소", "email"),
    ]

    # Y 기준으로 행 그룹화
    if words:
        sorted_for_pre = sorted(words, key=lambda w: (w['y'], w['x']))
        row_groups_pre = []
        cur_row_pre = [sorted_for_pre[0]]
        for wi in sorted_for_pre[1:]:
            if abs(wi['y'] - cur_row_pre[0]['y']) <= max(cur_row_pre[0]['height'] * 0.8, 8):
                cur_row_pre.append(wi)
            else:
                row_groups_pre.append(cur_row_pre)
                cur_row_pre = [wi]
        row_groups_pre.append(cur_row_pre)

        for row_pre in row_groups_pre:
            row_pre.sort(key=lambda w: w['x'])
            n_pre = len(row_pre)
            # 윈도우 크기 2~4개 단어를 결합하여 레이블 키워드 탐색
            for win_size in range(2, min(5, n_pre + 1)):
                for i_pre in range(n_pre - win_size + 1):
                    chunk = row_pre[i_pre: i_pre + win_size]
                    # 인접 단어 간격 검증 (너무 멀면 결합 안 함)
                    adjacent = True
                    for k_pre in range(len(chunk) - 1):
                        gap_pre = chunk[k_pre + 1]['x'] - (chunk[k_pre]['x'] + chunk[k_pre]['width'])
                        if gap_pre > max(chunk[0]['height'] * 2.0, 20):
                            adjacent = False
                            break
                    if not adjacent:
                        continue
                    combined_text = re.sub(r'\s+', '', ''.join(w['text'] for w in chunk))
                    # 레이블 키워드 매칭
                    for kw, lbl_type in ALL_LABEL_KEYWORDS:
                        if kw in combined_text:
                            # 첫 단어를 앵커로 레이블 박스 수집 및 마스킹 진행
                            anchor = chunk[0]
                            # 이미 처리된 앵커면 스킵
                            if anchor.get('_pre_scanned'):
                                break
                            anchor['_pre_scanned'] = True
                            anchor['_pre_label_type'] = lbl_type
                            # 연속 단어들의 레이블 박스 수동 합산
                            label_box_pre = merge_boxes(chunk)
                            if label_box_pre:
                                label_regions.append(label_box_pre)
                            break
    # ─────────────────────────────────────────────────────────────────────────

    for word in words:
        text_clean = re.sub(r'\s+', '', word['text'])

        matched_label_type = None

        # 사전 스캔에서 이미 레이블로 처리된 단어는 타입 승계
        if word.get('_pre_scanned'):
            matched_label_type = word.get('_pre_label_type')

        # 1. 성명 레이블 판정 완화 (오인식 오타 대응)
        elif any(lbl in text_clean for lbl in NAME_LABELS) or (
            "민원" in text_clean and "성" in text_clean) or (
            "성" in text_clean and "명" in text_clean) or (
            "보회" in text_clean) or (
            "인원" in text_clean and "성" in text_clean) or (
            "인성" in text_clean) or (
            text_clean.endswith("명") and len(text_clean) >= 2):
            matched_label_type = "name"

        # 2. 주민번호 레이블 판정 완화 (오인식 오타 대응 및 유사성 결합 매칭)
        elif (any(lbl in text_clean for lbl in RRN_LABELS) or
              ("주민" in text_clean and "번호" in text_clean) or
              ("등록" in text_clean and "번호" in text_clean) or
              ("주원" in text_clean) or ("들릨" in text_clean) or ("릨ä" in text_clean) or
              ("주인" in text_clean and "변호" in text_clean) or
              ("주" in text_clean and ("번호" in text_clean or "변호" in text_clean or "호" in text_clean)) or
              ("등록" in text_clean and ("번호" in text_clean or "변호" in text_clean or "호" in text_clean))):
            if "접수" not in text_clean and "제휴" not in text_clean:
                matched_label_type = "rrn"

        # 3. 휴대폰 레이블 판정 완화 (오인식 오타 대응)
        elif any(lbl in text_clean for lbl in PHONE_LABELS) or (
            "휴대" in text_clean and "번호" in text_clean) or (
            "휴대" in text_clean and "폰" in text_clean) or (
            "전화" in text_clean and "번호" in text_clean) or (
            "폰번" in text_clean):
            if "접수" not in text_clean and "제휴" not in text_clean:
                matched_label_type = "phone"
        # 4. 생년월일 레이블 판정 (신규 추가)
        elif any(lbl in text_clean for lbl in BIRTH_LABELS) or (
            "생년" in text_clean and ("월" in text_clean or "일" in text_clean)):
            matched_label_type = "birth"
        elif any(lbl in text_clean for lbl in DRIVER_LABELS):
            matched_label_type = "driver"
        elif any(lbl in text_clean for lbl in PASSPORT_LABELS):
            matched_label_type = "passport"
        elif any(lbl in text_clean for lbl in EMAIL_LABELS):
            matched_label_type = "email"
        elif any(lbl in text_clean for lbl in ADDRESS_LABELS):
            matched_label_type = "address"
        elif any(lbl in text_clean for lbl in CARD_LABELS):
            matched_label_type = "card"
        elif any(lbl in text_clean for lbl in BANK_LABELS):
            matched_label_type = "bank"
        elif any(lbl in text_clean for lbl in IP_LABELS):
            matched_label_type = "ip"
        elif any(lbl in text_clean for lbl in VEHICLE_LABELS):
            matched_label_type = "vehicle"

        if not matched_label_type:
            continue

        # ── 레이블 단어 전체의 바운딩박스를 label_regions에 추가 (노란 강조 표시용) ──
        # 사전 스캔에서 이미 추가한 레이블는 중복 추가 하지 않음
        if not word.get('_pre_scanned'):
            label_box = collect_label_box(word)
            label_regions.append(label_box)

        # 후보 탐색 기준점: 사전스캔 그룹이면 그룹의 마지막 레이블 단어 기준으로 보정
        effective_label_word = word
        if word.get('_pre_scanned'):
            y_tol_eff = max(word['height'] * 0.8, 10)
            same_row_eff = sorted(
                [w for w in words if abs(w['y'] - word['y']) <= y_tol_eff],
                key=lambda w: w['x']
            )
            found_anchor_pos = next(
                (i for i, w in enumerate(same_row_eff) if w.get('_idx') == word.get('_idx')), None
            )
            if found_anchor_pos is not None:
                max_gap_eff = max(word['height'] * 2.0, 20)
                last_label_word = word
                for k_eff in range(found_anchor_pos + 1, len(same_row_eff)):
                    nw = same_row_eff[k_eff]
                    gap_eff = nw['x'] - (last_label_word['x'] + last_label_word['width'])
                    if gap_eff > max_gap_eff:
                        break
                    nw_clean = re.sub(r'\s+', '', nw['text'])
                    if re.match(r'^[\d\-*\.]+$', nw_clean) or re.search(r'\d{4}', nw_clean):
                        break
                    hangul_only_eff = re.sub(r'[^\uac00-\ud7a3]', '', nw_clean)
                    if 2 <= len(hangul_only_eff) <= 4 and len(nw_clean) == len(hangul_only_eff):
                        break
                    last_label_word = nw
                effective_label_word = last_label_word

        # Y축 오차 허용치를 최소 30픽셀 이상으로 넉넉하게 잡음 (표 내부 셀 정렬 편차 극복)
        y_tolerance = max(word['height'] * 2.0, 30)
        
        candidates = []
        lbl_ref = effective_label_word  # 후보 탐색 기준점 (사전스캔 시 마지막 레이블 단어)
        for other in words:
            if other['_idx'] == word['_idx']:
                continue
            # Y축 오차 범위 내
            if abs(other['y'] - lbl_ref['y']) <= y_tolerance:
                # X축은 레이블 우측 (레이블 텍스트 폭의 절반 이상 오른쪽에 있는 것)
                if other['x'] > lbl_ref['x'] + lbl_ref['width'] * 0.5:
                    candidates.append(other)

        # X축 순서로 정렬
        candidates.sort(key=lambda c: c['x'])
        
        if not candidates and matched_label_type != "address":
            continue
            
        # 레이블별 매칭 로직
        if matched_label_type == "name":
            # 성명 우측의 첫 번째 텍스트 단어 탐색 (성명 필수 별표* 기호는 필터링)
            max_name_gap = max(word['height'] * 15.0, 250)
            
            for cand in candidates:
                gap = cand['x'] - (word['x'] + word['width'])
                if gap > max_name_gap:
                    break
                
                # 공백과 특수문자를 제거한 텍스트
                cand_clean = re.sub(r'[^가-힣a-zA-Z]', '', cand['text'])
                
                # 비어있거나 제외 명사 리스트에 속하면 건너뜀
                if not cand_clean or cand_clean in EXCLUDE_NOUNS:
                    continue
                    
                # 후보 단어가 사전스캔 레이블 그룹에 속하면 이름이 아니므로 건너뛰
                if cand.get('_pre_scanned'):
                    continue

                # 2글자 이상이면 이름으로 간주하여 즉시 마스킹
                if len(cand_clean) >= 2:
                    sub_masks = calculate_sub_masks(cand['text'], cand['x'], cand['y'], cand['width'], cand['height'], name_mask_style)
                    if sub_masks:
                        mask_regions.extend(sub_masks)
                    else:
                        mask_regions.append({
                            'x': cand['x'], 'y': cand['y'], 'width': cand['width'], 'height': cand['height']
                        })
                    used_indices.add(cand['_idx'])
                    break  # 첫 번째 이름 단어만 마스킹하고 종료
                    
        elif matched_label_type == "rrn":
            # 주민번호의 경우: 레이블 우측 X 범위 내에 존재하는 단어들을 수집
            # OCR 판독 깨짐 현상(예: ]圍1叫-1圄815)을 고려하여 숫자/대시 패턴에 얽매이지 않고 유효 값을 수집합니다.
            rrn_words = []
            max_rrn_gap = max(word['height'] * 15.0, 250)
            
            for cand in candidates:
                gap = cand['x'] - (word['x'] + word['width'])
                if gap > max_rrn_gap:
                    break
                
                # 순수 별표 단독 기호(필수 입력 별표* 등)는 주민번호 값 시작이 아니므로 스킵
                if cand['text'].strip() == '*' and not rrn_words:
                    continue
                    
                cand_clean = re.sub(r'\s+', '', cand['text'])
                
                # 비어있거나 시스템 명사(조회, 수정 등)에 해당하면 스킵
                if not cand_clean or cand_clean in EXCLUDE_NOUNS:
                    continue
                    
                rrn_words.append(cand)
                    
            if rrn_words:
                merged = merge_boxes(rrn_words)
                if merged:
                    combined_text = "".join(w['text'] for w in rrn_words)
                    sub_masks = calculate_sub_masks(combined_text, merged['x'], merged['y'], merged['width'], merged['height'], name_mask_style)
                    if sub_masks:
                        mask_regions.extend(sub_masks)
                    else:
                        mask_regions.append(merged)
                    for rw in rrn_words:
                        used_indices.add(rw['_idx'])
                        
        elif matched_label_type == "phone":
            # 휴대폰 번호: 레이블 우측 X 범위 내의 숫자/대시/별표 조합 단어들을 수집
            # 3분리 입력 필드([010] - [3559] - [4313]) 형태 완전 지원
            phone_words = []
            # gap을 레이블 기준이 아닌 직전 수집 단어 기준으로 계산 (분리 필드가 멀어도 수집)
            max_phone_seg_gap = max(word['height'] * 8.0, 120)  # 세그먼트 간 최대 허용 간격
            max_phone_start_gap = max(word['height'] * 20.0, 400)  # 레이블→첫 값 최대 간격

            prev_collected = None  # 직전에 수집한 단어

            for cand in candidates:
                if prev_collected is None:
                    # 아직 아무것도 수집 전: 레이블 기준 gap 체크
                    gap = cand['x'] - (lbl_ref['x'] + lbl_ref['width'])
                    if gap > max_phone_start_gap:
                        break
                else:
                    # 이미 수집 시작: 직전 수집 단어 기준 gap 체크
                    gap = cand['x'] - (prev_collected['x'] + prev_collected['width'])
                    if gap > max_phone_seg_gap:
                        break

                # 필수 입력 별표 기호는 필터링 (값이 없을 때 표시하는 *)
                if cand['text'].strip() == '*' and not phone_words:
                    continue

                cand_clean = re.sub(r'\s+', '', cand['text'])
                # 대괄호 포함 여부와 무관하게 숫자가 하나라도 있으면 수집 대상
                # (예: [010], [3559], [4313], 010, 3559, '-' 모두 포함)
                if re.search(r'[\d\-*]', re.sub(r'[\[\]]', '', cand_clean)):
                    phone_words.append(cand)
                    prev_collected = cand

            if phone_words:
                # 숫자 세그먼트만 추출 (대괄호 제거 후 순수 숫자가 있는 단어)
                numeric_segs = []
                for pw in phone_words:
                    digits_only = re.sub(r'\D', '', pw['text'])
                    if digits_only:
                        numeric_segs.append((pw, digits_only))

                if len(numeric_segs) >= 3:
                    # 3개 이상 숫자 세그먼트: 첫 번째(01x)는 노출, 나머지(국번+끝번호) 마스킹
                    # 단, 국번(두 번째)과 끝번호(세 번째)만 마스킹
                    for seg_idx, (pw, digits) in enumerate(numeric_segs):
                        if seg_idx == 0:
                            continue  # 첫 번째(010)은 노출
                        mask_regions.append({
                            'x': pw['x'], 'y': pw['y'],
                            'width': pw['width'], 'height': pw['height']
                        })
                elif len(numeric_segs) == 2:
                    # 세그먼트 2개 (예: 010-12345678 → 뒷부분 마스킹)
                    merged = merge_boxes(phone_words)
                    if merged:
                        combined_text = "".join(re.sub(r'[\[\]]', '', w['text']) for w in phone_words)
                        sub_masks = calculate_sub_masks(combined_text, merged['x'], merged['y'], merged['width'], merged['height'], name_mask_style)
                        if sub_masks:
                            mask_regions.extend(sub_masks)
                        else:
                            mask_regions.append(merged)
                else:
                    # 단어 1개 처리 (단일 토큰 전화번호)
                    merged = merge_boxes(phone_words)
                    if merged:
                        combined_text = re.sub(r'[\[\]]', '', "".join(w['text'] for w in phone_words))
                        sub_masks = calculate_sub_masks(combined_text, merged['x'], merged['y'], merged['width'], merged['height'], name_mask_style)
                        if sub_masks:
                            mask_regions.extend(sub_masks)
                        else:
                            mask_regions.append(merged)

                for pw in phone_words:
                    used_indices.add(pw['_idx'])

        elif matched_label_type == "birth":
            # 생년월일 레이아웃 기반 탐지: 레이블 우측의 날짜 형식 단어 수집
            birth_words = []
            max_birth_gap = max(word['height'] * 20.0, 350)
            for cand in candidates:
                gap = cand['x'] - (word['x'] + word['width'])
                if gap > max_birth_gap:
                    break
                if cand['text'].strip() == '*' and not birth_words:
                    continue
                cand_clean = re.sub(r'\s+', '', cand['text'])
                if not cand_clean or cand_clean in EXCLUDE_NOUNS:
                    continue
                # 날짜 패턴 또는 숫자/구분자 조합
                if re.search(r'[\d\-\./]', cand_clean):
                    birth_words.append(cand)
            if birth_words:
                merged = merge_boxes(birth_words)
                if merged:
                    combined_text = "".join(w['text'] for w in birth_words)
                    sub_masks = calculate_sub_masks(
                        combined_text, merged['x'], merged['y'],
                        merged['width'], merged['height'], name_mask_style
                    )
                    if sub_masks:
                        mask_regions.extend(sub_masks)
                    else:
                        mask_regions.append(merged)
                for bw in birth_words:
                    used_indices.add(bw['_idx'])

        elif matched_label_type in ["driver", "passport", "email", "card", "bank", "ip", "vehicle"]:
            # 6종 개인정보 레이아웃 자동 탐지 및 부분 마스킹 처리
            val_words = []
            max_gap = max(word['height'] * 20.0, 350)
            
            for cand in candidates:
                gap = cand['x'] - (word['x'] + word['width'])
                if gap > max_gap:
                    break
                
                if cand['text'].strip() == '*' and not val_words:
                    continue
                    
                cand_clean = re.sub(r'\s+', '', cand['text'])
                if not cand_clean or cand_clean in EXCLUDE_NOUNS:
                    continue
                    
                val_words.append(cand)
                
            if val_words:
                merged = merge_boxes(val_words)
                if merged:
                    combined_text = " ".join(w['text'] for w in val_words)
                    sub_masks = calculate_sub_masks(combined_text, merged['x'], merged['y'], merged['width'], merged['height'], name_mask_style)
                    if sub_masks:
                        mask_regions.extend(sub_masks)
                    else:
                        mask_regions.append(merged)
                for vw in val_words:
                    used_indices.add(vw['_idx'])

        elif matched_label_type == "address":
            # 주소는 여러 행에 걸쳐 있을 수 있으므로 Y축 허용치를 크게 확장
            # 행정구역 키워드(시/도/구/동/읍/면/로/길)를 포함한 단어들을 우선 수집하여 누락 방지
            addr_words = []
            # 주소 레이블은 2행 이상 이어질 수 있으므로 Y축을 넉넉하게 허용 (레이블 높이 6배)
            y_tolerance_addr = max(word['height'] * 6.0, 120)
            
            # 모든 단어 중 주소 레이블의 Y 범위 내에 있는 단어들을 후보로 수집
            addr_candidates = []
            for other in words:
                if other.get('_idx') == word.get('_idx'):
                    continue
                # 레이블과 같은 행(또는 하단 근접 행)에 있고, 레이블 우측에 있는 단어
                if abs(other['y'] - word['y']) <= y_tolerance_addr:
                    if other['x'] > word['x'] + word['width'] * 0.5:
                        addr_candidates.append(other)
                        
            addr_candidates.sort(key=lambda c: (c['y'], c['x']))
            
            max_addr_gap = max(word['height'] * 30.0, 500)
            for cand in addr_candidates:
                gap = cand['x'] - (word['x'] + word['width'])
                if gap > max_addr_gap:
                    break
                    
                if cand['text'].strip() == '*' and not addr_words:
                    continue
                    
                cand_clean = re.sub(r'\s+', '', cand['text'])
                if not cand_clean or cand_clean in EXCLUDE_NOUNS:
                    continue
                    
                # 행정구역 키워드를 포함하거나 한글/숫자 조합인 단어를 수집
                has_addr_keyword = any(kw in cand_clean for kw in ADDR_KEYWORDS)
                has_hangul_or_digit = bool(re.search(r'[가-힣\d]', cand_clean))
                if has_addr_keyword or has_hangul_or_digit:
                    addr_words.append(cand)
                    
            if addr_words:
                merged = merge_boxes(addr_words)
                if merged:
                    combined_text = " ".join(w['text'] for w in addr_words)
                    sub_masks = calculate_sub_masks(combined_text, merged['x'], merged['y'], merged['width'], merged['height'], name_mask_style)
                    if sub_masks:
                        mask_regions.extend(sub_masks)
                    else:
                        # 주소 전체를 하나의 박스로 마스킹
                        mask_regions.append(merged)
                for aw in addr_words:
                    used_indices.add(aw['_idx'])
                    
    # 원본 단어 객체들에 임시로 주입했던 _idx 키 청소
    for w in words:
        w.pop('_idx', None)
        
    return mask_regions, used_indices, label_regions


def detect_personal_info(ocr_result, name_mask_style="middle"):
    """
    OCR 단어 목록에서 정규식 및 한글 이름 분석을 적용하여 한국 실정에 맞는 정확한 개인정보 마스킹 영역을 검출합니다.
    무분별한 숫자 마스킹을 배제하고, 부분 마스킹 좌표계를 동적으로 생성합니다.
    또한, 화면 레이아웃 기반 예외 규칙을 적용하여 오탐/미탐을 방지합니다.
    """
    if ocr_result.get("status") != "success":
        return [], []
        
    words = ocr_result.get("words", [])
    if not words:
        return [], []
        
    mask_regions = []
    
    # 1. 레이아웃 기반 규칙 매칭 수행 (1순위 확정 개인정보 영역 확보 및 사용 단어 제외)
    # label_regions: 개인정보 항목명 레이블 단어 좌표 (노란 강조 표시 전용)
    layout_masks, used_word_indices, label_regions = detect_layout_based_info_and_indices(words, name_mask_style)
    mask_regions.extend(layout_masks)
    
    # 2-a. 분리된 전화번호 입력 필드 탐지 (010 - XXXX - XXXX 형태)
    # UI에서 전화번호가 3개의 분리된 입력 박스로 표현되어 OCR이 '[010]', '[3559]', '[4313]'
    # 처럼 별도 단어로 인식하는 경우를 처리합니다.
    # 같은 행에서 3~4자리 숫자(대괄호 포함 가능)가 연속 3개 등장하고, 첫 번째가 '01x' 형태면
    # 전화번호로 간주하여 2번째 세그먼트(국번)를 마스킹합니다.
    split_phone_used_indices = set()
    if words:
        # Y좌표 기준으로 행 그룹화
        sorted_for_split = sorted(words, key=lambda w: (w['y'], w['x']))
        row_groups_split = []
        cur_row_split = [sorted_for_split[0]]
        for wi in sorted_for_split[1:]:
            if abs(wi['y'] - cur_row_split[0]['y']) <= max(cur_row_split[0]['height'] * 0.8, 8):
                cur_row_split.append(wi)
            else:
                row_groups_split.append(cur_row_split)
                cur_row_split = [wi]
        row_groups_split.append(cur_row_split)

        for row_sp in row_groups_split:
            row_sp.sort(key=lambda w: w['x'])
            n_sp = len(row_sp)
            i_sp = 0
            while i_sp < n_sp - 2:
                # 현재 단어에서 대괄호·공백을 제거한 순수 숫자 추출
                def extract_digits(word_sp):
                    return re.sub(r'[^0-9]', '', word_sp['text'])

                seg1 = extract_digits(row_sp[i_sp])

                # 첫 번째 세그먼트: 01x 형태의 3자리 숫자
                if not re.match(r'^01[0-9]$', seg1):
                    i_sp += 1
                    continue

                # 두 번째/세 번째 세그먼트 후보: 인접 단어에서 탐색 (구분자 '-' 단어 건너뛰기)
                j_sp = i_sp + 1
                seg2_word = None
                seg3_word = None

                while j_sp < n_sp:
                    gap_sp = row_sp[j_sp]['x'] - (row_sp[j_sp - 1]['x'] + row_sp[j_sp - 1]['width'])
                    # 너무 먼 경우 종료 (대괄호 입력 필드는 간격이 넓을 수 있으므로 넉넉히 허용)
                    if gap_sp > max(row_sp[i_sp]['height'] * 15.0, 200):
                        break
                    t_sp = re.sub(r'[^0-9\-]', '', row_sp[j_sp]['text'])
                    only_digits_sp = re.sub(r'\D', '', row_sp[j_sp]['text'])
                    # 구분자('-'만 있는 단어) 또는 비어있는 단어 건너뜀
                    if t_sp == '-' or t_sp == '' or only_digits_sp == '':
                        j_sp += 1
                        continue
                    # 3~4자리 숫자 세그먼트 수집
                    if 3 <= len(only_digits_sp) <= 4:
                        if seg2_word is None:
                            seg2_word = row_sp[j_sp]
                        elif seg3_word is None:
                            seg3_word = row_sp[j_sp]
                            break
                    else:
                        break
                    j_sp += 1

                # 세 세그먼트 모두 찾은 경우 전화번호로 판정
                if seg2_word and seg3_word:
                    # 이미 레이아웃 기반 또는 다른 로직으로 처리된 단어면 스킵
                    idx1 = next((idx for idx, w in enumerate(words) if w is row_sp[i_sp]), None)
                    idx2 = next((idx for idx, w in enumerate(words) if w is seg2_word), None)
                    idx3 = next((idx for idx, w in enumerate(words) if w is seg3_word), None)

                    already_used = any(
                        ii is not None and ii in used_word_indices
                        for ii in [idx1, idx2, idx3]
                    )

                    if not already_used:
                        # 국번 필드(seg2_word) + 끝번호 필드(seg3_word) 모두 마스킹
                        # (010-[국번]-[끝번호] 중 010만 노출, 나머지 2개 가림)
                        mask_regions.append({
                            'x': seg2_word['x'],
                            'y': seg2_word['y'],
                            'width': seg2_word['width'],
                            'height': seg2_word['height']
                        })
                        mask_regions.append({
                            'x': seg3_word['x'],
                            'y': seg3_word['y'],
                            'width': seg3_word['width'],
                            'height': seg3_word['height']
                        })
                        for ii in [idx1, idx2, idx3]:
                            if ii is not None:
                                split_phone_used_indices.add(ii)
                        print(f"[분리전화] {row_sp[i_sp]['text']} / {seg2_word['text']} / {seg3_word['text']} → 국번+끝번호 마스킹")

                i_sp += 1

    used_word_indices.update(split_phone_used_indices)

    for idx, w in enumerate(words):
        w['_idx'] = idx
        
    sorted_words = sorted(words, key=lambda w: (w['y'], w['x']))
    
    # 행(Line)별로 단어 그룹화
    lines = []
    current_line = []
    current_y_base = -1
    
    for word in sorted_words:
        if current_y_base == -1:
            current_y_base = word['y']
            current_line.append(word)
        elif abs(word['y'] - current_y_base) < (word['height'] * 0.6):
            current_line.append(word)
        else:
            current_line.sort(key=lambda w: w['x'])
            lines.append(current_line)
            current_line = [word]
            current_y_base = word['y']
            
    if current_line:
        current_line.sort(key=lambda w: w['x'])
        lines.append(current_line)
        
    # 각 행별로 개인정보 감지 진행
    for line in lines:
        n = len(line)
        used_indices = set()
        
        # 긴 조합부터 우선 탐색 (탐욕적 조합 매칭)
        for length in range(n, 0, -1):
            for i in range(n - length + 1):
                sub_indices = list(range(i, i + length))
                
                # 1단계 매칭이나 기존 루프에서 이미 사용된 단어가 포함되어 있다면 패스
                if any((idx in used_indices or line[idx]['_idx'] in used_word_indices) for idx in sub_indices):
                    continue
                    
                sub_words = [line[idx] for idx in sub_indices]
                
                # 단어들 간의 수평 간격 검증
                valid_gap = True
                for k in range(len(sub_words) - 1):
                    w1 = sub_words[k]
                    w2 = sub_words[k+1]
                    gap = w2['x'] - (w1['x'] + w1['width'])
                    max_allowable_gap = max(w1['height'], w2['height']) * 1.5
                    if gap > max_allowable_gap:
                        valid_gap = False
                        break
                        
                if not valid_gap:
                    continue
                
                text_no_space = "".join(w['text'] for w in sub_words)
                text_with_space = " ".join(w['text'] for w in sub_words)
                
                # 1단계: 정규식 및 사전 기반 개인정보 타입 판정
                is_pi = False
                matched_type = None
                
                for pattern, p_type in [
                    (RRN_PATTERN, "rrn"), (PHONE_PATTERN, "phone"), 
                    (EMAIL_PATTERN, "email"), (CARD_PATTERN, "card"), 
                    (BANK_PATTERN, "bank"), (BIRTH_PATTERN, "birth"),
                    (PASSPORT_PATTERN, "passport"), (DRIVER_PATTERN, "driver"),
                    (IP_PATTERN, "ip"), (ADDRESS_PATTERN, "address"),
                    (VEHICLE_PATTERN, "vehicle"),  # 차량번호 정규식 기반 감지 추가
                ]:
                    if pattern.search(text_no_space) or pattern.search(text_with_space):
                        if p_type == "birth":
                            # 구분자 2개 이상 + 달(01~12)/일(01~31) 범위 검증으로 버전번호 오탐 방지
                            matched_text = text_no_space if pattern.search(text_no_space) else text_with_space
                            separators = re.findall(r'[-./]', matched_text)
                            if len(separators) < 2:
                                continue
                            # 달/일 숫자 추출하여 범위 검증 (버전번호 13.5.2 등 오탐 차단)
                            birth_nums = re.split(r'[-./]', matched_text.strip())
                            if len(birth_nums) >= 3:
                                try:
                                    mm_val = int(birth_nums[-2])
                                    dd_val = int(birth_nums[-1])
                                    if not (1 <= mm_val <= 12 and 1 <= dd_val <= 31):
                                        continue
                                except ValueError:
                                    continue
                        elif p_type == "rrn":
                            digits = re.sub(r'\D', '', text_no_space)
                            if not verify_rrn_checksum(digits):
                                continue
                        is_pi = True
                        matched_type = p_type
                        break
                        
                # 2단계: 한국어 이름 단독/조합 검출 (단어 길이 2~4글자)
                if not is_pi:
                    if is_likely_korean_name(text_no_space):
                        is_pi = True
                        matched_type = "name"
                
                # 3단계: 노이즈 낀 숫자 정제 매칭 (주민번호/전화번호 규격만 허용하여 단순 사번 배제)
                if not is_pi:
                    digits_only = re.sub(r'\D', '', text_no_space)
                    # 주민번호: 앞자리 정확히 6자리(YYMMDD) 또는 8자리(YYYYMMDD)로만 허용
                    if (len(digits_only) == 13 or len(digits_only) == 15) and re.match(r'^(\d{6}|\d{8})[1-8]\d{6}$', digits_only):
                        check_target = digits_only[-13:]
                        if verify_rrn_checksum(check_target):
                            is_pi = True
                            matched_type = "rrn"
                    elif (len(digits_only) >= 9 and len(digits_only) <= 11) and (re.match(r'^01\d{7,8}$', digits_only) or re.match(r'^0[2-6]\d{7,8}$', digits_only)):
                        is_pi = True
                        matched_type = "phone"
                
                # 감지 성공 시 좌표 병합 후 정밀한 부분 마스킹 영역들 생성
                if is_pi:
                    merged = merge_boxes(sub_words)
                    if merged:
                        combined_text = text_with_space if '-' in text_with_space or '.' in text_with_space else text_no_space
                        sub_masks = calculate_sub_masks(combined_text, merged['x'], merged['y'], merged['width'], merged['height'], name_mask_style)
                        
                        if sub_masks:
                            mask_regions.extend(sub_masks)
                        else:
                            mask_regions.append(merged)
                            
                        used_indices.update(sub_indices)
                        
    # 원본 단어 객체들에 임시로 주입했던 _idx 키 청소
    for w in words:
        w.pop('_idx', None)
        w.pop('_pre_scanned', None)
        w.pop('_pre_label_type', None)

    # 마스킹 영역 중복 제거 ((x,y,w,h) 동일한 것 제거)
    def dedup_regions(regions):
        seen = set()
        result = []
        for r in regions:
            key = (r['x'], r['y'], r['width'], r['height'])
            if key not in seen:
                seen.add(key)
                result.append(r)
        return result

    mask_regions = dedup_regions(mask_regions)

    # 레이블 강조 영역: 동일한 레이블 키워드가 중복 추가된 경우만 제거
    # (다른 레이블이 같은 Y행에 있더라도 X가 멀면 별개 항목으로 유지)
    def dedup_label_regions(regions):
        if not regions:
            return regions
        # (x,y,w,h) 완전 동일한 중복 제거
        seen = set()
        deduped = []
        for r in regions:
            key = (r['x'], r['y'], r['width'], r['height'])
            if key not in seen:
                seen.add(key)
                deduped.append(r)

        # 같은 Y행(±12px)에서 X 거리가 가까운(50px 이하 인접) 것들만 합산
        # X 거리가 먼 레이블은 별개 박스로 유지
        deduped.sort(key=lambda r: (r['y'], r['x']))
        groups = []
        current_group = [deduped[0]]
        for r in deduped[1:]:
            prev = current_group[-1]
            same_y = abs(r['y'] - prev['y']) <= 12
            # X 인접 거리: 이전 박스 오른쪽 끝(prev['x']+prev['width'])에서 현재 박스 왼쪽(r['x'])까지 50px 이하
            x_gap = r['x'] - (prev['x'] + prev['width'])
            if same_y and x_gap <= 50:
                current_group.append(r)
            else:
                groups.append(current_group)
                current_group = [r]
        groups.append(current_group)

        result = []
        for grp in groups:
            min_x = min(r['x'] for r in grp)
            min_y = min(r['y'] for r in grp)
            max_x = max(r['x'] + r['width'] for r in grp)
            max_h = max(r['height'] for r in grp)
            result.append({'x': min_x, 'y': min_y, 'width': max_x - min_x, 'height': max_h})
        return result

    label_regions = dedup_label_regions(label_regions)

    # mask_regions: 실제 개인정보 값의 마스킹 영역
    # label_regions: 개인정보 항목명(레이블) 단어들의 강조 표시 영역
    return mask_regions, label_regions



def apply_mask(image, regions, mask_type="mosaic", mosaic_size=10):
    """
    주어진 이미지 객체 위에 지정된 영역들(regions)에 대해 마스킹 처리를 적용하여 새 이미지 객체를 반환합니다.
    Excel 등 촘촘한 셀 레이아웃에서 텍스트 상하가 마스킹 박스를 벗어나는 문제를 막기 위해
    각 마스킹 영역에 상하 2px 여백(V_PAD)을 자동으로 추가합니다.
    """
    V_PAD = 2  # 상하 여백 (px) — Excel 셀처럼 텍스트가 빡빡하게 배치된 경우 경계 노출 방지
    img_masked = image.copy()
    draw = ImageDraw.Draw(img_masked)
    
    for r in regions:
        x, y, w, h = r['x'], r['y'], r['width'], r['height']
        
        # 상하 여백 확장 (이미지 경계를 초과하지 않도록 클램핑은 아래에서 처리)
        y -= V_PAD
        h += V_PAD * 2
        
        x = max(0, x)
        y = max(0, y)
        w = min(w, img_masked.width - x)
        h = min(h, img_masked.height - y)
        
        if w <= 0 or h <= 0:
            continue
            
        box = (x, y, x + w, y + h)
        
        if mask_type == "black":
            draw.rectangle(box, fill="black")
        elif mask_type == "mosaic":
            cropped = img_masked.crop(box)
            small_w = max(1, w // mosaic_size)
            small_h = max(1, h // mosaic_size)
            shrunk = cropped.resize((small_w, small_h), Image.Resampling.NEAREST)
            mosaic = shrunk.resize((w, h), Image.Resampling.NEAREST)
            img_masked.paste(mosaic, box)
            
    return img_masked
