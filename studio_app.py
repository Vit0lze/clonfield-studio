# 3. Iniciar ClonField Studio. Nenhum modelo é carregado até clicar em Gerar.
print('ClonField: iniciando processo da interface...', flush=True)
import os, sys, json, time, uuid, random, shutil, traceback, subprocess
from pathlib import Path
from functools import partial
import unicodedata
from urllib.parse import urlparse, parse_qs

# Gradio checks its own loopback endpoint during launch.
no_proxy = os.environ.get("no_proxy") or os.environ.get("NO_PROXY") or ""
os.environ["no_proxy"] = os.environ["NO_PROXY"] = ",".join(filter(None, (no_proxy, "127.0.0.1", "localhost")))
print("CLONFIELD_PHASE importando_bibliotecas", flush=True)
import requests, gradio as gr
from gradio import processing_utils
from PIL import Image, ImageFilter
import numpy as np
import zipfile
import cf_apps, cf_jobs, cf_loras, cf_tiers, cf_upscale
import cf_model_lab as model_lab
import cf_workflows as workflows

BASE=Path(os.environ.get('CLONFIELD_DIR','/content/ClonField_Lab'))
LORAS=BASE/'loras'; OUT=BASE/'outputs'
for p in (LORAS, OUT): p.mkdir(parents=True,exist_ok=True)
DEFAULT_SIZE = '768 × 768 · Inicial'
IMAGE_SIZES = {
    '512 × 512 · Rascunho': (512, 512),
    DEFAULT_SIZE: (768, 768),
    '1024 × 1024 · Quadrado': (1024, 1024),
    '1344 × 768 · Paisagem': (1344, 768),
    '768 × 1344 · Vertical': (768, 1344),
    '1536 × 1536 · Alta': (1536, 1536),
    '2048 × 2048 · Alta': (2048, 2048),
    '2752 × 1536 · Alta paisagem': (2752, 1536),
    '1536 × 2752 · Alta vertical': (1536, 2752),
}
SEEDVR2_POST = 'SeedVR2 INT8'
from cf_loras import CATALOGO, CATALOGO_BY_ID


def unload_qwen():
    """Qwen now runs inside ComfyUI, which frees its own models. Kept for the tool modules' callbacks."""


def phase(name):
    print(f"CLONFIELD_PHASE {name}", flush=True)


def nomes(): return sorted(p.name for p in LORAS.glob('*.safetensors'))
def atualizar(): return gr.update(choices=nomes())

def importar(upload):
    if not upload: raise gr.Error('Selecione um arquivo .safetensors.')
    p=Path(upload)
    if p.suffix.lower()!='.safetensors': raise gr.Error('Apenas .safetensors é aceito.')
    dest=LORAS/p.name; shutil.copyfile(p,dest)
    return f'Salvo: {dest.name}', gr.update(choices=nomes())

def baixar(url, token):
    u=url.strip(); parsed=urlparse(u)
    if parsed.scheme!='https' or parsed.hostname not in ('civitai.com','civitai.red','huggingface.co'):
        raise gr.Error('Use HTTPS em civitai.com, civitai.red ou huggingface.co.')
    if parsed.hostname in ('civitai.com','civitai.red') and parsed.path.startswith('/models/'):
        version=parse_qs(parsed.query).get('modelVersionId',[None])[0]
        if not version: raise gr.Error('Inclua ?modelVersionId=... no link Civitai ou use um link direto de download.')
        u='https://civitai.com/api/download/models/'+version
    if parsed.hostname=='huggingface.co': u=u.replace('/blob/','/resolve/')
    secret=(token or '').strip() or (os.environ.get('CIVITAI_TOKEN','') if parsed.hostname in ('civitai.com','civitai.red') else os.environ.get('HF_TOKEN',''))
    headers={'Authorization':'Bearer '+secret} if secret else {}
    # Credentials are sent only to the original host; requests strips authorization on cross-host redirects.
    try:
        with requests.get(u,headers=headers,stream=True,timeout=(30,120),allow_redirects=True) as r:
            r.raise_for_status()
            disposition=r.headers.get('content-disposition','')
            import re
            m=re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)',disposition,flags=re.I)
            name=Path(m.group(1)).name if m else Path(urlparse(r.url).path).name
            if not name.lower().endswith('.safetensors'): raise ValueError('O servidor não retornou nome .safetensors. Use upload manual ou link direto correto.')
            tmp=LORAS/(uuid.uuid4().hex+'.part'); dest=LORAS/name
            try:
                with tmp.open('wb') as f:
                    for chunk in r.iter_content(1024*1024):
                        if chunk: f.write(chunk)
                from safetensors import safe_open
                with safe_open(str(tmp),framework='pt',device='cpu') as s: list(s.keys())
                os.replace(tmp,dest)
            finally:
                if tmp.exists(): tmp.unlink()
        return f'Download concluído: {name}', gr.update(choices=nomes()), ''
    except Exception as e: raise gr.Error(f'Falha no download ({type(e).__name__}). Confira link, permissão, token e espaço disponível.')


UP_MODELS = cf_upscale.MODELS


def postprocessar(im, modo, escala, tile, pad, device, nitidez):
    return cf_upscale.process(im, modo, escala, int(tile), int(pad), device, nitidez, BASE)

def pos_manual(file, modo, escala, tile, pad, device, nitidez):
    if not file: raise gr.Error('Envie uma imagem primeiro.')
    try:
        with Image.open(file) as src: im=src.copy()
        out=postprocessar(im,modo,escala,int(tile),int(pad),device,nitidez)
        path=OUT/('upscale_manual_'+uuid.uuid4().hex[:10]+'.png'); out.save(path)
        return str(path),f'Salvo: {path} | {im.width}×{im.height} → {out.width}×{out.height}'
    except Exception as e:
        traceback.print_exc(); raise gr.Error(f'Falhou o pós-processamento: {e}. Se faltou VRAM, selecione CPU ou blocos menores.')

def image_size(preset):
    return IMAGE_SIZES.get(preset, (gr.skip(), gr.skip()))


class LegacyContext:
    """Lets the shared app runners report into a Gradio progress bar."""

    def __init__(self, progress):
        import types
        self._progress, self.out_dir, self.control = progress, OUT, workflows.Control()
        self.job = types.SimpleNamespace(id=uuid.uuid4().hex[:12], update=lambda **fields: None)

    def progress(self, fraction=None, desc=None, **_):
        self._progress(min(1, max(0, fraction or 0)), desc=desc)

    def check(self):
        pass


