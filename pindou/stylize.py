from __future__ import annotations

import base64
import io
import ipaddress
import os
from typing import Any
from urllib.parse import urlsplit

import httpx
from PIL import Image, ImageChops, ImageFilter, ImageOps


DEFAULT_PIXEL_PROMPT = (
    "将主体重绘为可爱的正面像素角色，保留最有辨识度的轮廓、配色和配饰。"
    "使用清晰的大像素块、有限色板、单像素深色描边，主体完整居中，透明背景，不要文字。"
)
MAX_MODEL_PIXELS = 40_000_000


def local_pixel_art(
    image: Image.Image,
    pixel_resolution: int = 72,
    color_count: int = 20,
    output_size: int = 640,
) -> Image.Image:
    """Create a deterministic pixel-art treatment without a remote model."""

    source = ImageOps.exif_transpose(image).convert("RGBA")
    alpha = source.getchannel("A")
    bbox = alpha.getbbox()
    if bbox is None:
        raise ValueError("图片中没有可见主体")
    source = source.crop(bbox)

    longest = max(source.size)
    inner_resolution = max(24, min(128, int(pixel_resolution)))
    scale = inner_resolution / float(longest)
    small_size = (
        max(1, int(round(source.width * scale))),
        max(1, int(round(source.height * scale))),
    )
    small = source.resize(small_size, Image.Resampling.LANCZOS)
    small_alpha = small.getchannel("A").point(lambda value: 255 if value >= 96 else 0)

    # Pillow's median-cut quantizer operates on RGB, then we restore the alpha
    # mask. A small, fixed palette produces predictable bead-friendly regions.
    rgb = Image.new("RGB", small.size, (246, 245, 242))
    rgb.paste(small.convert("RGB"), mask=small_alpha)
    quantized = rgb.quantize(
        colors=max(4, min(64, int(color_count))),
        method=Image.Quantize.MEDIANCUT,
        dither=Image.Dither.NONE,
    ).convert("RGBA")
    quantized.putalpha(small_alpha)

    # One low-resolution dilation creates a crisp pixel outline similar to the
    # reference sprite while preserving holes inside the subject.
    expanded_alpha = small_alpha.filter(ImageFilter.MaxFilter(3))
    outline_alpha = ImageChops.subtract(expanded_alpha, small_alpha)
    outlined = Image.new("RGBA", small.size, (0, 0, 0, 0))
    outline_layer = Image.new("RGBA", small.size, (33, 31, 38, 255))
    outlined.alpha_composite(Image.composite(outline_layer, Image.new("RGBA", small.size), outline_alpha))
    outlined.alpha_composite(quantized)

    padding = max(3, int(round(inner_resolution * 0.1)))
    canvas_side = max(outlined.width, outlined.height) + padding * 2
    canvas = Image.new("RGBA", (canvas_side, canvas_side), (0, 0, 0, 0))
    left = (canvas_side - outlined.width) // 2
    top = (canvas_side - outlined.height) // 2
    canvas.alpha_composite(outlined, (left, top))

    target = max(256, min(1400, int(output_size)))
    return canvas.resize((target, target), Image.Resampling.NEAREST)


