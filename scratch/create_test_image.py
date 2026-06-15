from PIL import Image, ImageDraw, ImageFont
import os

# 이미지를 저장할 경로 설정
image_path = os.path.abspath("test_target.png")

# 하얀색 배경의 이미지 생성 (가로 800, 세로 200)
img = Image.new("RGB", (800, 200), color="white")
draw = ImageDraw.Draw(img)

# 기본 폰트 로드 (한글 지원을 위해 맑은 고딕 사용 또는 기본 폰트 사용)
# Windows의 기본 폰트 경로: C:\Windows\Fonts\malgun.ttf
font_path = "C:\\Windows\\Fonts\\malgun.ttf"
if os.path.exists(font_path):
    font = ImageFont.truetype(font_path, 20)
else:
    font = ImageFont.load_default()

# 개인정보가 포함된 텍스트 작성
text = (
    "개인정보 테스트 이미지\n"
    "이름: 홍길동 (Hong Gil Dong)\n"
    "주민등록번호: 950101-1234567\n"
    "휴대폰 번호: 010-1234-5678 (이메일: security_test@example.com)"
)

# 텍스트 그리기
draw.text((20, 20), text, fill="black", font=font)

# 이미지 저장
img.save(image_path)
print(f"테스트 이미지가 생성되었습니다: {image_path}")