def gerar(prompt, negative, files, width, height, steps, cfg, seed, nimgs, choices, weights, composite_scene, mask_file, feather, model, curated, modo, escala, tile, pad, device, nitidez, progress=gr.Progress()):
    if not prompt or not prompt.strip(): raise gr.Error('Escreva um prompt.')
    try: strengths=[float(x.strip()) for x in (weights or '').split(',') if x.strip()]
    except ValueError: raise gr.Error('Pesos das LoRAs precisam ser números separados por vírgula.')
    if any(not -2 <= x <= 2 for x in strengths): raise gr.Error('Use pesos entre -2 e 2.')
    if bool(composite_scene) != bool(mask_file): raise gr.Error('Para composição, envie a cena e a máscara juntas.')
    names=list(dict.fromkeys((choices or [])+[Path(CATALOGO_BY_ID[k]['file']).name for k in (curated or [])]))
    loras=[{'name':n,'strength':strengths[i] if i<len(strengths) else 1.0} for i,n in enumerate(names)]
    preset=model_lab.PRESETS[model]
    refs=list(files or [])
    if composite_scene:
        from PIL import ImageOps
        with Image.open(composite_scene) as im: refs.insert(0, composite_scene)
    ctx=LegacyContext(progress)
    try:
        outs=cf_apps.run_graph_images(ctx, preset, {'prompt':prompt,'negative':negative,'steps':steps,'cfg':cfg,'seed':seed,'loras':loras}, refs, int(width), int(height), int(nimgs))
    except cf_jobs.JobError as exc:
        raise gr.Error(str(exc)) from exc
    paths=[]; originais=[]; report=[]
    from PIL import ImageOps
    for out in outs:
        img=Image.open(out).convert('RGB'); originais.append(str(out)); final=out
        if composite_scene:
            with Image.open(composite_scene) as source: background=ImageOps.exif_transpose(source).convert('RGB')
            with Image.open(mask_file) as source: mask=ImageOps.exif_transpose(source).convert('L')
            if mask.size != background.size: raise gr.Error('A máscara precisa ter a mesma largura e altura da cena.')
            if feather>0: mask=mask.filter(ImageFilter.GaussianBlur(radius=float(feather)))
            final=Path(out).with_name(Path(out).stem+'_composicao.png')
            Image.composite(img.resize(background.size,Image.Resampling.LANCZOS),background,mask).save(final)
        if modo not in ('Nenhum', SEEDVR2_POST) or nitidez>0:
            try:
                result=postprocessar(Image.open(final).convert('RGB'),'Nenhum' if modo==SEEDVR2_POST else modo,float(escala),int(tile),int(pad),device,nitidez)
                final=Path(final).with_name(Path(final).stem+'_final.png'); result.save(final)
            except Exception as exc: report.append(f'Pós-processamento falhou: {exc}; original preservado.')
        paths.append(str(final))
    meta={'prompt':prompt,'negative_prompt':negative,'seed':seed,'width':int(width),'height':int(height),'steps':steps,'cfg':cfg,'modelo':model,'loras':names,'arquivos_finais':paths,'originais':originais,'avisos':report}
    archive=OUT/('lote_'+uuid.uuid4().hex[:10]+'.zip')
    with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED) as z:
        for p in dict.fromkeys(originais+paths): z.write(p,arcname=Path(p).name)
    return paths,originais,json.dumps(meta,ensure_ascii=False,indent=2),str(archive)


def baixar_catalogo(ids):
    added=[]
    for ident in ids or []:
        if ident not in CATALOGO_BY_ID: raise ValueError('Entrada de catálogo desconhecida.')
        added.append(cf_loras.ensure(BASE, Path(CATALOGO_BY_ID[ident]['file']).name).name)
    return added

def instalar_catalogo(ids):
    if not ids: raise gr.Error('Selecione uma ou mais LoRAs.')
    try:
        names=baixar_catalogo(ids)
        return 'Preparadas: '+', '.join(names),gr.update(choices=nomes())
    except Exception as e:
        traceback.print_exc(); raise gr.Error('Não foi possível baixar a LoRA selecionada. Verifique acesso, conexão e espaço disponível.')

def filtrar_catalogo(q):
    q=(q or '').lower().strip()
    return gr.update(choices=[k for k in CATALOGO_BY_ID if q in k.lower()])

def workflow_result(job):
    folder = OUT / job["id"]
    files = [folder / name for name in job["results"] if (folder / name).is_file()]
    images = [str(path) for path in files if path.suffix in workflows.IMAGE_SUFFIXES]
    video = next((str(path) for path in files if path.suffix in workflows.VIDEO_SUFFIXES), None)
    audio = next((str(path) for path in files if path.suffix in workflows.AUDIO_SUFFIXES), None)
    status = job["status"].replace("_", " ").capitalize()
    if job.get("prompt_id"):
        status += "\nJob ComfyUI: " + job["prompt_id"]
    if job.get("message"):
        status += "\n" + job["message"]
    return images, video, audio, [str(path) for path in files], status


def api_workflow(file, server, media=None, progress=gr.Progress()):
    if not file:
        raise gr.Error('Envie um JSON em formato API.')
    if server.rstrip('/') not in (seedvr2.SERVER, 'http://localhost:8188'):
        raise gr.Error('Use o worker ComfyUI local na porta 8188.')
    try:
        graph = workflows.read_graph(file)
        unload_qwen()
        return workflow_result(workflows.run(graph, OUT, progress, media))
    except (OSError, ValueError, RuntimeError) as exc:
        raise gr.Error(str(exc)) from exc


def list_workflow_jobs():
    return gr.update(choices=workflows.recent(OUT), value=None)


def reopen_workflow(job_id):
    try:
        return workflow_result(workflows.reopen(OUT, job_id))
    except (OSError, ValueError) as exc:
        raise gr.Error(str(exc)) from exc


def ambiente():
    tier=cf_tiers.detect()
    disk=shutil.disk_usage(BASE)
    credentials='HF: '+('disponível' if os.environ.get('HF_TOKEN') else 'não configurado')+' · Civitai: '+('disponível' if os.environ.get('CIVITAI_TOKEN') else 'não configurado')
    return f'{tier.gpu} · {tier.vram_gb:.0f} GB · perfil {tier.label} | Espaço livre: {disk.free/1024**3:.1f} GiB | {credentials}'

# The preceding notebook cell extracts the workflow bundle.
STUDIO_MODULES = Path(__file__).resolve().parent / 'workflows'
import cf_seedvr2 as seedvr2
import cf_workflows as workflows
import cf_wan as wan
import cf_finish as finish
import cf_history as history
import cf_lab_ui
import cf_region as region
import cf_openjutsu as openjutsu


def upscale_result(job):
    result = str(OUT / job["id"] / job["result"]) if job.get("result") else None
    details = job["status"].replace("_", " ").capitalize()
    if job.get("fallback"):
        details += f" · {job['model']} após falta de VRAM em {job['fallback']['model']}"
    if job.get("error"):
        details += " · " + job["error"]
    if job.get("prompt_id"):
        details += "\nJob ComfyUI: " + job["prompt_id"]
    return result if job["kind"] == "Imagem" else None, result if job["kind"] == "Vídeo" else None, result, details


def launch_seedvr2(path, kind, model, scale, seed, tile, progress=gr.Progress()):
    try:
        seedvr2.validate(path, kind, model, scale, seed, tile)
        unload_qwen()
        return upscale_result(seedvr2.run(path, kind, model, scale, seed, tile, OUT, progress))
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        raise gr.Error(str(exc)) from exc


def list_seedvr2_jobs():
    return gr.update(choices=seedvr2.recent_jobs(OUT), value=None)


def reopen_seedvr2(job_id, progress=gr.Progress()):
    try:
        return upscale_result(seedvr2.reopen(OUT, job_id, progress))
    except (OSError, ValueError) as exc:
        raise gr.Error(str(exc)) from exc


