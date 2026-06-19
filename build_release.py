"""
build_release.py
================
PrivacyMasker 최종 배포 패키지 빌드 스크립트

빌드 결과물 (.\dist\ 폴더):
    PrivacyMasker.exe          : 단일 실행 파일
    name_whitelist.json        : 이름 오탐 방지 화이트리스트 (사용자 편집 가능)
    README_배포.txt            : 간단한 사용 방법 안내

사용법:
    python build_release.py               # 기본 빌드 (기존 dist 유지, 덮어쓰기)
    python build_release.py --clean       # dist/build 완전 삭제 후 새로 빌드
    python build_release.py --no-confirm  # 확인 없이 바로 빌드

포함 리소스:
    ocr_engine.ps1             : OCR 처리 PowerShell 스크립트 (EXE 내 번들)
    name_whitelist.json        : 화이트리스트 (EXE 옆 외부 배치 - 사용자 편집용)
"""

import os
import sys
import shutil
import argparse
import subprocess
import textwrap
from pathlib import Path

# Windows 콘솔에서 UTF-8 출력을 보장하기 위한 재인코딩
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# ── 설정 ──────────────────────────────────────────────────────────────────────
SCRIPT_DIR   = Path(__file__).parent.resolve()
EXE_NAME     = "PrivacyMasker"
ENTRY_SCRIPT = "main.py"
DIST_DIR     = SCRIPT_DIR / "dist"
BUILD_DIR    = SCRIPT_DIR / "build"
SPEC_NAME    = f"{EXE_NAME}_release"

# EXE 내부에 번들되는 파일 (--add-data)
# ocr_engine.ps1, name_whitelist.json 모두 EXE 내부에 포함하여 단일 파일 배포
BUNDLED_DATA = [
    ("ocr_engine.ps1",      "."),   # PowerShell OCR 스크립트
    ("name_whitelist.json", "."),   # 이름 오탐 방지 화이트리스트 (번들)
]

# EXE 옆에 외부 배치하는 파일 (현재는 없음 - 단일 EXE 배포)
# 사용자가 화이트리스트를 커스터마이징하려면 EXE 옆에 name_whitelist.json을
# 별도로 배치하면 자동으로 내부 번들보다 우선 적용됩니다.
SIDECAR_FILES = [
    # (비어 있음 - 단일 파일 배포)
]

# ── README 내용 ────────────────────────────────────────────────────────────────
README_CONTENT = textwrap.dedent("""\
    ┌───────────────────────────────────────────────────────────────┐
    │          개인정보 마스킹 캡쳐 프로그램 (PrivacyMasker)        │
    └───────────────────────────────────────────────────────────────┘

    [사용 방법]
    1. PrivacyMasker.exe 를 실행하면 시스템 트레이에 자물쥐 아이콘이 생깁니다.
    2. F9 키를 눌러 화면 취사 영역을 선택합니다.
    3. 개인정보(주민번호, 전화번호, 이름 등)가 자동으로 마스킹됩니다.
    4. 트레이 아이콘 우클릭 → '윈도우 시작 시 자동 실행'으로 시작 프로그램 등록/해제.

    [파일 구성]
    PrivacyMasker.exe         - 메인 실행 파일 (단일 파일 배포 - 이 파일 1개만 배포하면 됩니다!)
    README_배포.txt           - 이 파일

    [화이트리스트 커스터마이징 - 선택 사항]
    EXE 내부에 기본 name_whitelist.json이 포함되어 있습니다.
    필요 시 EXE와 같은 폴더에 name_whitelist.json을 따로 배치하면
    과그 파일이 내부 번들보다 우선 적용됩니다. (실행 재시작 후 적용)

    [시스템 요구사항]
    - Windows 10 / 11 (64비트)
    - PowerShell 5.0 이상

    [버전 정보]
    빌드 날짜: {build_date}
""")


def parse_args():
    parser = argparse.ArgumentParser(description="PrivacyMasker 배포용 EXE 빌드 스크립트")
    parser.add_argument("--clean", action="store_true",
                        help="빌드 전 dist/build 폴더 완전 삭제 후 새로 빌드")
    parser.add_argument("--no-confirm", action="store_true",
                        help="확인 없이 바로 빌드 시작")
    return parser.parse_args()


def clean_dirs(dirs: list):
    """지정된 디렉토리를 완전 삭제합니다."""
    for d in dirs:
        if not d.exists():
            continue
        print(f"  삭제 중: {d}")
        try:
            shutil.rmtree(d)
            print(f"  삭제 완료: {d.name}/")
        except PermissionError:
            # 실행 중인 EXE가 잠겨 있을 경우: EXE 파일만 개별 삭제 시도
            print(f"  [경고] {d.name}/ 전체 삭제 실패 - 내부 파일 개별 삭제 시도 중...")
            deleted, failed = 0, 0
            for item in d.rglob("*"):
                if item.is_file():
                    try:
                        item.unlink()
                        deleted += 1
                    except Exception:
                        failed += 1
            try:
                shutil.rmtree(d, ignore_errors=True)
                print(f"  삭제 완료 ({deleted}개 파일 삭제, {failed}개 잠금 실패)")
            except Exception as e2:
                print(f"  [경고] {d.name}/ 폴더 삭제 최종 실패: {e2}")
        except Exception as e:
            print(f"  [경고] {d.name}/ 삭제 실패: {e}")


