import sys
import os
import json
import datetime
import subprocess
import hashlib
import ctypes
from ctypes import wintypes
from typing import Dict, List, Tuple, Optional
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
    QPushButton, QLabel, QFileDialog, QTableWidget, QTableWidgetItem, 
    QHeaderView, QProgressBar, QSplitter, QSlider, QGroupBox, QTabWidget,
    QMessageBox, QDialog, QGraphicsView, QGraphicsScene, QGraphicsPixmapItem,
    QFrame, QLineEdit, QCheckBox
)
from PyQt6.QtCore import Qt, QSize, pyqtSignal, QObject, QThread
from PyQt6.QtGui import QPixmap, QColor, QFont, QImage, QPainter, QBrush
from PIL import Image
from PIL.ExifTags import TAGS
import imagehash

# ==========================================
# Windows Recycle Bin API (ctypes)
# ==========================================
FO_DELETE = 3
FOF_ALLOWUNDO = 0x0040
FOF_NOCONFIRMATION = 0x0010
FOF_SILENT = 0x0004
FOF_NOERRORUI = 0x0400

class SHFILEOPSTRUCTW(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("wFunc", wintypes.UINT),
        ("pFrom", wintypes.LPCWSTR),
        ("pTo", wintypes.LPCWSTR),
        ("fFlags", wintypes.WORD),
        ("fAnyOperationsAborted", wintypes.BOOL),
        ("hNameMappings", wintypes.LPVOID),
        ("lpszProgressTitle", wintypes.LPCWSTR),
    ]

def send_to_recycle_bin(filepath: str) -> bool:
    """Send a file to the Windows Recycle Bin using SHFileOperationW."""
    try:
        abs_path = os.path.abspath(filepath) + '\0\0'  # Double null-terminated
        fileop = SHFILEOPSTRUCTW()
        fileop.hwnd = None
        fileop.wFunc = FO_DELETE
        fileop.pFrom = abs_path
        fileop.pTo = None
        fileop.fFlags = FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_NOERRORUI | FOF_SILENT
        
        result = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(fileop))
        return result == 0
    except Exception as e:
        print(f"Error sending file to Recycle Bin: {e}")
        return False

# ==========================================
# Action History and Windows Recycle Bin Bridge (PowerShell based)
# ==========================================
class RecycleBinBridge:
    @staticmethod
    def is_in_recycle_bin(original_path: str) -> bool:
        """Check if a file with the given original path is currently in the Windows Recycle Bin."""
        escaped_path = original_path.replace('\\', '\\\\').replace("'", "''")
        ps_script = f"""
        $shell = New-Object -ComObject Shell.Application
        $recycleBin = $shell.Namespace(10)
        $found = $false
        foreach ($item in $recycleBin.Items()) {{
            $originalFolder = $recycleBin.GetDetailsOf($item, 1)
            $originalName = $recycleBin.GetDetailsOf($item, 0)
            $itemPath = Join-Path $originalFolder $originalName
            if ($itemPath -eq '{escaped_path}') {{
                $found = $true
                break
            }}
        }}
        Write-Output $found
        """
        try:
            result = subprocess.run(
                ["powershell", "-Command", ps_script], 
                capture_output=True, text=True, encoding='utf-8', timeout=5
            )
            return "True" in result.stdout
        except Exception as e:
            print(f"Error checking Recycle Bin: {e}")
            return False

    @staticmethod
    def restore_from_recycle_bin(original_path: str) -> bool:
        """Restore a file from the Windows Recycle Bin back to its original location."""
        escaped_path = original_path.replace('\\', '\\\\').replace("'", "''")
        ps_script = f"""
        $shell = New-Object -ComObject Shell.Application
        $recycleBin = $shell.Namespace(10)
        $restored = $false
        foreach ($item in $recycleBin.Items()) {{
            $originalFolder = $recycleBin.GetDetailsOf($item, 1)
            $originalName = $recycleBin.GetDetailsOf($item, 0)
            $itemPath = Join-Path $originalFolder $originalName
            if ($itemPath -eq '{escaped_path}') {{
                $item.InvokeVerb("restore")
                $restored = $true
                break
            }}
        }}
        Write-Output $restored
        """
        try:
            result = subprocess.run(
                ["powershell", "-Command", ps_script], 
                capture_output=True, text=True, encoding='utf-8', timeout=8
            )
            return "True" in result.stdout
        except Exception as e:
            print(f"Error restoring file: {e}")
            return False

# ==========================================
# Synchronized Zoom & Pan Side-by-Side Image Dialog
# ==========================================
class SyncedGraphicsView(QGraphicsView):
    panned = pyqtSignal(float, float)
    zoomed = pyqtSignal(float, float, float) # scale_factor, center_x, center_y
    doubleClicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self._is_syncing = False

    def wheelEvent(self, event):
        factor = 1.15 if event.angleDelta().y() > 0 else 0.85
        self.scale(factor, factor)
        
        # Emit signal to sync the other view
        if not self._is_syncing:
            self._is_syncing = True
            # Get current visible center
            center = self.mapToScene(self.viewport().rect().center())
            self.zoomed.emit(factor, center.x(), center.y())
            self._is_syncing = False
        super().wheelEvent(event)

    def scrollContentsBy(self, dx, dy):
        super().scrollContentsBy(dx, dy)
        if not self._is_syncing and (dx != 0 or dy != 0):
            self._is_syncing = True
            # Get scrollbar values as fraction
            h_bar = self.horizontalScrollBar()
            v_bar = self.verticalScrollBar()
            h_pct = h_bar.value() / max(1, h_bar.maximum()) if h_bar.maximum() > 0 else 0
            v_pct = v_bar.value() / max(1, v_bar.maximum()) if v_bar.maximum() > 0 else 0
            self.panned.emit(h_pct, v_pct)
            self._is_syncing = False

    def mouseDoubleClickEvent(self, event):
        self.doubleClicked.emit()
        super().mouseDoubleClickEvent(event)