APP_CARDS = (
    ('Imagem', 'Bancada de modelos', 'Combine checkpoints, difusão, LoRAs, VAE e encoders e gere pelo ComfyUI.', 'Qwen · FLUX · Krea · Z-Image', 'bancada', ''),
    ('Imagem', 'Direção de cena', 'Monte um prompt com câmera, ação, luz e o papel de cada referência.', 'Prompt · CPU', 'direcao', ''),
    ('Melhorar', 'Catálogo Civitai', 'Encontre arquivos compatíveis e use imagens de exemplo como referência.', 'Biblioteca online', 'civitai', ''),
    ('Imagem', 'Criar imagem', 'Transforme uma descrição em imagem.', 'Qwen 2.1', 'criar', ''),
    ('Imagem', 'Editar com referências', 'Descreva o que muda e o que precisa ser preservado.', 'Qwen 2.1', 'criar', 'editar'),
    ('Imagem', 'Editar região', 'Use uma máscara para retocar só uma área e manter o tamanho da foto.', 'Qwen 2.1', 'regiao', ''),
    ('Identidade', 'Retrato por referência', 'Use duas imagens para guiar a identidade e a composição.', 'Qwen 2.1', 'criar', 'retrato'),
    ('Vídeo', wan.IMAGE_MODE, 'Anime uma foto com instruções de movimento e câmera.', 'Wan 2.2 · 5B', 'video', wan.IMAGE_MODE),
    ('Vídeo', wan.TEXT_MODE, 'Crie um clipe curto descrevendo a cena.', 'Wan 2.2 · 5B', 'video', wan.TEXT_MODE),
    ('Melhorar', 'Upscale de imagem', 'Amplie fotos e ilustrações com o Real-ESRGAN.', 'Real-ESRGAN', 'upscale-rapido', ''),
    ('Melhorar', 'Upscale de imagem ou vídeo', 'Recupere detalhe e amplie com SeedVR2.', 'SeedVR2 · INT8', 'seedvr2', ''),
    ('Identidade', 'Trocar personagem · OpenJutsu', 'Aplique uma referência a um clipe com um worker H3 preparado.', 'H3 · classe 96 GB', 'openjutsu', ''),
    ('Melhorar', 'Comparar imagens', 'Deslize entre antes e depois e salve a comparação lado a lado.', 'Imagem · CPU', 'comparar', ''),
    ('Melhorar', finish.LOOK, 'Aplique um look com intensidade ajustável e compare com a foto de entrada.', 'Imagem · CPU', 'acabamento', finish.LOOK),
    ('Imagem', finish.FRAME, 'Prepare a foto para feed, stories ou paisagem e exporte em PNG, JPEG ou WebP.', 'Imagem · CPU', 'acabamento', finish.FRAME),
    ('Vídeo', finish.CLIP, 'Recorte o trecho e ajuste a proporção, com áudio opcional.', 'Vídeo · CPU', 'montagem', finish.CLIP),
    ('Vídeo', finish.STILL, 'Salve um quadro de um ponto do clipe como PNG.', 'Vídeo · CPU', 'montagem', finish.STILL),
    ('Vídeo', 'Montar sequência', 'Junte clipes em uma ordem escolhida e exporte um único MP4.', 'Vídeo · CPU', 'sequencia', ''),
    ('Vídeo', finish.BOARD, 'Veja seis momentos de um trecho em uma prancha com timecodes.', 'Vídeo · CPU', 'montagem', finish.BOARD),
)
ORIGINALS = {
    'Retrato, rosto e upscale': [('Capivara · composição de retrato', 'capivara-retrato')],
    'Substituir personagem em vídeo': [('SCAIL-2 · referência A', 'scail-2-referencia-a'),
                                      ('SCAIL-2 · referência B', 'scail-2-referencia-b'),
                                      ('SCAIL-2 · referência C', 'scail-2-referencia-c')],
    'Transferir atuação': [('Wan Animate · Estrelinha A', 'wan-animate-estrelinha-a'),
                           ('Wan Animate · Estrelinha B', 'wan-animate-estrelinha-b')],
}
PORTRAIT_PROMPT = (
    'Crie um retrato usando a pessoa da primeira imagem como referência de identidade. '
    'Use a segunda imagem como referência de pose, enquadramento, luz e cenário. '
    'Preserve os traços do rosto da primeira pessoa.'
)


def searchable(text):
    return ''.join(ch for ch in unicodedata.normalize('NFKD', text.casefold()) if not unicodedata.combining(ch))


def filter_cards(category, query):
    words = searchable(query or '').split()
    shown = [(category in ('Todas', entry[0]) and
              all(word in searchable(' '.join(entry[:4])) for word in words)) for entry in APP_CARDS]
    count = sum(shown)
    label = f"{count} ferramenta" + ("s" if count != 1 else "")
    return [gr.update(visible=value) for value in [*shown, not count]] + [label]


def downloaded_workflows():
    directory = BASE / 'civitai' / 'workflows'
    return sorted((path.name, str(path)) for path in directory.iterdir()
                  if path.is_file() and path.suffix.lower() in {'.json', '.png', '.zip'}) if directory.is_dir() else []


def open_civitai_workflow(selected):
    if selected not in {path for _, path in downloaded_workflows()}:
        raise gr.Error('Escolha um arquivo Civitai já baixado.')
    return selected


def original_choices(category):
    choices = ORIGINALS[category]
    return gr.update(choices=choices, value=choices[0][1]), None


def original_download(key):
    if key not in {item for group in ORIGINALS.values() for _, item in group}:
        raise gr.Error('Escolha um workflow da lista.')
    return str(STUDIO_MODULES / f'{key}.json')


def select_tool_tab(tab):
    return gr.Tabs(selected=tab)


def open_image_tool(mode, current_prompt):
    if mode == 'retrato':
        instructions = ('### Retrato por referência\nAnexe primeiro a pessoa e depois a imagem de composição. '
                        'A edição é guiada pelo prompt do Qwen.')
        draft = current_prompt or PORTRAIT_PROMPT
    elif mode == 'editar':
        instructions = '### Editar com referências\nAnexe a imagem e descreva o que deve mudar.'
        draft = current_prompt
    else:
        instructions = '### Criar imagem\nDescreva a cena. As referências são opcionais.'
        draft = current_prompt
    return gr.Tabs(selected='criar'), instructions, draft


def open_video_tool(mode):
    return gr.Tabs(selected='video'), gr.update(value=mode), gr.update(visible=mode == wan.IMAGE_MODE)


def launch_wan(mode, image, prompt, negative, size, frames, steps, seed, progress=gr.Progress()):
    try:
        graph = wan.make_graph(mode, image, prompt, negative, size, frames, steps, seed)
        unload_qwen()
        job = workflows.run(graph, OUT, progress, prepare=partial(wan.prepare, image=image),
                            title=mode)
        _, video, _, files, status = workflow_result(job)
        return video, files, status
    except (OSError, ValueError, RuntimeError) as exc:
        raise gr.Error(str(exc)) from exc


def launch_openjutsu(video, character, anchor, start, seconds, quality, direction, seed, progress=gr.Progress()):
    if not video or not character:
        raise gr.Error('Envie o clipe e a imagem do personagem.')
    try:
        graph = openjutsu.build_graph(start, seconds, int(quality), direction, seed, bool(anchor))
        unload_qwen()
        prepare = partial(openjutsu.prepare, video=video, character=character, anchor=anchor)
        job = workflows.run(graph, OUT, progress, prepare=prepare, title='OpenJutsu H3')
        _, result, _, files, status = workflow_result(job)
        return result, files, status
    except (OSError, ValueError, RuntimeError) as exc:
        raise gr.Error(str(exc)) from exc


def image_options(mode):
    return gr.update(visible=mode == finish.LOOK), gr.update(visible=mode == finish.FRAME)


def clip_options(mode):
    return gr.update(visible=mode != finish.STILL), gr.update(visible=mode == finish.CLIP)


def open_finish_tool(tab, mode):
    options = image_options(mode) if tab == 'acabamento' else clip_options(mode)
    return gr.Tabs(selected=tab), gr.update(value=mode), *options


def send_to_finish(tab, mode, media):
    if not media:
        raise gr.Error('Primeiro selecione ou gere um resultado.')
    routed = (*open_finish_tool(tab, mode), media)
    return (*routed, 0) if tab == 'montagem' else routed


def select_gallery_image(evt: gr.SelectData):
    return evt.index if isinstance(evt.index, int) and evt.selected else 0


def finish_gallery(items, index):
    if not items:
        raise gr.Error('Gere uma imagem primeiro.')
    image, _ = items[index if 0 <= index < len(items) else 0]
    return send_to_finish('acabamento', finish.LOOK, image)


def animate_image(media):
    if not media:
        raise gr.Error('Primeiro gere ou extraia uma imagem.')
    return gr.Tabs(selected='video'), gr.update(value=wan.IMAGE_MODE), gr.update(value=media, visible=True)


def finish_image(media, mode, look, intensity, ratio, fit, format_name):
    try:
        path, status = finish.image_edit(media, mode, look, intensity, ratio, fit, format_name, OUT)
        return path, path, status
    except (OSError, ValueError) as exc:
        raise gr.Error(str(exc)) from exc


def finish_clip(media, mode, start, duration, ratio, fit, mute, progress=gr.Progress()):
    try:
        progress(0.2, desc='Preparando a mídia')
        video, image, status = finish.video_edit(media, mode, start, duration, ratio, fit, mute, OUT)
        return gr.update(value=video, visible=bool(video)), gr.update(value=image, visible=bool(image)), video or image, status
    except (OSError, ValueError) as exc:
        raise gr.Error(str(exc)) from exc


