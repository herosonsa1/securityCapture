import sys
import io
import os

# PyInstaller GUI (--noconsole) 모드에서 표준 출력 관련 크래시 방지 및 디버깅을 위한 파일 리다이렉트
import tempfile
try:
    log_path = os.path.join(tempfile.gettempdir(), "privacy_masker_debug.log")
    sys.stdout = open(log_path, "a", encoding="utf-8", buffering=1)
    sys.stderr = sys.stdout
    print("\n--- APP START ---")
except Exception as e:
    sys.stdout = io.StringIO()
    sys.stderr = io.StringIO()

import queue
import threading
import tkinter as tk
import winreg
from PIL import Image, ImageDraw
import pystray
from pynput import keyboard

# 내부 모듈 로드
from capture_window import CaptureWindow
from edit_window import EditWindow
from config_manager import load_config, save_config


class PrivacyMaskerApp:
    """
    개인정보 마스킹 캡처 프로그램의 메인 컨트롤러 클래스입니다.
    트레이 아이콘 관리 및 전역 단축키 수신, 스레드-세이프 캡처 흐름 제어를 오케스트레이션합니다.
    """
    def __init__(self):
        self.root = None
        self.tray_icon = None
        self.keyboard_listener = None
        self.capturing = False # 캡처 창이 이미 떠있는지 방지용 플래그
        self.current_edit_win = None # 현재 열려 있는 편집 창 인스턴스 참조 보관용
        
        # 설정 로드 및 마지막 캡처 캐시 변수 초기화
        self.config = load_config()
        self.last_crop_area = None
        
        # 타 캡처프로그램 금지 스레드 및 리스너
        self.block_thread = None
        self.block_running = False
        self._warning_shown = False
        
        # 자체 복사 시 클립보드 보호 차단 우회 플래그
        self.skip_clipboard_clear = False

    def create_tray_image(self):
        """
        메모리 상에서 실시간으로 파란색 방패/자물쇠 형태의 트레이 아이콘 이미지를 렌더링합니다.
        외부 이미지 파일 종속성을 제거하여 배포를 수월하게 합니다.
        """
        image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        dc = ImageDraw.Draw(image)
        # 자물쇠 몸통 (둥근 사각형)
        dc.rounded_rectangle([12, 22, 52, 58], radius=6, fill="#007acc", outline="#ffffff", width=3)
        # 자물쇠 고리 (아크선)
        dc.arc([20, 6, 44, 34], 180, 0, fill="#ffffff", width=4)
        # 자물쇠 내부 구멍 (열쇠구멍 효과)
        dc.ellipse([28, 34, 36, 42], fill="#ffffff")
        dc.polygon([(32, 40), (29, 50), (35, 50)], fill="#ffffff")
        return image

    def on_hotkey_triggered(self):
        """
        단축키 입력 시 실행되는 콜백 함수 (스레드-세이프하게 Tkinter 루프에 전달)
        """
        # 캡처 중이 아니거나, 캡처 중이더라도 활성화된 편집 창이 떠 있다면 핫키 트리거 허용
        if not self.capturing or self.current_edit_win:
            self.root.after(0, self.trigger_capture)

    def trigger_capture(self):
        """
        메인 GUI 루프에서 안전하게 캡처 작업을 개시합니다 (메인 스레드 순차 실행).
        """
        if self.capturing:
            # 캡처 편집창이 열려 있는 상태에서 전역 F9 입력 시 다시 캡처 수행
            if self.current_edit_win:
                self.root.after(0, self.current_edit_win.request_recapture)
            return
        self.capturing = True
        
        # 캡처 및 편집 루프 오케스트레이션 (다시 캡처 기능 지원)
        try:
            recapture = True
            while recapture:
                # 1. 사각 영역 캡처 창 표시
                cap_win = CaptureWindow(self.root)
                crop_area = cap_win.start()
                
                if not crop_area:
                    # 사용자가 캡처를 취소했거나 영역이 유효하지 않은 경우 흐름 종료
                    break
                    
                # 최근 캡처 이미지 데이터 캐싱
                self.last_crop_area = crop_area
                
                # 최신 설정 로드 후 편집창을 열지 않는 즉시 복사 모드 판정
                self.config = load_config()
                show_editor = self.config.get("show_editor", True)
                
                if not show_editor:
                    # 편집창을 생략하고 백그라운드에서 마스킹 및 클립보드 자동 전송 수행
                    self.run_background_masking_flow(crop_area)
                    break
                    
                # 2. 마스킹 편집기 GUI 창 표시 (app_controller로 self 전달)
                edit_win = EditWindow(self.root, crop_area, app_controller=self)
                self.current_edit_win = edit_win
                try:
                    # edit_win.show()는 편집이 끝나고 창이 닫히면 "다시 캡처" 여부 플래그(bool)를 리턴합니다.
                    recapture = edit_win.show()
                finally:
                    self.current_edit_win = None
        finally:
            self.capturing = False

    def run_background_masking_flow(self, crop_area):
        """
        편집창 생략 모드 시 백그라운드 스레드에서 OCR 및 마스킹 처리를 수행하고
        완성된 비트맵 이미지를 클립보드에 무소음 전송 및 알림을 수행합니다.
        """
        def worker():
            import tempfile
            import os
            import subprocess
            import uuid
            from masking_core import run_ocr, detect_personal_info, apply_mask, detect_personal_info_multi_stage
            from config_manager import load_config
            
            # 알림 발송용 유틸리티 함수
            def notify_msg(title, message):
                if self.tray_icon:
                    try:
                        self.tray_icon.notify(message, title)
                    except Exception as e:
                        print(f"알림 전송 실패: {e}")
            
            # 0. 로컬 최신 설정 읽기
            config = load_config()
            mask_type = config.get("mask_type", "mosaic")
            name_mask_style = config.get("name_mask_style", "middle")
            
            unique_id = uuid.uuid4().hex
            
            # 1. OCR 대상 이미지를 임시 저장
            temp_dir = tempfile.gettempdir()
            temp_in_path = os.path.join(temp_dir, f"temp_bg_ocr_{unique_id}.png")
            original_image = crop_area["image"]
            original_image.save(temp_in_path)
            
            # 임시 파일 백그라운드 안전 삭제
            def safe_remove(path):
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
            
            # 2. 다단계 OCR 및 마스킹 수행
            mask_boxes, _label_regions, ocr_result = detect_personal_info_multi_stage(temp_in_path, name_mask_style, mask_type)
            
            if ocr_result.get("status") != "success":
                notify_msg("분석 실패", "OCR 분석에 실패하여 마스킹을 적용하지 못했습니다.")
                safe_remove(temp_in_path)
                return
                
            safe_remove(temp_in_path)
            
            # 3. 이미지 마스킹 필터 적용
            final_img = apply_mask(original_image, mask_boxes, mask_type=mask_type, mosaic_size=10)
            
            # 4. 고속 클립보드 복사 (ctypes API 직접 호출)
            from config_manager import copy_image_to_clipboard
            if copy_image_to_clipboard(final_img):
                cnt = len(mask_boxes)
                if cnt > 0:
                    notify_msg("복사 완료", "개인정보가 제외(마스킹)된 이미지가 클립보드에 복사되었습니다!")
                else:
                    notify_msg("복사 완료", "개인정보가 없는 깨끗한 이미지가 클립보드에 복사되었습니다.")
            else:
                notify_msg("오류 발생", "클립보드 데이터 탑재에 실패했습니다.")
                
            safe_remove(temp_in_path)
                
        # 백그라운드 데몬 스레드로 비동기 구동
        threading.Thread(target=worker, daemon=True).start()

    def toggle_show_editor_opt(self, icon, item):
        """
        트레이 아이콘의 '캡처 후 편집창 열기' 메뉴 선택 시 옵션을 토글 및 영구 보존합니다.
        """
        self.config = load_config()
        self.config["show_editor"] = not self.config.get("show_editor", True)
        save_config(self.config)
        # 트레이 메뉴 상태 동기화를 위해 아이콘 업데이트 유도
        if self.tray_icon:
            self.tray_icon.update_menu()

    def open_last_capture_editor(self):
        """
        가장 최근에 캡처한 이미지 데이터를 복원하여 편집창을 강제 개시합니다.
        """
        if not self.last_crop_area:
            from tkinter import messagebox
            # root 스레드-세이프 대화상자 노출
            self.root.after(0, lambda: messagebox.showwarning("복원 불가", "최근 캡처한 이미지 데이터가 없습니다!\n단축키(F9)로 먼저 화면을 캡처해 주세요.", parent=self.root))
            return
            
        if self.capturing:
            return
            
        def run_editor():
            self.capturing = True
            try:
                # 최근 캡처 복원 편집창 오픈 (app_controller로 self 전달)
                edit_win = EditWindow(self.root, self.last_crop_area, app_controller=self)
                self.current_edit_win = edit_win
                try:
                    edit_win.show()
                finally:
                    self.current_edit_win = None
            finally:
                self.capturing = False
                
        self.root.after(0, run_editor)

    def start_tray(self):
        """
        시스템 트레이 아이콘을 시작합니다.
        """
        menu = pystray.Menu(
            pystray.MenuItem("화면 캡처 (F9)", lambda icon, item: self.on_hotkey_triggered(), default=True),
            pystray.MenuItem("캡쳐편집창 열기", lambda icon, item: self.open_last_capture_editor()),
            pystray.MenuItem("캡처 후 편집창 열기", self.toggle_show_editor_opt, checked=lambda item: self.config.get("show_editor", True)),
            pystray.MenuItem("타 캡쳐프로그램 금지", self.toggle_block_other_captures, checked=lambda item: self.config.get("block_other_captures", False)),
            pystray.Menu.SEPARATOR,
            # 시작 프로그램 등록/해제 토글 (EXE 단독 배포 지원 — bat 파일 불필요)
            pystray.MenuItem(
                "윈도우 시작 시 자동 실행",
                self.toggle_startup,
                checked=lambda item: self.is_in_startup()
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("종료", lambda icon, item: self.root.after(0, self.exit_app))
        )
        
        self.tray_icon = pystray.Icon(
            "PrivacyMasker", 
            self.create_tray_image(), 
            "개인정보마스킹", 
            menu
        )
        # 트레이 아이콘을 백그라운드 스레드에서 구동
        self.tray_icon.run_detached()
        
        # 시스템 트레이 실행 즉시 윈도우 알림 토스트 메시지 전송
        # 캡처 후 편집창 띄우기 옵션이 꺼져(체크해제) 있을 때만 백그라운드 실행을 알리기 위해 토스트 알림을 띄웁니다.
        if not self.config.get("show_editor", True):
            try:
                self.tray_icon.notify(
                    "윈도우 시작 시 자동 기동 등록 완료! F9 를 눌러 즉시 기능을 시작할 수 있습니다.",
                    "개인정보마스킹 실행 중"
                )
            except Exception as e:
                print(f"알림 팝업 전송 실패: {e}")

    def exit_app(self):
        """
        프로그램을 완전히 종료합니다. (메인 GUI 스레드에서 실행되어야 함)
        """
        print("\n프로그램을 종료합니다.")
        
        # 1. 트레이 아이콘 숨기기 및 비동기 종료
        # visible = False로 트레이 아이콘을 즉시 감추고, stop()은 백그라운드 스레드에서 수행해 join 블로킹을 방지합니다.
        if self.tray_icon:
            try:
                self.tray_icon.visible = False
                tray = self.tray_icon
                threading.Thread(target=tray.stop, daemon=True).start()
            except:
                pass
            self.tray_icon = None
            
        # 2. 리스너 중지
        if self.keyboard_listener:
            try:
                self.keyboard_listener.stop()
            except:
                pass
                
        # 2-2. 차단 리스너 및 백그라운드 스레드 정지
        self.stop_capture_blocker()
            
        # 3. Tkinter 루프 종료
        if self.root:
            try:
                self.root.quit()
                self.root.destroy()
            except:
                pass
            
        # OS 트레이 삭제 윈도우 메시지 반영을 위한 지연 시간
        import time
        time.sleep(0.15)
        
        # 프로세스 강제 종료
        os._exit(0)

    def run(self):
        # 1. 백그라운드 Tkinter 루트 창 생성 및 숨김
        self.root = tk.Tk()
        self.root.withdraw() # 메인 루프 관리를 하되 보이지 않게 처리
        
        # 2. 메인 루프 진입 직후(100ms 후) 컴포넌트들을 안전하게 초기화
        # 레이스 컨디션(메인 루프 기동 전 이벤트 트리거로 인한 RuntimeError) 방지
        self.root.after(100, self.setup_app_components)
        
        # 3. Tkinter 메인 루프 돌입
        try:
            self.root.mainloop()
        except KeyboardInterrupt:
            self.exit_app()

    # ── 시작 프로그램 레지스트리 관리 메서드 ────────────────────────────────
    _REG_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
    _REG_VALUE_NAME = "PrivacyMasker"

    def _get_exe_path(self):
        """
        현재 실행 중인 EXE 경로를 반환합니다. (PyInstaller 빌드 EXE 전용)
        개발 스크립트 실행 중이면 None을 반환합니다.
        """
        if getattr(sys, 'frozen', False):
            return os.path.abspath(sys.executable)
        return None

    def is_in_startup(self):
        """
        현재 실행 파일이 윈도우 시작 프로그램에 등록되어 있는지 확인합니다.
        """
        exe_path = self._get_exe_path()
        if not exe_path:
            return False
        try:
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, self._REG_KEY_PATH, 0, winreg.KEY_READ
            )
            val, _ = winreg.QueryValueEx(key, self._REG_VALUE_NAME)
            winreg.CloseKey(key)
            # 등록된 경로가 현재 EXE와 일치하는지 확인 (경로 정규화 비교)
            registered_path = val.strip('"')
            return os.path.normcase(registered_path) == os.path.normcase(exe_path)
        except FileNotFoundError:
            return False
        except Exception as e:
            print(f"시작 프로그램 등록 여부 조회 중 예외: {e}")
            return False

    def add_to_startup(self):
        """
        현재 실행 파일(.exe)을 윈도우 시작 프로그램에 등록합니다.
        """
        exe_path = self._get_exe_path()
        if not exe_path:
            # 개발 스크립트 실행 중이면 등록 생략
            return False
        try:
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, self._REG_KEY_PATH, 0, winreg.KEY_SET_VALUE
            )
            winreg.SetValueEx(key, self._REG_VALUE_NAME, 0, winreg.REG_SZ, f'"{exe_path}"')
            winreg.CloseKey(key)
            print(f"윈도우 시작 프로그램 등록 완료: {exe_path}")
            return True
        except Exception as e:
            print(f"시작 프로그램 등록 중 예외: {e}")
            return False

    def remove_from_startup(self):
        """
        윈도우 시작 프로그램에서 현재 실행 파일 등록을 해제합니다.
        """
        exe_path = self._get_exe_path()
        if not exe_path:
            return False
        try:
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, self._REG_KEY_PATH, 0, winreg.KEY_SET_VALUE
            )
            winreg.DeleteValue(key, self._REG_VALUE_NAME)
            winreg.CloseKey(key)
            print("윈도우 시작 프로그램 등록 해제 완료")
            return True
        except FileNotFoundError:
            print("시작 프로그램에 등록된 항목이 없음 (이미 해제 상태)")
            return True
        except Exception as e:
            print(f"시작 프로그램 해제 중 예외: {e}")
            return False

    def toggle_startup(self, icon, item):
        """
        트레이 메뉴에서 '시작 프로그램 등록' 항목 클릭 시 등록/해제를 토글합니다.
        """
        if self.is_in_startup():
            ok = self.remove_from_startup()
            if self.tray_icon:
                msg = "시작 프로그램 등록이 해제되었습니다." if ok else "등록 해제에 실패했습니다."
                try:
                    self.tray_icon.notify(msg, "개인정보마스킹")
                except Exception:
                    pass
        else:
            ok = self.add_to_startup()
            if self.tray_icon:
                msg = "시작 프로그램에 등록되었습니다.\n다음 로그인부터 자동으로 실행됩니다." if ok else "등록에 실패했습니다."
                try:
                    self.tray_icon.notify(msg, "개인정보마스킹")
                except Exception:
                    pass
        if self.tray_icon:
            self.tray_icon.update_menu()

    def setup_app_components(self):
        """
        Tkinter mainloop이 구동된 직후 안전하게 트레이 아이콘과 단축키 리스너를 켭니다.
        """
        # 1. 시스템 트레이 시작
        self.start_tray()
        
        # 1-2. 타 캡처프로그램 금지 백그라운드 스레드 가동
        self.start_capture_blocker()
        
        # 2. 단일 통합 전역 키보드 리스너 구동 (F9 핫키 감지 및 PrintScreen 차단 통합)
        self.start_keyboard_listener()

    def start_keyboard_listener(self):
        """
        단 하나의 전역 키보드 리스너를 가동하여 F9 핫키 감지, PrintScreen 및 Windows+Shift+S 차단을 일괄 처리합니다.
        pynput 리스너 중복 구동으로 인한 윈도우 훅 충돌을 원천 차단합니다.
        """
        if self.keyboard_listener:
            return

        import ctypes
        GetAsyncKeyState = ctypes.windll.user32.GetAsyncKeyState
        GetAsyncKeyState.argtypes = [ctypes.c_int]
        GetAsyncKeyState.restype = ctypes.c_short

        def win32_filter(msg, data):
            # 1. F9 단축키 처리 (VK_F9 = 0x78)
            # WM_KEYDOWN = 0x0100, WM_SYSKEYDOWN = 0x0104
            if data.vkCode == 0x78:
                if msg in (0x0100, 0x0104):
                    self.root.after(0, self.on_hotkey_triggered)
                return False  # 시스템 전파 차단하여 핫키만 삼킴

            # '타 캡쳐프로그램 금지' 설정이 활성화된 경우만 캡처 단축키 차단 처리
            cur_cfg = load_config()
            if cur_cfg.get("block_other_captures", False):
                # 2. PrintScreen 차단 처리 (VK_SNAPSHOT = 0x2C)
                if data.vkCode == 0x2C:
                    if msg in (0x0100, 0x0104):
                        print("[차단] Print Screen 키 입력 무효화 완료")
                        self.root.after(0, self.show_block_warning)
                    return False  # 시스템 전파 차단하여 캡처 방지

                # 3. Windows + Shift + S 차단 처리 ('S' 키 = 0x53)
                if data.vkCode == 0x53:
                    # Windows 키 상태 검사 (LWIN: 0x5B, RWIN: 0x5C)
                    win_pressed = (GetAsyncKeyState(0x5B) & 0x8000) or (GetAsyncKeyState(0x5C) & 0x8000)
                    # Shift 키 상태 검사 (SHIFT: 0x10, LSHIFT: 0xA0, RSHIFT: 0xA1)
                    shift_pressed = (GetAsyncKeyState(0x10) & 0x8000) or (GetAsyncKeyState(0xA0) & 0x8000) or (GetAsyncKeyState(0xA1) & 0x8000)
                    
                    if win_pressed and shift_pressed:
                        if msg in (0x0100, 0x0104):
                            print("[차단] Windows+Shift+S 단축키 입력 무효화 완료")
                            self.root.after(0, self.show_block_warning)
                        return False  # 시스템 전파 차단하여 캡처 방지

            return True

        try:
            self.keyboard_listener = keyboard.Listener(win32_event_filter=win32_filter)
            self.keyboard_listener.start()
            print("[Keyboard] 단일 통합 키보드 리스너 구동 시작")
        except Exception as e:
            print(f"[Keyboard] 통합 키보드 리스너 기동 실패: {e}")

    def show_block_warning(self):
        """
        타 캡처 단축키 입력 시 차단 안내 경고창을 표시합니다.
        F9 부분을 강조하고 2줄로 깔끔하게 표현하는 커스텀 모달 다이얼로그를 사용합니다.
        """
        if getattr(self, "_warning_shown", False):
            return
        self._warning_shown = True

        # 커스텀 다이얼로그 생성
        dialog = tk.Toplevel(self.root)
        dialog.title("캡처 사용 불가 안내")
        dialog.resizable(False, False)
        dialog.attributes("-topmost", True)  # 항상 위에 노출
        dialog.transient(self.root)
        dialog.grab_set()

        # 크기 및 중앙 배치 계산
        win_w, win_h = 380, 160
        screen_w = dialog.winfo_screenwidth()
        screen_h = dialog.winfo_screenheight()
        pos_x = (screen_w - win_w) // 2
        pos_y = (screen_h - win_h) // 2
        dialog.geometry(f"{win_w}x{win_h}+{pos_x}+{pos_y}")

        # 스타일 정의
        bg_color = "#F8F9FA"  # 부드러운 소프트 화이트
        btn_color = "#0078D7"  # 모던 윈도우 블루
        btn_active = "#106EBE"
        
        dialog.config(bg=bg_color)
        
        # 내부 패딩 프레임
        frame = tk.Frame(dialog, bg=bg_color, padx=24, pady=20)
        frame.pack(fill=tk.BOTH, expand=True)

        # 텍스트 영역 (Rich Text 지원용 Text 위젯)
        text_area = tk.Text(
            frame, 
            wrap=tk.WORD, 
            font=("Malgun Gothic", 10), 
            bg=bg_color, 
            relief=tk.FLAT, 
            highlightthickness=0, 
            height=3, 
            width=40
        )
        text_area.pack(fill=tk.X, expand=True)

        # 태그 정의
        text_area.tag_configure("normal", foreground="#202124", spacing1=4)
        text_area.tag_configure("highlight", foreground="#D93025", font=("Malgun Gothic", 11, "bold")) # 구글 에러 레드 계열

        # 텍스트 삽입 (2줄)
        text_area.insert(tk.END, "타 캡쳐프로그램은 사용 불가 합니다.\n", "normal")
        text_area.insert(tk.END, "F9 ", "highlight")
        text_area.insert(tk.END, "키를 사용하여 개인정보 마스킹캡쳐를 이용해 주세요.", "normal")
        
        text_area.config(state=tk.DISABLED)

        # 닫힐 때 플래그 해제 처리
        def on_close():
            self._warning_shown = False
            dialog.destroy()

        dialog.protocol("WM_DELETE_WINDOW", on_close)

        # 모던 버튼 구현
        btn_style = {
            "font": ("Malgun Gothic", 10, "bold"),
            "fg": "white",
            "bg": btn_color,
            "activeforeground": "white",
            "activebackground": btn_active,
            "relief": tk.FLAT,
            "cursor": "hand2",
            "bd": 0,
            "padx": 20,
            "pady": 6
        }
        btn = tk.Button(frame, text="확인", command=on_close, **btn_style)
        btn.pack(pady=(12, 0))
        
        # 3. 최초 실행 시 시작 프로그램 자동 등록 (아직 등록 안 된 경우만)
        # 트레이 메뉴의 '윈도우 시작 시 자동 실행' 항목에서 언제든 해제 가능합니다.
        if getattr(sys, 'frozen', False) and not self.is_in_startup():
            if self.add_to_startup():
                try:
                    self.tray_icon.notify(
                        "시작 프로그램에 자동 등록되었습니다.\n"
                        "해제하려면 트레이 메뉴 → '윈도우 시작 시 자동 실행'을 클릭하세요.",
                        "개인정보마스킹"
                    )
                except Exception:
                    pass

        # 4. 콘솔 상태 출력
        print("==========================================================")
        print("개인정보 마스킹 화면 캡처 프로그램이 구동되었습니다.")
        print("- 캡처 단축키: [ F9 ]")
        print("- 트레이 메뉴에서 '윈도우 시작 시 자동 실행' 등록/해제 가능")
        print("- 윈도우 우측 하단 시스템 트레이에서 프로그램을 종료할 수 있습니다.")
        print("==========================================================")

    # ── 타 캡쳐프로그램 금지 옵션 관리 메서드 ───────────────────────────────
    def toggle_block_other_captures(self, icon, item):
        """
        트레이 메뉴에서 '타 캡쳐프로그램 금지' 메뉴 토글 시 옵션을 활성화/비활성화합니다.
        """
        self.config = load_config()
        val = not self.config.get("block_other_captures", False)
        self.config["block_other_captures"] = val
        save_config(self.config)
        
        # 트레이 메뉴 갱신
        if self.tray_icon:
            self.tray_icon.update_menu()
            
        # 차단기 상태 갱신
        self.start_capture_blocker()
        
        # 알림 메시지 노출
        if self.tray_icon:
            msg = "타 캡쳐프로그램 동작 및 Print Screen 캡처가 금지되었습니다." if val else "타 캡쳐프로그램 금지 옵션이 해제되었습니다."
            try:
                self.tray_icon.notify(msg, "개인정보마스킹")
            except:
                pass

    def start_capture_blocker(self):
        """
        설정 상태에 맞춰 백그라운드 차단 스레드를 켭니다.
        """
        self.config = load_config()
        enabled = self.config.get("block_other_captures", False)
        
        # 1. 백그라운드 프로세스/클립보드 감시 스레드 가동
        if enabled:
            if not self.block_running:
                self.block_running = True
                self.block_thread = threading.Thread(target=self.capture_block_worker, daemon=True)
                self.block_thread.start()
        else:
            self.block_running = False

    def stop_capture_blocker(self):
        """
        차단 관련 자원을 정지하고 소거합니다.
        """
        self.block_running = False

    def capture_block_worker(self):
        """
        0.5초마다 타 캡처 도구 프로세스를 강제 종료합니다.
        """
        import time
        import subprocess
        
        # 강제 차단할 캡처 프로그램 목록
        block_processes = [
            "SnippingTool.exe",        # 윈도우 기본 캡처 도구
            "ScreenSketch.exe",        # 캡처 및 스케치
            "SnippingToolProcess.exe", # Windows 11 캡처 도구 프로세스
            "ALCapture.exe",           # 알캡처
            "PicPick.exe",             # 픽픽
            "ShareX.exe"               # ShareX
        ]
        
        # 프로세스 종료용 CMD 명령 비동기 실행을 위한 구조체 설정 (콘솔창 숨김)
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = subprocess.SW_HIDE
        
        print("[Blocker] 감시 스레드 구동 시작")
        
        while self.block_running:
            # 1. 캡처 프로그램 프로세스 강제 종료 시도
            kill_cmds = []
            for p in block_processes:
                kill_cmds.append(f"/im {p}")
            cmd_args = ["taskkill", "/F"] + kill_cmds
            
            try:
                subprocess.Popen(
                    cmd_args, 
                    startupinfo=startupinfo, 
                    stdout=subprocess.DEVNULL, 
                    stderr=subprocess.DEVNULL
                )
            except Exception as e:
                print(f"[Blocker] taskkill 오류: {e}")
                
            time.sleep(0.5)
            
        print("[Blocker] 감시 스레드 구동 종료")


