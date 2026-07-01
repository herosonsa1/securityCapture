import ctypes
import time
import tkinter as tk
from PIL import Image, ImageTk
# DXGI → MSS → GDI 순서로 폴백하는 화면 획득 모듈 (녹색 DLP 환경 지원)
from screen_grab import grab_screen, get_virtual_screen_bounds, get_monitor_under_cursor



class CaptureWindow:
    """
    단축키 입력 시 실행되는 전체 화면 반투명 캡처 가이드 창입니다.
    사용자가 마우스 드래그를 통해 캡처할 사각형 영역을 선택할 수 있도록 지원합니다.
    """
    def __init__(self, parent):
        self.parent = parent
        self.root = None
        self.canvas = None
        self.screenshot = None
        self.screenshot_tk = None
        
        # 캡처 좌표 기록용 변수
        self.start_x = None
        self.start_y = None
        self.rect_id = None
        self.crop_area = None
        self.canceled = False
        
        # 어두운 반투명 마스크 효과용 캔버스 오브젝트 ID 기록
        self.mask_left = None
        self.mask_right = None
        self.mask_top = None
        self.mask_bottom = None

    def start(self):
        # 단축키 입력 완료 및 포커스 유실 등으로 인한 창 모션 정리를 위해 미세 딜레이(250ms) 부여
        # 다시 캡처 시 이전 편집창이 완전히 사라진 상태에서 화면이 확보되도록 넉넉한 딜레이를 할당합니다.
        time.sleep(0.25)
        
        # 0. 마우스 커서 아래 모니터 정보 구하기
        left, top, width, height = get_monitor_under_cursor()
        
        # 1. 마우스 커서가 위치한 모니터 화면 획득
        # DXGI Desktop Duplication 우선 시도 (DLP WDA_EXCLUDEFROMCAPTURE 우회 가능성)
        self.screenshot = grab_screen(region=(left, top, left + width, top + height))
        
        # 화면 획득 실패 시 안전 종료
        if self.screenshot is None:
            print("[CaptureWindow] 화면 획득 실패 - 모든 방법 시도 실패")
            return None

        # 혹시 metrics 값이 0이면 화면 획득 이미지 크기로 폴백
        if width == 0 or height == 0:
            width, height = self.screenshot.size
            left, top = 0, 0

        # ── DPI 스케일 보정 ─────────────────────────────────────────────────
        # mss/dxcam은 물리픽셀로 캡쳐하고, GetSystemMetrics는 논리픽셀을 반환합니다.
        # (SetProcessDpiAwareness 미설정 시 GetSystemMetrics = 논리픽셀 = Tkinter 좌표계)
        # 두 값이 다른 경우(고DPI 환경) 캡쳐 이미지를 Tkinter 논리픽셀 크기로 리사이즈하여
        # 마우스 선택 좌표 ↔ 이미지 픽셀 좌표 ↔ OCR 단어 좌표가 모두 논리픽셀로 통일됩니다.
        img_w, img_h = self.screenshot.size
        if img_w != width or img_h != height:
            print(f"[DPI보정] 캡쳐이미지({img_w}×{img_h}) → Tkinter창({width}×{height})으로 리사이즈")
            self.screenshot = self.screenshot.resize((width, height), Image.Resampling.LANCZOS)
        # ─────────────────────────────────────────────────────────────────────
        
        # 2. Tkinter Toplevel 윈도우 설정 (메인 루트의 자식 창)
        self.root = tk.Toplevel(self.parent)
        self.root.title("개인정보마스킹")
        
        # 타이틀바를 숨김 (테두리 없는 창)
        self.root.overrideredirect(True)
        # 듀얼 모니터의 음수 좌표계(left, top)를 지원하고, 세로만 1픽셀 줄여 독점 풀스크린 모드 우회
        self.root.geometry(f"{width}x{height-1}+{left}+{top}")
        # 창이 항상 위에 뜨도록 설정
        self.root.attributes("-topmost", True)
        
        # 3. Canvas 생성
        self.canvas = tk.Canvas(self.root, width=width, height=height, highlightthickness=0, cursor="cross")
        self.canvas.pack(fill="both", expand=True)
        
        # 4. 백그라운드 캡처 이미지를 캔버스에 표시
        self.screenshot_tk = ImageTk.PhotoImage(self.screenshot)
        self.canvas.create_image(0, 0, anchor="nw", image=self.screenshot_tk)
        
        # 5. 어두운 복사본 이미지 생성
        self.dimmed_screenshot = Image.blend(self.screenshot, Image.new("RGB", self.screenshot.size, "black"), 0.5)
        self.dimmed_screenshot_tk = ImageTk.PhotoImage(self.dimmed_screenshot)
        
        # 캔버스 밑바닥에는 어두운 이미지를 깔아둡니다.
        self.canvas.create_image(0, 0, anchor="nw", image=self.dimmed_screenshot_tk)
        
        # 드래그 영역을 실시간으로 보여주기 위한 캔버스 조각용 이미지 아이디
        self.bright_patch_id = None
        self.rect_border_id = None
        
        # 6. 이벤트 바인딩
        self.canvas.bind("<ButtonPress-1>", self.on_button_press)
        self.canvas.bind("<B1-Motion>", self.on_move_press)
        self.canvas.bind("<ButtonRelease-1>", self.on_button_release)
        
        # 취소 이벤트 (Esc: 전역 키보드 훅에서도 처리되지만 Tkinter 레벨에서도 바인딩)
        self.root.bind("<Escape>", self.cancel)
        # 우클릭: 취소 옵션이 포함된 컨텍스트 메뉴 팝업
        self.canvas.bind("<Button-3>", self.on_right_click)
        
        # 포커스 강제
        self.root.focus_force()
        
        # Toplevel 창이 파괴(destroy)될 때까지 스크립트 실행의 흐름 대기
        self.parent.wait_window(self.root)
        
        return self.crop_area

    def on_button_press(self, event):
        # 드래그 시작 좌표 기록
        self.start_x = event.x
        self.start_y = event.y

    def on_move_press(self, event):
        cur_x = event.x
        cur_y = event.y
        
        # 드래그 사각형 크기 한계 보정
        x1 = min(self.start_x, cur_x)
        y1 = min(self.start_y, cur_y)
        x2 = max(self.start_x, cur_x)
        y2 = max(self.start_y, cur_y)
        
        if x2 - x1 < 2 or y2 - y1 < 2:
            return
            
        # 1. 이전 밝은 조각 및 보더 제거
        if self.bright_patch_id:
            self.canvas.delete(self.bright_patch_id)
        if self.rect_border_id:
            self.canvas.delete(self.rect_border_id)
            
        # 2. 선택된 밝은 영역 크롭 및 패치 이미지 생성
        patch = self.screenshot.crop((x1, y1, x2, y2))
        self.patch_tk = ImageTk.PhotoImage(patch)
        
        # 3. 캔버스 위에 밝은 패치 표시
        self.bright_patch_id = self.canvas.create_image(x1, y1, anchor="nw", image=self.patch_tk)
        
        # 4. 빨간색 테두리 그리기
        self.rect_border_id = self.canvas.create_rectangle(x1, y1, x2, y2, outline="#ff3333", width=2)

    def on_button_release(self, event):
        end_x = event.x
        end_y = event.y
        
        x1 = min(self.start_x, end_x)
        y1 = min(self.start_y, end_y)
        x2 = max(self.start_x, end_x)
        y2 = max(self.start_y, end_y)
        
        width = x2 - x1
        height = y2 - y1
        
        # 드래그 영역이 너무 작으면 캡처를 취소로 간주
        if width > 5 and height > 5:
            # 원본 이미지에서 사각형 영역 크롭
            cropped = self.screenshot.crop((x1, y1, x2, y2))
            self.crop_area = {
                "image": cropped,
                "x": x1,
                "y": y1,
                "width": width,
                "height": height
            }
            
        self.close_window()

    def on_right_click(self, event):
        """마우스 우클릭 시 캡처 취소 옵션을 담은 컨텍스트 메뉴를 팝업합니다."""
        # 드래그 진행 중 우클릭으로 컨텍스트 메뉴가 열리더라도
        # 드래그 상태 변수를 초기화하여 잔여 드래그 효과가 남지 않도록 처리합니다.
        self.start_x = None
        self.start_y = None
        if self.bright_patch_id:
            self.canvas.delete(self.bright_patch_id)
            self.bright_patch_id = None
        if self.rect_border_id:
            self.canvas.delete(self.rect_border_id)
            self.rect_border_id = None

        menu = tk.Menu(
            self.root,
            tearoff=0,
            bg="#2b2b2b",
            fg="#ffffff",
            activebackground="#ff3333",
            activeforeground="#ffffff",
            bd=0,
            relief="flat",
            font=("맑은 고딕", 10),
        )
        menu.add_command(
            label="  캡처 취소  (ESC)",
            command=self.cancel
        )
        # 메뉴 외부 클릭 시 자동으로 닫히도록 포커스 해제 처리
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def cancel(self, event=None):
        self.canceled = True
        self.crop_area = None
        self.close_window()

    def close_window(self):
        if self.root:
            self.root.destroy()
            self.root = None
