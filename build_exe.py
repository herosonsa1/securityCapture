import PyInstaller.__main__
import os
import shutil

def build():
    # 이전 빌드 찌꺼기 삭제
    for dir_name in ["build", "dist"]:
        if os.path.exists(dir_name):
            try:
                shutil.rmtree(dir_name)
            except Exception as e:
                print(f"이전 {dir_name} 디렉토리 제거 중 실패: {e}")
                
    spec_file = "PrivacyMasker.spec"
    if os.path.exists(spec_file):
        try:
            os.remove(spec_file)
            print(f"기존 {spec_file} 파일을 제거했습니다.")
        except Exception as e:
            print(f"기존 {spec_file} 파일 제거 중 실패: {e}")
                
    # PyInstaller 빌드 명령 수행
    # -F / --onefile : 단일 실행 파일 빌드
    # -w / --noconsole : GUI 전용 (콘솔 창 숨김)
    # --add-data : ocr_engine.ps1 스크립트를 빌드 파일 내부에 삽입 (Windows 구분자는 세미콜론)
    # --clean : 빌드 캐시 클리어
    PyInstaller.__main__.run([
        'main.py',
        '--onefile',
        '--noconsole',
        '--add-data=ocr_engine.ps1;.',
        '--name=PrivacyMasker',
        '--clean'
    ])
    
    # register_startup.bat 파일을 dist 폴더로 복사
    bat_file = "register_startup.bat"
    if os.path.exists(bat_file):
        try:
            shutil.copy(bat_file, "dist")
            print(f"{bat_file} 파일을 dist 폴더로 복사했습니다.")
        except Exception as e:
            print(f"{bat_file} 파일 복사 중 실패: {e}")
            
    print("\n==============================================")
    print("빌드가 성공적으로 완료되었습니다!")
    print("생성된 실행 파일 경로: dist\\PrivacyMasker.exe")
    print("및 복사된 설정 파일: dist\\register_startup.bat")
    print("==============================================")

if __name__ == "__main__":
    build()
