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
        
        # 자체 복사 시 클립보드 보호 차단 우회 플래그
        self.skip_clipboard_clear = False
        
        # 경고 알림창 중복 활성화 방지 플래그
        self.warning_active = False
        
        # 훅 관련 내부 변수
        self._hook_handle = None
        self._hook_thread_id = None
        self._hook_proc = None
        
        # 관리자 암호 다이얼로그 활성 상태 플래그 (F9 캡처 차단용)
        self._password_dialog_active = False

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
        # 관리자 암호 다이얼로그가 열려 있으면 F9 캡처 무시
        if self._password_dialog_active:
            return
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
            pystray.Menu.SEPARATOR,
            # 시작 프로그램 등록/해제 토글 (EXE 단독 배포 지원 — bat 파일 불필요)
            pystray.MenuItem(
                "윈도우 시작 시 자동 실행",
                self.toggle_startup,
                checked=lambda item: self.is_in_startup()
            ),
            # 타 캡쳐프로그램 금지 토글
            pystray.MenuItem(
                "타 캡쳐프로그램 금지",
                self.toggle_block_captures,
                checked=lambda item: self.config.get("block_other_captures", True)
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("종료", lambda icon, item: self.request_exit_app())
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

    def request_exit_app(self):
        """
        트레이 메뉴에서 '종료' 클릭 시 관리자 암호를 확인한 후 종료합니다.
        """
        if not self.verify_admin_password("프로그램 종료"):
            return
        self.root.after(0, self.exit_app)

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
            
        # 2. 키보드 훅 해제 및 훅 스레드 메시지 루프 종료
        if self.keyboard_listener:
            try:
                import ctypes
                # 훅 스레드에 WM_QUIT을 전달하여 GetMessage 루프를 종료시킴
                if self._hook_thread_id:
                    ctypes.windll.user32.PostThreadMessageW(self._hook_thread_id, 0x0012, 0, 0)
            except:
                pass
            self.keyboard_listener = None
                
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

    def _auto_register_startup(self):
        """
        프로그램 최초 구동 시 윈도우 시작 프로그램에 자동 등록합니다.
        이미 등록되어 있으면 중복 등록을 건너뜁니다.
        """
        if not self.is_in_startup():
            ok = self.add_to_startup()
            if ok:
                print("[자동등록] 윈도우 시작 프로그램에 자동 등록 완료")
            else:
                print("[자동등록] 윈도우 시작 프로그램 자동 등록 실패 (개발 환경이거나 권한 부족)")

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

    # ── 관리자 암호 상수 ──────────────────────────────────────────────────
    _ADMIN_PASSWORD = "Herosonsa1!"

    def verify_admin_password(self, action_description="보안 설정 변경"):
        """
        보안 기능 비활성화 시 관리자 암호를 입력받아 검증합니다.
        올바른 암호 입력 시 True, 취소 또는 오류 시 False를 반환합니다.
        """
        result = [None]  # 스레드 간 결과 전달용
        event = threading.Event()
        
        def ask_password():
            try:
                self._password_dialog_active = True
                
                # 커스텀 암호 입력 다이얼로그 생성
                dialog = tk.Toplevel(self.root)
                dialog.title("관리자 인증")
                dialog.resizable(False, False)
                dialog.wm_attributes('-topmost', True)
                dialog.grab_set()  # 모달 처리
                
                # 창 크기 및 화면 중앙 배치
                dlg_width, dlg_height = 380, 180
                screen_w = dialog.winfo_screenwidth()
                screen_h = dialog.winfo_screenheight()
                x = (screen_w - dlg_width) // 2
                y = (screen_h - dlg_height) // 2
                dialog.geometry(f"{dlg_width}x{dlg_height}+{x}+{y}")
                dialog.minsize(dlg_width, dlg_height)
                
                # 안내 문구
                label = tk.Label(
                    dialog,
                    text=f"{action_description}을(를) 위해\n관리자 암호를 입력하세요:",
                    font=("맑은 고딕", 10),
                    justify="center",
                    pady=10
                )
                label.pack(padx=20, pady=(15, 5))
                
                # 암호 입력 필드
                entry = tk.Entry(dialog, show='*', font=("맑은 고딕", 12), width=28)
                entry.pack(padx=20, pady=5)
                entry.focus_set()
                
                # 버튼 프레임
                btn_frame = tk.Frame(dialog)
                btn_frame.pack(pady=(15, 10))
                
                def on_ok(evt=None):
                    password = entry.get()
                    if password == self._ADMIN_PASSWORD:
                        result[0] = True
                    else:
                        from tkinter import messagebox
                        messagebox.showerror(
                            "인증 실패",
                            "관리자 암호가 올바르지 않습니다.",
                            parent=dialog
                        )
                        result[0] = False
                    dialog.destroy()
                
                def on_cancel(evt=None):
                    result[0] = False
                    dialog.destroy()
                
                ok_btn = tk.Button(btn_frame, text="확인", width=10, command=on_ok)
                ok_btn.pack(side="left", padx=8)
                cancel_btn = tk.Button(btn_frame, text="취소", width=10, command=on_cancel)
                cancel_btn.pack(side="left", padx=8)
                
                # Enter/Escape 키 바인딩
                dialog.bind("<Return>", on_ok)
                dialog.bind("<Escape>", on_cancel)
                dialog.protocol("WM_DELETE_WINDOW", on_cancel)
                
                dialog.wait_window()
            except Exception as e:
                print(f"암호 입력 다이얼로그 오류: {e}")
                result[0] = False
            finally:
                self._password_dialog_active = False
                event.set()
        
        # 메인 스레드(Tkinter)에서 실행
        self.root.after(0, ask_password)
        event.wait(timeout=120)  # 최대 2분 대기
        return result[0] if result[0] is not None else False

    def toggle_startup(self, icon, item):
        """
        트레이 메뉴에서 '시작 프로그램 등록' 항목 클릭 시 등록/해제를 토글합니다.
        비활성화(해제) 시에는 관리자 암호 인증을 요구합니다.
        """
        if self.is_in_startup():
            # 비활성화 시 관리자 암호 요구
            if not self.verify_admin_password("윈도우 시작 시 자동 실행 해제"):
                return
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

    def toggle_block_captures(self, icon, item):
        """
        트레이 메뉴에서 '타 캡쳐프로그램 금지' 항목 클릭 시 활성/비활성을 토글합니다.
        비활성화 시에는 관리자 암호 인증을 요구합니다.
        """
        self.config = load_config()
        current = self.config.get("block_other_captures", True)
        
        if current:
            # 활성 → 비활성 전환: 관리자 암호 요구
            if not self.verify_admin_password("타 캡쳐프로그램 금지 해제"):
                return
        
        self.config["block_other_captures"] = not current
        save_config(self.config)
        
        if self.tray_icon:
            if not current:
                msg = "타 캡쳐프로그램 금지가 활성화되었습니다.\nPrintScreen, Win+Shift+S 등의 캡처가 차단됩니다."
            else:
                msg = "타 캡쳐프로그램 금지가 해제되었습니다.\n다른 캡처 도구를 사용할 수 있습니다."
            try:
                self.tray_icon.notify(msg, "개인정보마스킹")
            except Exception:
                pass
            self.tray_icon.update_menu()

    def setup_app_components(self):
        """
        Tkinter mainloop이 구동된 직후 안전하게 트레이 아이콘과 단축키 리스너를 켭니다.
        """
        # 0. 최초 구동 시 윈도우 시작 프로그램에 자동 등록
        self._auto_register_startup()
        
        # 0-1. 프로그램 기동 시 타 캡쳐프로그램 금지를 항상 활성화 (재시작 시 자동 복원)
        self.config = load_config()
        if not self.config.get("block_other_captures", True):
            self.config["block_other_captures"] = True
            save_config(self.config)
            print("[자동복원] 타 캡쳐프로그램 금지 기능이 활성화 상태로 복원되었습니다.")
        
        # 1. 시스템 트레이 시작
        self.start_tray()
        
        # 2. 전역 키보드 훅 설치 (전용 스레드 방식)
        self.start_keyboard_listener()

        # 3. 콘솔 상태 출력
        self.show_app_info()

    def show_capture_blocked_warning(self):
        """
        타 캡처프로그램 사용 차단 경고 메시지 창을 표시합니다.
        중복 실행을 방지하기 위해 warning_active 플래그로 보호합니다.
        """
        if self.warning_active:
            return
        self.warning_active = True

        def run_warning():
            try:
                from tkinter import messagebox
                # ── self.root는 withdraw() 상태이므로 직접 parent로 쓰면
                #    경고창이 다른 창 뒤에 숨어 보이지 않을 수 있음.
                #    topmost 임시 Toplevel을 parent로 사용하여 최상위 표시 보장.
                popup = tk.Toplevel(self.root)
                popup.withdraw()                          # 창 자체는 숨김
                popup.wm_attributes('-topmost', True)     # 최상위 레이어 고정
                popup.focus_force()                       # 포커스 강제 취득
                messagebox.showwarning(
                    "캡처 불가 안내",
                    "다른 캡쳐프로그램은 사용이 불가합니다.\n'F9' 키를 활용해 캡쳐해주세요.",
                    parent=popup
                )
                popup.destroy()
            except Exception as e:
                print(f"경고 창 표시 실패: {e}")
                # 폴백: 트레이 알림으로 대체
                if self.tray_icon:
                    try:
                        self.tray_icon.notify(
                            "다른 캡쳐프로그램은 사용이 불가합니다.\n'F9' 키를 활용해 캡쳐해주세요.",
                            "캡처 불가 안내"
                        )
                    except Exception:
                        pass
            finally:
                self.warning_active = False

        self.root.after(0, run_warning)

    def start_keyboard_listener(self):
        """
        WH_KEYBOARD_LL 저수준 전역 키보드 훅을 전용 데몬 스레드에서 설치합니다.
        훅은 설치한 스레드의 메시지 루프에서만 콜백을 받기 때문에,
        전용 스레드에서 GetMessage/DispatchMessage 루프를 운영하여
        훅 콜백이 즉시·안정적으로 처리되도록 합니다.
        """
        if self.keyboard_listener:
            return

        import ctypes
        import ctypes.wintypes as wintypes

        user32   = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        WH_KEYBOARD_LL = 13
        WM_KEYDOWN     = 0x0100
        WM_SYSKEYDOWN  = 0x0104

        # ── ctypes 구조체·함수 타입 정의 ──────────────────────────────────────
        # 스레드 내부가 아닌 메서드 스코프에서 한 번만 정의해야 타입 캐시 불일치 오류를 방지합니다.

        class KBDLLHOOKSTRUCT(ctypes.Structure):
            _fields_ = [
                ("vkCode",      wintypes.DWORD),
                ("scanCode",    wintypes.DWORD),
                ("flags",       wintypes.DWORD),
                ("time",        wintypes.DWORD),
                ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
            ]

        class MSG(ctypes.Structure):
            _fields_ = [
                ("hwnd",    wintypes.HWND),
                ("message", wintypes.UINT),
                ("wParam",  wintypes.WPARAM),
                ("lParam",  wintypes.LPARAM),
                ("time",    wintypes.DWORD),
                ("pt",      wintypes.POINT),
            ]

        # HOOKPROC: SetWindowsHookExW에 전달하는 콜백 함수 타입
        # 이 타입은 메서드 스코프에서 한 번만 생성되어 스레드 내부의 클로저로 캡처됩니다.
        # LRESULT = LONG_PTR = 64비트(c_longlong). 반환 타입을 정확히 지정해야 합니다.
        HOOKPROC = ctypes.WINFUNCTYPE(ctypes.c_longlong, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)

        # ── 훅 스레드 작업 함수 ───────────────────────────────────────────────

        def hook_thread_worker():
            """
            전용 Win32 메시지 루프를 운영하는 훅 스레드입니다.
            SetWindowsHookExW → GetMessage 루프 → UnhookWindowsHookEx 순서로 실행됩니다.
            """
            self._hook_thread_id = kernel32.GetCurrentThreadId()

            _hook_handle = ctypes.c_void_p()

            # CallNextHookEx argtypes/restype 미리 설정
            # argtypes 없이 호출하면 lParam(64비트 포인터)이 c_int(32비트)로 절삭되어
            # CallNextHookEx가 실패하고 nonzero를 반환 → 모든 키 차단 버그 발생
            _CallNext = user32.CallNextHookEx
            _CallNext.restype  = ctypes.c_longlong
            _CallNext.argtypes = [ctypes.c_void_p, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]

            def low_level_keyboard_proc(nCode, wParam, lParam):
                """
                저수준 키보드 훅 콜백 함수입니다.
                차단 대상 키는 0을 반환하여 CallNextHookEx를 호출하지 않음으로써
                OS 훅 체인에서 키 이벤트를 완전히 소멸시킵니다.
                """
                if nCode >= 0:
                    kb = ctypes.cast(lParam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
                    vk = kb.vkCode
                    is_key_down = wParam in (WM_KEYDOWN, WM_SYSKEYDOWN)

                    # 1. F9 단축키 처리 (VK_F9 = 0x78) - 프로그램 캡처 트리거
                    if vk == 0x78:
                        if is_key_down:
                            self.root.after(0, self.on_hotkey_triggered)
                        # nonzero 반환: 시스템 및 다음 훅에 전달하지 않음 (MSDN: return nonzero to prevent)
                        return 1

                    # 2. PrintScreen 단축키 처리 (VK_SNAPSHOT = 0x2C)
                    # PrintScreen, Alt+PrintScreen, Ctrl+PrintScreen, Ctrl+Alt+PrintScreen 모두 0x2C 발생
                    # block_other_captures 설정이 활성화된 경우에만 차단
                    if vk == 0x2C and self.config.get("block_other_captures", True):
                        if is_key_down:
                            self.show_capture_blocked_warning()
                        # nonzero 반환: OS 수준에서 캡처 이벤트 완전 차단
                        return 1

                    # 3. Win + Shift + S 단축키 처리 (VK_S = 0x53)
                    # block_other_captures 설정이 활성화된 경우에만 차단
                    if vk == 0x53 and self.config.get("block_other_captures", True):
                        # VK_LWIN = 0x5B, VK_RWIN = 0x5C, VK_SHIFT = 0x10
                        win_pressed   = (user32.GetAsyncKeyState(0x5B) & 0x8000) or \
                                        (user32.GetAsyncKeyState(0x5C) & 0x8000)
                        shift_pressed = (user32.GetAsyncKeyState(0x10) & 0x8000)
                        if win_pressed and shift_pressed:
                            if is_key_down:
                                self.show_capture_blocked_warning()
                            # nonzero 반환: 윈도우 기본 캡처 도구 실행 완전 차단
                            return 1

                # 처리 대상이 아닌 모든 키는 다음 훅으로 정상 전달
                return _CallNext(_hook_handle.value, nCode, wParam, lParam)

            # HOOKPROC 인스턴스 생성 (가비지 컬렉션 방지를 위해 인스턴스 변수에 보관)
            self._hook_proc = HOOKPROC(low_level_keyboard_proc)

            # WH_KEYBOARD_LL 훅 설치
            # PyInstaller 빌드 환경에서 GetModuleHandleW(None)은 NULL을 반환할 수 있습니다.
            # WH_KEYBOARD_LL은 전역 훅(dwThreadId=0)이므로 hMod=NULL(0)으로도 정상 동작합니다.
            _SetHook = user32.SetWindowsHookExW
            _SetHook.restype  = ctypes.c_void_p
            _SetHook.argtypes = [ctypes.c_int, HOOKPROC, ctypes.c_void_p, wintypes.DWORD]

            _hook_handle.value = _SetHook(
                WH_KEYBOARD_LL,
                self._hook_proc,
                ctypes.c_void_p(0),  # hMod=NULL: 전역 저수준 훅은 NULL 핸들로도 동작
                0
            )

            if not _hook_handle.value:
                err = kernel32.GetLastError()
                print(f"[Keyboard] 저수준 키보드 훅 설치 실패 (오류 코드: {err})")
                return

            self._hook_handle = _hook_handle.value
            print("[Keyboard] WH_KEYBOARD_LL 훅 설치 완료 — 전용 메시지 루프 시작")

            # 전용 Win32 메시지 루프
            # GetMessage는 WM_QUIT(0x0012)를 받으면 0을 반환하여 루프를 종료시킵니다.
            msg = MSG()
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))

            # 루프 종료 후 훅 해제
            if _hook_handle.value:
                user32.UnhookWindowsHookEx(_hook_handle.value)
                self._hook_handle = None
            print("[Keyboard] WH_KEYBOARD_LL 훅 해제 및 메시지 루프 종료")

        # 전용 데몬 스레드 구동 (프로그램 종료 시 자동 소멸)
        t = threading.Thread(target=hook_thread_worker, daemon=True, name="KeyboardHookThread")
        t.start()
        self.keyboard_listener = t
        print("[Keyboard] 전용 키보드 훅 스레드 시작")



    def show_app_info(self):
        """
        프로그램 실행 시 콘솔 상태를 출력합니다.
        """
        print("==========================================================")
        print("개인정보 마스킹 화면 캡처 프로그램이 구동되었습니다.")
        print("- 캡처 단축키: [ F9 ]")
        print("- 트레이 메뉴에서 '윈도우 시작 시 자동 실행' 등록/해제 가능")
        print("- 윈도우 우측 하단 시스템 트레이에서 프로그램을 종료할 수 있습니다.")
        print("==========================================================")


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
