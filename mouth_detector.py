# mouth_detector.py
import cv2
import numpy as np
import mediapipe as mp
from mediapipe.python.solutions.drawing_utils import (
    _normalized_to_pixel_coordinates as denormalize_coordinates
)

DEBUG = True

def dbg(*args):
    if DEBUG:
        print(*args)

def get_mediapipe_app(
    max_num_faces=1,
    refine_landmarks=True,
    min_detection_confidence=0.5,
    min_tracking_confidence=0.5,
):
    return mp.solutions.face_mesh.FaceMesh(
        max_num_faces=max_num_faces,
        refine_landmarks=refine_landmarks,
        min_detection_confidence=min_detection_confidence,
        min_tracking_confidence=min_tracking_confidence,
    )

def distance(p1, p2):
    return ((p1[0]-p2[0])**2 + (p1[1]-p2[1])**2) ** 0.5

def get_mouth_open_ratio(landmarks, refer_idxs, frame_width, frame_height):
    coords_points = []

    try:
        for i in refer_idxs:
            lm = landmarks[i]
            coord = denormalize_coordinates(lm.x, lm.y, frame_width, frame_height)
            if coord is None:
                return None
            coords_points.append(coord)

        left, top, right, bottom = coords_points

        vertical = distance(top, bottom)
        horizontal = distance(left, right)

        if horizontal == 0:
            return None

        return vertical / horizontal

    except Exception as e:
        dbg("[get_mouth_open_ratio] Exception:", repr(e))
        return None


class MouthDetector:
    """Measure mouth height relative to mouth width.

    update(frame) returns (face_ok, mouth_open_ratio).
    """

    def __init__(self):
        self.mouth_landmark_indices = [61, 13, 291, 14]  # left, top, right, bottom

        self.facemesh = get_mediapipe_app(
            max_num_faces=1,
            refine_landmarks=True,
            min_detection_confidence=0.5,
            min_tracking_confidence=0.5,
        )


    def update(self, frame):

        if frame is None:
            return False, None

        h, w, _ = frame.shape

        frame.flags.writeable = False
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        rgb = np.ascontiguousarray(rgb)

        results = self.facemesh.process(rgb)
        frame.flags.writeable = True

        if not results.multi_face_landmarks:
            return False, None

        face_ok = True
        landmarks = results.multi_face_landmarks[0].landmark

        mouth_open_ratio = get_mouth_open_ratio(
            landmarks,
            self.mouth_landmark_indices,
            w,
            h
        )

        return face_ok, mouth_open_ratio