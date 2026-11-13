# render_debug.py
import cv2
import numpy as np

class RendererDebug:
    def __init__(self, config=None):
        self.config = config or {}
        self.window_name = self.config.get("window_name", "DEBUG")
        cv2.namedWindow(self.window_name, cv2.WINDOW_NORMAL)
        cv2.resizeWindow(self.window_name, 640, 480)
        cv2.moveWindow(self.window_name, 50, 50)

    def render(self, *, frame=None, face_ok=False, mouth_open_ratio=None):
        if frame is None:
            img = np.full((480, 640, 3), 40, dtype=np.uint8)
        else:
            img = frame.copy()

        cv2.putText(img, f"face_ok: {face_ok}", (10, 55), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0,255,0), 2)
        cv2.putText(img, f"Mouth opening: {mouth_open_ratio}", (10, 85), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0,255,0), 2)

        cv2.imshow(self.window_name, img)
