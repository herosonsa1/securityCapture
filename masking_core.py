import json
import os
import re
import subprocess
from PIL import Image, ImageDraw, ImageFilter, ImageOps

# 1. 개인정보 탐지를 위한 정규표현식 정의
# 주민등록번호/외국인등록번호 (예: 950101-1234567, 19790722-1234567, 대시 필수)
# 앞자리는 반드시 6자리(YYMMDD) 또는 8자리(YYYYMMDD)로만 허용하여 오탐 최소화
# 입력 필드 UI의 대괄호 처리: [950101]-[1234567] / [950101] - [1234567] 형태도 지원
# 뒷자리 성별코드: 1~4(내국인), 5~8(외국인)
RRN_PATTERN = re.compile(
    r'(?<![.\d])\[?(\d{6}|\d{8})\]?\s*-\s*\[?[1-8]\d{6}\]?(?!\d)'
)

# 전화번호 (01x-xxxx-xxxx 및 대시 없는 형태)
# 대괄호로 감싸진 형태([010], [3559] 등 입력 필드 UI OCR 오인식 대응) 포함
# \b 경계조건이 대괄호 [에 의해 오동작하지 않도록 보완
PHONE_PATTERN = re.compile(
    r'\[?01[0-9]\]?[-\s]?\[?\d{3,4}\]?[-\s]?\[?\d{4}\]?'
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

# 운전면허번호
# 실제 포맷: 숫자2자리 - 숫자6자리 - 숫자2자리 (지역코드2 + 일련번호6 + 검증번호2 = 총 10자리)
# 예: 92-692533-74  /  13-123456-74
# 분리 입력 필드 예: [92] [-] [123456] [-] [74]  → 각각 2자리·6자리·2자리 입력
# 대시 포함 단일 OCR: 92-123456-74  (총 12자리 표현)
# 대시 없는 연속 10자리: 9212345674  (분리 필드 합산 또는 OCR 연결)
DRIVER_PATTERN = re.compile(
    r'\b\d{2}-\d{6}-\d{2}\b'              # 대시 포함: XX-XXXXXX-XX (총 12자 표현, 숫자 10자리)
    r'|(?<![.\d/])\d{10}(?![.\d/])'       # 대시 없이 10자리 연속 숫자
)

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

# 한글 이름 성씨 패턴 (한국인 인구 대다수를 차지하는 주요 성씨 33종)
# 일반 명사의 접두사로 오남용되는 희귀 성씨들을 걷어내어 오탐지를 최소화합니다.
SURNAMES = "김이박최정강조윤장임한오서신권황안송전홍유고문양손배백허남심노하지채엄민방변천곽우성소주설마길구연라탁국표금기류석공도위원빈나"
NAME_PATTERN = re.compile(rf'^[{SURNAMES}][가-힣]{{1,3}}$')

# 2글자 단어가 한글 이름으로 인정받기 위해 필요한 이름 음절 (다빈도 인명용)
COMMON_NAME_SYLLABLES = set("준서민영지수진훈현우호재태철석성원경은선혜연윤동건창병상종규환용승아희락필엽곤혁찬솔슬비빈율설담은겸송원지윤희주은재민하율예준서윤봉택평기노빛여산")

# 한글 이름 부분(성씨를 제외한 글자들)에 포함될 수 없는 인명 금지 음절 목록
# 업무용 단어(예: 조회, 수정, 등록, 전체, 배치, 백업, 관리, 정보, 이력, 노드, 조직 등)에서 파생되는 글자들 차단
# ※ 주의: 장(이장훈), 화(김화진), 국(박국현), 함(함준혁) 등은 실제 인명용 음절이므로 제외함
# '용', '제', '권', '의', '류', '식', '단', '별', '표', '체', '객', '판', '통', '합' 등 인명용 다빈도 글자들은 금지 목록에서 제외합니다.
FORBIDDEN_NAME_SYLLABLES = set("업치법과품물역력록학교실점등및것요됨할적조회")

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

    border_crop = 4  # 대비 왜곡을 방지하기 위한 가장자리 테두리(검은 선 등) 크롭 여백

    def preprocess_and_save(img_pil, invert=False):
        """
        이미지를 전처리(스케일업, autocontrast, UnsharpMask)한 후
        임시 파일로 저장하고 경로를 반환합니다. 이진화 과정은 이미지 깨짐을 방지하기 위해 수행하지 않습니다.
        invert=True이면 그레이스케일 이미지를 반전시켜 어두운 배경에 밝은 글자 환경을 보정합니다.
        """
        # 가장자리 테두리(검은 선 등)가 autocontrast 명암 히스토그램 조정을 방해하지 않도록
        # 4px만큼 사방을 크롭하여 글자 부분 명암비 확장에 집중시킵니다.
        if img_pil.width > border_crop * 2 and img_pil.height > border_crop * 2:
            img_pil = img_pil.crop((border_crop, border_crop, img_pil.width - border_crop, img_pil.height - border_crop))

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
        # 이진화(Otsu)는 글자 깨짐 및 딤드 오버레이 시 손실을 방지하기 위해 제외합니다.
        # 대신, invert=True인 경우 그레이스케일 이미지를 반전합니다.
        if invert:
            final_img = ImageOps.invert(sharp_img)
        else:
            final_img = sharp_img
        # ─────────────────────────────────────────────────────────────────
        temp_dir = tempfile.gettempdir()
        suffix = "_inv" if invert else ""
        tmp_path = os.path.join(
            temp_dir,
            f"temp_scaled_ocr{suffix}_{os.path.basename(image_path)}"
        )
        final_img.save(tmp_path)
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

    # 확대 비율(scale_factor) 및 크롭(border_crop) 오프셋을 적용해 단어들의 좌표계를 원상 복구 (Scale-down & Shift-back)
    if ocr_result.get("status") == "success":
        words = ocr_result.get("words", [])
        
        has_border = False
        try:
            if os.path.exists(image_path):
                with Image.open(image_path) as orig_img:
                    if orig_img.width > border_crop * 2 and orig_img.height > border_crop * 2:
                        has_border = True
        except:
            pass

        for w in words:
            if scale_factor > 1.0:
                w['x'] = int(w['x'] / scale_factor)
                w['y'] = int(w['y'] / scale_factor)
                w['width'] = int(w['width'] / scale_factor)
                w['height'] = int(w['height'] / scale_factor)
            if has_border:
                w['x'] += border_crop
                w['y'] += border_crop

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
    입력 필드 UI의 [ ] 대괄호를 제거한 정규화 텍스트(norm_text)로 패턴 매칭 및 문자 위치를 계산하여
    '[950101]-[1234567]', '[02-020589-74]' 등 대괄호 포함 OCR 결과에서도 정확히 마스킹합니다.
    """
    sub_masks = []
    # ── 대괄호 제거 정규화 ─────────────────────────────────────────────────────
    # 입력 필드 UI의 [ ] 처리: '[950101]-[1234567]' → '950101-1234567'
    # 패턴 탐지·문자 위치 계산은 norm_text 기준으로 수행하여 오프셋 오류를 방지합니다.
    norm_text = re.sub(r'[\[\]]', '', text)
    char_w = width / max(1, len(norm_text))
    # ─────────────────────────────────────────────────────────────────────────

    # 1. 주민등록번호 / 외국인등록번호 (예: 950101-1*****)
    # 생년월일과 성별(뒷자리 첫 번호)을 제외한 뒤 6자리 마스킹
    is_rrn = False
    digits_only = re.sub(r'\D', '', norm_text)
    if RRN_PATTERN.search(norm_text) or ((len(digits_only) == 13 or len(digits_only) == 15) and re.match(r'^(\d{6}|\d{8})[1-8]\d{6}$', digits_only)):
        is_rrn = True

    if is_rrn:
        dash_idx = norm_text.find('-')
        if dash_idx != -1:
            # 앞 6자리(생년월일) + 대시 1자리 + 성별 1자리 = 8자리 노출, 이후 6자리 가림
            w_back = 6 * char_w
            sub_masks.append({
                'x': int(x + 8 * char_w),
                'y': y,
                'width': int(w_back),
                'height': height
            })
        else:
            # 앞 6자리(생년월일) + 성별 1자리 = 7자리 노출, 이후 6자리 가림
            w_back = 6 * char_w
            sub_masks.append({
                'x': int(x + 7 * char_w),
                'y': y,
                'width': int(w_back),
                'height': height
            })

    # 2. 생년월일 (예: 1979.07.22 / 1979-07-22 → 19******)
    # 연도 앞 2자리만 남기고 뒤를 전부 가림
    elif BIRTH_PATTERN.search(norm_text):
        w_mask = (len(norm_text) - 2) * char_w
        sub_masks.append({
            'x': int(x + 2 * char_w),
            'y': y,
            'width': int(w_mask),
            'height': height
        })

    # 3. 전화번호 / 휴대전화번호 (예: 010-1234-5678 → 010-****-5678)
    # 가운데 4자리(국번) 마스킹
    elif PHONE_PATTERN.search(norm_text):
        if '-' in norm_text:
            # 대시 포함 포맷 (예: 010-1234-5678)
            dash_idx = norm_text.find('-')
            sub_masks.append({
                'x': int(x + (dash_idx + 1) * char_w),
                'y': y,
                'width': int(4 * char_w),
                'height': height
            })
        else:
            # 대시 미포함 포맷 (예: 01012345678): 앞 3자리(010) 노출 후 4자리 가림
            sub_masks.append({
                'x': int(x + 3 * char_w),
                'y': y,
                'width': int(4 * char_w),
                'height': height
            })

    # 4. 한글 사람 이름 (글자 수와 무관하게 이름 영역 전체 마스킹)
    elif is_likely_korean_name(text):
        sub_masks.append({
            'x': x,
            'y': y,
            'width': width,
            'height': height
        })

    # 5. 운전면허번호 (포맷: 지역코드2 - 일련번호6 - 검증번호2, 예: 92-123456-74)
    # 지역코드(앞 2자리)만 노출, 이후 전체(일련번호+검증) 마스킹
    elif DRIVER_PATTERN.search(norm_text):
        if '-' in norm_text:
            # 대시 포함 포맷: XX-XXXXXX-XX (norm_text 기준으로 위치 계산)
            parts = norm_text.split('-')
            # 지역코드(2자리) + 대시(1자리) 이후부터 마스킹
            start_idx = len(parts[0]) + 1
            w_mask = (len(norm_text) - start_idx) * char_w
            sub_masks.append({
                'x': int(x + start_idx * char_w),
                'y': y,
                'width': int(w_mask),
                'height': height
            })
        else:
            # 대시 없는 연속 10자리: 앞 2자리 노출 후 나머지 8자리 마스킹
            sub_masks.append({
                'x': int(x + 2 * char_w),
                'y': y,
                'width': int(8 * char_w),
                'height': height
            })

    # 6. 여권번호 (예: M12345678 → M123*****)
    elif PASSPORT_PATTERN.search(norm_text):
        w_mask = (len(norm_text) - 4) * char_w
        if w_mask > 0:
            sub_masks.append({
                'x': int(x + 4 * char_w),
                'y': y,
                'width': int(w_mask),
                'height': height
            })

    # 7. 이메일 주소 → 전체 마스킹
    elif EMAIL_PATTERN.search(norm_text):
        sub_masks.append({
            'x': x,
            'y': y,
            'width': width,
            'height': height
        })

    # 8. 신용카드 번호 (예: 1234-1234-1234-1234 → 1234-****-****-1234)
    elif CARD_PATTERN.search(norm_text):
        if '-' in norm_text:
            sub_masks.append({
                'x': int(x + 5 * char_w),
                'y': y,
                'width': int(9 * char_w),
                'height': height
            })
        else:
            sub_masks.append({
                'x': int(x + 4 * char_w),
                'y': y,
                'width': int(8 * char_w),
                'height': height
            })

    # 9. 계좌번호 (예: 110-123-456789 → 110-123-*****)
    elif BANK_PATTERN.search(norm_text):
        w_mask = 6 * char_w
        if len(norm_text) > 6:
            sub_masks.append({
                'x': int(x + (len(norm_text) - 6) * char_w),
                'y': y,
                'width': int(w_mask),
                'height': height
            })

    # 10. IP 주소 (예: 192.168.1.1 → 192.168.*.**)
    elif IP_PATTERN.search(norm_text):
        dots = [i for i, char in enumerate(norm_text) if char == '.']
        if len(dots) >= 2:
            start_idx = dots[1] + 1
            w_mask = (len(norm_text) - start_idx) * char_w
            sub_masks.append({
                'x': int(x + start_idx * char_w),
                'y': y,
                'width': int(w_mask),
                'height': height
            })

    # 11. 주소 (예: 경기도 성남시 수정구 태평동 123 → 경기도 성남시 수정구 ****)
    elif ADDRESS_PATTERN.search(norm_text):
        match = None
        for kw in ["구", "동", "읍", "면", "로", "길", "시", "도"]:
            idx = norm_text.rfind(kw)
            if idx != -1:
                match = idx + 1
                break
        if match and match < len(norm_text):
            sub_masks.append({
                'x': int(x + match * char_w),
                'y': y,
                'width': int((len(norm_text) - match) * char_w),
                'height': height
            })

    # 12. 차량번호 (예: 12가1234 → 12가****)
    elif VEHICLE_PATTERN.search(norm_text):
        m = VEHICLE_PATTERN.search(norm_text)
        if m:
            matched_str = m.group()
            last4_match = re.search(r'\d{4}$', matched_str)
            if last4_match:
                offset_in_text = m.start() + last4_match.start()
                sub_masks.append({
                    'x': int(x + offset_in_text * char_w),
                    'y': y,
                    'width': int(4 * char_w),
                    'height': height
                })

    # 대괄호 '[', ']' 처리 보정: 대괄호 경계 근처의 마스킹 영역은 대괄호를 덮어쓰도록 확장
    if sub_masks:
        for mask in sub_masks:
            # 텍스트에 '['가 존재하고 마스킹 영역의 시작이 텍스트 시작 근처이면 왼쪽 끝(x)으로 확장
            if '[' in text and (mask['x'] - x) <= (char_w * 2.5):
                mask['width'] += (mask['x'] - x)
                mask['x'] = x
            # 텍스트에 ']'가 존재하고 마스킹 영역의 끝이 텍스트 끝 근처이면 오른쪽 끝(x+width)으로 확장
            if ']' in text and ((x + width) - (mask['x'] + mask['width'])) <= (char_w * 2.5):
                mask['width'] = (x + width) - mask['x']

    return sub_masks


def detect_layout_based_info_and_indices(words, name_mask_style="middle"):
    """
    레이블(성명, 주민번호, 휴대폰, 생년월일 등 11종) 텍스트의 우측 인접 영역을 탐색하여
    개인정보 영역을 강제로 식별하고 마스킹 좌표와 사용된 단어들의 인덱스 세트를 반환합니다.
    레이블이 여러 단어로 OCR 인식된 경우 동일 행의 연속된 레이블 단어들을 합산하여 전체 레이블
    바운딩박스를 label_regions에 저장하여 노란 강조 표시 영역을 정확히 반영합니다.
    """
    NAME_LABELS = {
        "성명", "민원인성명", "고객명", "이름", "대표자", "대표자명", "성 명", "민원인 성명",
        "보회자", "피보험자", "피보험자명", "인원인", "인원점수번호", "보회자Q卜", "보회云|략", "피보",
        "운전자", "운전자명"
    }
    RRN_LABELS = {
        "주민등록번호", "주민번호", "실명번호", "외국인등록번호", "주민등록 번호",
        "주원들릨ä호", "주원들", "릨ä호", "들릨ä", "주원", "주민등록", "주원들릨", "릨ä",
        "주인등록변호", "주인등록", "주인등록변"
    }
    PHONE_LABELS = {
        "휴대폰번호", "휴대폰", "연락처", "전화번호", "핸드폰", "이동전화", "휴대폰 번호", "전화 번호",
        "폰번", "폰번호", "핸드폰번호", "폰 번", "연력처", "연락", "연력", "인락처", "연락저", "연락처*"
    }
    DRIVER_LABELS = {"운전면허번호", "운전면허", "면허번호", "면허"}
    PASSPORT_LABELS = {"여권번호", "여권"}
    EMAIL_LABELS = {"이메일주소", "이메일", "E-Mail", "email", "이매일", "인터넷주소", "메일주소", "메일"}
    ADDRESS_LABELS = {"주소", "소재지", "주 소", "사고장소", "사고지", "장소", "주소지"}
    CARD_LABELS = {"신용카드", "카드번호", "카드"}
    BANK_LABELS = {"계좌번호", "계좌"}
    IP_LABELS = {"IP주소", "IP", "아이피"}
    # 차량번호 레이블
    VEHICLE_LABELS = {
        "차량번호", "자동차번호", "차 번호", "차량 번호", "자동차 번호",
        "차번호", "등록번호", "시고번호", "사고차량", "차량", "차량변호"
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
        ("운전자명", "name"), ("운전자", "name"),
        ("주민등록번호", "rrn"), ("주민번호", "rrn"), ("외국인등록번호", "rrn"),
        ("휴대폰번호", "phone"), ("전화번호", "phone"), ("핸드폰번호", "phone"),
        ("생년월일", "birth"), ("출생년월일", "birth"),
        ("여권번호", "passport"), ("운전면허번호", "driver"),
        ("이메일주소", "email"),
        ("사고장소", "address"), ("사고지", "address"), ("장소", "address"),
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
        # 특수문자(*, :, ?, [, ] 등)를 제거한 순수 한글/영어/숫자 기준 텍스트
        text_stripped = re.sub(r'[^가-힣a-zA-Z0-9]', '', text_clean)

        matched_label_type = None

        # 사전 스캔에서 이미 레이블로 처리된 단어는 타입 승계
        if word.get('_pre_scanned'):
            matched_label_type = word.get('_pre_label_type')

        # 1. 성명 레이블 판정 완화 (오인식 오타 대응)
        elif any(lbl in text_stripped for lbl in NAME_LABELS) or (
            "민원" in text_stripped and "성" in text_stripped) or (
            "성" in text_stripped and "명" in text_stripped) or (
            "보회" in text_stripped) or (
            "인원" in text_stripped and "성" in text_stripped) or (
            "인성" in text_stripped) or (
            text_stripped.endswith("명") and len(text_stripped) >= 2):
            matched_label_type = "name"

        # 2. 주민번호 레이블 판정 완화 (오인식 오타 대응 및 유사성 결합 매칭)
        elif (any(lbl in text_stripped for lbl in RRN_LABELS) or
              ("주민" in text_stripped and "번호" in text_stripped) or
              ("주인" in text_stripped and "번호" in text_stripped) or
              ("주원" in text_stripped and "번호" in text_stripped) or
              ("들릨" in text_stripped and "번호" in text_stripped) or
              ("주인" in text_stripped and "변호" in text_stripped)):
            if "접수" not in text_stripped and "제휴" not in text_stripped:
                matched_label_type = "rrn"

        # 3. 휴대폰 레이블 판정 완화 (오인식 오타 대응)
        elif any(lbl in text_stripped for lbl in PHONE_LABELS) or (
            "휴대" in text_stripped and "번호" in text_stripped) or (
            "휴대" in text_stripped and "폰" in text_stripped) or (
            "전화" in text_stripped and "번호" in text_stripped) or (
            "폰번" in text_stripped):
            if "접수" not in text_stripped and "제휴" not in text_stripped:
                matched_label_type = "phone"
        # 4. 생년월일 레이블 판정 (신규 추가)
        elif any(lbl in text_stripped for lbl in BIRTH_LABELS) or (
            "생년" in text_stripped and ("월" in text_stripped or "일" in text_stripped)):
            matched_label_type = "birth"
        elif any(lbl in text_stripped for lbl in DRIVER_LABELS):
            matched_label_type = "driver"
        elif any(lbl in text_stripped for lbl in PASSPORT_LABELS):
            matched_label_type = "passport"
        elif any(lbl in text_stripped for lbl in EMAIL_LABELS):
            matched_label_type = "email"
        elif any(lbl in text_stripped for lbl in ADDRESS_LABELS):
            matched_label_type = "address"
        elif any(lbl in text_stripped for lbl in CARD_LABELS):
            matched_label_type = "card"
        elif any(lbl in text_stripped for lbl in BANK_LABELS):
            matched_label_type = "bank"
        elif any(lbl in text_stripped for lbl in IP_LABELS):
            matched_label_type = "ip"
        elif any(lbl in text_stripped for lbl in VEHICLE_LABELS):
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

        # Y축 오차 허용치를 엄격하게 제한하여 아래위 다른 행의 텍스트 오수집(병합 오탐) 방지
        y_tolerance = max(word['height'] * 0.9, 12)
        
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
            name_found = False  # 이름 마스킹 완료 여부
            
            for cand in candidates:
                gap = cand['x'] - (word['x'] + word['width'])
                if gap > max_name_gap:
                    break
                
                # 후보 단어가 사전스캔 레이블 그룹에 속하면 이름/주민번호 아님 → 건너뜀
                if cand.get('_pre_scanned'):
                    continue

                cand_text_raw = cand['text'].strip()
                cand_clean = re.sub(r'[^가-힣a-zA-Z]', '', cand_text_raw)

                # 1순위: 주민번호 패턴 탐지 (이름 레이블 행에 주민번호가 함께 있는 경우 처리)
                # 예: 피보험자 행에 이름 + 주민번호(731225-1542622) + [사업자조회] 버튼
                # 대괄호 제거 후 패턴 탐지 (입력 필드 UI 대응: [950101]-[1234567])
                cand_text_norm = re.sub(r'[\[\]]', '', cand_text_raw)
                if RRN_PATTERN.search(cand_text_norm):
                    sub_masks = calculate_sub_masks(cand_text_raw, cand['x'], cand['y'], cand['width'], cand['height'], name_mask_style)
                    if sub_masks:
                        mask_regions.extend(sub_masks)
                    else:
                        mask_regions.append({
                            'x': cand['x'], 'y': cand['y'], 'width': cand['width'], 'height': cand['height']
                        })
                    used_indices.add(cand['_idx'])
                    continue  # RRN 처리 완료 → 다음 후보로 (break 아님)

                # 1-2순위: 분리 입력 필드 주민번호 탐지 (6자리 앞번호 + 7자리 뒷번호 별도 OCR 단어)
                # 예: [950101] [-] [1234567] 형태로 OCR 인식 시 각 단어가 개별 candidate로 들어옴
                cand_digits_only = re.sub(r'\D', '', cand_text_norm)
                if len(cand_digits_only) == 6:
                    # 이 후보가 6자리 생년월일 필드일 가능성 → 인접 후보에서 7자리 뒷번호 탐색
                    cand_pos = candidates.index(cand) if cand in candidates else -1
                    for next_cand in (candidates[cand_pos + 1:] if cand_pos >= 0 else []):
                        next_norm = re.sub(r'[\[\]]', '', next_cand['text'].strip())
                        next_digits = re.sub(r'\D', '', next_norm)
                        if len(next_digits) == 7 and next_digits[0] in '12345678':
                            # 7자리 뒷번호 필드 발견 → 뒷번호 전체 마스킹 (박스 직접 마스킹)
                            mask_regions.append({
                                'x': next_cand['x'], 'y': next_cand['y'],
                                'width': next_cand['width'], 'height': next_cand['height']
                            })
                            used_indices.add(next_cand['_idx'])
                            break
                        elif next_norm == '-' or not next_digits:
                            continue  # 대시나 빈 구분자는 스킵
                        else:
                            break

                # 비어있거나 제외 명사 리스트에 속하면 건너뜀
                if not cand_clean:
                    # 한글/영문자가 없는 숫자/기호인 경우 (주민번호, 전화번호 필드 등)
                    # 이름 매칭 대상은 아니지만, RRN/Phone 매칭은 진행할 수 있어야 하므로 break하지 않고 건너뜁니다.
                    pass
                elif cand_clean in EXCLUDE_NOUNS:
                    if name_found:
                        break  # 이름 이후 실제 업무 명사를 만나면 스캔 종료
                    continue

                # 이름을 이미 찾은 후 또 다른 한글 단어 → 스캔 영역 종료
                if name_found:
                    break

                # 2순위: 이름 패턴 탐지 (is_likely_korean_name 으로 엄격하게 판별)
                if is_likely_korean_name(cand_clean):
                    sub_masks = calculate_sub_masks(cand['text'], cand['x'], cand['y'], cand['width'], cand['height'], name_mask_style)
                    if sub_masks:
                        mask_regions.extend(sub_masks)
                    else:
                        mask_regions.append({
                            'x': cand['x'], 'y': cand['y'], 'width': cand['width'], 'height': cand['height']
                        })
                    used_indices.add(cand['_idx'])
                    name_found = True
                    # break 제거 → 이름 이후에도 주민번호 등 추가 스캔 계속
                    
        elif matched_label_type == "rrn":
            # 주민번호의 경우: 레이블 우측 X 범위 내에 존재하는 단어들을 수집
            # OCR 판독 깨짐 현상(예: ]圍1叫-1圄815)을 고려하여 숫자/대시 패턴에 얽매이지 않고 유효 값을 수집합니다.
            # 분리 입력 필드([YYMMDD] [-] [1234567]) 형태도 완전 지원합니다.
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
                # ── 분리 입력 필드 직접 박스 마스킹 시도 ────────────────────────────────
                # 숫자 세그먼트 추출: 대괄호 제거 후 순수 숫자가 있는 단어만
                numeric_segs_rrn = [
                    (w, re.sub(r'\D', '', re.sub(r'[\[\]]', '', w['text'])))
                    for w in rrn_words
                    if re.sub(r'\D', '', re.sub(r'[\[\]]', '', w['text']))
                ]
                total_rrn_digits = ''.join(d for _, d in numeric_segs_rrn)
                # 6자리 + 7자리 = 13자리 숫자이고 세그먼트가 2개 이상인 분리 필드 형태
                if (len(total_rrn_digits) == 13
                        and len(numeric_segs_rrn) >= 2
                        and total_rrn_digits[6] in '12345678'):
                    # 첫 번째 세그먼트(6자리 생년월일)는 노출
                    # 두 번째 이후 세그먼트(7자리 뒷번호)는 해당 박스 전체 마스킹
                    for seg_idx, (rw, _) in enumerate(numeric_segs_rrn):
                        if seg_idx == 0:
                            continue  # 생년월일 필드 노출
                        mask_regions.append({
                            'x': rw['x'], 'y': rw['y'],
                            'width': rw['width'], 'height': rw['height']
                        })
                    for rw, _ in numeric_segs_rrn:
                        used_indices.add(rw['_idx'])
                else:
                    # ── 단일 토큰 또는 합산 방식 마스킹 ─────────────────────────────────
                    merged = merge_boxes(rrn_words)
                    if merged:
                        combined_text = "".join(w['text'] for w in rrn_words)
                        sub_masks = calculate_sub_masks(combined_text, merged['x'], merged['y'], merged['width'], merged['height'], name_mask_style)
                        if sub_masks:
                            mask_regions.extend(sub_masks)
                        else:
                            # sub_masks가 비어있을 때, 무조건 통째로 가리는 것은 오탐이 크므로
                            # 최소한 주민번호 구조의 특징(숫자, 대시, 별표 등)을 가졌는지 검증 후 마스킹
                            norm_comb = re.sub(r'[\[\]]', '', combined_text)
                            digits_in_comb = re.sub(r'\D', '', norm_comb)
                            stars_in_comb = len(re.findall(r'\*', norm_comb))
                            if len(digits_in_comb) >= 6 or (len(digits_in_comb) >= 3 and '-' in norm_comb and stars_in_comb >= 3):
                                mask_regions.append(merged)
                    for rw in rrn_words:
                        used_indices.add(rw['_idx'])
                        
        elif matched_label_type == "phone":
            # 휴대폰 번호: 레이블 우측 X 범위 내의 숫자/대시/별표 조합 단어들을 수집
            # 3분리 입력 필드([010] - [3559] - [4313]) 형태 완전 지원
            phone_words = []
            # gap을 레이블 기준이 아닌 직전 수집 단어 기준으로 계산 (분리 필드가 멀어도 수집)
            max_phone_seg_gap = max(word['height'] * 25.0, 400)  # 세그먼트 간 최대 허용 간격 대폭 확대
            max_phone_start_gap = max(word['height'] * 45.0, 900)  # 레이블→첫 값 최대 간격 확대

            prev_collected = None  # 직전에 수집한 단어

            for cand in candidates:
                if cand.get('_pre_scanned'):
                    continue
                if prev_collected is None:
                    # 아직 아무것도 수집 전: 레이블 기준 gap 체크
                    gap = cand['x'] - (lbl_ref['x'] + lbl_ref['width'])
                    if gap > max_phone_start_gap:
                        continue  # break 대신 continue로 뒷부분 후보 계속 검증
                else:
                    # 이미 수집 시작: 직전 수집 단어 기준 gap 체크
                    gap = cand['x'] - (prev_collected['x'] + prev_collected['width'])
                    if gap > max_phone_seg_gap:
                        continue  # break 대신 continue

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

                if len(numeric_segs) >= 2 and re.match(r'^01[0-9]$|^0[2-6]\d?$', numeric_segs[0][1]):
                    # 첫 번째 세그먼트가 010 등 번호 식별자이면 노출하고, 나머지 세그먼트들을 마스킹 대상에 추가
                    for seg_idx, (pw, digits) in enumerate(numeric_segs):
                        if seg_idx == 0:
                            continue  # 첫 번째는 노출
                        
                        pw_text_norm = re.sub(r'[\[\]]', '', pw['text'])
                        if '-' in pw_text_norm:
                            sub = calculate_sub_masks(pw_text_norm, pw['x'], pw['y'], pw['width'], pw['height'], name_mask_style)
                            if sub:
                                mask_regions.extend(sub)
                                continue
                        
                        mask_regions.append({
                            'x': pw['x'], 'y': pw['y'],
                            'width': pw['width'], 'height': pw['height']
                        })
                else:
                    # 단일 토큰 또는 식별자가 없는 경우 일반 마스킹 적용
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

        elif matched_label_type == "driver":
            # 운전면허번호 레이아웃 탐지: 3분리 입력 필드 및 단일 토큰 모두 지원
            # 실제 포맷: 숫자2자리 - 숫자6자리 - 숫자2자리 (총 10자리 숫자)
            # 분리 입력 필드 예: [92] [-] [123456] [-] [74]
            # 단일 토큰 예: 92-123456-74  또는  9212345674
            driver_words = []
            max_driver_seg_gap = max(word['height'] * 8.0, 120)   # 세그먼트 간 최대 간격
            max_driver_start_gap = max(word['height'] * 40.0, 800)  # 레이블→첫 값 최대 간격
            prev_dr = None  # 직전 수집 단어
            driver_seg_counts = []  # (단어, 숫자문자열) 리스트

            for cand in candidates:
                # 간격 체크
                if prev_dr is None:
                    gap = cand['x'] - (lbl_ref['x'] + lbl_ref['width'])
                    if gap > max_driver_start_gap:
                        break
                else:
                    gap = cand['x'] - (prev_dr['x'] + prev_dr['width'])
                    if gap > max_driver_seg_gap:
                        break

                if cand['text'].strip() == '*' and not driver_words:
                    continue

                cand_text_clean = re.sub(r'[\[\]]', '', re.sub(r'\s+', '', cand['text']))

                # 한글(업무명 등) 단어 나오면 종료
                if re.search(r'[\uac00-\ud7a3]', cand_text_clean) and not driver_words:
                    continue  # 다른 라벨 유형 단어 스킵

                digits_only = re.sub(r'\D', '', cand_text_clean)
                is_dash_only = cand_text_clean == '-'

                # 숫자가 있으면 후보로 수집
                if digits_only:
                    total_collected = ''.join(d for _, d in driver_seg_counts) + digits_only
                    # 누적 자릿수가 10자리 이하이거나, 또는 이번 단어를 더해서 정확히 10자리를 일시적으로 초과하더라도 수집할 수 있게 최대 12자리까지 허용
                    if len(total_collected) <= 12:
                        driver_words.append(cand)
                        driver_seg_counts.append((cand, digits_only))
                        prev_dr = cand
                        # 누적 자릿수가 10자리 이상 채워지면 수집 완료
                        if len(total_collected) >= 10:
                            break
                    else:
                        break  # 자릿수 초과 → 종료
                elif is_dash_only:
                    # 대시는 세그먼트 사이 연결자로만 허용 (수집 시작 후에만)
                    if driver_words:
                        driver_words.append(cand)
                        prev_dr = cand
                else:
                    if driver_words:
                        break  # 수집 시작 후 숫자/대시 아닌 단어 → 종료

            # 수집된 세그먼트를 합친 후 정규식 매칭 또는 직접 자릿수 확인
            total_digits = ''.join(d for _, d in driver_seg_counts)
            is_valid_driver = (
                DRIVER_PATTERN.search(''.join(w['text'] for w in driver_words)) or
                DRIVER_PATTERN.search(' '.join(w['text'] for w in driver_words)) or
                # 분리 입력 필드: 2자리+6자리+2자리 = 총 10자리 숫자이고 세그먼트가 2개 이상
                (len(total_digits) == 10 and len(driver_seg_counts) >= 2)
            )

            if is_valid_driver and driver_words:
                numeric_dr_segs = [(w, d) for w, d in driver_seg_counts if d]
                if len(numeric_dr_segs) >= 2:
                    # 첫 번째 세그먼트(지역코드 2자리)만 노출, 나머지(일련번호 6자리 + 검증번호 2자리) 마스킹
                    for dr_idx, (pw, digits) in enumerate(numeric_dr_segs):
                        if dr_idx == 0:
                            # 첫 번째 세그먼트더라도 숫자가 2자리를 초과하면, 그 단어 내의 앞 2자리 이후는 마스킹해야 함
                            # 예: "92-692533" -> 앞 "92" 및 대시 이후를 마스킹 영역에 추가
                            pw_text_norm = re.sub(r'[\[\]]', '', pw['text'])
                            digits_found = 0
                            split_idx = len(pw_text_norm)
                            for c_idx, char in enumerate(pw_text_norm):
                                if char.isdigit():
                                    digits_found += 1
                                    if digits_found == 2:
                                        # 지역코드 2자리가 채워진 다음 문자부터 가림 (예: 대시가 있으면 대시부터 마스킹)
                                        split_idx = c_idx + 1
                                        break
                            
                            if split_idx < len(pw_text_norm):
                                char_w = pw['width'] / max(1, len(pw_text_norm))
                                mask_regions.append({
                                    'x': int(pw['x'] + split_idx * char_w),
                                    'y': pw['y'],
                                    'width': int((len(pw_text_norm) - split_idx) * char_w),
                                    'height': pw['height']
                                })
                            continue  # 지역코드(첫 번째 2자리)가 들어있는 부분은 노출하고 루프 계속
                        
                        mask_regions.append({
                            'x': pw['x'], 'y': pw['y'],
                            'width': pw['width'], 'height': pw['height']
                        })
                elif driver_words:
                    # 단일 토큰으로 OCR된 경우 (예: 92-123456-74)
                    merged = merge_boxes(driver_words)
                    if merged:
                        combined_text = ''.join(w['text'] for w in driver_words)
                        sub_masks = calculate_sub_masks(combined_text, merged['x'], merged['y'], merged['width'], merged['height'], name_mask_style)
                        if sub_masks:
                            mask_regions.extend(sub_masks)
                        else:
                            mask_regions.append(merged)
                for vw in driver_words:
                    used_indices.add(vw['_idx'])

        elif matched_label_type in ["passport", "email", "card", "bank", "ip", "vehicle"]:
            # 6종 개인정보 레이아웃 자동 탐지 및 부분 마스킹 처리
            val_words = []
            max_gap = max(word['height'] * 20.0, 350)
            
            pattern_map = {
                "passport": PASSPORT_PATTERN,
                "email": EMAIL_PATTERN,
                "card": CARD_PATTERN,
                "bank": BANK_PATTERN,
                "ip": IP_PATTERN,
                "vehicle": VEHICLE_PATTERN
            }
            target_pattern = pattern_map.get(matched_label_type)
            
            temp_words = []
            matched_group = None
            
            for cand in candidates:
                gap = cand['x'] - (word['x'] + word['width'])
                if gap > max_gap:
                    break
                
                if cand['text'].strip() == '*' and not temp_words:
                    continue
                    
                cand_clean = re.sub(r'\s+', '', cand['text'])
                if not cand_clean or cand_clean in EXCLUDE_NOUNS:
                    break
                    
                # 특수한 예외: 차량번호 탐색 중 "차량명", "배기량", "연식", "제휴사", "고객", "연락처" 등이 감지되면 탐색 종료
                if matched_label_type == "vehicle" and any(k in cand_clean for k in ["차량명", "배기량", "연식", "제휴사", "고객", "연락처"]):
                    break
                
                temp_words.append(cand)
                
                combined_text_no_space = "".join(w['text'] for w in temp_words)
                combined_text_with_space = " ".join(w['text'] for w in temp_words)
                
                # 대괄호 [ ] 제거 정규화 텍스트로 패턴 매칭
                combined_norm_no = re.sub(r'[\[\]]', '', combined_text_no_space)
                combined_norm_with = re.sub(r'[\[\]]', '', combined_text_with_space)
                
                m_no = target_pattern.search(combined_norm_no)
                m_with = target_pattern.search(combined_norm_with)
                
                if m_no or m_with:
                    matched_group = list(temp_words)
                    # 단일 단어 중심의 이메일, IP, 여권번호 등은 첫 매칭 즉시 중단하여 탐욕적 오탐 방지
                    if matched_label_type in ["email", "ip", "passport"]:
                        break
                else:
                    if matched_group is not None:
                        # 이미 정규식 만족 완료 단계가 한 번 있었는데, 새로운 단어를 추가했더니
                        # 정규식을 더 이상 만족하지 못한다면, 이전의 정형 데이터까지만 취하고 수집 중단
                        break
            
            if matched_group:
                val_words = matched_group
                
            if val_words:
                if matched_label_type == "bank":
                    # 계좌번호 분리 입력 필드 대응
                    # 숫자 세그먼트 단어 추출
                    numeric_segs = []
                    for vw in val_words:
                        digits_only = re.sub(r'\D', '', re.sub(r'[\[\]]', '', vw['text']))
                        if digits_only:
                            numeric_segs.append((vw, digits_only))
                            
                    if len(numeric_segs) >= 2:
                        # 분리 필드 형태: 마지막 숫자 필드 박스 전체를 마스킹
                        for idx_seg, (vw, digits) in enumerate(numeric_segs):
                            if idx_seg == len(numeric_segs) - 1:
                                mask_regions.append({
                                    'x': vw['x'], 'y': vw['y'],
                                    'width': vw['width'], 'height': vw['height']
                                })
                    else:
                        # 단일 토큰 형태
                        merged = merge_boxes(val_words)
                        if merged:
                            combined_text = re.sub(r'[\[\]]', '', "".join(w['text'] for w in val_words))
                            sub_masks = calculate_sub_masks(combined_text, merged['x'], merged['y'], merged['width'], merged['height'], name_mask_style)
                            if sub_masks:
                                mask_regions.extend(sub_masks)
                            else:
                                mask_regions.append(merged)
                else:
                    # bank 외 나머지 5종 (passport, email, card, ip, vehicle)
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
                # 레이블과 같은 행(또는 하단 근접 행)에 있고, 레이블 우측 또는 하단에 있는 단어
                # 레이블보다 현저히 위쪽 줄(height의 0.5배 위)에 있는 단어는 제외하여 오탐 방지
                y_diff = other['y'] - word['y']
                if -word['height'] * 0.5 <= y_diff <= y_tolerance_addr:
                    # 같은 행일 때: 레이블 우측 (레이블 폭의 절반 이상 오른쪽에 있는 것)
                    # 다른 행(하단 행)일 때: 레이블 시작 위치 대비 약간 왼쪽(x-150)까지 포함하여 다음 줄에 시작하는 주소 수집
                    is_same_row = abs(y_diff) <= max(word['height'] * 0.8, 12)
                    if is_same_row:
                        if other['x'] > word['x'] + word['width'] * 0.5:
                            addr_candidates.append(other)
                    else:
                        if other['x'] > word['x'] - 150:
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
                # ── 개별 단어 단위 상세주소 판별 마스킹 ────────────────────────────
                seen_base_addr = False
                for aw in addr_words:
                    aw_text_norm = re.sub(r'[\[\]]', '', aw['text']).strip()
                    if not aw_text_norm:
                        continue
                    
                    has_kw = False
                    last_kw_idx = -1
                    # 행정구역 키워드 검색
                    for kw in ["구", "동", "읍", "면", "로", "길", "시", "도", "군", "가"]:
                        idx = aw_text_norm.rfind(kw)
                        if idx != -1:
                            has_kw = True
                            last_kw_idx = max(last_kw_idx, idx)
                            
                    # 단어 내에서 숫자의 시작 위치 탐색
                    num_match = re.search(r'\d', aw_text_norm)
                    num_start_idx = num_match.start() if num_match else -1
                    
                    if has_kw:
                        seen_base_addr = True
                        
                        # 1. 키워드 이후에 숫자가 있는 경우 (예: "대연3동54-1")
                        after_kw_str = aw_text_norm[last_kw_idx + 1:]
                        num_match_after = re.search(r'\d', after_kw_str)
                        
                        if num_match_after:
                            split_idx = (last_kw_idx + 1) + num_match_after.start()
                            char_w = aw['width'] / max(1, len(aw_text_norm))
                            mask_regions.append({
                                'x': int(aw['x'] + split_idx * char_w),
                                'y': aw['y'],
                                'width': int((len(aw_text_norm) - split_idx) * char_w),
                                'height': aw['height']
                            })
                        # 2. 키워드 이전 또는 키워드 포함 부위에 숫자가 있는 경우 (예: "123번길", "대연3동")
                        elif num_start_idx != -1:
                            # 숫자 부분부터 키워드까지의 텍스트 추출
                            num_to_kw = aw_text_norm[num_start_idx:last_kw_idx + 1]
                            num_part = re.sub(r'\D', '', num_to_kw)
                            kw_part = re.sub(r'\d', '', num_to_kw)
                            
                            # 1자리 숫자 + [동/가/읍/면/시/도] 인 경우는 행정구역 번호이므로 노출 유지
                            is_admin_dong = len(num_part) == 1 and kw_part in ["동", "가", "읍", "면", "시", "도"]
                            
                            if is_admin_dong:
                                pass
                            else:
                                # 그 외의 건물번호(123번길 등)나 도로명 숫자는 숫자 시작 위치부터 마스킹
                                split_idx = num_start_idx
                                char_w = aw['width'] / max(1, len(aw_text_norm))
                                mask_regions.append({
                                    'x': int(aw['x'] + split_idx * char_w),
                                    'y': aw['y'],
                                    'width': int((len(aw_text_norm) - split_idx) * char_w),
                                    'height': aw['height']
                                })
                        else:
                            # 숫자가 없는데 키워드 이후에 문자가 더 붙어 있다면 부분 마스킹
                            if last_kw_idx + 1 < len(aw_text_norm):
                                split_idx = last_kw_idx + 1
                                char_w = aw['width'] / max(1, len(aw_text_norm))
                                mask_regions.append({
                                    'x': int(aw['x'] + split_idx * char_w),
                                    'y': aw['y'],
                                    'width': int((len(aw_text_norm) - split_idx) * char_w),
                                    'height': aw['height']
                                })
                    else:
                        # 행정구역 키워드가 없으면서, 이미 기본 주소를 지났거나 첫 단어부터 없는 경우 상세주소 단어로 간주하여 박스 전체 마스킹
                        mask_regions.append({
                            'x': aw['x'], 'y': aw['y'],
                            'width': aw['width'], 'height': aw['height']
                        })
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


def detect_personal_info_multi_stage(image_path, name_mask_style="middle", mask_type="mosaic"):
    """
    1차 OCR 및 마스킹 적용 후, 명암비 스트레칭 왜곡 해소 효과를 이용해 2차 OCR 및 마스킹 분석을 연속으로 수행합니다.
    이를 통해 대비 왜곡으로 인해 1차에서 인식에 실패하여 누락되었던 개인정보(예: 면허번호, 연락처 등)를
    다단계(Iterative)로 구제하여 누락률을 최소화합니다.
    """
    import tempfile
    import uuid
    from PIL import Image, ImageDraw
    
    # 1. 1차 OCR 수행
    ocr_result_1 = run_ocr(image_path)
    if ocr_result_1.get("status") != "success":
        return [], [], ocr_result_1

    mask_regions_1, label_regions_1 = detect_personal_info(ocr_result_1, name_mask_style)
    
    # 누적할 최종 마스킹 영역 및 라벨 영역
    accumulated_masks = list(mask_regions_1)
    accumulated_labels = list(label_regions_1)
    
    # 2차 다단계 검증 시도
    temp_img_path_2 = None
    try:
        # 1차 마스킹 결과 이미지 임시 생성
        with Image.open(image_path) as img:
            highlighted = img.copy().convert("RGBA")
            yellow_overlay = Image.new("RGBA", highlighted.size, (0, 0, 0, 0))
            draw_yellow = ImageDraw.Draw(yellow_overlay)
            
            # 1차 강조 표시 적용
            for box in label_regions_1:
                draw_yellow.rectangle(
                    [box['x'], box['y'], box['x'] + box['width'] - 1, box['y'] + box['height'] - 1],
                    fill=(255, 215, 0, 110), outline=(255, 165, 0, 240), width=2
                )
            highlighted = Image.alpha_composite(highlighted, yellow_overlay).convert("RGB")
            
            # 1차 실제 마스킹 적용
            img_masked_1 = apply_mask(highlighted, mask_regions_1, mask_type=mask_type, mosaic_size=10)
            
            # 2차 분석용 임시 파일 저장
            temp_dir = tempfile.gettempdir()
            temp_img_path_2 = os.path.join(temp_dir, f"temp_ocr_stage2_{uuid.uuid4().hex}.png")
            img_masked_1.save(temp_img_path_2)
            
            # 2차 OCR 구동
            ocr_result_2 = run_ocr(temp_img_path_2)
            
            if ocr_result_2.get("status") == "success":
                mask_regions_2, label_regions_2 = detect_personal_info(ocr_result_2, name_mask_style)
                
                # 2차 추가 검출 영역 누적
                for m2 in mask_regions_2:
                    # 중복 방지를 위한 단순 (x, y, w, h) 체크
                    if not any(m1['x'] == m2['x'] and m1['y'] == m2['y'] and m1['width'] == m2['width'] and m1['height'] == m2['height'] for m1 in accumulated_masks):
                        accumulated_masks.append(m2)
                for l2 in label_regions_2:
                    if not any(l1['x'] == l2['x'] and l1['y'] == l2['y'] and l1['width'] == l2['width'] and l1['height'] == l2['height'] for l1 in accumulated_labels):
                        accumulated_labels.append(l2)
                        
    except Exception as e:
        print(f"[다단계 OCR] 2차 마스킹 분석 중 실패 (1차 결과로 유지): {e}")
    finally:
        if temp_img_path_2 and os.path.exists(temp_img_path_2):
            try:
                os.remove(temp_img_path_2)
            except:
                pass
                
    return accumulated_masks, accumulated_labels, ocr_result_1