async def model_pixel_art(image: Image.Image, prompt: str) -> Image.Image:
    """Call a configurable image-model gateway.

    The gateway receives JSON with ``model``, ``prompt`` and a PNG data URL in
    ``image``. Responses may use ``image_base64``, ``b64_json``,
    ``data[0].b64_json`` or ``data[0].url``. This deliberately small contract
    works with a thin adapter in front of most hosted image-editing models.
    """

    endpoint = os.environ.get("PINDOU_MODEL_API_URL", "").strip()
    if not endpoint:
        raise RuntimeError("尚未配置 PINDOU_MODEL_API_URL")

    buffer = io.BytesIO()
    image.convert("RGBA").save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    payload = {
        "model": os.environ.get("PINDOU_MODEL_NAME", "pixel-art-editor"),
        "prompt": prompt.strip() or DEFAULT_PIXEL_PROMPT,
        "image": f"data:image/png;base64,{encoded}",
    }
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    api_key = os.environ.get("PINDOU_MODEL_API_KEY", "").strip()
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    timeout = httpx.Timeout(150.0, connect=15.0)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        response = await client.post(endpoint, json=payload, headers=headers)
        response.raise_for_status()
        if len(response.content) > 35 * 1024 * 1024:
            raise RuntimeError("模型 API 响应超过 35 MB")
        data = response.json()
        image_bytes = await _image_bytes_from_response(client, data)

    result = Image.open(io.BytesIO(image_bytes))
    if result.width * result.height > MAX_MODEL_PIXELS:
        raise RuntimeError("模型 API 返回的图片像素数量过大")
    result.load()
    result = ImageOps.exif_transpose(result).convert("RGBA")
    if max(result.size) > 4096:
        result.thumbnail((4096, 4096), Image.Resampling.LANCZOS)
    return result


async def _image_bytes_from_response(client: httpx.AsyncClient, data: Any) -> bytes:
    if not isinstance(data, dict):
        raise RuntimeError("模型 API 返回了无法识别的数据")

    encoded = data.get("image_base64") or data.get("b64_json")
    image_url = data.get("url")
    items = data.get("data")
    if isinstance(items, list) and items and isinstance(items[0], dict):
        encoded = encoded or items[0].get("b64_json") or items[0].get("image_base64")
        image_url = image_url or items[0].get("url")

    if isinstance(encoded, str) and encoded:
        if encoded.startswith("data:"):
            encoded = encoded.split(",", 1)[-1]
        try:
            image_bytes = base64.b64decode(encoded, validate=True)
        except ValueError as exc:
            raise RuntimeError("模型 API 返回的图片 Base64 无效") from exc
        if len(image_bytes) > 25 * 1024 * 1024:
            raise RuntimeError("模型 API 返回的图片超过 25 MB")
        return image_bytes

    if isinstance(image_url, str) and image_url.startswith(("https://", "http://")):
        _validate_model_result_url(image_url)
        async with client.stream("GET", image_url, follow_redirects=False) as response:
            response.raise_for_status()
            content_length = int(response.headers.get("content-length", "0") or 0)
            if content_length > 25 * 1024 * 1024:
                raise RuntimeError("模型 API 返回的图片超过 25 MB")
            chunks: list[bytes] = []
            total = 0
            async for chunk in response.aiter_bytes():
                total += len(chunk)
                if total > 25 * 1024 * 1024:
                    raise RuntimeError("模型 API 返回的图片超过 25 MB")
                chunks.append(chunk)
            return b"".join(chunks)

    raise RuntimeError("模型 API 响应中没有图片字段")


def model_api_is_configured() -> bool:
    return bool(os.environ.get("PINDOU_MODEL_API_URL", "").strip())


def _validate_model_result_url(image_url: str) -> None:
    endpoint = urlsplit(os.environ.get("PINDOU_MODEL_API_URL", ""))
    target = urlsplit(image_url)
    if target.scheme != "https" or not target.hostname:
        raise RuntimeError("模型图片地址必须使用 HTTPS")
    if endpoint.hostname and target.hostname.lower() != endpoint.hostname.lower():
        allowed = {
            value.strip().lower()
            for value in os.environ.get("PINDOU_MODEL_API_ALLOWED_HOSTS", "").split(",")
            if value.strip()
        }
        if target.hostname.lower() not in allowed:
            raise RuntimeError("模型图片地址不在允许的域名范围内")
    try:
        address = ipaddress.ip_address(target.hostname)
    except ValueError:
        return
    if address.is_private or address.is_loopback or address.is_link_local or address.is_reserved:
        raise RuntimeError("模型图片地址不能指向内网地址")
