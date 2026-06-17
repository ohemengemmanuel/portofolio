from deepface import DeepFace

MODEL = "ArcFace"
DETECTOR = "opencv"
THRESHOLD = 0.45  # cosine distance ≈ 0.65 similarity (very strict)


def verify_faces(live_img_path, stored_face_path):
    """1-to-1 verification. Returns (verified: bool, detail: str)."""
    try:
        res = DeepFace.verify(
            img1_path=live_img_path,
            img2_path=stored_face_path,
            model_name=MODEL,
            detector_backend=DETECTOR,
            enforce_detection=True,
        )
        dist = res["distance"]
        verified = dist < THRESHOLD
        return verified, f"Distance: {dist:.3f} / threshold: {THRESHOLD}"
    except Exception as e:
        return False, str(e)
