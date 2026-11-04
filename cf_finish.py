"""Local image and video finishing tools used by the Studio."""

import json
import math
import shutil
import subprocess
import uuid
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image, ImageDraw, ImageEnhance, ImageOps

LOOK = "Cor e contraste"
FRAME = "Enquadrar imagem"
CLIP = "Cortar e enquadrar vídeo"
STILL = "Extrair quadro"
BOARD = "Prancha de cenas"
SIZES = {"Vertical · 9:16": (1080, 1920), "Quadrado · 1:1": (1080, 1080),
         "Paisagem · 16:9": (1920, 1080), "Retrato · 4:5": (1080, 1350)}
LOOKS = ("Cinema quente", "Frio suave", "Preto e branco", "Contraste limpo")
FORMATS = {"PNG": ".png", "JPEG": ".jpg", "WebP": ".webp"}


def output_path(directory, stem, suffix):
    directory = Path(directory) / "acabamento"
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"{stem}-{uuid.uuid4().hex[:12]}{suffix}"


def image_edit(path, mode, look, strength, ratio, fit, format_name, directory):
    if not path:
        raise ValueError("Envie uma imagem primeiro.")
    if format_name not in FORMATS:
        raise ValueError("Escolha PNG, JPEG ou WebP.")
    with Image.open(path) as opened:
        if opened.width * opened.height > 24_000_000:
            raise ValueError("Use uma imagem de até 24 megapixels.")
        source = ImageOps.exif_transpose(opened).convert("RGBA")
    if mode == LOOK:
        if look not in LOOKS or not 0 <= strength <= 100:
            raise ValueError("Escolha um look e uma intensidade de 0 a 100.")
        original = source.convert("RGB")
        if look in ("Cinema quente", "Frio suave"):
            color = "#d98544" if look == "Cinema quente" else "#6394bf"
            graded = Image.blend(original, Image.new("RGB", source.size, color), .13)
            graded = ImageEnhance.Contrast(graded).enhance(1.18 if look == "Cinema quente" else .93)
        elif look == "Preto e branco":
            graded = ImageOps.grayscale(original).convert("RGB")
        else:
            graded = ImageOps.autocontrast(original, cutoff=1)
        result = Image.blend(original, graded, strength / 100).convert("RGBA")
        result.putalpha(source.getchannel("A"))
    elif mode == FRAME:
        if ratio not in SIZES or fit not in ("Preencher", "Manter imagem inteira"):
            raise ValueError("Escolha uma proporção e um modo de encaixe.")
        size = SIZES[ratio]
        if fit == "Preencher":
            result = ImageOps.fit(source, size, Image.Resampling.LANCZOS)
        else:
            fitted = ImageOps.contain(source, size, Image.Resampling.LANCZOS)
            result = Image.new("RGBA", size, "#17171e")
            result.alpha_composite(fitted, ((size[0]-fitted.width)//2, (size[1]-fitted.height)//2))
    else:
        raise ValueError("Escolha uma ferramenta de imagem.")
    if format_name == "JPEG":
        background = Image.new("RGBA", result.size, "#ffffff")
        background.alpha_composite(result)
        result = background.convert("RGB")
    destination = output_path(directory, "imagem", FORMATS[format_name])
    result.save(destination, **({"quality": 92} if format_name != "PNG" else {}))
    return str(destination), f"{source.width} × {source.height} → {result.width} × {result.height} · {format_name}"


def media_command(args, timeout):
    if not shutil.which(args[0]):
        raise ValueError(f"{args[0]} precisa estar disponível no ambiente.")
    try:
        return subprocess.run(args, capture_output=True, text=True, check=True, timeout=timeout).stdout
    except subprocess.CalledProcessError as exc:
        detail = next((line for line in reversed(exc.stderr.splitlines()) if line.strip()), "arquivo inválido")
        raise ValueError(f"{args[0]}: {detail}") from exc
    except subprocess.TimeoutExpired as exc:
        raise ValueError(f"{args[0]} excedeu o tempo de processamento.") from exc


def video_duration(path):
    raw = media_command(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                         "stream=duration:format=duration", "-of", "json", path], 20)
    data = json.loads(raw)
    streams = data.get("streams", [])
    if not streams:
        raise ValueError("O arquivo não contém uma faixa de vídeo.")
    duration = streams[0].get("duration")
    if duration in (None, "N/A"):
        duration = data.get("format", {}).get("duration")
    if duration in (None, "N/A") or not math.isfinite(float(duration)) or float(duration) <= 0:
        raise ValueError("Não consegui determinar a duração do vídeo.")
    return float(duration)


def extract_frame(path, timestamp, destination):
    media_command(["ffmpeg", "-v", "error", "-nostdin", "-y", "-ss", str(timestamp), "-i", path,
                   "-map", "0:v:0", "-frames:v", "1", "-threads", "1", str(destination)], 40)
    if not destination.is_file() or not destination.stat().st_size:
        raise ValueError("Nenhum quadro nesse ponto. Escolha um tempo anterior.")


def video_edit(path, mode, start, duration, ratio, fit, mute, directory):
    if not path:
        raise ValueError("Envie um vídeo primeiro.")
    path = str(path)
    total = video_duration(path)
    if not math.isfinite(start) or not 0 <= start < total:
        raise ValueError(f"Escolha um tempo entre 0 e {total:.2f} s.")
    if mode == STILL:
        destination = output_path(directory, "quadro", ".png")
        extract_frame(path, start, destination)
        return None, str(destination), f"Quadro em {start:.2f} s."
    if not math.isfinite(duration) or not .1 <= duration <= 180:
        raise ValueError("Escolha uma duração entre 0,1 e 180 s.")
    length = min(duration, total - start)
    if mode == BOARD:
        board = Image.new("RGB", (960, 448), "#17171e")
        draw = ImageDraw.Draw(board)
        with TemporaryDirectory() as temp:
            for index in range(6):
                timestamp = start + length * (index + .5) / 6
                frame = Path(temp) / f"frame-{index}.png"
                extract_frame(path, timestamp, frame)
                with Image.open(frame) as opened:
                    tile = ImageOps.contain(opened.convert("RGB"), (300, 170), Image.Resampling.LANCZOS)
                x, y = (index % 3) * 320 + 10, (index // 3) * 224 + 12
                board.paste(tile, (x+(300-tile.width)//2, y+(170-tile.height)//2))
                draw.text((x, y+183), f"{timestamp:.2f} s", fill="#ffffff")
        destination = output_path(directory, "prancha", ".png")
        board.save(destination)
        return None, str(destination), f"6 quadros entre {start:.2f} e {start+length:.2f} s."
    if mode != CLIP or ratio not in ("Original", *SIZES) or fit not in ("Preencher", "Manter imagem inteira"):
        raise ValueError("Escolha um formato e um encaixe disponíveis.")
    if ratio == "Original":
        video_filter = "pad=ceil(iw/2)*2:ceil(ih/2)*2"
    else:
        w, h = SIZES[ratio]
        if fit == "Preencher":
            video_filter = f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},setsar=1"
        else:
            video_filter = (f"scale={w}:{h}:force_original_aspect_ratio=decrease:force_divisible_by=2,"
                            f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1")
    destination = output_path(directory, "clipe", ".mp4")
    args = ["ffmpeg", "-v", "error", "-nostdin", "-y", "-ss", str(start), "-i", path,
            "-t", str(length), "-map", "0:v:0"]
    args += ["-an"] if mute else ["-map", "0:a:0?", "-c:a", "aac"]
    args += ["-vf", video_filter, "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
             "-movflags", "+faststart", str(destination)]
    try:
        media_command(args, 600)
    except ValueError:
        destination.unlink(missing_ok=True)
        raise
    return str(destination), None, f"Clipe de {length:.2f} s · {ratio} · {'sem áudio' if mute else 'áudio da fonte, quando disponível'}."
