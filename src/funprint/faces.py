"""
Smart face and bust detection and framing for Fun Print thermal printers.
Supports single or multiple faces, head/bust margins, and auto-orientation.
"""

from typing import Tuple
from PIL import Image

try:
    import cv2
    import numpy as np
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False


def detect_and_frame_faces(
    img: Image.Image,
    bust_ratio: float = 1.5,
    head_ratio: float = 0.5,
    side_ratio: float = 0.5,
    auto_orient: bool = True
) -> Tuple[Image.Image, str]:
    """
    Detects all faces in the image.
    If faces are found, crops tightly around the collective face group with:
      - Head clearance above (head_ratio * avg_face_h)
      - Bust / torso margin below (bust_ratio * avg_face_h)
      - Shoulder width on sides (side_ratio * avg_face_w)

    If auto_orient is True:
      - If the cropped group is wider than tall (W > 1.15 * H), rotates 90°
        so the wide group spans the continuous paper roll, maximizing face scale.
      - If portrait (H >= W), keeps upright.

    Returns: (framed_image, orientation_description)
    """
    if not CV2_AVAILABLE:
        return img, "upright (cv2 not available)"

    # Convert PIL Image to OpenCV BGR format
    rgb_img = img.convert("RGB")
    cv_img = cv2.cvtColor(np.array(rgb_img), cv2.COLOR_RGB2BGR)
    gray = cv2.cvtColor(cv_img, cv2.COLOR_BGR2GRAY)

    cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    face_cascade = cv2.CascadeClassifier(cascade_path)
    faces = face_cascade.detectMultiScale(
        gray,
        scaleFactor=1.1,
        minNeighbors=5,
        minSize=(40, 40)
    )

    img_w, img_h = img.size

    if len(faces) == 0:
        return img, "upright (no faces detected)"

    # Calculate bounding box encompassing all detected faces
    min_x = min(x for x, y, w, h in faces)
    min_y = min(y for x, y, w, h in faces)
    max_x = max(x + w for x, y, w, h in faces)
    max_y = max(y + h for x, y, w, h in faces)

    avg_face_h = sum(h for x, y, w, h in faces) / len(faces)
    avg_face_w = sum(w for x, y, w, h in faces) / len(faces)

    # Margins
    pad_top = int(avg_face_h * head_ratio)
    pad_bottom = int(avg_face_h * bust_ratio)
    pad_sides = int(avg_face_w * side_ratio)

    crop_x1 = max(0, min_x - pad_sides)
    crop_y1 = max(0, min_y - pad_top)
    crop_x2 = min(img_w, max_x + pad_sides)
    crop_y2 = min(img_h, max_y + pad_bottom)

    crop_w = crop_x2 - crop_x1
    crop_h = crop_y2 - crop_y1

    cropped = img.crop((crop_x1, crop_y1, crop_x2, crop_y2))

    # Auto-Orientation
    if auto_orient:
        if crop_w > 1.15 * crop_h:
            # Landscape framing -> rotate 90° to stretch down the continuous paper roll
            cropped = cropped.rotate(270, expand=True)
            orientation = "horizontal (rotated 90°)"
        else:
            orientation = "vertical (upright)"
    else:
        orientation = "upright"

    return cropped, orientation