class DiffHighlightPopup(QDialog):
    def __init__(self, left_path: str, right_path: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("차이점 분석 하이라이트 (오브젝트 변형 감지)")
        self.setMinimumSize(700, 700)
        self.setStyleSheet("""
            QDialog {
                background-color: #FFF5F5;
                border: 3px solid #E53E3E;
                border-radius: 8px;
            }
            QLabel {
                color: #C53030;
                font-weight: bold;
            }
            QPushButton {
                background-color: #E53E3E;
                color: white;
                font-weight: bold;
                border-radius: 6px;
                padding: 8px 16px;
            }
            QPushButton:hover {
                background-color: #C53030;
            }
        """)
        
        layout = QVBoxLayout(self)
        
        title = QLabel("🔴 두 이미지 간의 픽셀 차분 분석 (빨간색 하이라이트)")
        title.setFont(QFont("Arial", 12, QFont.Weight.Bold))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        
        desc = QLabel("오각형 추가, 서명, 리터칭 등 좌/우 간에 물리적 변화가 있는 부분만 붉은색으로 오버레이됩니다.")
        desc.setFont(QFont("Arial", 9))
        desc.setStyleSheet("color: #742A2A;")
        desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(desc)
        
        # Display Area
        self.view = QGraphicsView()
        self.scene = QGraphicsScene(self)
        self.view.setScene(self.scene)
        self.view.setStyleSheet("background-color: #FFFFFF; border: 1px solid #FED7D7; border-radius: 4px;")
        
        pix_diff = self.compute_diff_overlay(left_path, right_path)
        self.scene.addPixmap(pix_diff)
        
        layout.addWidget(self.view)
        
        # Adjust view to fit image
        self.view.fitInView(self.scene.itemsBoundingRect(), Qt.AspectRatioMode.KeepAspectRatio)
        
        btn_close = QPushButton("닫기")
        btn_close.clicked.connect(self.accept)
        btn_close.setFixedHeight(38)
        layout.addWidget(btn_close)
        
        # Center the popup relative to the parent (main window)
        if parent:
            self.center_on_parent(parent)

    def center_on_parent(self, parent):
        parent_geo = parent.geometry()
        popup_width = self.width()
        popup_height = self.height()
        # Position popup in the center of the main window (between the left and right sides)
        new_x = parent_geo.x() + (parent_geo.width() - popup_width) // 2
        new_y = parent_geo.y() + (parent_geo.height() - popup_height) // 2
        self.move(new_x, new_y)

    def compute_diff_overlay(self, path1: str, path2: str) -> QPixmap:
        try:
            import cv2
            import numpy as np
            img1 = cv2.imread(path1)
            img2 = cv2.imread(path2)
            if img1 is None or img2 is None:
                return QPixmap(path1)
            if img1.shape != img2.shape:
                img2 = cv2.resize(img2, (img1.shape[1], img1.shape[0]))
                
            # Compute absolute difference
            diff = cv2.absdiff(img1, img2)
            gray_diff = cv2.cvtColor(diff, cv2.COLOR_BGR2GRAY)
            
            # Threshold
            _, thresh = cv2.threshold(gray_diff, 15, 255, cv2.THRESH_BINARY)
            
            # Create red neon overlay (BGR: B=0, G=0, R=255)
            overlay = img1.copy()
            overlay[thresh > 0] = [0, 0, 255]
            
            # Convert BGR to RGB
            overlay_rgb = cv2.cvtColor(overlay, cv2.COLOR_BGR2RGB)
            h, w, ch = overlay_rgb.shape
            bytes_per_line = ch * w
            qimg = QImage(overlay_rgb.data, w, h, bytes_per_line, QImage.Format.Format_RGB888)
            return QPixmap.fromImage(qimg.copy())
        except Exception as e:
            print(f"Error computing diff overlay: {e}")
            return QPixmap(path1)

# ==========================================
# Background Processing Worker
# ==========================================
class ScanWorker(QThread):
    progress_val = pyqtSignal(int)
    status_msg = pyqtSignal(str)
    finished_results = pyqtSignal(list, list, list, dict, dict) # left_info, right_info, dup_groups, left_to_right, right_to_left
    error_occurred = pyqtSignal(str)

    def __init__(self, left_dir, right_dir, enable_phash, enable_sha256, threshold, is_image_file_fn, get_image_metadata_fn):
        super().__init__()
        self.left_dir = left_dir
        self.right_dir = right_dir
        self.enable_phash = enable_phash
        self.enable_sha256 = enable_sha256
        self.threshold = threshold
        self.is_image_file = is_image_file_fn
        self.get_image_metadata = get_image_metadata_fn
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True

    def run(self):
        try:
            self.status_msg.emit("스캔 시작 및 대상 이미지 색인 중...")
            self.progress_val.emit(0)

            if self._is_cancelled:
                return

            # Gather left files
            left_files = []
            for root, _, files in os.walk(self.left_dir):
                if self._is_cancelled:
                    return
                for file in files:
                    if self.is_image_file(file):
                        left_files.append(os.path.join(root, file))

            # Gather right files
            right_files = []
            for root, _, files in os.walk(self.right_dir):
                if self._is_cancelled:
                    return
                for file in files:
                    if self.is_image_file(file):
                        right_files.append(os.path.join(root, file))

            total_files = len(left_files) + len(right_files)
            if total_files == 0:
                self.error_occurred.emit("이미지 파일 없음")
                return

            self.status_msg.emit("이미지 메타데이터 및 유사도 분석 중...")
            left_files_info = []
            right_files_info = []
            processed = 0

            # Load metadata left
            for p in left_files:
                if self._is_cancelled:
                    return
                info = self.get_image_metadata(p, self.enable_phash, self.enable_sha256)
                left_files_info.append(info)
                processed += 1
                self.progress_val.emit(int((processed / total_files) * 50))

            # Load metadata right
            for p in right_files:
                if self._is_cancelled:
                    return
                info = self.get_image_metadata(p, self.enable_phash, self.enable_sha256)
                right_files_info.append(info)
                processed += 1
                self.progress_val.emit(50 + int((processed / total_files) * 50))

            self.status_msg.emit("유사 이미지 매칭 분석 중...")
            duplicate_groups = []
            left_to_right_matches = {}
            right_to_left_matches = {}

            # Matching logic
            for l_info in left_files_info:
                if self._is_cancelled:
                    return
                
                l_hash = l_info["phash"]
                for r_info in right_files_info:
                    if self._is_cancelled:
                        return

                    r_hash = r_info["phash"]
                    is_match = False
                    similarity = 0.0

                    # 1. SHA-256 match
                    if self.enable_sha256 and l_info["sha256"] and l_info["sha256"] == r_info["sha256"]:
                        is_match = True
                        similarity = 100.0
                    
                    # 2. Perceptual Hash match
                    elif self.enable_phash and l_hash and r_hash:
                        try:
                            distance = l_hash - r_hash
                            sim = (1.0 - (distance / 64.0)) * 100.0
                            if sim >= self.threshold:
                                is_match = True
                                similarity = sim
                        except Exception:
                            pass

                    # 3. Fast Metadata Match
                    elif not self.enable_phash:
                        size_match = (l_info["size_bytes"] == r_info["size_bytes"])
                        res_match = (l_info["resolution"] == r_info["resolution"] and l_info["resolution"] != "알 수 없음")
                        name_match = (l_info["filename"].lower() == r_info["filename"].lower())

                        if (size_match and res_match) or (name_match and size_match):
                            is_match = True
                            similarity = 100.0 if size_match and name_match else 95.0

                    if is_match:
                        duplicate_groups.append((l_info, r_info, similarity))
                        
                        if l_info["path"] not in left_to_right_matches:
                            left_to_right_matches[l_info["path"]] = []
                        left_to_right_matches[l_info["path"]].append((r_info, similarity))
                        
                        if r_info["path"] not in right_to_left_matches:
                            right_to_left_matches[r_info["path"]] = []
                        right_to_left_matches[r_info["path"]].append((l_info, similarity))

            if self._is_cancelled:
                return

            self.finished_results.emit(left_files_info, right_files_info, duplicate_groups, left_to_right_matches, right_to_left_matches)
        except Exception as e:
            self.error_occurred.emit(str(e))

# ==========================================
# Main Application Window
# ==========================================
class SmartDupFinderApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Smart Photo Comparator - 스마트 중복 사진 파일 정리")
        self.setMinimumSize(1600, 950)

        # Variables
        self.left_dir = ""
        self.right_dir = ""
        self.left_files_info: List[dict] = []
        self.right_files_info: List[dict] = []
        self.scan_worker = None
        
        # Duplicate mapping
        # Keys: Group Index, Value: Tuple of (Left File Info Dict, Right File Info Dict, Similarity %)
        self.duplicate_groups: List[Tuple[dict, dict, float]] = []
        # Mapping from left file path to list of right matching files
        self.left_to_right_matches: Dict[str, List[Tuple[dict, float]]] = {}
        # Mapping from right file path to list of left matching files
        self.right_to_left_matches: Dict[str, List[Tuple[dict, float]]] = {}
        
        # Action History Log Path
        self.log_filepath = os.path.join(os.path.dirname(os.path.abspath(__file__)), "smart_dup_finder_log.json")
        self.history_items: List[dict] = []
        self.load_history_log()

        # Stylesheet setup
        self.apply_theme()
        
        # Main Tab Widget
        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)
        
        self.init_compare_tab()
        self.init_history_tab()

    def apply_theme(self):
        """Apply modern clean gray/white theme with light blue accent."""
        qss = """
        QMainWindow {
            background-color: #F7FAFC;
        }
        QTabWidget::pane {
            border: 1px solid #E2E8F0;
            background-color: #FFFFFF;
            border-radius: 8px;
        }
        QTabBar::tab {
            background-color: #EDF2F7;
            color: #4A5568;
            border: 1px solid #CBD5E0;
            border-top-left-radius: 6px;
            border-top-right-radius: 6px;
            padding: 10px 24px;
            font-weight: bold;
            font-size: 13px;
            margin-right: 2px;
        }
        QTabBar::tab:selected {
            background-color: #FFFFFF;
            color: #3182CE;
            border-bottom: 2px solid #3182CE;
            border-top: 2px solid #3182CE;
        }
        QTableWidget {
            background-color: #FFFFFF;
            gridline-color: #EDF2F7;
            border: 1px solid #E2E8F0;
            border-radius: 6px;
            font-size: 13px;
            color: #2D3748;
        }
        QTableWidget::item {
            padding: 6px;
        }
        QTableWidget::item:selected {
            background-color: #EBF8FF;
            color: #2B6CB0;
        }
        QHeaderView::section {
            background-color: #EDF2F7;
            color: #4A5568;
            font-weight: bold;
            padding: 6px;
            border: 1px solid #E2E8F0;
        }
        QGroupBox {
            font-weight: bold;
            border: 1px solid #E2E8F0;
            border-radius: 8px;
            margin-top: 12px;
            padding-top: 16px;
            background-color: #FFFFFF;
            color: #2D3748;
        }
        QGroupBox::title {
            subcontrol-origin: margin;
            subcontrol-position: top left;
            left: 12px;
            padding: 0 6px;
            background-color: #FFFFFF;
            color: #3182CE;
        }
        QPushButton {
            background-color: #3182CE;
            color: white;
            border: none;
            border-radius: 6px;
            padding: 8px 16px;
            font-weight: bold;
            font-size: 13px;
        }
        QPushButton:hover {
            background-color: #2B6CB0;
        }
        QPushButton:pressed {
            background-color: #2C5282;
        }
        QLineEdit {
            border: 1px solid #CBD5E0;
            border-radius: 6px;
            padding: 6px 12px;
            background-color: #FFFFFF;
            color: #2D3748;
        }
        QLineEdit:focus {
            border: 2px solid #3182CE;
        }
        QProgressBar {
            border: 1px solid #E2E8F0;
            border-radius: 6px;
            text-align: center;
            background-color: #EDF2F7;
            color: #2D3748;
            font-weight: bold;
        }
        QProgressBar::chunk {
            background-color: #3182CE;
            border-radius: 6px;
        }
        """
        self.setStyleSheet(qss)

    def init_compare_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(15, 15, 15, 15)
        
        # 1. Directory Selection Header
        dir_group = QGroupBox("대조 대상 폴더 선택")
        dir_layout = QVBoxLayout(dir_group)
        
        # Row 1: Paths & Browse
        paths_layout = QHBoxLayout()
        
        # Left Folder
        left_dir_layout = QHBoxLayout()
        self.lbl_left_dir = QLabel("좌측 폴더:")
        self.lbl_left_dir.setStyleSheet("font-weight: bold;")
        self.txt_left_dir = QLineEdit()
        self.txt_left_dir.setReadOnly(True)
        self.txt_left_dir.setPlaceholderText("비교할 첫 번째 폴더를 선택하세요...")
        btn_browse_left = QPushButton("선택...")
        btn_browse_left.clicked.connect(self.browse_left_dir)
        left_dir_layout.addWidget(self.lbl_left_dir)
        left_dir_layout.addWidget(self.txt_left_dir)
        left_dir_layout.addWidget(btn_browse_left)
        
        # Right Folder
        right_dir_layout = QHBoxLayout()
        self.lbl_right_dir = QLabel("우측 폴더:")
        self.lbl_right_dir.setStyleSheet("font-weight: bold;")
        self.txt_right_dir = QLineEdit()
        self.txt_right_dir.setReadOnly(True)
        self.txt_right_dir.setPlaceholderText("비교할 두 번째 폴더를 선택하세요...")
        btn_browse_right = QPushButton("선택...")
        btn_browse_right.clicked.connect(self.browse_right_dir)
        right_dir_layout.addWidget(self.lbl_right_dir)
        right_dir_layout.addWidget(self.txt_right_dir)
        right_dir_layout.addWidget(btn_browse_right)
        
        paths_layout.addLayout(left_dir_layout)
        paths_layout.addSpacing(20)
        paths_layout.addLayout(right_dir_layout)
        dir_layout.addLayout(paths_layout)
        
        # Row 2: Control Toolbar
        toolbar_layout = QHBoxLayout()
        
        # Options checkboxes
        options_layout = QHBoxLayout()
        self.chk_enable_phash = QCheckBox("지각 유사도 (pHash) 스캔")
        self.chk_enable_phash.setChecked(True)
        self.chk_enable_phash.setStyleSheet("font-weight: bold; color: #2D3748;")
        self.chk_enable_phash.toggled.connect(self.on_phash_toggle)
        
        self.chk_enable_sha256 = QCheckBox("정밀 해시 (SHA-256) 스캔")
        self.chk_enable_sha256.setChecked(False)
        self.chk_enable_sha256.setStyleSheet("font-weight: bold; color: #2D3748;")
        
        options_layout.addWidget(self.chk_enable_phash)
        options_layout.addWidget(self.chk_enable_sha256)
        toolbar_layout.addLayout(options_layout)
        toolbar_layout.addSpacing(15)
        
        # Similarity threshold slider
        slider_layout = QHBoxLayout()
        lbl_threshold = QLabel("유사도 임계값 (pHash):")
        lbl_threshold.setStyleSheet("font-weight: bold; color: #4A5568;")
        self.slider_threshold = QSlider(Qt.Orientation.Horizontal)
        self.slider_threshold.setRange(60, 100)
        self.slider_threshold.setValue(90)
        self.slider_threshold.setFixedWidth(160)
        self.slider_threshold.valueChanged.connect(self.update_slider_label)
        self.lbl_threshold_val = QLabel("90%")
        self.lbl_threshold_val.setStyleSheet("font-weight: bold; color: #3182CE; min-width: 35px;")
        
        slider_layout.addWidget(lbl_threshold)
        slider_layout.addWidget(self.slider_threshold)
        slider_layout.addWidget(self.lbl_threshold_val)
        
        toolbar_layout.addLayout(slider_layout)
        toolbar_layout.addSpacing(20)
        
        # Helper Buttons
        self.btn_auto_select = QPushButton("⚡ 저품질 중복 파일 자동 선택")
        self.btn_auto_select.setObjectName("helperBtn")
        self.btn_auto_select.setStyleSheet("background-color: #319795; color: white;")
        self.btn_auto_select.setEnabled(False)
        self.btn_auto_select.clicked.connect(self.auto_select_lower_quality)
        toolbar_layout.addWidget(self.btn_auto_select)
        
        toolbar_layout.addStretch()
        
        # Status message label placed EXACTLY between helper and scan buttons!
        self.lbl_status = QLabel("준비 완료. 폴더를 선택하고 분석을 실행해 주세요.")
        self.lbl_status.setStyleSheet("color: #2B6CB0; font-weight: bold; padding: 2px;")
        self.lbl_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        toolbar_layout.addWidget(self.lbl_status)
        
        toolbar_layout.addStretch()
        
        # Scan Button
        self.btn_scan = QPushButton("🔍 중복 및 유사 이미지 분석 시작")
        self.btn_scan.setFixedHeight(38)
        self.btn_scan.setStyleSheet("background-color: #3182CE; font-size: 13px; padding: 0 20px;")
        self.btn_scan.clicked.connect(self.scan_directories)
        toolbar_layout.addWidget(self.btn_scan)
        
        dir_layout.addLayout(toolbar_layout)
        layout.addWidget(dir_group)
        
        # Progress Bar (static under Top Selection, doesn't cause vertical stretches)
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setFixedHeight(14)
        layout.addWidget(self.progress_bar)

        # 2. Main Vertical Splitter for Resizable Layout
        v_splitter = QSplitter(Qt.Orientation.Vertical)
        v_splitter.setStyleSheet("QSplitter::handle { background-color: #CBD5E0; height: 5px; }")
        
        # Left Table
        self.table_left = QTableWidget()
        self.table_left.setColumnCount(5)
        self.table_left.setHorizontalHeaderLabels(["파일명", "용량", "수정한 날짜", "해상도", "촬영 날짜 (EXIF)"])
        self.table_left.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table_left.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table_left.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table_left.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.table_left.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.table_left.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table_left.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table_left.itemSelectionChanged.connect(self.on_left_selection_changed)
        
        # Right Table
        self.table_right = QTableWidget()
        self.table_right.setColumnCount(5)
        self.table_right.setHorizontalHeaderLabels(["파일명", "용량", "수정한 날짜", "해상도", "촬영 날짜 (EXIF)"])
        self.table_right.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table_right.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table_right.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table_right.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.table_right.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.table_right.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table_right.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table_right.itemSelectionChanged.connect(self.on_right_selection_changed)
        
        # Top Widget containing both tables (Horizontal Layout)
        top_widget = QWidget()
        top_layout = QHBoxLayout(top_widget)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(10)
        
        left_table_container = QWidget()
        left_table_layout = QVBoxLayout(left_table_container)
        left_table_layout.setContentsMargins(0, 0, 0, 0)
        left_table_layout.addWidget(QLabel("📂 좌측 폴더의 유사/중복 발견 목록"))
        left_table_layout.addWidget(self.table_left)
        
        right_table_container = QWidget()
        right_table_layout = QVBoxLayout(right_table_container)
        right_table_layout.setContentsMargins(0, 0, 0, 0)
        right_table_layout.addWidget(QLabel("📂 우측 폴더의 매칭 유사/중복 파일"))
        right_table_layout.addWidget(self.table_right)
        
        top_layout.addWidget(left_table_container)
        top_layout.addWidget(right_table_container)
        
        # Left Preview Card (SyncedGraphicsView)
        left_card = QGroupBox("좌측 이미지 미리보기 및 속성 (마우스 휠 확대/드래그 이동 가능)")
        left_card_layout = QVBoxLayout(left_card)
        
        self.preview_left = SyncedGraphicsView()
        self.scene_left = QGraphicsScene(self)
        self.preview_left.setScene(self.scene_left)
        self.preview_left.setMinimumHeight(200)
        self.preview_left.setStyleSheet("background-color: #EDF2F7; border: 1px solid #CBD5E0; border-radius: 4px;")
        
        meta_left_widget = QWidget()
        self.meta_left_layout = QHBoxLayout(meta_left_widget)
        self.meta_left_layout.setContentsMargins(0, 5, 0, 5)
        
        self.lbl_meta_left = QLabel("사진을 선택하면 메타데이터가 표시됩니다.")
        self.lbl_meta_left.setStyleSheet("color: #4A5568; line-height: 1.4;")
        
        self.badge_left = QLabel("")
        self.badge_left.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.badge_left.setFixedSize(140, 30)
        self.badge_left.setFont(QFont("Arial", 10, QFont.Weight.Bold))
        self.badge_left.setStyleSheet("border-radius: 4px; border: 1px solid #CBD5E0; background-color: #EDF2F7;")
        
        self.meta_left_layout.addWidget(self.lbl_meta_left, 1)
        self.meta_left_layout.addWidget(self.badge_left)
        
        self.btn_delete_left = QPushButton("🗑️ 좌측 파일 휴지통으로 삭제")
        self.btn_delete_left.setObjectName("deleteBtn")
        self.btn_delete_left.setStyleSheet("background-color: #E53E3E; color: white;")
        self.btn_delete_left.setFixedHeight(36)
        self.btn_delete_left.setEnabled(False)
        self.btn_delete_left.clicked.connect(self.delete_left_file)
        
        left_card_layout.addWidget(self.preview_left, 1)
        left_card_layout.addWidget(meta_left_widget)
        left_card_layout.addWidget(self.btn_delete_left)
        
        # Right Preview Card (SyncedGraphicsView)
        right_card = QGroupBox("우측 이미지 미리보기 및 속성 (마우스 휠 확대/드래그 이동 가능)")
        right_card_layout = QVBoxLayout(right_card)
        
        self.preview_right = SyncedGraphicsView()
        self.scene_right = QGraphicsScene(self)
        self.preview_right.setScene(self.scene_right)
        self.preview_right.setMinimumHeight(200)
        self.preview_right.setStyleSheet("background-color: #EDF2F7; border: 1px solid #CBD5E0; border-radius: 4px;")
        
        meta_right_widget = QWidget()
        self.meta_right_layout = QHBoxLayout(meta_right_widget)
        self.meta_right_layout.setContentsMargins(0, 5, 0, 5)
        
        self.lbl_meta_right = QLabel("사진을 선택하면 메타데이터가 표시됩니다.")
        self.lbl_meta_right.setStyleSheet("color: #4A5568; line-height: 1.4;")
        
        self.badge_right = QLabel("")
        self.badge_right.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.badge_right.setFixedSize(140, 30)
        self.badge_right.setFont(QFont("Arial", 10, QFont.Weight.Bold))
        self.badge_right.setStyleSheet("border-radius: 4px; border: 1px solid #CBD5E0; background-color: #EDF2F7;")
        
        self.meta_right_layout.addWidget(self.lbl_meta_right, 1)
        self.meta_right_layout.addWidget(self.badge_right)
        
        self.btn_delete_right = QPushButton("🗑️ 우측 파일 휴지통으로 삭제")
        self.btn_delete_right.setObjectName("deleteBtn")
        self.btn_delete_right.setStyleSheet("background-color: #E53E3E; color: white;")
        self.btn_delete_right.setFixedHeight(36)
        self.btn_delete_right.setEnabled(False)
        self.btn_delete_right.clicked.connect(self.delete_right_file)
        
        right_card_layout.addWidget(self.preview_right, 1)
        right_card_layout.addWidget(meta_right_widget)
        right_card_layout.addWidget(self.btn_delete_right)
        
        # Bottom Widget containing both cards (Horizontal Layout)
        bottom_widget = QWidget()
        bottom_layout = QHBoxLayout(bottom_widget)
        bottom_layout.setContentsMargins(0, 0, 0, 0)
        bottom_layout.setSpacing(10)
        bottom_layout.addWidget(left_card)
        bottom_layout.addWidget(right_card)
        
        # Add widgets to vertical splitter
        v_splitter.addWidget(top_widget)
        v_splitter.addWidget(bottom_widget)
        v_splitter.setStretchFactor(0, 3)
        v_splitter.setStretchFactor(1, 4)
        
        layout.addWidget(v_splitter)
        self.tabs.addTab(tab, "🖼️ 이미지 비교 및 선별")
        
        # Connect main screen previews synchronization!
        self.preview_left.zoomed.connect(lambda factor, cx, cy: self.sync_main_zoom(self.preview_left, self.preview_right, factor))
        self.preview_left.panned.connect(lambda hpct, vpct: self.sync_main_pan(self.preview_left, self.preview_right, hpct, vpct))
        self.preview_right.zoomed.connect(lambda factor, cx, cy: self.sync_main_zoom(self.preview_right, self.preview_left, factor))
        self.preview_right.panned.connect(lambda hpct, vpct: self.sync_main_pan(self.preview_right, self.preview_left, hpct, vpct))
        
        # Connect double click signals to open the popup between the two previews!
        self.preview_left.doubleClicked.connect(self.open_detail_comparison)
        self.preview_right.doubleClicked.connect(self.open_detail_comparison)

    # ==========================================
    # Tab 2: Action History and Restore UI
    # ==========================================
    def init_history_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(15, 15, 15, 15)
        
        header = QLabel("📜 파일 삭제 및 복원 기록 관리")
        header.setFont(QFont("Arial", 12, QFont.Weight.Bold))
        header.setStyleSheet("color: #2B6CB0; padding-bottom: 5px;")
        layout.addWidget(header)
        
        desc = QLabel("앱을 통해 휴지통으로 안전하게 보낸 파일 목록입니다. 파일이 여전히 휴지통에 존재할 경우 완벽히 원본 위치로 복원할 수 있습니다.")
        desc.setStyleSheet("color: #4A5568; margin-bottom: 10px;")
        layout.addWidget(desc)
        
        # History Table
        self.table_history = QTableWidget()
        self.table_history.setColumnCount(5)
        self.table_history.setHorizontalHeaderLabels(["삭제 일시", "파일명", "원래 파일 경로", "삭제 전 크기", "휴지통 상태"])
        self.table_history.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table_history.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table_history.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table_history.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.table_history.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.table_history.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table_history.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table_history.itemSelectionChanged.connect(self.on_history_selection_changed)
        layout.addWidget(self.table_history)
        
        # Action Toolbar
        action_layout = QHBoxLayout()
        
        self.btn_refresh_history = QPushButton("🔄 상태 새로고침")
        self.btn_refresh_history.setStyleSheet("background-color: #4A5568; color: white;")
        self.btn_refresh_history.clicked.connect(self.refresh_history_statuses)
        
        self.btn_restore = QPushButton("↩️ 선택 파일 휴지통에서 원래 위치로 복원")
        self.btn_restore.setStyleSheet("background-color: #2ECC71; color: white; font-size: 13px; font-weight: bold;")
        self.btn_restore.setEnabled(False)
        self.btn_restore.clicked.connect(self.restore_selected_history_file)
        
        action_layout.addWidget(self.btn_refresh_history)
        action_layout.addWidget(self.btn_restore)
        action_layout.addStretch()
        
        layout.addLayout(action_layout)
        
        self.tabs.addTab(tab, "📜 작업 기록 및 휴지통 복원")
        
        # Load tables
        self.update_history_table()

    # ==========================================
    # Logic: Directory Selection & Sliders
    # ==========================================
    def browse_left_dir(self):
        directory = QFileDialog.getExistingDirectory(self, "좌측 폴더 선택")
        if directory:
            self.left_dir = directory
            self.txt_left_dir.setText(directory)

    def browse_right_dir(self):
        directory = QFileDialog.getExistingDirectory(self, "우측 폴더 선택")
        if directory:
            self.right_dir = directory
            self.txt_right_dir.setText(directory)

    def on_phash_toggle(self, checked):
        self.slider_threshold.setEnabled(checked)
        if checked:
            self.lbl_threshold_val.setText(f"{self.slider_threshold.value()}%")
            self.lbl_threshold_val.setStyleSheet("font-weight: bold; color: #3182CE; min-width: 35px;")
        else:
            self.lbl_threshold_val.setText("비활성")
            self.lbl_threshold_val.setStyleSheet("font-weight: bold; color: #A0AEC0; min-width: 35px;")

    def update_slider_label(self, val):
        self.lbl_threshold_val.setText(f"{val}%")

    # ==========================================
    # Logic: Core Search & Comparison Engine
    # ==========================================
    def is_image_file(self, filename: str) -> bool:
        ext = os.path.splitext(filename)[1].lower()
        return ext in {'.jpg', '.jpeg', '.png', '.bmp', '.gif', '.tiff', '.webp'}

    def get_image_metadata(self, filepath: str, enable_phash: bool = True, enable_sha256: bool = False) -> dict:
        """Extract size, mod time, resolution, and EXIF Date Taken. Optimizations applied based on options."""
        stats = os.stat(filepath)
        size_bytes = stats.st_size
        size_mb = size_bytes / (1024 * 1024)
        mtime = datetime.datetime.fromtimestamp(stats.st_mtime)
        mtime_str = mtime.strftime("%Y-%m-%d %H:%M:%S")
        
        width, height = 0, 0
        date_taken_str = "없음 (기본 날짜 사용)"
        date_taken_obj = mtime
        
        # 1. Read EXIF (Fast - PIL only reads header, not entire image pixels)
        try:
            with Image.open(filepath) as img:
                width, height = img.size
                exif = img._getexif()
                if exif:
                    for tag_id, value in exif.items():
                        tag = TAGS.get(tag_id, tag_id)
                        if tag in ('DateTimeOriginal', 'DateTime'):
                            try:
                                date_taken_obj = datetime.datetime.strptime(value.strip(), "%Y:%m:%d %H:%M:%S")
                                date_taken_str = date_taken_obj.strftime("%Y-%m-%d %H:%M:%S")
                                break
                            except Exception:
                                pass
        except Exception:
            pass
            
        # 2. Calculate SHA256 (Very slow, only runs if explicitly enabled!)
        sha256 = ""
        if enable_sha256:
            try:
                h = hashlib.sha256()
                with open(filepath, 'rb') as f:
                    for block in iter(lambda: f.read(65536), b''):
                        h.update(block)
                sha256 = h.hexdigest()
            except Exception:
                pass
            
        # 3. Calculate pHash (Slow, only runs if enabled!)
        phash_val = None
        if enable_phash:
            try:
                with Image.open(filepath) as img:
                    phash_val = imagehash.phash(img)
            except Exception:
                pass

        return {
            "path": filepath,
            "filename": os.path.basename(filepath),
            "size_bytes": size_bytes,
            "size_mb_str": f"{size_mb:.2f} MB",
            "mtime_str": mtime_str,
            "mtime_obj": mtime,
            "width": width,
            "height": height,
            "resolution": f"{width}x{height}" if width else "알 수 없음",
            "date_taken_str": date_taken_str,
            "date_taken_obj": date_taken_obj,
            "sha256": sha256,
            "phash": phash_val
        }

    def scan_directories(self):
        # If currently running, cancel it
        if self.scan_worker and self.scan_worker.isRunning():
            self.lbl_status.setText("스캔 작업 취소 요청 중...")
            self.scan_worker.cancel()
            self.btn_scan.setEnabled(False)
            return

        if not self.left_dir or not self.right_dir:
            QMessageBox.warning(self, "폴더 선택 누락", "좌측 및 우측 비교 폴더를 모두 지정해 주세요!")
            return
            
        self.btn_scan.setText("🔴 분석 중단")
        self.btn_scan.setStyleSheet("background-color: #E53E3E; font-size: 13px; padding: 0 20px;")
        self.btn_auto_select.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)

        enable_phash = self.chk_enable_phash.isChecked()
        enable_sha256 = self.chk_enable_sha256.isChecked()
        threshold = self.slider_threshold.value()

        # Start ScanWorker Thread
        self.scan_worker = ScanWorker(
            left_dir=self.left_dir,
            right_dir=self.right_dir,
            enable_phash=enable_phash,
            enable_sha256=enable_sha256,
            threshold=threshold,
            is_image_file_fn=self.is_image_file,
            get_image_metadata_fn=self.get_image_metadata
        )
        self.scan_worker.progress_val.connect(self.progress_bar.setValue)
        self.scan_worker.status_msg.connect(self.lbl_status.setText)
        self.scan_worker.finished_results.connect(self.on_scan_finished)
        self.scan_worker.error_occurred.connect(self.on_scan_error)
        self.scan_worker.finished.connect(self.on_scan_thread_finished)
        self.scan_worker.start()

    def on_scan_finished(self, left_files_info, right_files_info, duplicate_groups, left_to_right_matches, right_to_left_matches):
        self.left_files_info = left_files_info
        self.right_files_info = right_files_info
        self.duplicate_groups = duplicate_groups
        self.left_to_right_matches = left_to_right_matches
        self.right_to_left_matches = right_to_left_matches

        self.update_tables()
        self.lbl_status.setText(f"분석 완료! 매칭 그룹 {len(self.duplicate_groups)}건을 발견했습니다.")
        if len(self.duplicate_groups) > 0:
            self.btn_auto_select.setEnabled(True)

    def on_scan_error(self, err_msg):
        if err_msg == "이미지 파일 없음":
            QMessageBox.information(self, "이미지 파일 없음", "지정한 폴더 하위에 지원하는 이미지 파일이 존재하지 않습니다.")
        else:
            QMessageBox.critical(self, "오류", f"스캔 중 오류가 발생했습니다:\n{err_msg}")

    def on_scan_thread_finished(self):
        # Reset UI button
        self.btn_scan.setText("🔍 중복 및 유사 이미지 분석 시작")
        self.btn_scan.setStyleSheet("background-color: #3182CE; font-size: 13px; padding: 0 20px;")
        self.btn_scan.setEnabled(True)
        self.progress_bar.setVisible(False)
        self.scan_worker = None

    # ==========================================
    # Logic: Table Rendering
    # ==========================================
    def update_tables(self):
        """Update tables showing ONLY images that have duplicates in the other folder."""
        # 1. Left Table
        self.table_left.setRowCount(0)
        # Unique paths in left directory that have matches in right directory
        matched_left_paths = list(self.left_to_right_matches.keys())
        
        for path in matched_left_paths:
            # Find the metadata dict
            l_info = next(x for x in self.left_files_info if x["path"] == path)
            row = self.table_left.rowCount()
            self.table_left.insertRow(row)
            
            # Explorer columns: File Name (stretch), Size, Mod Date, Resolution, Taken Date
            item_name = QTableWidgetItem(l_info["filename"])
            item_name.setData(Qt.ItemDataRole.UserRole, l_info) # Store info dict in UserRole
            
            self.table_left.setItem(row, 0, item_name)
            self.table_left.setItem(row, 1, QTableWidgetItem(l_info["size_mb_str"]))
            self.table_left.setItem(row, 2, QTableWidgetItem(l_info["mtime_str"]))
            self.table_left.setItem(row, 3, QTableWidgetItem(l_info["resolution"]))
            self.table_left.setItem(row, 4, QTableWidgetItem(l_info["date_taken_str"]))
            
        # 2. Right Table starts empty. It will populate when a Left item is selected!
        self.table_right.setRowCount(0)
        self.clear_previews()

    def clear_previews(self):
        self.scene_left.clear()
        self.lbl_meta_left.setText("사진을 선택하면 메타데이터가 표시됩니다.")
        self.badge_left.setText("")
        self.badge_left.setStyleSheet("border-radius: 4px; border: 1px solid #CBD5E0; background-color: #EDF2F7;")
        self.btn_delete_left.setEnabled(False)
        
        self.scene_right.clear()
        self.lbl_meta_right.setText("사진을 선택하면 메타데이터가 표시됩니다.")
        self.badge_right.setText("")
        self.badge_right.setStyleSheet("border-radius: 4px; border: 1px solid #CBD5E0; background-color: #EDF2F7;")
        self.btn_delete_right.setEnabled(False)

    # ==========================================
    # Logic: Selection Changed Handlers & Badging
    # ==========================================
    def on_left_selection_changed(self):
        selected_ranges = self.table_left.selectedRanges()
        if not selected_ranges:
            return
            
        row = selected_ranges[0].topRow()
        item = self.table_left.item(row, 0)
        if not item:
            return
            
        l_info = item.data(Qt.ItemDataRole.UserRole)
        self.display_left_image(l_info)
        
        # Populate and highlight right table with matching duplicates only!
        self.table_right.setRowCount(0)
        matches = self.left_to_right_matches.get(l_info["path"], [])
        
        for r_info, sim in matches:
            r_row = self.table_right.rowCount()
            self.table_right.insertRow(r_row)
            
            item_r_name = QTableWidgetItem(r_info["filename"])
            item_r_name.setData(Qt.ItemDataRole.UserRole, (r_info, sim)) # Store info and similarity
            
            self.table_right.setItem(r_row, 0, item_r_name)
            self.table_right.setItem(r_row, 1, QTableWidgetItem(r_info["size_mb_str"]))
            self.table_right.setItem(r_row, 2, QTableWidgetItem(r_info["mtime_str"]))
            self.table_right.setItem(r_row, 3, QTableWidgetItem(r_info["resolution"]))
            self.table_right.setItem(r_row, 4, QTableWidgetItem(r_info["date_taken_str"]))
            
        # Auto-select the first matching item on the right
        if self.table_right.rowCount() > 0:
            self.table_right.selectRow(0)

    def on_right_selection_changed(self):
        selected_ranges = self.table_right.selectedRanges()
        if not selected_ranges:
            # If nothing selected, clear right preview
            self.scene_right.clear()
            self.lbl_meta_right.setText("사진을 선택하면 메타데이터가 표시됩니다.")
            self.badge_right.setText("")
            self.btn_delete_right.setEnabled(False)
            return
            
        row = selected_ranges[0].topRow()
        item = self.table_right.item(row, 0)
        if not item:
            return
            
        r_info, sim = item.data(Qt.ItemDataRole.UserRole)
        self.display_right_image(r_info, sim)
        
        # We now have BOTH left and right images selected. Let's compare and update quality badges!
        self.update_quality_badges()

    def display_left_image(self, info: dict):
        self.lbl_meta_left.setText(
            f"<b>파일명:</b> {info['filename']}<br/>"
            f"<b>경로:</b> {info['path']}<br/>"
            f"<b>용량:</b> {info['size_mb_str']} ({info['size_bytes']:,} Bytes)<br/>"
            f"<b>해상도:</b> {info['resolution']}<br/>"
            f"<b>촬영일:</b> {info['date_taken_str']}"
        )
        self.btn_delete_left.setEnabled(True)
        self.load_image_preview(info["path"], self.preview_left, self.scene_left)

    def display_right_image(self, info: dict, similarity: float):
        # Calculate SSIM score if possible
        ssim_text = ""
        left_ranges = self.table_left.selectedRanges()
        if left_ranges:
            l_row = left_ranges[0].topRow()
            l_info = self.table_left.item(l_row, 0).data(Qt.ItemDataRole.UserRole)
            try:
                import cv2
                from skimage.metrics import structural_similarity as ssim
                img1 = cv2.imread(l_info["path"])
                img2 = cv2.imread(info["path"])
                if img1 is not None and img2 is not None:
                    if img1.shape != img2.shape:
                        img2 = cv2.resize(img2, (img1.shape[1], img1.shape[0]))
                    gray1 = cv2.cvtColor(img1, cv2.COLOR_BGR2GRAY)
                    gray2 = cv2.cvtColor(img2, cv2.COLOR_BGR2GRAY)
                    score, _ = ssim(gray1, gray2, full=True)
                    ssim_pct = score * 100.0
                    if ssim_pct < 99.5:
                        ssim_text = f"<br/><b>구조 유사도 (SSIM):</b> <font color='#E53E3E'><b>{ssim_pct:.2f}% (오브젝트 변형 감지)</b></font>"
                    else:
                        ssim_text = f"<br/><b>구조 유사도 (SSIM):</b> <font color='#2ECC71'><b>{ssim_pct:.2f}% (구조적 일치)</b></font>"
            except Exception as e:
                print(f"Error calculating SSIM: {e}")
                
        self.lbl_meta_right.setText(
            f"<b>파일명:</b> {info['filename']}<br/>"
            f"<b>용량:</b> {info['size_mb_str']} ({info['size_bytes']:,} Bytes)<br/>"
            f"<b>해상도:</b> {info['resolution']}<br/>"
            f"<b>촬영일:</b> {info['date_taken_str']}<br/>"
            f"<b>지각 유사도:</b> <font color='#3182CE'><b>{similarity:.1f}%</b></font>"
            f"{ssim_text}"
        )
        self.btn_delete_right.setEnabled(True)
        self.load_image_preview(info["path"], self.preview_right, self.scene_right)

    def load_image_preview(self, filepath: str, view: SyncedGraphicsView, scene: QGraphicsScene):
        try:
            scene.clear()
            pixmap = QPixmap(filepath)
            if pixmap.isNull():
                return
            scene.addPixmap(pixmap)
            view.resetTransform()
            view.fitInView(scene.itemsBoundingRect(), Qt.AspectRatioMode.KeepAspectRatio)
        except Exception as e:
            print(f"Error loading preview: {e}")

    def update_quality_badges(self):
        """Compare left and right selected images, apply green/orange recommendation badges."""
        left_ranges = self.table_left.selectedRanges()
        right_ranges = self.table_right.selectedRanges()
        
        if not left_ranges or not right_ranges:
            return
            
        l_row = left_ranges[0].topRow()
        l_info = self.table_left.item(l_row, 0).data(Qt.ItemDataRole.UserRole)
        
        r_row = right_ranges[0].topRow()
        r_info, sim = self.table_right.item(r_row, 0).data(Qt.ItemDataRole.UserRole)
        
        l_pixels = l_info["width"] * l_info["height"]
        r_pixels = r_info["width"] * r_info["height"]
        
        # Base recommendations
        if l_info["sha256"] == r_info["sha256"]:
            # Completely identical
            self.badge_left.setText("완벽 중복 파일")
            self.badge_left.setStyleSheet("border-radius: 4px; border: 1px solid #CBD5E0; background-color: #EDF2F7; color: #4A5568;")
            self.badge_right.setText("완벽 중복 파일")
            self.badge_right.setStyleSheet("border-radius: 4px; border: 1px solid #CBD5E0; background-color: #EDF2F7; color: #4A5568;")
        elif l_pixels > r_pixels:
            # Left has higher resolution
            self.badge_left.setText("원본 (고해상도) ⭐")
            self.badge_left.setStyleSheet("border-radius: 4px; border: 1px solid #C6F6D5; background-color: #F0FFF4; color: #22543D;")
            self.badge_right.setText("압축/저해상도 ⚠️")
            self.badge_right.setStyleSheet("border-radius: 4px; border: 1px solid #FEEBC8; background-color: #FFFAF0; color: #744210;")
        elif r_pixels > l_pixels:
            # Right has higher resolution
            self.badge_left.setText("압축/저해상도 ⚠️")
            self.badge_left.setStyleSheet("border-radius: 4px; border: 1px solid #FEEBC8; background-color: #FFFAF0; color: #744210;")
            self.badge_right.setText("원본 (고해상도) ⭐")
            self.badge_right.setStyleSheet("border-radius: 4px; border: 1px solid #C6F6D5; background-color: #F0FFF4; color: #22543D;")
        else:
            # Resolutions are identical, compare file size
            if l_info["size_bytes"] > r_info["size_bytes"] * 1.05:
                # Left has significantly larger size
                self.badge_left.setText("추천 (고화질) ⭐")
                self.badge_left.setStyleSheet("border-radius: 4px; border: 1px solid #C6F6D5; background-color: #F0FFF4; color: #22543D;")
                self.badge_right.setText("저화질/압축 ⚠️")
                self.badge_right.setStyleSheet("border-radius: 4px; border: 1px solid #FEEBC8; background-color: #FFFAF0; color: #744210;")
            elif r_info["size_bytes"] > l_info["size_bytes"] * 1.05:
                # Right has significantly larger size
                self.badge_left.setText("저화질/압축 ⚠️")
                self.badge_left.setStyleSheet("border-radius: 4px; border: 1px solid #FEEBC8; background-color: #FFFAF0; color: #744210;")
                self.badge_right.setText("추천 (고화질) ⭐")
                self.badge_right.setStyleSheet("border-radius: 4px; border: 1px solid #C6F6D5; background-color: #F0FFF4; color: #22543D;")
            else:
                # Basically same quality
                self.badge_left.setText("유사 이미지")
                self.badge_left.setStyleSheet("border-radius: 4px; border: 1px solid #E2E8F0; background-color: #EDF2F7; color: #4A5568;")
                self.badge_right.setText("유사 이미지")
                self.badge_right.setStyleSheet("border-radius: 4px; border: 1px solid #E2E8F0; background-color: #EDF2F7; color: #4A5568;")

    # ==========================================
    # Logic: Double-Click zoom & Detailed comparison
    # ==========================================
    def open_detail_comparison(self):
        left_ranges = self.table_left.selectedRanges()
        right_ranges = self.table_right.selectedRanges()
        
        if not left_ranges or not right_ranges:
            return
            
        l_row = left_ranges[0].topRow()
        l_info = self.table_left.item(l_row, 0).data(Qt.ItemDataRole.UserRole)
        
        r_row = right_ranges[0].topRow()
        r_info, sim = self.table_right.item(r_row, 0).data(Qt.ItemDataRole.UserRole)
        
        # Open detailed dialog
        dlg = DiffHighlightPopup(l_info["path"], r_info["path"], self)
        dlg.exec()

    # ==========================================
    # Logic: Helper Tools (Auto-Select)
    # ==========================================
    def auto_select_lower_quality(self):
        """Auto-select the lower-quality duplicate in the table view for immediate deletion review."""
        if not self.left_to_right_matches:
            return
            
        selected_count = 0
        
        # Select the first row on the left to activate selection
        if self.table_left.rowCount() > 0:
            self.table_left.selectRow(0)
            
        # Iterate through items in the left table, look at their best matches on right, 
        # and highlight or auto-select low-quality files.
        # Since PyQt selection is single-selection for standard review, we'll let the user
        # automatically select the lower-quality duplicate *of the currently viewed pair*!
        left_ranges = self.table_left.selectedRanges()
        right_ranges = self.table_right.selectedRanges()
        
        if left_ranges and right_ranges:
            l_row = left_ranges[0].topRow()
            l_info = self.table_left.item(l_row, 0).data(Qt.ItemDataRole.UserRole)
            
            r_row = right_ranges[0].topRow()
            r_info, sim = self.table_right.item(r_row, 0).data(Qt.ItemDataRole.UserRole)
            
            l_pixels = l_info["width"] * l_info["height"]
            r_pixels = r_info["width"] * r_info["height"]
            
            if l_pixels < r_pixels:
                # Left is lower quality, notify and advise to delete left
                QMessageBox.information(self, "일괄 자동 선택", "분석 결과 좌측 이미지가 더 저해상도 파일입니다. 좌측의 [삭제] 버튼 클릭을 권장합니다.")
            elif r_pixels < l_pixels:
                # Right is lower quality
                QMessageBox.information(self, "일괄 자동 선택", "분석 결과 우측 이미지가 더 저해상도 파일입니다. 우측의 [삭제] 버튼 클릭을 권장합니다.")
            else:
                # Compare file sizes
                if l_info["size_bytes"] < r_info["size_bytes"]:
                    QMessageBox.information(self, "일괄 자동 선택", "해상도가 같습니다. 좌측 파일의 크기가 더 작으므로 좌측 삭제를 권장합니다.")
                else:
                    QMessageBox.information(self, "일괄 자동 선택", "해상도가 같습니다. 우측 파일의 크기가 더 작으므로 우측 삭제를 권장합니다.")

    # ==========================================
    # Logic: Delete Left or Right File
    # ==========================================
    def delete_left_file(self):
        left_ranges = self.table_left.selectedRanges()
        if not left_ranges:
            return
            
        row = left_ranges[0].topRow()
        item = self.table_left.item(row, 0)
        l_info = item.data(Qt.ItemDataRole.UserRole)
        
        filepath = l_info["path"]
        
        reply = QMessageBox.question(
            self, "파일 안전 삭제", 
            f"다음 파일을 휴지통으로 안전하게 이동하시겠습니까?\n\n{l_info['filename']}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            success = send_to_recycle_bin(filepath)
            if success:
                # Append to history
                self.add_to_history(l_info)
                QMessageBox.information(self, "성공", "파일을 휴지통으로 안전하게 보냈습니다.")
                
                # Re-scan to update matches!
                self.scan_directories()
            else:
                QMessageBox.critical(self, "오류", "파일을 휴지통으로 보내지 못했습니다.")

    def delete_right_file(self):
        right_ranges = self.table_right.selectedRanges()
        if not right_ranges:
            return
            
        row = right_ranges[0].topRow()
        item = self.table_right.item(row, 0)
        r_info, sim = item.data(Qt.ItemDataRole.UserRole)
        
        filepath = r_info["path"]
        
        reply = QMessageBox.question(
            self, "파일 안전 삭제", 
            f"다음 파일을 휴지통으로 안전하게 이동하시겠습니까?\n\n{r_info['filename']}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            success = send_to_recycle_bin(filepath)
            if success:
                # Append to history
                self.add_to_history(r_info)
                QMessageBox.information(self, "성공", "파일을 휴지통으로 안전하게 보냈습니다.")
                
                # Re-scan to update matches!
                self.scan_directories()
            else:
                QMessageBox.critical(self, "오류", "파일을 휴지통으로 보내지 못했습니다.")

    # ==========================================
    # Logic: Action History and Restore Tab Functions
    # ==========================================
    def load_history_log(self):
        self.history_items = []
        if os.path.exists(self.log_filepath):
            try:
                with open(self.log_filepath, 'r', encoding='utf-8') as f:
                    self.history_items = json.load(f)
            except Exception as e:
                print(f"Error reading log file: {e}")

    def save_history_log(self):
        try:
            with open(self.log_filepath, 'w', encoding='utf-8') as f:
                json.dump(self.history_items, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Error saving log file: {e}")

    def add_to_history(self, info: dict):
        item = {
            "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "filename": info["filename"],
            "original_path": info["path"],
            "size_mb_str": info["size_mb_str"],
            "status": "In Recycle Bin"
        }
        self.history_items.append(item)
        self.save_history_log()
        self.update_history_table()

    def update_history_table(self):
        self.table_history.setRowCount(0)
        # Load from self.history_items in reverse chronological order
        for item in reversed(self.history_items):
            row = self.table_history.rowCount()
            self.table_history.insertRow(row)
            
            # Status styling
            status_str = item["status"]
            status_item = QTableWidgetItem(status_str)
            if status_str == "Restored":
                status_item.setBackground(QColor("#C6F6D5"))
                status_item.setForeground(QColor("#22543D"))
                status_item.setText("복원 완료됨")
            elif status_str == "In Recycle Bin":
                status_item.setBackground(QColor("#FEEBC8"))
                status_item.setForeground(QColor("#744210"))
                status_item.setText("휴지통에 존재")
            else:
                status_item.setBackground(QColor("#FED7D7"))
                status_item.setForeground(QColor("#742A2A"))
                status_item.setText("삭제됨 (복구 불가)")
                
            self.table_history.setItem(row, 0, QTableWidgetItem(item["timestamp"]))
            
            filename_item = QTableWidgetItem(item["filename"])
            filename_item.setData(Qt.ItemDataRole.UserRole, item) # Store history item dictionary
            self.table_history.setItem(row, 1, filename_item)
            self.table_history.setItem(row, 2, QTableWidgetItem(item["original_path"]))
            self.table_history.setItem(row, 3, QTableWidgetItem(item["size_mb_str"]))
            self.table_history.setItem(row, 4, status_item)

    def on_history_selection_changed(self):
        ranges = self.table_history.selectedRanges()
        if not ranges:
            self.btn_restore.setEnabled(False)
            return
            
        row = ranges[0].topRow()
        item = self.table_history.item(row, 1)
        if not item:
            return
            
        history_item = item.data(Qt.ItemDataRole.UserRole)
        # Enable restore button only if status is "In Recycle Bin"
        self.btn_restore.setEnabled(history_item["status"] == "In Recycle Bin")

    def refresh_history_statuses(self):
        """Run background PowerShell query to verify which files are still inside the Windows Recycle Bin."""
        self.btn_refresh_history.setEnabled(False)
        self.lbl_status.setText("휴지통 내 삭제 파일 실시간 감지 중...")
        QApplication.processEvents()
        
        for item in self.history_items:
            if item["status"] == "In Recycle Bin":
                still_there = RecycleBinBridge.is_in_recycle_bin(item["original_path"])
                if not still_there:
                    item["status"] = "Not Found (Emptied)"
            elif item["status"] == "Not Found (Emptied)":
                # Check if it has been put back by some chance
                still_there = RecycleBinBridge.is_in_recycle_bin(item["original_path"])
                if still_there:
                    item["status"] = "In Recycle Bin"
                    
        self.save_history_log()
        self.update_history_table()
        self.btn_refresh_history.setEnabled(True)
        self.lbl_status.setText("휴지통 파일 상태가 성공적으로 갱신되었습니다.")

    def restore_selected_history_file(self):
        ranges = self.table_history.selectedRanges()
        if not ranges:
            return
            
        row = ranges[0].topRow()
        item = self.table_history.item(row, 1)
        history_item = item.data(Qt.ItemDataRole.UserRole)
        
        original_path = history_item["original_path"]
        
        reply = QMessageBox.question(
            self, "파일 복원", 
            f"선택한 파일을 휴지통에서 원래 위치로 복원하시겠습니까?\n\n{history_item['filename']}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            self.lbl_status.setText("휴지통 복원 명령 전송 중...")
            QApplication.processEvents()
            
            success = RecycleBinBridge.restore_from_recycle_bin(original_path)
            if success:
                history_item["status"] = "Restored"
                self.save_history_log()
                self.update_history_table()
                QMessageBox.information(self, "성공", "파일이 원래 경로로 완벽히 복원되었습니다!")
                
                # Re-scan to update comparison screens if active
                if self.left_dir and self.right_dir:
                    self.scan_directories()
            else:
                # Double check if it actually succeeded despite return value
                if os.path.exists(original_path):
                    history_item["status"] = "Restored"
                    self.save_history_log()
                    self.update_history_table()
                    QMessageBox.information(self, "성공", "파일이 성공적으로 복원되었습니다.")
                    if self.left_dir and self.right_dir:
                        self.scan_directories()
                else:
                    QMessageBox.critical(self, "오류", "휴지통에서 파일을 복원하지 못했습니다.\n이미 복원되었거나, 파일이 휴지통에서 완전히 비워졌을 수 있습니다.")
                    # Refresh statuses
                    self.refresh_history_statuses()

    def sync_main_zoom(self, source, target, factor):
        if target._is_syncing:
            return
        target._is_syncing = True
        target.scale(factor, factor)
        target._is_syncing = False

    def sync_main_pan(self, source, target, hpct, vpct):
        if target._is_syncing:
            return
        target._is_syncing = True
        h_bar = target.horizontalScrollBar()
        v_bar = target.verticalScrollBar()
        h_bar.setValue(int(hpct * h_bar.maximum()))
        v_bar.setValue(int(vpct * v_bar.maximum()))
        target._is_syncing = False

# ==========================================
# Main Execution Entry Point
# ==========================================
if __name__ == "__main__":
    app = QApplication(sys.argv)
    
    # Modern font selection
    font = QFont("Malgun Gothic", 9)
    app.setFont(font)
    
    window = SmartDupFinderApp()
    window.show()
    sys.exit(app.exec())