# 전역 변수로 뮤텍스 객체 참조를 유지하여 가비지 컬렉터에 의해 핸들이 닫히는 현상을 방지합니다.
app_mutex = None

if __name__ == "__main__":
    import ctypes
    from tkinter import messagebox
    import tkinter as tk
    
    # 윈도우 전역 뮤텍스 상수 및 API 선언
    ERROR_ALREADY_EXISTS = 183
    mutex_name = "Global\\PrivacyMasker_SingleInstance_Mutex_829cf3"
    
    CreateMutex = ctypes.windll.kernel32.CreateMutexW
    GetLastError = ctypes.windll.kernel32.GetLastError
    
    # 뮤텍스 생성 시도
    app_mutex = CreateMutex(None, True, mutex_name)
    last_error = GetLastError()
    
    if last_error == ERROR_ALREADY_EXISTS:
        # 가짜 tk 루트 창을 임시 생성하여 경고 팝업이 활성화되도록 제어
        root = tk.Tk()
        root.withdraw()
        messagebox.showwarning(
            "중복 실행 방지",
            "개인정보마스킹 프로그램이 이미 백그라운드에서 실행 중입니다.\n\n"
            "화면 오른쪽 아래(작업 표시줄 트레이 아이콘 영역)에서 해당 아이콘을 확인해 주세요.",
            parent=root
        )
        root.destroy()
        sys.exit(0)
        
    app = PrivacyMaskerApp()
    app.run()