def edit_region(source, mask, prompt, size, padding, feather, steps, seed, progress=gr.Progress()):
    if not prompt or not prompt.strip():
        raise gr.Error('Descreva a alteração na região.')
    if not source or not mask:
        raise gr.Error('Envie a imagem e a máscara.')
    params = {'source': [source], 'mask': [mask], 'prompt': prompt.strip(), 'size': int(size), 'padding': int(padding),
              'feather': int(feather), 'steps': int(steps), 'seed': int(seed)}
    try:
        out = cf_apps.run_region(LegacyContext(progress), params, cf_tiers.detect())[0]
    except cf_jobs.JobError as exc:
        raise gr.Error(str(exc)) from exc
    return str(out), str(out), 'Editado pelo ComfyUI'


def finish_sequence(media, order, ratio, fit, mute, progress=gr.Progress()):
    try:
        progress(0.1, desc='Analisando os clipes e montando a sequência…')
        path, status = finish.video_sequence(media, order, ratio, fit, mute, OUT)
        return path, path, status
    except (OSError, ValueError) as exc:
        raise gr.Error(str(exc)) from exc


def list_history(kind, query):
    try:
        entries = history.choices(OUT, kind, query)
    except OSError as exc:
        raise gr.Error('Não consegui ler a pasta de saídas. Confira se o Drive continua montado.') from exc
    count = len(entries)
    if not count:
        status = 'Nenhum resultado para este filtro.'
    elif count == history.MAX_RESULTS:
        status = f'{count} resultados mais recentes. Use a busca para encontrar outros.'
    else:
        status = '1 resultado' if count == 1 else f'{count} resultados'
    return gr.update(choices=entries, value=None), status


def history_video_preview(path):
    # Gradio may transcode a preview in place. Keep that copy separate from the saved output.
    if processing_utils.ffmpeg_installed() and not processing_utils.video_is_playable(str(path)):
        cache = Path(hist_video.GRADIO_CACHE) / 'clonfield-previews'
        return processing_utils.save_file_to_cache(path, cache_dir=str(cache))
    return str(path)


def history_preview(key):
    if not key:
        return (*(gr.update(value=None, visible=False) for _ in range(3)), None, '',
                gr.update(visible=False), gr.update(visible=False), gr.update(visible=False))
    try:
        path = history.resolve_media(OUT, key)
    except (OSError, ValueError) as exc:
        raise gr.Error(str(exc)) from exc
    kind = history.media_type(path)
    title, data = history.describe(OUT.resolve(), path, {})
    preview = history_video_preview(path) if kind == 'Vídeo' else str(path)
    previews = [gr.update(value=preview if kind == media else None, visible=kind == media)
                for media in history.TYPES[1:]]
    details = json.dumps(data, ensure_ascii=False, indent=2) if data else title
    return (*previews, str(path), details, gr.update(visible=kind == 'Imagem'),
            gr.update(visible=kind == 'Vídeo'), gr.update(visible=bool(history.qwen_pair(path))))


def history_route(destination, key):
    try:
        path = history.resolve_media(OUT, key)
        kind = history.media_type(path)
        if destination == 'seedvr2' and kind in ('Imagem', 'Vídeo'):
            return gr.Tabs(selected=destination), str(path), kind
        if destination == 'acabamento' and kind == 'Imagem':
            return send_to_finish(destination, finish.LOOK, str(path))
        if destination == 'montagem' and kind == 'Vídeo':
            return send_to_finish(destination, finish.CLIP, history_video_preview(path))
        if destination == 'video' and kind == 'Imagem':
            return animate_image(str(path))
        if destination == 'comparar':
            pair = history.qwen_pair(path)
            if pair:
                return open_comparison(*pair)
    except (OSError, ValueError) as exc:
        raise gr.Error(str(exc)) from exc
    raise gr.Error('Esse resultado não é compatível com a ferramenta escolhida.')


def compare_images(before, after):
    try:
        return finish.compare_images(before, after, OUT)
    except (OSError, ValueError) as exc:
        raise gr.Error(str(exc)) from exc


def open_comparison(before, after):
    if not before or not after:
        raise gr.Error('Gere o resultado para comparar com o original.')
    return gr.Tabs(selected='comparar'), before, after, None, None, ''


