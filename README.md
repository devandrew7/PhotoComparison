# 🖼️ Smart Photo Comparator (스마트 포토 컴패레이터) v3.5

[![Python 3.12](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![PyQt6](https://img.shields.io/badge/PyQt-6-41CD52?logo=qt&logoColor=white)](https://www.qt.io/)
[![License](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

대량의 사진이 저장된 폴더 두 개를 지정하여 **중복 및 유사 이미지(해상도 변경, 화질 압축, 로컬 편집 파일 등)를 지능적으로 탐색하고, 시각적으로 비교 분석하여 안전하게 정리**할 수 있는 최고 사양의 데스크톱 GUI 애플리케이션입니다.

기존 중복 파일 정리 프로그램들과 달리, 단순 파일 크기/해시 비교뿐만 아니라 **인간의 시각 시스템을 모방한 지각 유사도(pHash)** 및 **구조 유사도(SSIM)** 기술을 결합하여 정밀한 파일 선별 작업을 지원합니다.

---

## ✨ 핵심 기능 (Key Features)

### 1. 🔍 비동기 초고속 스캔 엔진 (`QThread` & Toggles)
* **GUI 멈춤 현상 차단**: 모든 스캔 및 분석 작업을 백그라운드 스레드(`ScanWorker`)로 이관하여 대용량 폴더를 읽을 때도 화면 멈춤 없이 100% 부드러운 반응성을 유지합니다.
* **언제든지 중단 가능**: 스캔 중에 클릭 한 번으로 안전하게 스캔을 중단할 수 있는 `🔴 분석 중단` 기능 지원.
* **정밀도/속도 맞춤 토글 옵션**:
  * **지각 유사도 (pHash 스캔)**: 이미지 픽셀 구조를 비교하여 압축되거나 크기가 다른 유사 이미지까지 대조 (보통 속도).
  * **정밀 해시 (SHA-256 스캔)**: 파일의 100% 물리적 바이트 동일성 대조 (디스크 I/O 최적화).
  * **빠른 메타데이터 비교 (대안 모드)**: pHash 옵션을 끄면 디코딩을 생략하고 `[파일명 + 크기]`, `[크기 + 해상도]` 정보만 매칭하여 **수천 장의 이미지를 1초 만에 스캔** 완료.

### 2. 📊 탐색기 스타일의 좌/우 듀얼 테이블 뷰
* **Windows 탐색기식 UI**: 파일명(왼쪽), 크기, 수정일, 해상도, 촬영일(EXIF) 정보를 깔끔하게 배치하여 파일 식별이 직관적입니다.
* **동적 상하 분할 조절 (`QSplitter`)**: 마우스 드래그를 통해 상단 파일 목록과 하단 사진 미리보기 영역 간의 경계를 조절할 수 있으며, **좌/우 레이아웃이 완벽하게 대칭으로 동기화되어 조절**됩니다.

### 3. 👁️ 실시간 동기 이미지 프리뷰 & 디테일 뷰어
* **메인 화면 드래그 & 휠 동기화**: 좌/우 미리보기 창 중 하나에서 마우스 휠을 굴려 확대/축소하거나 마우스 드래그로 화면을 이동하면 **반대쪽 미리보기 창도 소수점 픽셀 단위로 실시간 동기화(Synchronized Graphics)되어 작동**합니다.
* **차이점 분석 하이라이트 (오브젝트 변형 감지)**: 이미지를 더블클릭하면 1:1 해상도로 픽셀 간 차분을 연산하여 **추가된 개체, 편집된 텍스트, 서명 등을 붉은색 네온 오버레이 마스크로 또렷하게 하이라이트** 해주는 전용 비교 팝업이 제공됩니다.

### 4. 🏷️ 스마트 품질 분석 및 추천 배지 (Smart Quality Badging)
* **해상도/압축도 자동 분석**: 대조하는 두 파일 간의 픽셀 해상도 및 파일 용량을 입체적으로 분석하여 품질 배지를 메타데이터 영역에 표기합니다.
  * `[원본 (고해상도) ⭐]` / `[추천 (고화질) ⭐]` (녹색 배지)
  * `[압축/저해상도 ⚠️]` / `[저화질/압축 ⚠️]` (오렌지색 배지)
  * `[완벽 중복 파일]` (동일 파일 표시)

### 5. 🗑️ Windows 휴지통 연동 & 실시간 복원 시스템
* **휴지통 안전 삭제 (`SHFileOperationW`)**: 잘못 삭제해도 걱정 없도록 임시 삭제가 아닌 Windows 표준 휴지통으로 안전하게 보냅니다.
* **PowerShell COM 기반 실시간 복원**: 별도로 분리된 `[작업 기록 및 휴지통 복원]` 탭에서 삭제된 파일을 실시간으로 조회하고, **휴지통 내에 파일이 남아 있는 경우 원래 폴더 위치로 완벽하게 1-Click 복원**합니다.

---

## 🛠️ 기술 스택 (Technology Stack)

* **언어 및 GUI 프레임워크**: Python 3.12, PyQt6
* **이미지 처리 및 알고리즘**:
  * **PIL (Pillow)**: 고속 이미지 로딩 및 메타데이터(EXIF) 파싱
  * **imagehash**: Perceptual Hash (지각 해시) 알고리즘 구현
  * **OpenCV (cv2)**: 픽셀 절대 차분(`absdiff`) 연산 및 이미지 리사이징
  * **scikit-image (skimage)**: 구조 유사도(SSIM) 정밀 점수 산출
* **운영체제 브리지**: Windows `ctypes` Shell API, PowerShell COM Bridge

---

## 📂 폴더 구조 (Project Structure)

```text
PhotoComparison/
│
├── README.md               # 프로젝트 매뉴얼
├── .gitignore              # Git 제외 설정 (.venv, 빌드 임시파일 방지)
│
├── SmartDupFinder/         # 핵심 애플리케이션 폴더
│   ├── smart_dup_finder.py # 애플리케이션 메인 프로그램 소스
│   ├── test_app.py         # 이미지 차분 분석 검증용 자동화 테스트 스크립트
│   └── build.bat           # 단일 실행 포터블 파일(.exe) 자동 빌드 스크립트
│
├── TestFolder1/            # 테스트용 비교 폴더 1 (고화질 및 원본)
└── TestFolder2/            # 테스트용 비교 폴더 2 (저화질, 편집본 포함)
```

---

## 🚀 시작하기 (How to Run)

### 1. 가상환경 및 의존성 패키지 설치
이 프로젝트는 격리된 파이썬 가상환경을 사용하여 의존성 패키지를 안전하게 설치합니다.

```powershell
# 프로젝트 루트 디렉터리로 이동
cd d:\Antigravity\PhotoComparison

# 가상환경 활성화 (Windows PowerShell 기준)
.\.venv\Scripts\Activate.ps1

# 라이브러리 설치
pip install PyQt6 Pillow imagehash opencv-python scikit-image
```

### 2. 프로그램 실행
```powershell
python SmartDupFinder\smart_dup_finder.py
```

### 3. 검증용 자동화 테스트 실행
```powershell
python SmartDupFinder\test_app.py
```
> 이 테스트를 실행하면 `TestFolder1`과 `TestFolder2` 간의 중복 분석, 로컬 변형 감지(SSIM score), 배지 추천 로직을 헤드리스 모드로 정밀 검증하고 보고서를 출력합니다.

---

## 📦 단일 포터블 실행 파일 (.exe) 빌드 방법

Windows 환경에서 설치 없이 즉시 실행 가능한 단일 독립 파일(`.exe`)로 빌드할 수 있는 스크립트를 제공합니다.

1. `SmartDupFinder/` 디렉터리로 이동합니다.
2. **`build.bat`** 파일을 **더블클릭**하거나 파워쉘에서 실행합니다.
3. 빌드가 완료되면 `SmartDupFinder/dist/` 폴더 하위에 **`SmartPhotoComparator.exe`** 파일이 생성됩니다.

---

## 📝 라이선스 (License)

이 프로젝트는 **MIT License**에 따라 자유롭게 이용 및 수정, 배포할 수 있습니다. 자세한 내용은 `LICENSE` 파일을 확인하세요.
