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


def image_edit(path, mode, look, strength, ratio, fit, format_name, directory, focus=(0.5, 0.5)):
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
        try:
            fx, fy = (min(1.0, max(0.0, float(v))) for v in focus)
        except (TypeError, ValueError):
            raise ValueError("Posição do enquadramento inválida.") from None
        if fit == "Preencher":
            result = ImageOps.fit(source, size, Image.Resampling.LANCZOS, centering=(fx, fy))
        else:
            fitted = ImageOps.contain(source, size, Image.Resampling.LANCZOS)
            result = Image.new("RGBA", size, "#17171e")
            result.alpha_composite(fitted, (round((size[0]-fitted.width)*fx), round((size[1]-fitted.height)*fy)))
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


SEQUENCE_SIZES = {"Paisagem · 16:9": (1280, 720), "Vertical · 9:16": (720, 1280),
                  "Quadrado · 1:1": (720, 720)}


def video_sequence(paths, order, ratio, fit, mute, directory):
    if not paths or not 2 <= len(paths) <= 8:
        raise ValueError("Envie de 2 a 8 clipes.")
    if ratio not in SEQUENCE_SIZES or fit not in ("Preencher", "Manter imagem inteira"):
        raise ValueError("Escolha um formato e um encaixe disponíveis.")
    indexes = range(1, len(paths) + 1)
    if order.strip():
        try:
            indexes = [int(part.strip()) for part in order.split(",")]
        except ValueError:
            raise ValueError("Use números separados por vírgula para definir a ordem.") from None
        if sorted(indexes) != list(range(1, len(paths) + 1)):
            raise ValueError("Use o número de cada clipe exatamente uma vez.")
    paths = [str(paths[index - 1]) for index in indexes]
    durations = [video_duration(path) for path in paths]
    if sum(durations) > 180:
        raise ValueError("A sequência pode ter até 180 s no total.")

    width, height = SEQUENCE_SIZES[ratio]
    if fit == "Preencher":
        framing = f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height}"
    else:
        framing = (f"scale={width}:{height}:force_original_aspect_ratio=decrease:force_divisible_by=2,"
                   f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2")

    args = ["ffmpeg", "-v", "error", "-nostdin", "-y", "-filter_complex_threads", "2"]
    filters, segments = [], []
    for i, (path, duration) in enumerate(zip(paths, durations)):
        args += ["-threads", "2", "-i", path]
        filters.append(f"[{i}:v:0]{framing},setsar=1,fps=24,format=yuv420p,setpts=PTS-STARTPTS[v{i}]")
        segments.append(f"[v{i}]")
        if not mute:
            audio = media_command(["ffprobe", "-v", "error", "-select_streams", "a:0",
                                   "-show_entries", "stream=index", "-of", "csv=p=0", path], 20)
            track = f"[{i}:a:0]" if audio.strip() else "anullsrc=r=48000:cl=stereo,"
            filters.append(f"{track}aformat=sample_rates=48000:channel_layouts=stereo,"
                           f"asetpts=PTS-STARTPTS,apad,atrim=duration={duration:.9f}[a{i}]")
            segments.append(f"[a{i}]")
    filters.append(f"{''.join(segments)}concat=n={len(paths)}:v=1:a={int(not mute)}[video]"
                   + ("" if mute else "[audio]"))
    args += ["-filter_complex", ";".join(filters), "-map", "[video]"]
    if not mute:
        args += ["-map", "[audio]", "-c:a", "aac", "-b:a", "192k"]
    destination = output_path(directory, "sequencia", ".mp4")
    try:
        media_command(args + ["-c:v", "libx264", "-threads", "2", "-preset", "veryfast",
                              "-movflags", "+faststart", str(destination)], 600)
    except ValueError:
        destination.unlink(missing_ok=True)
        raise
    return str(destination), f"{len(paths)} clipes · {width} × {height} · 24 fps · {sum(durations):.2f} s de entrada"


def compare_images(before_path, after_path, directory):
    if not before_path or not after_path:
        raise ValueError("Envie as duas imagens para comparar.")
    images = []
    for path in (before_path, after_path):
        with Image.open(path) as opened:
            images.append(ImageOps.exif_transpose(opened).convert("RGBA"))
    before, after = images
    scale = min(1, 1600 / max(after.size))
    canvas_size = tuple(max(1, round(edge * scale)) for edge in after.size)
    aligned = []
    for image in images:
        scale = min(canvas_size[0] / image.width, canvas_size[1] / image.height)
        fitted_size = tuple(max(1, round(edge * scale)) for edge in image.size)
        fitted = image.resize(fitted_size, Image.Resampling.LANCZOS)
        canvas = Image.new("RGBA", canvas_size, "#17171e")
        canvas.alpha_composite(fitted, ((canvas.width - fitted.width) // 2,
                                        (canvas.height - fitted.height) // 2))
        aligned.append(canvas.convert("RGB"))
    separator = 4
    sheet = Image.new("RGB", (2 * canvas_size[0] + separator, canvas_size[1]), "#ffffff")
    sheet.paste(aligned[0], (0, 0))
    sheet.paste(aligned[1], (canvas_size[0] + separator, 0))
    destination = output_path(directory, "comparacao", ".png")
    sheet.save(destination)
    status = f"Antes {before.width} × {before.height} · Depois {after.width} × {after.height}"
    return tuple(aligned), str(destination), status