CSS = """
.gradio-container {max-width: 1760px !important; margin-inline:auto; background: #0b0708 !important;}
#hero {padding: 1rem 1.3rem; border:1px solid #2d2024; border-radius:14px; background:linear-gradient(110deg,#2a1216,#130d0f);}
#hero h1 {font-size: 2rem; margin:0;}
#primary button {font-weight:700;}
#cf-app-grid {display:grid; grid-template-columns:repeat(auto-fill,minmax(min(100%,254px),1fr)); gap:12px;}
#cf-app-grid .cf-app-card {justify-content:space-between; height:100%; box-sizing:border-box;}
#cf-bench .cf-slot {align-items:end;}
#cf-app-grid .cf-app-card button {justify-content:flex-start;}
#cf-app-grid .cf-app-card h3 {font-size:1.08rem;}
#cf-app-grid .cf-app-card strong {font-size:.76rem; color:#eeabbc;}
#cf-tool-count p {margin:0; font-size:.9rem;}
@media (max-width:600px) {
  #hero {padding:.8rem;}
  #hero h1 {font-size:1.55rem;}
}
.cf-app-card {padding:16px; min-width:0 !important; border:1px solid #43303a;
  border-radius:14px; background:linear-gradient(148deg,#241418,#130d0f); color:#f7edf6;}
.cf-app-card h3 {color:#fff; margin:.35rem 0;}
.cf-app-card p {color:#e2d5e1;}
"""
phase('montando_interface')
with gr.Blocks(title='ClonField Studio', theme=gr.themes.Soft(primary_hue='red', neutral_hue='slate'),
               css=CSS, analytics_enabled=False) as demo:
    gr.Markdown('# ClonField Studio · modo clássico\nO app novo está em **/studio/** no mesmo link. Esta interface continua disponível como alternativa.',elem_id='hero')
    with gr.Tabs(selected='explorar') as main_tabs:
        with gr.Tab('Explorar', id='explorar'):
            gr.Markdown('## O que você quer fazer?\nEscolha uma ferramenta para abrir o formulário.')
            with gr.Row():
                app_category = gr.Radio(['Todas', 'Imagem', 'Vídeo', 'Identidade', 'Melhorar'],
                                        value='Todas', label='Categoria')
                app_search = gr.Textbox(label='Buscar ferramenta', placeholder='Ex.: retrato, vídeo, SeedVR2')
            with gr.Row():
                tool_count = gr.Markdown(f'{len(APP_CARDS)} ferramentas', elem_id='cf-tool-count')
                clear_filter = gr.Button('Limpar filtros', size='sm', scale=0)
            card_layouts, card_buttons = [], []
            with gr.Row(elem_id='cf-app-grid'):
                for category, title, description, engine, _, _ in APP_CARDS:
                    with gr.Column(min_width=0, elem_classes=['cf-app-card']) as card:
                        gr.Markdown(f'**{category} · {engine}**\n\n### {title}\n\n{description}')
                        card_buttons.append(gr.Button('Abrir ' + title.lower()))
                    card_layouts.append(card)
            no_apps = gr.Markdown('Nenhuma ferramenta encontrada.', visible=False)
            for control in (app_category, app_search):
                control.input(filter_cards, [app_category, app_search], [*card_layouts, no_apps, tool_count],
                              queue=False, api_name=False)
            clear_filter.click(
                lambda: ('Todas', '', *filter_cards('Todas', '')), None,
                [app_category, app_search, *card_layouts, no_apps, tool_count], queue=False, api_name=False)
        with gr.Tab('Criar',id='criar'):
            image_tool_help = gr.Markdown('### Criar imagem\nDescreva a cena. As referências são opcionais.')
            with gr.Row():
                with gr.Column(scale=5,min_width=330):
                    prompt=gr.Textbox(label='O que você quer criar ou editar?',lines=4,placeholder='Descreva a imagem ou a alteração…')
                    imgs=gr.File(label='Imagens de referência • até 10, na ordem enviada',file_count='multiple',file_types=['image'],type='filepath')
                    with gr.Row():
                        model=gr.Dropdown([(model_lab.PRESETS[k].title.split(' · ')[0],k) for k in cf_apps.IMAGE_MODELS],value='flux2' if cf_tiers.detect().vram_gb<16 else 'qwen21',label='Modelo')
                        num=gr.Slider(1,4,value=1,step=1,label='Variações')
                    size_preset = gr.Dropdown([*IMAGE_SIZES, 'Personalizado'], value=DEFAULT_SIZE, label='Resolução',
                                              info='Tamanhos maiores usam mais VRAM. O máximo na T4 depende da sessão e das referências.')
                    with gr.Row():
                        w = gr.Slider(256, 2752, value=768, step=32, label='Largura')
                        h = gr.Slider(256, 2752, value=768, step=32, label='Altura')
                    size_preset.input(image_size, size_preset, [w, h], queue=False, api_name=False)
                    for dimension in (w, h):
                        dimension.input(lambda: 'Personalizado', None, size_preset, queue=False, api_name=False)
                    with gr.Accordion('LoRAs',open=False):
                        choices=gr.Dropdown(choices=nomes(),multiselect=True,label='Arquivos locais')
                        curated=gr.Dropdown(choices=list(CATALOGO_BY_ID),multiselect=True,label='Catálogo • baixar ao gerar',filterable=True)
                        weights=gr.Textbox(value='1.0',label='Pesos em ordem, separados por vírgula')
                        gr.Markdown('Confira a família da LoRA. Turbo e LoRAs de aceleração podem exigir configurações próprias.')
                    with gr.Accordion('Configurações avançadas',open=False):
                        neg=gr.Textbox(label='Prompt negativo • aplicado quando True CFG > 1')
                        with gr.Row():
                            steps=gr.Slider(0,80,value=0,step=1,label='Passos • 0 usa o recomendado'); cfg=gr.Slider(0,8,value=0,step=.5,label='CFG • 0 usa o recomendado'); seed=gr.Number(value=-1,precision=0,label='Seed • -1 aleatório')
                    with gr.Accordion('Composição por máscara',open=False):
                        gr.Markdown('Branco revela o resultado; preto preserva a cena. A composição acontece após gerar; não é inpainting.')
                        with gr.Row():
                            composite_scene=gr.File(label='Cena',file_types=['image'],type='filepath');mask_file=gr.File(label='Máscara',file_types=['image'],type='filepath')
                        feather=gr.Slider(0,64,value=4,step=1,label='Suavização da borda')
                    with gr.Accordion('Pós-processamento',open=False):
                        modo=gr.Dropdown(choices=['Nenhum','Lanczos (rápido, sem IA)']+list(UP_MODELS)+[SEEDVR2_POST],value='Nenhum',label='Upscale após gerar')
                        gr.Markdown('SeedVR2 usa o worker local. Bloco, margem e dispositivo abaixo se aplicam ao Real-ESRGAN.')
                        with gr.Row():
                            escala=gr.Slider(1,4,value=2,step=.5,label='Escala');nitidez=gr.Slider(0,200,value=0,step=10,label='Nitidez (%)')
                        with gr.Row():
                            tile=gr.Slider(64,512,value=128,step=32,label='Bloco');pad=gr.Slider(0,64,value=16,step=4,label='Margem');device=gr.Radio(['cpu','cuda'],value='cpu',label='Dispositivo')
                    run=gr.Button('Gerar imagem',variant='primary',size='lg',elem_id='primary')
                with gr.Column(scale=6,min_width=330):
                    gallery=gr.Gallery(label='Resultado final',columns=2,format='png',height=410,type='filepath')
                    gallery_index = gr.State(0)
                    gallery.select(select_gallery_image, None, gallery_index, queue=False, api_name=False)
                    to_image_finish = gr.Button('Abrir imagem selecionada em Acabamento', size='sm')
                    download_zip=gr.File(label='Baixar imagens e parâmetros')
                    with gr.Accordion('Original e detalhes do job',open=False):
                        originals=gr.Gallery(label='Antes do pós-processamento',columns=2,format='png')
                        meta=gr.Textbox(label='Parâmetros e avisos',lines=8)
            generate = run.click(gerar,[prompt,neg,imgs,w,h,steps,cfg,seed,num,choices,weights,composite_scene,mask_file,feather,model,curated,modo,escala,tile,pad,device,nitidez],[gallery,originals,meta,download_zip],api_name='gerar', concurrency_id='gpu', concurrency_limit=1)
            generate.success(lambda: 0, None, gallery_index, queue=False, api_name=False)
        with gr.Tab('Editar região', id='regiao'):
            gr.Markdown('Branco na máscara define a área editável. O Qwen trabalha no recorte, e o restante da foto é preservado.')
            with gr.Row():
                with gr.Column():
                    with gr.Row():
                        region_source = gr.Image(type='filepath', format='png', label='Imagem original', sources=['upload'])
                        region_mask = gr.Image(type='filepath', format='png', label='Máscara em tons de cinza', sources=['upload'])
                    region_prompt = gr.Textbox(label='Alteração', placeholder='Troque a luminária por uma de latão.', lines=3)
                    with gr.Accordion('Ajustes do recorte', open=False):
                        region_size = gr.Dropdown(list(region.SIZES), value=768, label='Lado maior do recorte')
                        region_padding = gr.Slider(0, 256, value=96, step=8, label='Margem de contexto (px)')
                        region_feather = gr.Slider(0, 64, value=8, step=1, label='Suavização dentro da máscara (px)')
                        region_steps = gr.Slider(1, 80, value=40, step=1, label='Passos')
                        region_seed = gr.Number(value=-1, precision=0, label='Seed • -1 aleatório')
                    region_go = gr.Button('Editar área marcada', variant='primary')
                with gr.Column():
                    region_result = gr.Image(label='Foto editada', type='filepath', interactive=False)
                    region_file = gr.File(label='Baixar PNG')
                    with gr.Row():
                        region_to_finish = gr.Button('Abrir foto em Acabamento', size='sm')
                        region_compare = gr.Button('Comparar antes e depois', size='sm')
                    region_status = gr.Textbox(label='Detalhes', interactive=False)
            region_go.click(edit_region, [region_source, region_mask, region_prompt, region_size, region_padding,
                                           region_feather, region_steps, region_seed],
                            [region_result, region_file, region_status], api_name='editar_regiao',
                            concurrency_id='gpu', concurrency_limit=1)
        with gr.Tab('Vídeo', id='video'):
            with gr.Row():
                with gr.Column():
                    gr.Markdown('### Wan 2.2 · 5B\nClipes curtos a 24 FPS. No primeiro job, o Studio pode baixar cerca de 18 GB de pesos.')
                    video_mode = gr.Radio([wan.IMAGE_MODE, wan.TEXT_MODE], value=wan.IMAGE_MODE, label='Ferramenta')
                    video_image = gr.Image(type='filepath', sources=['upload'], label='Foto inicial')
                    video_prompt = gr.Textbox(lines=4, label='Cena e movimento',
                                             placeholder='Ex.: câmera se aproxima lentamente enquanto o vento move as folhas.')
                    with gr.Row():
                        video_size = gr.Dropdown(list(wan.SIZES), value=next(iter(wan.SIZES)), label='Proporção')
                        video_frames = gr.Dropdown(list(wan.FRAMES), value='33 quadros', label='Duração')
                    with gr.Accordion('Parâmetros avançados', open=False):
                        video_neg = gr.Textbox(label='Prompt negativo', value='flicker, artifacts, blurry, subtitles')
                        video_steps = gr.Slider(8, 30, value=20, step=1, label='Passos')
                        video_seed = gr.Number(value=-1, precision=0, label='Seed · -1 aleatória')
                    video_run = gr.Button('Gerar vídeo', variant='primary')
                with gr.Column():
                    video_preview = gr.Video(label='Resultado')
                    video_download = gr.File(label='Baixar saídas', file_count='multiple')
                    video_status = gr.Textbox(label='Estado do job', interactive=False)
                    to_clip_finish = gr.Button('Editar este clipe', size='sm')
                    gr.Button('Abrir histórico de workflows').click(
                        lambda: gr.Tabs(selected='workflows'), None, main_tabs, queue=False, api_name=False)
            video_mode.input(lambda mode: gr.update(visible=mode == wan.IMAGE_MODE), video_mode, video_image,
                             queue=False, api_name="video_opcoes")
            video_run.click(launch_wan, [video_mode, video_image, video_prompt, video_neg, video_size,
                                         video_frames, video_steps, video_seed],
                            [video_preview, video_download, video_status],
                            concurrency_id='gpu', concurrency_limit=1, api_name='gerar_video')
        with gr.Tab('OpenJutsu', id='openjutsu'):
            gr.Markdown('### Trocar personagem\nMiniMax H3 · worker ComfyUI local da classe de 96 GB.')
            with gr.Row():
                with gr.Column():
                    oj_video = gr.Video(sources=['upload'], label='Clipe de atuação')
                    oj_ref = gr.Image(type='filepath', sources=['upload'], label='Personagem de referência')
                    oj_anchor = gr.Image(type='filepath', sources=['upload'], label='Primeiro quadro pronto (opcional)')
                    with gr.Row():
                        oj_start = gr.Number(value=0, minimum=0, label='Início (s)')
                        oj_seconds = gr.Slider(5, 15, value=5, step=.1, label='Duração (s)')
                        oj_quality = gr.Dropdown([480, 768], value=480, label='Resolução')
                    oj_direction = gr.Textbox(label='Direção adicional')
                    oj_seed = gr.Number(value=-1, precision=0, label='Seed')
                    oj_submit = gr.Button('Trocar personagem', variant='primary')
                with gr.Column():
                    oj_result = gr.Video(label='Clipe final')
                    oj_files = gr.File(label='Baixar saídas', file_count='multiple')
                    oj_status = gr.Textbox(label='Estado do job', interactive=False)
            oj_submit.click(launch_openjutsu, [oj_video, oj_ref, oj_anchor, oj_start, oj_seconds,
                                             oj_quality, oj_direction, oj_seed], [oj_result, oj_files, oj_status],
                            api_name='openjutsu', concurrency_id='gpu', concurrency_limit=1)
        with gr.Tab('Acabamento', id='acabamento'):
            with gr.Row():
                with gr.Column(scale=2, min_width=270):
                    finish_image_mode = gr.Radio([finish.LOOK, finish.FRAME], value=finish.LOOK, label='Ferramenta')
                    with gr.Group() as look_options:
                        finish_look = gr.Dropdown(list(finish.LOOKS), value=finish.LOOKS[0], label='Look')
                        finish_strength = gr.Slider(0, 100, value=75, step=1, label='Intensidade (%)')
                    with gr.Group(visible=False) as frame_options:
                        finish_ratio = gr.Dropdown(list(finish.SIZES), value=next(iter(finish.SIZES)), label='Proporção')
                        finish_fit = gr.Radio(['Preencher', 'Manter imagem inteira'], value='Preencher', label='Encaixe')
                    finish_format = gr.Radio(list(finish.FORMATS), value='PNG', label='Formato')
                    finish_image_button = gr.Button('Aplicar', variant='primary')
                    finish_image_status = gr.Textbox(label='Resultado', interactive=False)
                with gr.Column(scale=5):
                    with gr.Row():
                        finish_image_input = gr.Image(type='filepath', sources=['upload'], label='Antes', height=300)
                        finish_image_output = gr.Image(type='filepath', label='Depois', height=300, interactive=False)
                    with gr.Row():
                        finish_image_download = gr.File(label='Baixar imagem')
                        finish_image_reframe = gr.Button('Enquadrar resultado', size='sm')
                        finish_image_animate = gr.Button('Animar esta imagem', size='sm')
            finish_image_mode.input(image_options, finish_image_mode, [look_options, frame_options],
                                    queue=False, api_name="acabamento_opcoes")
            finish_image_button.click(finish_image, [finish_image_input, finish_image_mode, finish_look,
                                     finish_strength, finish_ratio, finish_fit, finish_format],
                                     [finish_image_output, finish_image_download, finish_image_status],
                                     api_name='acabamento_imagem')
        with gr.Tab('Montagem', id='montagem'):
            with gr.Row():
                with gr.Column(scale=2, min_width=270):
                    finish_video_mode = gr.Radio([finish.CLIP, finish.STILL, finish.BOARD], value=finish.CLIP,
                                                 label='Ferramenta')
                    finish_start = gr.Number(label='Início ou ponto do quadro (s)', value=0, minimum=0)
                    finish_length = gr.Number(label='Duração do trecho (s)', value=5, minimum=.1, maximum=180)
                    with gr.Group() as clip_frame_options:
                        clip_ratio = gr.Dropdown(['Original', *finish.SIZES], value='Original', label='Proporção')
                        clip_fit = gr.Radio(['Preencher', 'Manter imagem inteira'], value='Preencher', label='Encaixe')
                        clip_mute = gr.Checkbox(label='Remover áudio')
                    finish_clip_button = gr.Button('Processar', variant='primary')
                    finish_clip_status = gr.Textbox(label='Resultado', interactive=False)
                with gr.Column(scale=5):
                    with gr.Row():
                        finish_video_input = gr.Video(sources=['upload'], label='Vídeo de entrada')
                        with gr.Column():
                            finish_video_output = gr.Video(label='Clipe final')
                            finish_clip_image = gr.Image(type='filepath', label='Quadro ou prancha', visible=False,
                                                         interactive=False)
                    with gr.Row():
                        finish_clip_download = gr.File(label='Baixar saída')
                        finish_clip_extract = gr.Button('Extrair quadro deste clipe', size='sm')
                        finish_clip_animate = gr.Button('Animar quadro ou prancha', size='sm')
            finish_video_mode.input(clip_options, finish_video_mode, [finish_length, clip_frame_options],
                                    queue=False, api_name="montagem_opcoes")
            finish_clip_button.click(finish_clip, [finish_video_input, finish_video_mode, finish_start,
                                    finish_length, clip_ratio, clip_fit, clip_mute],
                                    [finish_video_output, finish_clip_image, finish_clip_download, finish_clip_status],
                                    api_name='montagem_video')
        with gr.Tab('Sequência', id='sequencia'):
            with gr.Row():
                with gr.Column():
                    sequence_input = gr.File(label='Clipes • 2 a 8', file_count='multiple',
                                             file_types=['video'], type='filepath')
                    sequence_order = gr.Textbox(label='Ordem dos clipes', placeholder='Ex.: 2, 1, 3',
                                                info='Deixe em branco para seguir a lista de arquivos.')
                    sequence_ratio = gr.Dropdown(list(finish.SEQUENCE_SIZES), value='Paisagem · 16:9', label='Proporção')
                    sequence_fit = gr.Radio(['Preencher', 'Manter imagem inteira'],
                                            value='Manter imagem inteira', label='Encaixe')
                    sequence_mute = gr.Checkbox(label='Exportar sem áudio')
                    sequence_go = gr.Button('Montar sequência', variant='primary')
                with gr.Column():
                    sequence_result = gr.Video(label='Sequência final')
                    sequence_file = gr.File(label='Baixar MP4')
                    sequence_to_finish = gr.Button('Abrir sequência em Montagem', size='sm')
                    sequence_status = gr.Textbox(label='Detalhes', interactive=False)
            sequence_go.click(finish_sequence, [sequence_input, sequence_order, sequence_ratio, sequence_fit,
                                                sequence_mute], [sequence_result, sequence_file, sequence_status],
                              api_name='montar_sequencia')
        civ_workflow_button, civ_workflow_open, civ_workflow_inputs = cf_lab_ui.render(
            main_tabs, BASE / 'civitai' / 'lab', OUT, workflow_result, unload_qwen)
        with gr.Tab('Biblioteca'):
            gr.Markdown('### Componentes\nLoRAs selecionadas em Criar são baixadas ao iniciar o job. Você também pode preparar arquivos manualmente.')
            with gr.Row():
                with gr.Column():
                    gr.Markdown('#### Catálogo do projeto')
                    cat_search=gr.Textbox(label='Buscar por nome ou autor')
                    cat_select=gr.Dropdown(choices=list(CATALOGO_BY_ID),multiselect=True,label='LoRAs catalogadas',filterable=True)
                    cat_search.change(filtrar_catalogo,cat_search,cat_select)
                    cat_btn=gr.Button('Baixar selecionadas');cat_msg=gr.Textbox(label='Estado',interactive=False)
                    cat_btn.click(instalar_catalogo,cat_select,[cat_msg,choices])
                with gr.Column():
                    gr.Markdown('#### Importar ou baixar')
                    upload=gr.File(label='LoRA .safetensors',file_types=['.safetensors'],type='filepath');up=gr.Button('Importar arquivo');um=gr.Textbox(label='Resultado',interactive=False)
                    up.click(importar,upload,[um,choices])
                    link=gr.Textbox(label='Link Civitai ou Hugging Face',placeholder='Cole a URL da versão do arquivo')
                    token=gr.Textbox(type='password',label='Token avulso opcional • prevalece sobre o Secret desta fonte')
                    down=gr.Button('Baixar por link');dm=gr.Textbox(label='Resultado',interactive=False)
                    down.click(baixar,[link,token],[dm,choices,token]);gr.Button('Atualizar arquivos locais').click(atualizar,None,choices)
            gr.Markdown('Use links Civitai com `modelVersionId`. Arquivos e modelos têm licenças e requisitos próprios.')
        with gr.Tab('Histórico', id='historico') as history_tab:
            gr.Markdown('### Acervo de resultados\nEncontre as mídias produzidas no Studio e abra em outra ferramenta. '
                        'Use o Drive no Colab para guardar os resultados entre sessões.')
            with gr.Row():
                with gr.Column(scale=2):
                    hist_kind = gr.Radio(history.TYPES, value='Todas', label='Tipo de mídia')
                    hist_query = gr.Textbox(label='Busca', placeholder='Ex.: Qwen, sequência, seed, trecho do prompt')
                    hist_reload = gr.Button('Buscar e atualizar', variant='primary')
                    hist_list = gr.Dropdown(label='Resultados recentes', filterable=True)
                    hist_count = gr.Markdown()
                    with gr.Accordion('Detalhes da saída', open=False):
                        hist_meta = gr.Textbox(label='Parâmetros ou origem', lines=6, interactive=False)
                with gr.Column(scale=3):
                    hist_img = gr.Image(label='Imagem', interactive=False, visible=False)
                    hist_video = gr.Video(label='Vídeo', interactive=False, visible=False)
                    hist_audio = gr.Audio(label='Áudio', interactive=False, visible=False)
                    hist_download = gr.File(label='Baixar mídia')
                    with gr.Row(visible=False) as hist_image_actions:
                        hist_finish = gr.Button('Acabamento', size='sm')
                        hist_animate = gr.Button('Animar foto', size='sm')
                        hist_image_upscale = gr.Button('Upscale SeedVR2', size='sm')
                        hist_compare = gr.Button('Comparar original e final', size='sm', visible=False)
                    with gr.Row(visible=False) as hist_video_actions:
                        hist_cut = gr.Button('Abrir em Montagem', size='sm')
                        hist_video_upscale = gr.Button('Upscale SeedVR2', size='sm')
            hist_reload.click(list_history, [hist_kind, hist_query], [hist_list, hist_count], api_name="historico_listar")
            for event in (history_tab.select, hist_kind.input, hist_query.submit):
                event(list_history, [hist_kind, hist_query], [hist_list, hist_count], api_name=False)
            hist_list.change(history_preview, hist_list, [hist_img, hist_video, hist_audio, hist_download,
                             hist_meta, hist_image_actions, hist_video_actions, hist_compare], api_name="historico_abrir")
        with gr.Tab('Comparar', id='comparar'):
            gr.Markdown('### Antes e depois\nArraste a divisão para inspecionar as diferenças. '
                        'As prévias usam a proporção da segunda imagem, com margens quando necessário.')
            with gr.Row():
                with gr.Column():
                    with gr.Row():
                        compare_before = gr.Image(type='filepath', image_mode=None, label='Antes', sources=['upload'])
                        compare_after = gr.Image(type='filepath', image_mode=None, label='Depois', sources=['upload'])
                    compare_go = gr.Button('Comparar imagens', variant='primary')
                with gr.Column():
                    compare_slider = gr.ImageSlider(label='Antes / depois', interactive=False, format='png')
                    compare_file = gr.File(label='Baixar prancha lado a lado')
                    compare_status = gr.Textbox(label='Dimensões', interactive=False)
            compare_outputs = [compare_slider, compare_file, compare_status]
            compare_go.click(compare_images, [compare_before, compare_after], compare_outputs,
                             api_name='comparar_imagens')
        with gr.Tab('Upscale rápido', id='upscale-rapido'):
            mfile=gr.File(label='Imagem',file_types=['image'],type='filepath');mmode=gr.Dropdown(choices=['Nenhum','Lanczos (rápido, sem IA)']+list(UP_MODELS),value='RealESRGAN_x4plus (fotografia)',label='Método')
            with gr.Row():
                mscale=gr.Slider(1,4,value=2,step=.5,label='Escala');mtile=gr.Slider(64,512,value=128,step=32,label='Bloco');mpad=gr.Slider(0,64,value=16,step=4,label='Margem')
            with gr.Row():mdev=gr.Radio(['cpu','cuda'],value='cpu',label='Dispositivo');msharp=gr.Slider(0,200,value=0,step=10,label='Nitidez')
            mgo=gr.Button('Aplicar upscale',variant='primary');mresult=gr.Image(label='Imagem final',type='filepath');mlog=gr.Textbox(label='Resultado')
            mgo.click(pos_manual,[mfile,mmode,mscale,mtile,mpad,mdev,msharp],[mresult,mlog], concurrency_id='gpu', concurrency_limit=1)

        with gr.Tab('Upscale SeedVR2', id='seedvr2'):
            inp = gr.File(label='Mídia', type='filepath', file_types=['image', 'video'])
            with gr.Row():
                kind = gr.Radio(['Imagem', 'Vídeo'], value='Imagem', label='Tipo')
                model = gr.Dropdown(list(seedvr2.PROFILES), value=seedvr2.DEFAULT, label='Modelo')
                scale = gr.Slider(1, 4, value=2, step=.25, label='Escala')
            gr.Markdown('Vídeo: até 2 s e 24 quadros. Os pesos são baixados sob demanda. Se faltar VRAM no 7B, o job tenta o 3B INT8 uma vez na mesma escala.')
            with gr.Accordion('Opções avançadas', open=False):
                seed = gr.Number(value=42, precision=0, label='Seed')
                tile = gr.Dropdown([256, 384, 512], value=seedvr2.DEFAULT_TILE, label='Tile do VAE')
            execute_seed = gr.Button('Aplicar upscale', variant='primary')
            upscale_image = gr.Image(label='Imagem final', type='filepath')
            upscale_video = gr.Video(label='Vídeo final')
            download_upscale = gr.File(label='Baixar resultado')
            upscale_status = gr.Textbox(label='Estado do job', interactive=False)
            outputs = [upscale_image, upscale_video, download_upscale, upscale_status]
            execute_seed.click(launch_seedvr2, [inp, kind, model, scale, seed, tile], outputs,
                               api_name='seedvr2', concurrency_id='gpu', concurrency_limit=1)
            with gr.Accordion('Reabrir resultado ou retomar coleta', open=False):
                past_seedvr2 = gr.Dropdown(label='Upscales anteriores')
                gr.Button('Atualizar lista').click(list_seedvr2_jobs, None, past_seedvr2)
                gr.Button('Abrir job').click(reopen_seedvr2, past_seedvr2, outputs,
                                             concurrency_id='gpu', concurrency_limit=1)
        with gr.Tab('Workflows', id='workflows'):
            gr.Markdown('### Workflows avançados\nImporte um grafo da API do ComfyUI ou baixe uma referência visual.')
            with gr.Accordion('Grafos originais para ComfyUI', open=False):
                gr.Markdown('As referências visuais usam dependências próprias. Abra o arquivo no ComfyUI para revisar os nós e modelos.')
                family = gr.Radio(list(ORIGINALS), value=next(iter(ORIGINALS)), label='Finalidade')
                variants = next(iter(ORIGINALS.values()))
                original = gr.Dropdown(variants, value=variants[0][1], label='Versão de referência')
                wfout = gr.File(label='Arquivo visual')
                family.input(original_choices, family, [original, wfout], queue=False, api_name=False)
                gr.Button('Baixar grafo original').click(original_download, original, wfout, api_name=False)
            with gr.Accordion('Arquivos baixados do Civitai', open=False):
                civ_file = gr.Dropdown(label='Arquivo')
                civ_download = gr.File(label='Abrir ou baixar')
                gr.Button('Atualizar lista').click(
                    lambda: gr.update(choices=downloaded_workflows(), value=None), None, civ_file, api_name=False)
                gr.Button('Abrir arquivo').click(open_civitai_workflow, civ_file, civ_download, api_name=False)
            with gr.Accordion('Executar API JSON no ComfyUI local',open=False):
                wf = gr.File(file_types=['.json'], type='filepath', label='Workflow API JSON')
                civ_workflow_button.click(civ_workflow_open, civ_workflow_inputs, [main_tabs, wf], api_name=False)
                wm = gr.File(type='filepath', file_count='multiple', file_types=['image', 'video', 'audio'],
                             label='Mídias de entrada (opcional)')
                gr.Markdown('Anexe arquivos com os mesmos nomes usados nos nós nativos de entrada do grafo.')
                server = gr.Textbox(value=seedvr2.SERVER, label='Servidor local', interactive=False)
                go = gr.Button('Executar workflow', variant='primary')
                wg = gr.Gallery(label='Imagens')
                with gr.Row():
                    wv = gr.Video(label='Primeiro vídeo')
                    wa = gr.Audio(label='Primeiro áudio', type='filepath')
                wd = gr.File(label='Baixar saídas', file_count='multiple')
                wl = gr.Textbox(label='Estado do job', lines=4, interactive=False)
                workflow_outputs = [wg, wv, wa, wd, wl]
                go.click(api_workflow, [wf, server, wm], workflow_outputs, api_name='executar_workflow',
                         concurrency_id='gpu', concurrency_limit=1)
                with gr.Accordion('Histórico e retomada de workflows', open=False):
                    old_workflows = gr.Dropdown(label='Workflows anteriores')
                    gr.Button('Atualizar lista').click(list_workflow_jobs, None, old_workflows)
                    gr.Button('Abrir ou retomar coleta').click(
                        reopen_workflow, old_workflows, workflow_outputs, concurrency_id='gpu', concurrency_limit=1)
        with gr.Tab('Configurações e diagnóstico'):
            gr.Markdown('### Ambiente\nOs Secrets são carregados no Colab antes de iniciar esta interface. Os valores não aparecem aqui.')
            env_status=gr.Textbox(value=ambiente,label='Estado local',interactive=False,lines=3)
            gr.Button('Atualizar diagnóstico').click(ambiente,None,env_status)
            gr.Markdown("""**Hugging Face:** use o Secret `HF_TOKEN`. **Civitai:** use `CIVITAI_TOKEN`. Modelos públicos podem funcionar sem eles.\n\n**Armazenamento:** ative o Drive na célula indicada se quiser preservar arquivos.\n\n**T4:** a aba Criar começa em 768×768, uma imagem e NF4 carregado direto na GPU. A sondagem usa 512×512. O offload é opcional e usa RAM do sistema.\n\n**SeedVR2:** usa ComfyUI no mesmo Colab. Os jobs e resultados ficam no diretório de saída do Studio.""")

    for button, entry in zip(card_buttons, APP_CARDS):
        target, preset = entry[-2:]
        if target == 'criar':
            button.click(partial(open_image_tool, preset), prompt, [main_tabs, image_tool_help, prompt],
                         queue=False, api_name=False)
        elif target == 'video':
            button.click(partial(open_video_tool, preset), None, [main_tabs, video_mode, video_image],
                         queue=False, api_name=False)
        elif target == 'acabamento':
            button.click(partial(open_finish_tool, target, preset), None,
                         [main_tabs, finish_image_mode, look_options, frame_options], queue=False, api_name=False)
        elif target == 'montagem':
            button.click(partial(open_finish_tool, target, preset), None,
                         [main_tabs, finish_video_mode, finish_length, clip_frame_options], queue=False, api_name=False)
        else:
            button.click(partial(select_tool_tab, target), None, main_tabs, queue=False, api_name=False)

    finish_image_route = [main_tabs, finish_image_mode, look_options, frame_options, finish_image_input]
    finish_video_route = [main_tabs, finish_video_mode, finish_length, clip_frame_options,
                          finish_video_input, finish_start]
    region_to_finish.click(partial(send_to_finish, 'acabamento', finish.LOOK), region_result,
                           finish_image_route, queue=False, api_name=False)
    sequence_to_finish.click(partial(send_to_finish, 'montagem', finish.CLIP), sequence_result,
                             finish_video_route, queue=False, api_name=False)
    to_image_finish.click(finish_gallery, [gallery, gallery_index], finish_image_route, queue=False, api_name=False)
    compare_route = [main_tabs, compare_before, compare_after, *compare_outputs]
    region_compare.click(open_comparison, [region_source, region_result], compare_route, queue=False, api_name=False)
    for button, destination, route in (
        (hist_finish, 'acabamento', finish_image_route),
        (hist_cut, 'montagem', finish_video_route),
        (hist_animate, 'video', [main_tabs, video_mode, video_image]),
        (hist_image_upscale, 'seedvr2', [main_tabs, inp, kind]),
        (hist_video_upscale, 'seedvr2', [main_tabs, inp, kind]),
        (hist_compare, 'comparar', compare_route),
    ):
        button.click(partial(history_route, destination), hist_list, route, queue=False, api_name=False)
    to_clip_finish.click(partial(send_to_finish, 'montagem', finish.CLIP), video_preview, finish_video_route,
                         queue=False, api_name=False)
    finish_clip_extract.click(partial(send_to_finish, 'montagem', finish.STILL), finish_video_output,
                              finish_video_route, queue=False, api_name=False)
    finish_image_reframe.click(partial(send_to_finish, 'acabamento', finish.FRAME), finish_image_output,
                               finish_image_route, queue=False, api_name=False)
    for button, media in ((finish_image_animate, finish_image_output), (finish_clip_animate, finish_clip_image)):
        button.click(animate_image, media, [main_tabs, video_mode, video_image], queue=False, api_name=False)

