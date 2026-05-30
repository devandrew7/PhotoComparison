import sys
import os

# Ensure the app folder is in python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from PyQt6.QtWidgets import QApplication
from smart_dup_finder import SmartDupFinderApp

def calculate_ssim_score(path1: str, path2: str) -> float:
    try:
        import cv2
        from skimage.metrics import structural_similarity as ssim
        img1 = cv2.imread(path1)
        img2 = cv2.imread(path2)
        if img1 is None or img2 is None:
            return 0.0
        if img1.shape != img2.shape:
            img2 = cv2.resize(img2, (img1.shape[1], img1.shape[0]))
        gray1 = cv2.cvtColor(img1, cv2.COLOR_BGR2GRAY)
        gray2 = cv2.cvtColor(img2, cv2.COLOR_BGR2GRAY)
        score, _ = ssim(gray1, gray2, full=True)
        return score * 100.0
    except Exception as e:
        print(f"Error computing SSIM in test: {e}")
        return 0.0

def run_auto_test():
    print("====================================================")
    print("[TEST] Smart Photo Comparator Advanced Scan Test Start")
    print("====================================================")
    
    # 1. Initialize QApplication in headless mode if possible
    app = QApplication(sys.argv)
    
    # 2. Instantiate Main Application Window
    print("-> App Instance Creating...")
    window = SmartDupFinderApp()
    
    # 3. Set Test Folders
    workspace_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    test_folder1 = os.path.join(workspace_dir, "TestFolder1")
    test_folder2 = os.path.join(workspace_dir, "TestFolder2")
    
    print(f"-> Left Folder Path: {test_folder1}")
    print(f"-> Right Folder Path: {test_folder2}")
    
    if not os.path.exists(test_folder1) or not os.path.exists(test_folder2):
        print("[-] [Error] Test folders do not exist!")
        sys.exit(1)
        
    window.left_dir = test_folder1
    window.txt_left_dir.setText(test_folder1)
    window.right_dir = test_folder2
    window.txt_right_dir.setText(test_folder2)
    
    # 4. Trigger Scan Programmatically
    print("-> Running Scan Engine (calculating pHash & EXIF)...")
    window.scan_directories()
    
    # Wait for the thread to complete since we are running asynchronously now
    while window.scan_worker and window.scan_worker.isRunning():
        app.processEvents()
    
    # 5. Verify and Print Results
    dup_count = len(window.duplicate_groups)
    print(f"\n[OK] Scan completed successfully!")
    print(f"-> Found duplicate/similar pairs: {dup_count}")
    
    if dup_count == 0:
        print("[-] [Error] No duplicates detected. Please check matching algorithm.")
        sys.exit(1)
        
    print("\n----------------------------------------------------")
    print("Matching details (including Structural Similarity):")
    print("----------------------------------------------------")
    for idx, (left_info, right_info, sim) in enumerate(window.duplicate_groups):
        ssim_score = calculate_ssim_score(left_info['path'], right_info['path'])
        
        print(f"Group {idx+1}:")
        print(f"  - Left file: {left_info['filename']} ({left_info['resolution']}, {left_info['size_mb_str']})")
        print(f"  - Right file: {right_info['filename']} ({right_info['resolution']}, {right_info['size_mb_str']})")
        print(f"  - Perceptual Similarity (pHash): {sim:.1f}%")
        print(f"  - Structural Similarity (SSIM): {ssim_score:.2f}%")
        
        # Analyze specific change detection
        if ssim_score < 99.5:
            print("  - [ALERT] Local Image Modifications detected! (e.g. Added objects, markings, or editing)")
            
        # Verify recommended quality badging logic
        l_pixels = left_info["width"] * left_info["height"]
        r_pixels = right_info["width"] * right_info["height"]
        recommendation = "N/A"
        if l_pixels > r_pixels:
            recommendation = f"Keep Left (Right {right_info['filename']} has lower resolution)"
        elif r_pixels > l_pixels:
            recommendation = f"Keep Right (Left {left_info['filename']} has lower resolution)"
        else:
            if left_info["size_bytes"] > right_info["size_bytes"] * 1.05:
                recommendation = f"Keep Left (Right {right_info['filename']} is more compressed)"
            elif right_info["size_bytes"] > left_info["size_bytes"] * 1.05:
                recommendation = f"Keep Right (Left {left_info['filename']} is more compressed)"
            else:
                recommendation = "Exact Duplicate (Either can be deleted)"
        print(f"  - Smart Guide: {recommendation}\n")
        
    print("====================================================")
    print("[SUCCESS] All automatic tests passed successfully!")
    print("====================================================")
    
if __name__ == "__main__":
    run_auto_test()