def check_prerequisites():
    """빌드 필수 파일 존재 여부 확인"""
    errors = []

    entry = SCRIPT_DIR / ENTRY_SCRIPT
    if not entry.exists():
        errors.append(f"엔트리 스크립트 없음: {entry}")

    for src, _ in BUNDLED_DATA:
        p = SCRIPT_DIR / src
        if not p.exists():
            errors.append(f"번들 대상 파일 없음: {p}")

    for sf in SIDECAR_FILES:
        p = SCRIPT_DIR / sf
        if not p.exists():
            errors.append(f"사이드카 파일 없음: {p}")

    # PyInstaller 설치 확인
    try:
        import PyInstaller
    except ImportError:
        errors.append("PyInstaller 미설치 — 'pip install pyinstaller' 실행 필요")

    if errors:
        print("\n[오류] 빌드 사전 조건 미충족:")
        for e in errors:
            print(f"  . {e}")
        sys.exit(1)

    print("  사전 조건 확인 완료")


def run_pyinstaller():
    """PyInstaller를 실행하여 단일 EXE 파일을 생성합니다."""
    import PyInstaller.__main__

    # --add-data 인자 구성 (절대경로 사용, Windows: 세미콜론 구분자)
    add_data_args = []
    for src, dst in BUNDLED_DATA:
        abs_src = SCRIPT_DIR / src
        add_data_args += [f"--add-data={abs_src};{dst}"]

    args = [
        str(SCRIPT_DIR / ENTRY_SCRIPT),
        "--onefile",                    # 단일 EXE
        "--noconsole",                  # 콘솔 창 숨김 (GUI 전용)
        f"--name={EXE_NAME}",
        f"--distpath={DIST_DIR}",
        f"--workpath={BUILD_DIR}",
        f"--specpath={BUILD_DIR}",
        "--clean",                      # 빌드 캐시 클리어
        "--noupx",                      # UPX 압축 생략 (안정성)
        *add_data_args,
    ]

    print("\n  [PyInstaller 실행]")
    print("  " + " ".join(["pyinstaller"] + args[1:]))
    print()

    try:
        PyInstaller.__main__.run(args)
    except SystemExit as e:
        if e.code != 0:
            print(f"\n[오류] PyInstaller 빌드 실패 (종료코드: {e.code})")
            sys.exit(e.code)


def copy_sidecar_files():
    """EXE 옆에 외부 배치해야 하는 파일들을 dist/ 폴더로 복사합니다."""
    if not SIDECAR_FILES:
        print("  사이드카 파일 없음 - 단일 EXE 배포 모드")
        return
    print("\n  [사이드카 파일 배치]")
    for sf in SIDECAR_FILES:
        src = SCRIPT_DIR / sf
        dst = DIST_DIR / sf
        if src.exists():
            shutil.copy2(src, dst)
            print(f"  복사 완료: {sf} → dist/{sf}")
        else:
            print(f"  [경고] 소스 파일 없음, 건너맴: {sf}")


def write_readme():
    """dist/ 폴더에 사용자용 README 파일을 생성합니다."""
    from datetime import datetime
    content = README_CONTENT.format(
        build_date=datetime.now().strftime("%Y-%m-%d %H:%M")
    )
    readme_path = DIST_DIR / "README_배포.txt"
    with open(readme_path, "w", encoding="utf-8-sig") as f:
        f.write(content)
    print(f"  README 생성 완료: {readme_path.name}")


def print_summary():
    """빌드 결과 요약을 출력합니다."""
    print("\n" + "=" * 60)
    print("  빌드 완료!")
    print("=" * 60)
    print(f"\n  배포 폴더: {DIST_DIR}")
    print()

    total_size = 0
    for f in sorted(DIST_DIR.iterdir()):
        size_mb = f.stat().st_size / (1024 * 1024)
        total_size += f.stat().st_size
        print(f"  [{size_mb:6.2f} MB]  {f.name}")

    print()
    print(f"  종 크기: {total_size / (1024 * 1024):.1f} MB")
    print()
    print("  [배포 방법 - 단일 파일 배포]")
    print("  PrivacyMasker.exe 1개만 배포 대상 PC에 복사하면 됩니다.")
    print("  name_whitelist.json은 EXE 내부에 내장되어 있습니다.")
    print("  (커스터마이징 시 EXE 옆에 name_whitelist.json 배치 가능 - 내장 파일 오버라이드)")
    print("=" * 60)


def build(args):
    print("\n" + "=" * 60)
    print("  PrivacyMasker 배포용 EXE 빌드 시작")
    print("=" * 60)

    # 1. 기존 빌드 디렉토리 정리
    if args.clean:
        print("\n[1단계] 기존 빌드 아티팩트 삭제 (--clean)")
        clean_dirs([DIST_DIR, BUILD_DIR])
    else:
        print("\n[1단계] 클린 옵션 없음 - 기존 dist/ 파일 유지")

    # 2. 사전 조건 확인
    print("\n[2단계] 사전 조건 확인")
    check_prerequisites()

    # 3. PyInstaller 빌드
    print("\n[3단계] PyInstaller 빌드")
    run_pyinstaller()

    # 4. 사이드카 파일 복사 (EXE 옆에 배치)
    print("\n[4단계] 사이드카 파일 배치")
    copy_sidecar_files()

    # 5. README 생성
    print("\n[5단계] README 파일 생성")
    write_readme()

    # 6. 결과 요약
    print_summary()


def main():
    args = parse_args()

    os.chdir(SCRIPT_DIR)  # 항상 프로젝트 루트에서 실행

    if not args.no_confirm:
        print(f"\n배포용 EXE 빌드를 시작합니다.")
        print(f"  출력 폴더: {DIST_DIR}")
        print(f"  --clean 옵션: {'ON' if args.clean else 'OFF'}")
        ans = input("\n계속하시겠습니까? [Y/n]: ").strip().lower()
        if ans not in ("", "y", "yes"):
            print("빌드를 취소했습니다.")
            sys.exit(0)

    build(args)


if __name__ == "__main__":
    main()