demo.queue(default_concurrency_limit=1)
import secrets
import threading
from starlette.middleware import Middleware
from cf_portal import PortalAPI, let_studio_answer_cors

GRADIO_USUARIO = 'clonfield'
GRADIO_SENHA = os.environ.get('CLONFIELD_PASSWORD') or secrets.token_urlsafe(16)
public = '--local' not in sys.argv
phase('abrindo_tunel_publico' if public else 'abrindo_servidor_local')
workflows.clear_orphans()
let_studio_answer_cors()
print('Iniciando Gradio...', flush=True)
try:
    demo.launch(share=public, server_name='127.0.0.1', inline=False, inbrowser=False,
                auth=(GRADIO_USUARIO, GRADIO_SENHA), prevent_thread_lock=True,
                show_error=True, enable_monitoring=False, allowed_paths=[str(OUT.resolve())],
                app_kwargs={"middleware": [Middleware(PortalAPI, username=GRADIO_USUARIO, password=GRADIO_SENHA,
                                                        engine_paths=(BASE, OUT))]})
    if demo.share_url:
        print('LINK PÚBLICO: ' + demo.share_url, flush=True)
        print('STUDIO: ' + demo.share_url.rstrip('/') + '/studio/', flush=True)
        if os.environ.get('CLONFIELD_FRONT'):
            print('PAINEL PÚBLICO: ' + os.environ['CLONFIELD_FRONT'].rstrip('/') + '/?api=' + demo.share_url.rstrip('/'), flush=True)
    elif public:
        print('O túnel público falhou. Use o link do Colab se estiver no notebook.', flush=True)
    print(f'SENHA DA SESSÃO: {GRADIO_SENHA}', flush=True)
    phase('interface_pronta')
    print(f'CLONFIELD_READY {demo.server_port}', flush=True)
    threading.Event().wait()
finally:
    demo.close()
