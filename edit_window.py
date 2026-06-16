import os
import subprocess
import tempfile
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from PIL import Image, ImageDraw, ImageTk
from masking_core import run_ocr, detect_personal_info, apply_mask, detect_personal_info_multi_stage
from config_manager import load_config, save_config


class EditWindow:
    """
    캡처된 이미지를 보여주고, 자동 마스킹된 영역을 편집(추가/제거)하며,
    클립보드 복사 또는 파일 저장을 수행하는 모던 편집 GUI 창입니다.
    """
    def __init__(self, parent, crop_area):
        self.parent = parent
        self.crop_area = crop_area
        self.original_image = crop_area["image"]
        self.x_offset = crop_area["x"]
        self.y_offset = crop_area["y"]
        
        self.root = None
        self.canvas = None
        
        # 마스킹 상자 좌표 리스트: [{'x': x, 'y': y, 'width': w, 'height': h}]
        # 캡처본 내부 이미지 기준 상대 좌표
        self.mask_boxes = []
        
        # 개인정보 항목명(레이블) 강조 박스 좌표 리스트
        # 예: "주민등록번호", "성명", "전화번호" 등의 레이블 단어 위치
        self.label_boxes = []
        
        # 로컬 설정 로드
        self.config = load_config()
        
        # 마스킹 타입: "mosaic" 또는 "black"
        self.mask_type = self.config.get("mask_type", "mosaic")
        
        # 이름 마스킹 방식: "middle"(가운데 가림) 또는 "surname"(성씨만 남김)
        self.name_mask_style = self.config.get("name_mask_style", "middle")
        
        # 캡처 후 편집창 항상 열기 옵션
        self.show_editor_opt = self.config.get("show_editor", True)
        
        # OCR 결과 캐시 (이름 마스킹 방식 변경 시 실시간 재사용)
        self.ocr_result_cache = None
        
        # 수동 마스킹 드래그용 임시 좌표
        self.drag_start_x = None
        self.drag_start_y = None
        self.drag_rect_id = None
        
        # 표시용 이미지 PhotoImage 레퍼런스 유지
        self.display_image_tk = None
        
        # 다시 캡처 요청 상태 플래그
        self.recapture_requested = False
        
        # 원형 로딩 스피너 관련 상태 변수
        self.spinner_angle = 0
        self.spinner_items = []
        self.spinner_running = False

    def show(self):
        # 1. OCR 엔진 백그라운드 구동을 위해 임시 저장
        import uuid
        temp_dir = tempfile.gettempdir()
        temp_img_path = os.path.join(temp_dir, f"temp_ocr_{uuid.uuid4().hex}.png")
        self.original_image.save(temp_img_path)
        
        # 2. Tkinter Toplevel 창 설정 (이미지 크기에 맞게 생성)
        self.root = tk.Toplevel(self.parent)
        self.root.title("개인정보마스킹")
        self.root.configure(bg="#1e1e1e") # 프리미엄 다크 모드 배경
        
        # 모니터 해상도 한도 내에서 윈도우 크기 맞추기
        img_w, img_h = self.original_image.size
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        
        # 여유 공간 확보를 위한 마진 설정 (최소 크기를 가로 720, 세로 520으로 보장)
        win_w = max(img_w + 40, 720)
        win_h = max(img_h + 130, 520)
        
        win_w = min(win_w, int(screen_w * 0.9))
        win_h = min(win_h, int(screen_h * 0.9))
        
        # 화면 중앙 배치 계산
        pos_x = (screen_w - win_w) // 2
        pos_y = (screen_h - win_h) // 2
        self.root.geometry(f"{win_w}x{win_h}+{pos_x}+{pos_y}")
        self.root.minsize(720, 520) # 창의 최소 크기 강제!
        
        # F9 단축키 입력 시 다시 캡처 기능이 작동하도록 바인딩
        self.root.bind("<F9>", lambda event: self.request_recapture())
        
        # 포커스 강제 (topmost 제거로 타 창과 자유로운 전환 보장)
        self.root.focus_force()
        
        # 3. 레이아웃 분할
        # 상단 알림 라벨
        self.info_label = tk.Label(
            self.root, 
            text="개인정보 자동 탐지 중입니다. 잠시만 기다려주세요...", 
            fg="#e0e0e0", bg="#1e1e1e", font=("맑은 고딕", 10, "bold")
        )
        self.info_label.pack(pady=10)
        
        # 4. 하단 툴바 레이아웃 (다크 모드 스타일 버튼) - 창 세로 크기 감소 시 툴바 잘림을 막기 위해 canvas_frame보다 먼저 아래쪽에 팩(pack)합니다.
        toolbar = tk.Frame(self.root, bg="#1e1e1e")
        toolbar.pack(fill="x", side="bottom", pady=10, padx=20)

        # 툴바 내부를 2단(옵션 표시용 첫 번째 줄, 동작 실행 버튼용 두 번째 줄)으로 구분하여 가로 폭 부족으로 인한 버튼 잘림을 완전히 차단합니다.
        options_bar = tk.Frame(toolbar, bg="#1e1e1e")
        options_bar.pack(fill="x", side="top", pady=5)
        
        actions_bar = tk.Frame(toolbar, bg="#1e1e1e")
        actions_bar.pack(fill="x", side="top", pady=5)

        # 중앙 이미지 스크롤 지원 가능한 프레임 구성 - 남은 공간을 꽉 채우도록 툴바보다 늦게 팩합니다.
        canvas_frame = tk.Frame(self.root, bg="#1e1e1e")
        canvas_frame.pack(fill="both", expand=True, padx=20, pady=5)
        
        # 가로/세로 스크롤바 추가
        h_scroll = tk.Scrollbar(canvas_frame, orient="horizontal")
        h_scroll.pack(side="bottom", fill="x")
        v_scroll = tk.Scrollbar(canvas_frame, orient="vertical")
        v_scroll.pack(side="right", fill="y")
        
        # Canvas 생성
        self.canvas = tk.Canvas(
            canvas_frame, 
            width=img_w, height=img_h, 
            bg="#2d2d2d", highlightthickness=1, highlightbackground="#3d3d3d",
            xscrollcommand=h_scroll.set, yscrollcommand=v_scroll.set,
            scrollregion=(0, 0, img_w, img_h)
        )
        self.canvas.pack(fill="both", expand=True)
        h_scroll.config(command=self.canvas.xview)
        v_scroll.config(command=self.canvas.yview)
        
        # --- 1단: 옵션 바 설정 ---
        # 1-1. 마스킹 타입 라디오 버튼
        self.mask_type_var = tk.StringVar(value=self.mask_type)
        rb_frame = tk.LabelFrame(options_bar, text="마스킹 스타일", fg="#e0e0e0", bg="#1e1e1e", bd=1, font=("맑은 고딕", 9))
        rb_frame.pack(side="left", padx=10)
        
        rb_mosaic = tk.Radiobutton(
            rb_frame, text="모자이크", variable=self.mask_type_var, value="mosaic",
            command=self.on_mask_type_change, fg="#e0e0e0", bg="#1e1e1e", selectcolor="#2d2d2d",
            activeforeground="#ffffff", activebackground="#1e1e1e"
        )
        rb_mosaic.pack(side="left", padx=5, pady=2)
        
        rb_black = tk.Radiobutton(
            rb_frame, text="블랙박스", variable=self.mask_type_var, value="black",
            command=self.on_mask_type_change, fg="#e0e0e0", bg="#1e1e1e", selectcolor="#2d2d2d",
            activeforeground="#ffffff", activebackground="#1e1e1e"
        )
        rb_black.pack(side="left", padx=5, pady=2)
        
        # 1-2. 이름 마스킹 방식 라디오 버튼
        self.name_mask_var = tk.StringVar(value=self.name_mask_style)
        name_rb_frame = tk.LabelFrame(options_bar, text="이름 마스킹 방식", fg="#e0e0e0", bg="#1e1e1e", bd=1, font=("맑은 고딕", 9))
        name_rb_frame.pack(side="left", padx=10)
        
        rb_name_middle = tk.Radiobutton(
            name_rb_frame, text="가운데 가림 (김*기)", variable=self.name_mask_var, value="middle",
            command=self.on_name_mask_style_change, fg="#e0e0e0", bg="#1e1e1e", selectcolor="#2d2d2d",
            activeforeground="#ffffff", activebackground="#1e1e1e"
        )
        rb_name_middle.pack(side="left", padx=5, pady=2)
        
        rb_name_surname = tk.Radiobutton(
            name_rb_frame, text="성씨만 남김 (김**)", variable=self.name_mask_var, value="surname",
            command=self.on_name_mask_style_change, fg="#e0e0e0", bg="#1e1e1e", selectcolor="#2d2d2d",
            activeforeground="#ffffff", activebackground="#1e1e1e"
        )
        rb_name_surname.pack(side="left", padx=5, pady=2)
        
        # 1-3. 편집창 생략 모드 체크박스
        self.show_editor_var = tk.BooleanVar(value=self.show_editor_opt)
        chk_show_editor = tk.Checkbutton(
            options_bar, text="캡처 후 편집창 열기", variable=self.show_editor_var,
            command=self.on_show_editor_change, fg="#e0e0e0", bg="#1e1e1e", selectcolor="#2d2d2d",
            activeforeground="#ffffff", activebackground="#1e1e1e", font=("맑은 고딕", 9)
        )
        chk_show_editor.pack(side="left", padx=15)
        
        # --- 2단: 액션 버튼 모음 ---
        btn_style = {
            "font": ("맑은 고딕", 9, "bold"),
            "fg": "#ffffff",
            "activeforeground": "#ffffff",
            "bd": 0,
            "padx": 15,
            "pady": 6,
            "cursor": "hand2"
        }
        
        btn_close = tk.Button(actions_bar, text="취소", command=self.close_editor, bg="#4e4e4e", activebackground="#5e5e5e", **btn_style)
        btn_close.pack(side="right", padx=5)
        
        btn_save = tk.Button(actions_bar, text="파일 저장", command=self.save_file, bg="#008060", activebackground="#009e76", **btn_style)
        btn_save.pack(side="right", padx=5)
        
        btn_recapture = tk.Button(actions_bar, text="다시 캡처 (F9)", command=self.request_recapture, bg="#b37400", activebackground="#d68b00", **btn_style)
        btn_recapture.pack(side="right", padx=5)
        
        # 5. 초기 캔버스 화면 드로잉 (아직 마스킹 없음)
        self.redraw_canvas()
        
        # 원형 로딩 스피너 시작
        self.start_spinner()
        
        # 6. 마우스 바인딩 (수동 추가 및 클릭 제거)
        self.canvas.bind("<ButtonPress-1>", self.on_canvas_press)
        self.canvas.bind("<B1-Motion>", self.on_canvas_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_canvas_release)
        
        # 7. 비동기 OCR 연동 시작 (GUI가 뜬 뒤 100ms 후 실행하여 GUI 락다운 지연 방지)
        self.root.after(100, lambda: self.async_ocr_and_mask(temp_img_path))
        
        # Toplevel 창이 파괴(destroy)될 때까지 스크립트 실행의 흐름 대기
        self.parent.wait_window(self.root)
                
        return self.recapture_requested

    def async_ocr_and_mask(self, temp_img_path):
        """
        백그라운드 데몬 스레드에서 다단계 OCR 및 마스킹을 구동하여 Tkinter 메인 GUI 스레드가 얼어붙는 현상을 차단합니다.
        이를 통해 사용자가 캡처 즉시 [취소/닫기]를 눌러도 딜레이 없이 창이 0.001초만에 즉시 닫힙니다.
        """
        def ocr_worker():
            mask_regions, label_regions, ocr_result = detect_personal_info_multi_stage(
                temp_img_path, self.name_mask_style, self.mask_type
            )
            # 메인 스레드 Tcl 컨텍스트로 콜백 연동 (창이 살아있는 상태에서만 수행)
            if self.root:
                try:
                    self.root.after(0, lambda: self.on_ocr_complete(mask_regions, label_regions, ocr_result, temp_img_path))
                except:
                    # 백그라운드 처리 도중 창이 닫힌 경우
                    self.safe_remove_temp_file(temp_img_path)
            else:
                self.safe_remove_temp_file(temp_img_path)
                
        threading.Thread(target=ocr_worker, daemon=True).start()

    def on_ocr_complete(self, mask_regions, label_regions, ocr_result, temp_img_path):
        """
        비동기 OCR 완료 시 메인 스레드 상에서 실행되는 렌더링 및 자동 복사 콜백 메서드입니다.
        """
        if not self.root:
            self.safe_remove_temp_file(temp_img_path)
            return

        # 백그라운드 분석이 완료되었으므로 원형 로딩 스피너 정지 및 제거
        self.stop_spinner()
            
        if ocr_result.get("status") == "success":
            # 디버깅용 OCR 결과 로컬 세이브
            try:
                import json
                debug_path = r"C:\Users\Herosonsa\.gemini\antigravity-ide\brain\26568f6f-fcd2-46c7-a0f8-cea01619caac\last_ocr_result.json"
                with open(debug_path, "w", encoding="utf-8") as f:
                    json.dump(ocr_result, f, ensure_ascii=False, indent=4)
            except Exception as e:
                print(f"디버그 파일 저장 실패: {e}")
                
            self.ocr_result_cache = ocr_result
            
            # 검출된 상대좌표 마스킹 목록에 대입
            self.mask_boxes = mask_regions
            # 검출된 개인정보 항목명(레이블) 박스 목록
            self.label_boxes = label_regions
            
            # 라벨 텍스트 변경
            self.update_info_label()
                
            # 화면 리프레시
            self.redraw_canvas()
            
            # 마스킹 완료 즉시 자동으로 클립보드 복사 수행 (팝업 없이 조용히 복사)
            self.copy_clipboard(show_popup=False)
        else:
            err_msg = ocr_result.get("message", "알 수 없는 에러")
            self.info_label.config(text="OCR 자동 감지에 실패했습니다. (수동 마스킹만 사용 가능)", fg="#ff6666")
            print(f"OCR 에러 상세: {err_msg}")
            
        # 임시 파일 백그라운드 안전 삭제
        self.safe_remove_temp_file(temp_img_path)

    def safe_remove_temp_file(self, path):
        """
        PowerShell 프로세스의 파일 점유 상태를 고려하여 비동기적으로 안전하게 임시 파일을 제거합니다.
        """
        def remove_action():
            import time
            for _ in range(5):
                if os.path.exists(path):
                    try:
                        os.remove(path)
                        break
                    except:
                        time.sleep(0.2)
                else:
                    break
        threading.Thread(target=remove_action, daemon=True).start()

    def update_info_label(self):
        """
        현재 마스킹 상자 개수와 클립보드 복사 완료 상태를 상단 정보 라벨에 표시합니다.
        """
        if not self.info_label:
            return
        cnt = len(self.mask_boxes)
        if cnt > 0:
            self.info_label.config(text=f"개인정보 영역 {cnt}개가 감지되어 마스킹 및 클립보드에 복사되었습니다.", fg="#00cc99")
        else:
            self.info_label.config(text="감지된 개인정보가 없습니다. (원본 이미지 클립보드 복사 완료)", fg="#e0e0e0")

    def redraw_canvas(self):
        """
        캔버스를 새로 그립니다.
        - 개인정보 항목명(레이블): 반투명 황금색 음영으로 강조 표시
          예) "주민등록번호", "성명", "전화번호", "주소" 등 항목명 글자 영역
        - 실제 개인정보 값: 마스킹 필터(모자이크/블랙박스) 처리
          예) "950101-1234567", "홍길동", "010-1234-5678" 등 실제 값
        """
        # 1. 원본 이미지 복사본 위에 노란 강조 오버레이 생성
        base_image = self.original_image.copy().convert("RGBA")
        yellow_overlay = Image.new("RGBA", base_image.size, (0, 0, 0, 0))
        draw_yellow = ImageDraw.Draw(yellow_overlay)
        
        # label_boxes: 개인정보 항목명 레이블 영역에 반투명 황금색 음영 적용
        for box in self.label_boxes:
            x, y, w, h = box['x'], box['y'], box['width'], box['height']
            # 황금빛 반투명 배경 + 진한 황금색 테두리 (항목명 시각 강조)
            draw_yellow.rectangle(
                [x, y, x + w - 1, y + h - 1],
                fill=(255, 215, 0, 110),       # 황금빛 노란색 (43% 불투명도)
                outline=(255, 165, 0, 240),    # 진한 주황-황금색 테두리
                width=2
            )
            
        # 노란 강조 오버레이를 원본 이미지에 합성
        highlighted = Image.alpha_composite(base_image, yellow_overlay).convert("RGB")
        
        # 2. 강조된 이미지에 마스킹(black/mosaic) 적용 (실제 개인정보 값 영역만)
        edit_image = apply_mask(highlighted, self.mask_boxes, mask_type=self.mask_type, mosaic_size=10)
            
        # 3. PhotoImage 생성 및 캔버스 갱신
        self.display_image_tk = ImageTk.PhotoImage(edit_image)
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, anchor="nw", image=self.display_image_tk)

    def on_canvas_press(self, event):
        """
        캔버스를 클릭했을 때 동작.
        만약 기존 마스킹 상자 내부를 클릭했다면 상자를 삭제하고,
        빈 곳이라면 수동 드래그 추가를 시작합니다.
        """
        # Canvas 스크롤 상의 상대 좌표 계산
        click_x = self.canvas.canvasx(event.x)
        click_y = self.canvas.canvasy(event.y)
        
        # 1. 클릭 위치가 기존 마스킹 박스 안에 포함되는지 역순(위 레이어부터)으로 검사
        clicked_box_idx = -1
        for idx in range(len(self.mask_boxes) - 1, -1, -1):
            box = self.mask_boxes[idx]
            x, y, w, h = box['x'], box['y'], box['width'], box['height']
            if x <= click_x <= x + w and y <= click_y <= y + h:
                clicked_box_idx = idx
                break
                
        # 2. 기존 마스킹 박스를 클릭한 경우 -> 삭제 처리
        if clicked_box_idx != -1:
            self.mask_boxes.pop(clicked_box_idx)
            self.redraw_canvas()
            self.update_info_label()
            # 삭제 시 클립보드 조용히 자동 동기화
            self.copy_clipboard(show_popup=False)
            # 드래그가 시작되지 않도록 초기화
            self.drag_start_x = None
            self.drag_start_y = None
        else:
            # 빈 영역 클릭 시 -> 드래그 추가 시작
            self.drag_start_x = click_x
            self.drag_start_y = click_y
            self.drag_rect_id = self.canvas.create_rectangle(
                click_x, click_y, click_x, click_y, 
                outline="#ff3333", width=1, dash=(4, 4)
            )

    def on_canvas_drag(self, event):
        """
        마우스 드래그 중 실시간으로 점선 가이드 그리기
        """
        if self.drag_start_x is None or self.drag_start_y is None:
            return
            
        cur_x = self.canvas.canvasx(event.x)
        cur_y = self.canvas.canvasy(event.y)
        
        self.canvas.coords(self.drag_rect_id, self.drag_start_x, self.drag_start_y, cur_x, cur_y)

    def on_canvas_release(self, event):
        """
        마우스 드래그 종료 시, 영역을 신규 마스킹 박스로 등록
        """
        if self.drag_start_x is None or self.drag_start_y is None:
            return
            
        end_x = self.canvas.canvasx(event.x)
        end_y = self.canvas.canvasy(event.y)
        
        x1 = min(self.drag_start_x, end_x)
        y1 = min(self.drag_start_y, end_y)
        x2 = max(self.drag_start_x, end_x)
        y2 = max(self.drag_start_y, end_y)
        
        width = x2 - x1
        height = y2 - y1
        
        # 유의미한 드래그 크기인 경우에만 마스킹 등록
        if width > 3 and height > 3:
            # 이미지 범위 이내로 클램핑 처리
            img_w, img_h = self.original_image.size
            x1 = max(0, min(x1, img_w))
            y1 = max(0, min(y1, img_h))
            width = min(width, img_w - x1)
            height = min(height, img_h - y1)
            
            new_box = {
                "x": int(x1),
                "y": int(y1),
                "width": int(width),
                "height": int(height)
            }
            self.mask_boxes.append(new_box)
            
        # 가이드 사각형 삭제 및 상태 초기화
        self.canvas.delete(self.drag_rect_id)
        self.drag_start_x = None
        self.drag_start_y = None
        self.drag_rect_id = None
        
        # 최종 다시 그리기 및 클립보드 조용히 자동 동기화
        self.redraw_canvas()
        self.update_info_label()
        self.copy_clipboard(show_popup=False)

    def on_show_editor_change(self):
        """
        편집창 열기 옵션 변경 시 설정을 파일에 즉시 영구 반영합니다.
        """
        self.show_editor_opt = self.show_editor_var.get()
        self.config["show_editor"] = self.show_editor_opt
        save_config(self.config)

    def on_mask_type_change(self):
        """
        마스킹 라디오 버튼 선택 변경 시 스타일 캐시 갱신 및 실시간 갱신
        """
        self.mask_type = self.mask_type_var.get()
        self.config["mask_type"] = self.mask_type
        save_config(self.config)
        self.redraw_canvas()
        self.update_info_label()
        self.copy_clipboard(show_popup=False)

    def on_name_mask_style_change(self):
        """
        이름 마스킹 방식 라디오 버튼 변경 시 호출되는 이벤트 핸들러입니다.
        캐시된 OCR 결과를 이용해 마스킹 영역 좌표를 실시간으로 다시 생성하여 반영합니다.
        """
        self.name_mask_style = self.name_mask_var.get()
        self.config["name_mask_style"] = self.name_mask_style
        save_config(self.config)
        if self.ocr_result_cache:
            # 실시간 재계산
            detected_regions, detected_labels = detect_personal_info(self.ocr_result_cache, self.name_mask_style)
            self.mask_boxes = detected_regions
            self.label_boxes = detected_labels
            
            self.redraw_canvas()
            self.update_info_label()
            # 클립보드 자동 조용히 업데이트
            self.copy_clipboard(show_popup=False)

    def get_final_masked_image(self):
        """
        사용자가 지정한 마스킹 박스들을 실제 필터(모자이크 또는 블랙박스)로 구워 최종 이미지를 생성합니다.
        """
        return apply_mask(self.original_image, self.mask_boxes, mask_type=self.mask_type, mosaic_size=10)

    def copy_clipboard(self, show_popup=True):
        """
        최종 마스킹 이미지를 빌드하고 윈도우 클립보드에 픽셀 비트맵 데이터 형식으로 전송합니다.
        """
        final_img = self.get_final_masked_image()
        
        # 임시 이미지 파일로 세이브
        import uuid
        temp_dir = tempfile.gettempdir()
        temp_out_path = os.path.join(temp_dir, f"temp_copied_capture_{uuid.uuid4().hex}.png")
        final_img.save(temp_out_path)
        
        # PowerShell 백그라운드 구동으로 .NET 클립보드 이미지 세팅
        # Set-Clipboard -Path 명령어는 파일 경로 자체를 복사하므로 메신저 등에서 Ctrl+V가 불가능합니다.
        # 따라서 [System.Windows.Forms.Clipboard]::SetImage를 이용해 이미지 비트맵 픽셀 데이터를 직접 탑재합니다.
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = subprocess.SW_HIDE
        
        # 경로 백슬래시 처리
        safe_path = temp_out_path.replace("\\", "\\\\")
        ps_cmd = (
            "[void][System.Reflection.Assembly]::LoadWithPartialName('System.Windows.Forms'); "
            "[void][System.Reflection.Assembly]::LoadWithPartialName('System.Drawing'); "
            f"$img = [System.Drawing.Image]::FromFile('{safe_path}'); "
            "[System.Windows.Forms.Clipboard]::SetImage($img); "
            "$img.Dispose();"
        )
        
        cmd = [
            "powershell",
            "-NoProfile",
            "-Command",
            ps_cmd
        ]
        
        try:
            result = subprocess.run(cmd, startupinfo=startupinfo, text=True, capture_output=True)
            if result.returncode == 0:
                if show_popup:
                    messagebox.showinfo("완료", "마스킹된 이미지가 클립보드에 복사되었습니다!\n다른 앱에 바로 붙여넣기(Ctrl+V) 하세요.", parent=self.root)
            else:
                if show_popup:
                    messagebox.showerror("실패", f"클립보드 복사 중 파워쉘 오류 발생: {result.stderr}", parent=self.root)
                else:
                    print(f"[클립보드 자동복사 오류] {result.stderr}")
        except Exception as e:
            if show_popup:
                messagebox.showerror("오류", f"클립보드 복사 중 예외 발생: {str(e)}", parent=self.root)
            else:
                print(f"[클립보드 자동복사 예외] {e}")
        finally:
            if os.path.exists(temp_out_path):
                try:
                    os.remove(temp_out_path)
                except:
                    pass

    def save_file(self):
        """
        최종 마스킹 이미지를 로컬 경로에 파일로 저장합니다.
        """
        final_img = self.get_final_masked_image()
        
        file_path = filedialog.asksaveasfilename(
            parent=self.root,
            title="마스킹된 이미지 저장",
            defaultextension=".png",
            filetypes=[("PNG Image", "*.png"), ("All Files", "*.*")]
        )
        
        if file_path:
            try:
                final_img.save(file_path)
                messagebox.showinfo("성공", f"이미지가 성공적으로 저장되었습니다:\n{file_path}", parent=self.root)
            except Exception as e:
                messagebox.showerror("저장 오류", f"파일 저장 중 에러가 발생했습니다:\n{str(e)}", parent=self.root)

    def request_recapture(self):
        """
        다시 캡처 버튼 클릭 시 실행. 창을 즉시 숨겨 다음 스크린샷에 걸리지 않도록 방지하고, 
        창을 닫고 플래그를 True로 반환하여 메인에 전달합니다.
        """
        if self.root:
            self.root.withdraw() # 윈도우 즉시 물리적으로 숨김
            self.root.update()   # 화면 버퍼 갱신 강제
        self.recapture_requested = True
        self.close_editor()

    def close_editor(self):
        # 창이 닫힐 때 원형 스피너 안전하게 종료
        self.stop_spinner()
        if self.root:
            self.root.destroy()
            self.root = None

    def start_spinner(self):
        """캔버스 이미지 중앙에 원형 로딩 스피너 애니메이션을 구동합니다."""
        self.spinner_running = True
        self.spinner_angle = 0
        self.animate_spinner()

    def stop_spinner(self):
        """원형 로딩 스피너를 정지하고 캔버스에 그려진 스피너 잔해를 깨끗하게 제거합니다."""
        self.spinner_running = False
        for item in self.spinner_items:
            try:
                self.canvas.delete(item)
            except:
                pass
        self.spinner_items = []

    def animate_spinner(self):
        """캔버스 중앙에 파란색 아크 원형 링을 30ms 주기로 회전 렌더링합니다."""
        if not self.spinner_running or not self.root:
            return
            
        # 기존 스피너 프레임 요소 소거
        for item in self.spinner_items:
            try:
                self.canvas.delete(item)
            except:
                pass
        self.spinner_items = []
        
        try:
            # 캔버스 이미지 크기의 중앙 좌표 도출
            img_w, img_h = self.original_image.size
            cx = img_w // 2
            cy = img_h // 2
            
            # 더 크고 시인성이 높은 스피너 크기(반지름 45px, 지름 90px)
            r = 45
            
            # 1. 둥근 백그라운드 트랙 회색 링
            bg_ring = self.canvas.create_oval(
                cx - r, cy - r, cx + r, cy + r, 
                outline="#252525", width=4
            )
            self.spinner_items.append(bg_ring)
            
            # 2. 꼬리가 흐려지는 3단계 그라데이션 아크 (역동적인 꼬리 효과)
            # 2-1. 꼬리 부분 (어두운 블루, 40도 범위)
            arc_tail = self.canvas.create_arc(
                cx - r, cy - r, cx + r, cy + r,
                start=(self.spinner_angle - 80) % 360, extent=40,
                style="arc", outline="#003b66", width=4
            )
            self.spinner_items.append(arc_tail)
            
            # 2-2. 몸통 부분 (네이비 블루, 40도 범위)
            arc_body = self.canvas.create_arc(
                cx - r, cy - r, cx + r, cy + r,
                start=(self.spinner_angle - 40) % 360, extent=40,
                style="arc", outline="#007acc", width=4
            )
            self.spinner_items.append(arc_body)
            
            # 2-3. 머리 부분 (테크 밝은 블루, 40도 범위)
            arc_head = self.canvas.create_arc(
                cx - r, cy - r, cx + r, cy + r,
                start=self.spinner_angle, extent=40,
                style="arc", outline="#00d2ff", width=4
            )
            self.spinner_items.append(arc_head)
            
            # 3. 스피너 링 정중앙에 '분석 중' 안내 텍스트 가독성 높여 렌더링
            text_item = self.canvas.create_text(
                cx, cy, 
                text="분석 중", 
                fill="#b0b0b0", 
                font=("맑은 고딕", 9, "bold")
            )
            self.spinner_items.append(text_item)
            
            # 시계 방향 회전 (프레임당 15도로 회전 속도를 역동적으로 향상)
            self.spinner_angle = (self.spinner_angle - 15) % 360
            
            # 30ms 지연 기법으로 자연스러운 애니메이션 루프 수행
            self.root.after(30, self.animate_spinner)
        except Exception as e:
            print(f"[로딩 스피너 애니메이션 예외] {e}")
