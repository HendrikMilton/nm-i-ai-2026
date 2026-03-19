import base64
import io
import numpy as np

try:
    import cv2
except ImportError:
    cv2 = None

from PIL import Image


def img_to_base64(img: np.ndarray, fmt: str = ".png") -> str:
    """Encode numpy image (BGR or grayscale) to base64 string."""
    if cv2 is not None:
        _, buf = cv2.imencode(fmt, img)
        return base64.b64encode(buf.tobytes()).decode()
    # fallback to PIL
    if img.ndim == 3 and img.shape[2] == 3:
        img = img[:, :, ::-1]  # BGR -> RGB
    pil = Image.fromarray(img)
    buf = io.BytesIO()
    pil.save(buf, format=fmt.strip(".").upper())
    return base64.b64encode(buf.getvalue()).decode()


def base64_to_img(b64: str) -> np.ndarray:
    """Decode base64 string to numpy image (BGR)."""
    data = base64.b64decode(b64)
    if cv2 is not None:
        arr = np.frombuffer(data, dtype=np.uint8)
        return cv2.imdecode(arr, cv2.IMREAD_COLOR)
    pil = Image.open(io.BytesIO(data))
    img = np.array(pil)
    if img.ndim == 3 and img.shape[2] == 3:
        img = img[:, :, ::-1]  # RGB -> BGR
    return img


def base64_to_pil(b64: str) -> Image.Image:
    """Decode base64 string to PIL Image."""
    return Image.open(io.BytesIO(base64.b64decode(b64)))


def pil_to_base64(img: Image.Image, fmt: str = "PNG") -> str:
    """Encode PIL Image to base64 string."""
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    return base64.b64encode(buf.getvalue()).decode()
