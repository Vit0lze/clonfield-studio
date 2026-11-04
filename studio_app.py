# 3. Iniciar ClonField Studio. Nenhum modelo é carregado até clicar em Gerar.
print('ClonField: iniciando processo da interface...', flush=True)
import os, sys, json, time, uuid, random, shutil, traceback, subprocess, socket
from pathlib import Path
from functools import partial
import unicodedata
from urllib.parse import urlparse, parse_qs
import requests, torch, gradio as gr
from PIL import Image, ImageFilter
import numpy as np
import zipfile

BASE=Path(os.environ.get('CLONFIELD_DIR','/content/ClonField_Lab'))
LORAS=BASE/'loras'; OUT=BASE/'outputs'
for p in (LORAS, OUT): p.mkdir(parents=True,exist_ok=True)
pipe=None; loaded=[]; current_config=None
QWEN_DEFAULT = 'Qwen/Qwen-Image-2.1'
QWEN_TURBO = 'Qwen/Qwen-Image-2.1-Turbo'
SEEDVR2_POST = 'SeedVR2 INT8'
CATALOGO = [{'repo': 'Viggle/Qwen-Image-2.1-viggle-turbo', 'revision': '009a44a895ef85f7e643c80fdca9543795248867', 'file': 'Qwen-Image-2.1-viggle-turbo-4step-lora-r64.safetensors'}, {'repo': 'Viggle/Qwen-Image-2.1-viggle-turbo', 'revision': '009a44a895ef85f7e643c80fdca9543795248867', 'file': 'Qwen-Image-2.1-viggle-turbo-v0.2-5step-lora-r128.safetensors'}, {'repo': 'Viggle/Qwen-Image-2.1-viggle-turbo', 'revision': '009a44a895ef85f7e643c80fdca9543795248867', 'file': 'Qwen-Image-2.1-viggle-turbo-v0.2-5step-lora-r256.safetensors'}, {'repo': 'Viggle/Qwen-Image-2.1-viggle-turbo', 'revision': '009a44a895ef85f7e643c80fdca9543795248867', 'file': 'Qwen-Image-2.1-viggle-turbo-v0.2.1-6step-lora-r128.safetensors'}, {'repo': 'Viggle/Qwen-Image-2.1-viggle-turbo', 'revision': '009a44a895ef85f7e643c80fdca9543795248867', 'file': 'Qwen-Image-2.1-viggle-turbo-v0.2.1-6step-lora-r256.safetensors'}, {'repo': 'Viggle/Qwen-Image-2.1-viggle-turbo', 'revision': '009a44a895ef85f7e643c80fdca9543795248867', 'file': 'Qwen-Image-2.1-viggle-turbo-v0.3-6step-lora-r128.safetensors'}, {'repo': 'Viggle/Qwen-Image-2.1-viggle-turbo', 'revision': '009a44a895ef85f7e643c80fdca9543795248867', 'file': 'Qwen-Image-2.1-viggle-turbo-v0.3-6step-lora-r256.safetensors'}, {'repo': 'Alissonerdx/BFS-Best-Face-Swap', 'revision': '0ca3913ade4b4ada458d60c232354e8586c4c181', 'file': 'bfs_body_swap_v1.0_qwen_2.1.safetensors'}, {'repo': 'Alissonerdx/BFS-Best-Face-Swap', 'revision': '0ca3913ade4b4ada458d60c232354e8586c4c181', 'file': 'bfs_head_swap_v1_ltx2_ic_lora_12000_train_3.safetensors'}, {'repo': 'Alissonerdx/BFS-Best-Face-Swap', 'revision': '0ca3913ade4b4ada458d60c232354e8586c4c181', 'file': 'bfs_head_swap_v1_ltx2_ic_lora_5000.safetensors'}, {'repo': 'Alissonerdx/BFS-Best-Face-Swap', 'revision': '0ca3913ade4b4ada458d60c232354e8586c4c181', 'file': 'bfs_head_swap_v1_ltx2_ic_lora_6000.safetensors'}, {'repo': 'Alissonerdx/BFS-Best-Face-Swap', 'revision': '0ca3913ade4b4ada458d60c232354e8586c4c181', 'file': 'bfs_head_v1.1_alternative_qwen_2.1.safetensors'}, {'repo': 'Alissonerdx/BFS-Best-Face-Swap', 'revision': '0ca3913ade4b4ada458d60c232354e8586c4c181', 'file': 'bfs_head_v1.1_qwen_2.1.safetensors'}, {'repo': 'Alissonerdx/BFS-Best-Face-Swap', 'revision': '0ca3913ade4b4ada458d60c232354e8586c4c181', 'file': 'bfs_head_v1_qwen_2.1.safetensors'}, {'repo': 'Comfy-Org/SCAIL-2', 'revision': 'fe3c728bc793ba21ca674688f822afb709ad44fb', 'file': 'loras/wan2.1_SCAIL_2_DPO_lora_bf16.safetensors'}, {'repo': 'Comfy-Org/SCAIL-2', 'revision': 'fe3c728bc793ba21ca674688f822afb709ad44fb', 'file': 'loras/wan2.1_SCAIL_2_relight_lora_bf16.safetensors'}, {'repo': 'Comfy-Org/Krea-2', 'revision': '588feaf955b08b9ac4723eeb751752ab045dba71', 'file': 'loras/krea2_darkbrush.safetensors'}, {'repo': 'Comfy-Org/Krea-2', 'revision': '588feaf955b08b9ac4723eeb751752ab045dba71', 'file': 'loras/krea2_dotmatrix.safetensors'}, {'repo': 'Comfy-Org/Krea-2', 'revision': '588feaf955b08b9ac4723eeb751752ab045dba71', 'file': 'loras/krea2_kidsdrawing.safetensors'}, {'repo': 'Comfy-Org/Krea-2', 'revision': '588feaf955b08b9ac4723eeb751752ab045dba71', 'file': 'loras/krea2_neondrip.safetensors'}, {'repo': 'Comfy-Org/Krea-2', 'revision': '588feaf955b08b9ac4723eeb751752ab045dba71', 'file': 'loras/krea2_rainywindow.safetensors'}, {'repo': 'Comfy-Org/Krea-2', 'revision': '588feaf955b08b9ac4723eeb751752ab045dba71', 'file': 'loras/krea2_retroanime.safetensors'}, {'repo': 'Comfy-Org/Krea-2', 'revision': '588feaf955b08b9ac4723eeb751752ab045dba71', 'file': 'loras/krea2_softwatercolor.safetensors'}, {'repo': 'Comfy-Org/Krea-2', 'revision': '588feaf955b08b9ac4723eeb751752ab045dba71', 'file': 'loras/krea2_style_reference.safetensors'}, {'repo': 'Comfy-Org/Krea-2', 'revision': '588feaf955b08b9ac4723eeb751752ab045dba71', 'file': 'loras/krea2_sunsetblur.safetensors'}, {'repo': 'Comfy-Org/Krea-2', 'revision': '588feaf955b08b9ac4723eeb751752ab045dba71', 'file': 'loras/krea2_turbo_lora_rank_64_bf16.safetensors'}, {'repo': 'Comfy-Org/Krea-2', 'revision': '588feaf955b08b9ac4723eeb751752ab045dba71', 'file': 'loras/krea2_vintagetarot.safetensors'}]
CATALOGO_BY_ID = {f"{r['repo']} :: {r['file']}":r for r in CATALOGO}


def unload_qwen():
    global pipe, loaded, current_config
    if pipe is None:
        return
    import gc
    old = pipe
    pipe, loaded, current_config = None, [], None
    try:
        if hasattr(old, 'remove_all_hooks'):
            old.remove_all_hooks()
    finally:
        del old
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()


def model_defaults(model):
    if model == QWEN_TURBO:
        return 8, 1
    if model == QWEN_DEFAULT:
        return 40, 1
    return gr.skip(), gr.skip()


def phase(name):
    print(f"CLONFIELD_PHASE {name}", flush=True)


def qwen_memory(stage):
    try:
        rss = next(line.split()[1] for line in Path('/proc/self/status').read_text().splitlines()
                   if line.startswith('VmRSS:'))
        available = next(line.split()[1] for line in Path('/proc/meminfo').read_text().splitlines()
                         if line.startswith('MemAvailable:'))
        cpu = f'RAM do processo {int(rss) / 1024**2:.1f} GiB · RAM disponível {int(available) / 1024**2:.1f} GiB'
    except (OSError, ValueError, StopIteration):
        cpu = 'RAM indisponível'
    try:
        free, total = torch.cuda.mem_get_info(0)
        gpu = f'VRAM livre {free / 1024**3:.1f}/{total / 1024**3:.1f} GiB'
    except (OSError, RuntimeError):
        gpu = 'VRAM indisponível'
    print(f'Qwen · {stage} · {cpu} · {gpu}', flush=True)


def iniciar(model, quant, offload):
    global pipe, loaded, current_config
    if not torch.cuda.is_available():
        raise gr.Error('GPU não encontrada. Ative GPU no Colab e reinicie a sessão.')
    wanted = (model, bool(quant), bool(offload))
    if pipe is not None and current_config == wanted:
        return f'Modelo em memória: {model}'
    unload_qwen()

    phase('qwen_import')
    try:
        from diffusers import QwenImage21Pipeline
        from diffusers.quantizers import PipelineQuantizationConfig

        dtype = torch.bfloat16 if torch.cuda.is_bf16_supported(including_emulation=False) else torch.float16
        kwargs = {'dtype': dtype, 'token': os.environ.get('HF_TOKEN') or None,
                  'low_cpu_mem_usage': True}
        if not offload:
            # Envia os componentes à GPU durante o carregamento. Evita mover a pipeline inteira depois.
            kwargs['device_map'] = 'cuda'
        if quant:
            kwargs['quantization_config'] = PipelineQuantizationConfig(
                quant_backend='bitsandbytes_4bit',
                quant_kwargs={'load_in_4bit': True, 'bnb_4bit_quant_type': 'nf4',
                              'bnb_4bit_compute_dtype': dtype, 'bnb_4bit_use_double_quant': True},
                components_to_quantize=['transformer', 'text_encoder'],
            )
        qwen_memory(f'carregando componentes (dtype {dtype}, NF4 {bool(quant)})')
        phase('qwen_from_pretrained')
        p = QwenImage21Pipeline.from_pretrained(model, **kwargs)
        phase('qwen_components_ready')
        qwen_memory('componentes carregados')
        if offload:
            qwen_memory('ativando offload para CPU')
            phase('qwen_cpu_offload')
            p.enable_model_cpu_offload()
        phase('qwen_vae_setup')
        p.vae.enable_slicing()
        p.vae.enable_tiling()
        pipe, loaded, current_config = p, [], wanted
        phase('qwen_ready')
        qwen_memory('pipeline pronta')
        return f'Carregado: {model}'
    except Exception as e:
        if isinstance(e, torch.cuda.OutOfMemoryError):
            phase('cuda_oom')
        traceback.print_exc()
        raise gr.Error(f'Falha ao carregar o Qwen: {e}. Veja a etapa e a memória no log do Colab.') from e

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


UP_MODELS={
    'RealESRGAN_x4plus (fotografia)': ('RealESRGAN_x4plus.pth','https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.0/RealESRGAN_x4plus.pth'),
    'RealESRGAN anime 6B (desenho)': ('RealESRGAN_x4plus_anime_6B.pth','https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.2.4/RealESRGAN_x4plus_anime_6B.pth'),
}
def baixar_upscaler(nome):
    from spandrel import ModelLoader, ImageModelDescriptor
    filename,url=UP_MODELS[nome]; directory=BASE/'upscalers'; directory.mkdir(exist_ok=True)
    weight=directory/filename
    if not weight.exists():
        part=weight.with_suffix('.part')
        try:
            with requests.get(url,stream=True,timeout=(30,180)) as r:
                r.raise_for_status()
                with open(part,'wb') as f:
                    for chunk in r.iter_content(1024*1024):
                        if chunk: f.write(chunk)
            os.replace(part,weight)
        finally:
            if part.exists(): part.unlink()
    model=ModelLoader().load_from_file(str(weight))
    if not isinstance(model, ImageModelDescriptor): raise ValueError('O arquivo não é um upscaler de imagem suportado.')
    return model

def upscale_ia(im, nome, scale, tile, pad, device):
    # Overlap/crop evita bordas visíveis e mantém o pico de VRAM controlado.
    model=None
    try:
        model=baixar_upscaler(nome).to(device).eval()
        native=int(model.scale); w,h=im.size; tile=int(tile); pad=int(pad)
        rgb=np.asarray(im.convert('RGB'),dtype=np.float32)/255.0
        result=Image.new('RGB',(w*native,h*native))
        with torch.inference_mode():
            for y in range(0,h,tile):
                for x in range(0,w,tile):
                    x2=min(x+tile,w); y2=min(y+tile,h)
                    left=max(0,x-pad); top=max(0,y-pad); right=min(w,x2+pad); bottom=min(h,y2+pad)
                    arr=np.ascontiguousarray(rgb[top:bottom,left:right])
                    t=torch.from_numpy(arr).permute(2,0,1).unsqueeze(0).to(device)
                    out=model(t).clamp(0,1)[0].permute(1,2,0).cpu().numpy()
                    patch=Image.fromarray((out*255.0+0.5).astype(np.uint8),'RGB')
                    patch=patch.crop(((x-left)*native,(y-top)*native,(x2-left)*native,(y2-top)*native))
                    result.paste(patch,(x*native,y*native))
                    del t,out,patch
        size=(int(round(w*float(scale))),int(round(h*float(scale))))
        if result.size!=size: result=result.resize(size,Image.Resampling.LANCZOS)
        if 'A' in im.getbands(): result.putalpha(im.getchannel('A').resize(size,Image.Resampling.LANCZOS))
        return result
    finally:
        if model is not None: del model
        if torch.cuda.is_available(): torch.cuda.empty_cache()

def postprocessar(im, modo, escala, tile, pad, device, nitidez):
    if modo=='Nenhum': out=im.copy()
    elif modo=='Lanczos (rápido, sem IA)':
        out=im.resize((round(im.width*escala),round(im.height*escala)),Image.Resampling.LANCZOS)
    else:
        out=upscale_ia(im,modo,escala,tile,pad,device)
    if nitidez>0:
        # Filtro atua apenas no RGB, preservando canal alfa.
        alpha=out.getchannel('A') if 'A' in out.getbands() else None
        out=out.convert('RGB').filter(ImageFilter.UnsharpMask(radius=1.2,percent=int(nitidez),threshold=3))
        if alpha is not None: out.putalpha(alpha)
    return out

def pos_manual(file, modo, escala, tile, pad, device, nitidez):
    if not file: raise gr.Error('Envie uma imagem primeiro.')
    try:
        with Image.open(file) as src: im=src.copy()
        out=postprocessar(im,modo,escala,int(tile),int(pad),device,nitidez)
        path=OUT/('upscale_manual_'+uuid.uuid4().hex[:10]+'.png'); out.save(path)
        return str(path),f'Salvo: {path} | {im.width}×{im.height} → {out.width}×{out.height}'
    except Exception as e:
        traceback.print_exc(); raise gr.Error(f'Falhou o pós-processamento: {e}. Se faltou VRAM, selecione CPU ou blocos menores.')

def gerar(prompt, negative, files, width, height, steps, cfg, seed, nimgs, choices, weights, transparent, kv_cache, sigmas, modo, escala, tile, pad, device, nitidez, model, quant, offload, curated, composite_scene, mask_file, feather, progress=gr.Progress()):
    global loaded, pipe
    if not prompt or not prompt.strip(): raise gr.Error('Escreva um prompt.')
    try: vals_pre=[float(x.strip()) for x in (weights or '').split(',') if x.strip()]
    except ValueError: raise gr.Error('Pesos das LoRAs precisam ser números separados por vírgula.')
    if any(not -2 <= x <= 2 for x in vals_pre): raise gr.Error('Use pesos entre -2 e 2.')
    if bool(composite_scene) != bool(mask_file): raise gr.Error('Para composição, envie a cena e a máscara juntas.')
    if len(files or []) + bool(composite_scene)>10: raise gr.Error('Máximo de 10 imagens de referência, incluindo a cena da composição.')
    if composite_scene:
        from PIL import ImageOps
        with Image.open(composite_scene) as im: scene_size=ImageOps.exif_transpose(im).size
        with Image.open(mask_file) as im: mask_size=ImageOps.exif_transpose(im).size
        if scene_size != mask_size: raise gr.Error('A máscara precisa ter a mesma largura e altura da cena.')
    progress(0,desc='Preparando modelo e componentes sob demanda…')
    iniciar(model,quant,offload)
    if curated:
        progress(0.10,desc='Baixando LoRAs selecionadas…')
        try: baixar_catalogo(curated)
        except Exception as e: raise gr.Error('Falha ao baixar uma LoRA do catálogo. Confira acesso, conexão e espaço disponível.')
        choices=list(dict.fromkeys((choices or [])+[Path(CATALOGO_BY_ID[k]['file']).name for k in curated]))
    progress(0.2,desc='Modelo preparado; iniciando geração…')
    try:
        if loaded:
            if hasattr(pipe,'unload_lora_weights'): pipe.unload_lora_weights()
            else:
                for name in loaded: pipe.transformer.delete_adapters(name)
            loaded=[]
        vals=[float(x.strip()) for x in weights.split(',') if x.strip()]
        for i,name in enumerate(choices or []):
            path=LORAS/Path(name).name; adapter=f'lora_{i}'
            if hasattr(pipe,'load_lora_weights'): pipe.load_lora_weights(str(path.parent),weight_name=path.name,adapter_name=adapter)
            elif hasattr(pipe.transformer,'load_lora_adapter'): pipe.transformer.load_lora_adapter(str(path.parent),weight_name=path.name,adapter_name=adapter,prefix=None)
            else: raise ValueError('Esta versão do Diffusers não oferece carregamento de LoRA para este pipeline.')
            loaded.append(adapter)
        if loaded:
            scales=[vals[i] if i<len(vals) else 1.0 for i in range(len(loaded))]
            if hasattr(pipe,'set_adapters'): pipe.set_adapters(loaded,adapter_weights=scales)
            else: pipe.transformer.set_adapters(loaded,weights=scales)
        refs=[]
        if composite_scene:
            from PIL import ImageOps
            with Image.open(composite_scene) as im: refs.append(ImageOps.exif_transpose(im).convert('RGB').copy())
        for f in files or []:
            with Image.open(f) as im: refs.append(im.convert('RGB').copy())
        if transparent: prompt='This is an RGBA image with transparency. '+prompt+' The image has alpha channel and the background is transparent.'
        seed=int(seed); seed=random.randrange(0,2**32-1) if seed<0 else seed
        paths=[]; originais=[]; report=[]; meta={'prompt':prompt,'negative_prompt':negative,'seed':seed,'width':int(width),'height':int(height),'steps':int(steps),'true_cfg_scale':cfg,'loras':choices,'weights':weights,'references':len(refs),'kv_cache':kv_cache,'sigmas':sigmas,'upscale':modo,'escala':escala,'bloco':tile,'margem':pad,'dispositivo_upscale':device,'nitidez':nitidez,'modelo':model,'quantizado_4bit':quant,'offload_cpu':offload,'catalogo_loras':curated,'composicao_mascara':bool(mask_file),'borda_suave':feather}
        for i in range(int(nimgs)):
            args=dict(prompt=prompt,width=int(width),height=int(height),num_inference_steps=int(steps),true_cfg_scale=float(cfg),generator=torch.Generator('cpu').manual_seed(seed+i))
            args['use_kv_cache']=kv_cache
            if sigmas.strip():
                values=[float(v.strip()) for v in sigmas.split(',') if v.strip()]
                if not values or any(v<0 or v>1 for v in values) or any(a<=b for a,b in zip(values,values[1:])): raise ValueError('Sigmas devem estar entre 0 e 1, em ordem decrescente, separados por vírgulas.')
                args['sigmas']=values
            if negative.strip() and cfg>1: args['negative_prompt']=negative
            if refs: args['image']=refs if len(refs)>1 else refs[0]
            total_steps=len(values) if sigmas.strip() else int(steps)
            def report_step(_pipe, step, timestep, kwargs):
                if step == 0:
                    phase('qwen_first_step')
                if step + 1 == total_steps:
                    phase('qwen_decode')
                progress(min(0.9, 0.2 + 0.7 * (i + (step+1)/max(total_steps,1)) / int(nimgs)), desc=f'Imagem {i+1}/{int(nimgs)} · passo {step+1}/{total_steps}')
                return kwargs
            args['callback_on_step_end']=report_step
            phase('qwen_encode_and_first_step')
            img=pipe(**args).images[0]
            phase('qwen_image_ready')
            if composite_scene:
                from PIL import ImageOps
                with Image.open(composite_scene) as source: background=ImageOps.exif_transpose(source).convert('RGB')
                with Image.open(mask_file) as source: mask=ImageOps.exif_transpose(source).convert('L')
                if mask.size != background.size: raise ValueError('A máscara precisa ter a mesma largura e altura da cena.')
                if feather>0: mask=mask.filter(ImageFilter.GaussianBlur(radius=float(feather)))
                img=Image.composite(img.convert('RGB').resize(background.size,Image.Resampling.LANCZOS),background,mask)
            path=OUT/(time.strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:8]+'.png'); img.save(path)
            originais.append(str(path)); final=path
            if modo != SEEDVR2_POST and (modo != 'Nenhum' or nitidez > 0):
                progress(0.92,desc='Aplicando pós-processamento…')
                try:
                    img_final=postprocessar(img,modo,float(escala),int(tile),int(pad),device,nitidez)
                    final=path.with_name(path.stem+'_final.png'); img_final.save(final)
                except Exception as e:
                    traceback.print_exc(); report.append(f'Pós-processamento falhou para seed {seed+i}: {e}; original preservado.')
            paths.append(str(final))
            path.with_suffix('.json').write_text(json.dumps({**meta,'seed':seed+i,'original':str(path),'final':str(final),'avisos':report},ensure_ascii=False,indent=2))
        if modo == SEEDVR2_POST:
            unload_qwen()
            pending = False
            for i, original in enumerate(originais):
                path = Path(original)
                details_path = path.with_suffix('.json')
                details = json.loads(details_path.read_text())
                notices = []
                try:
                    if pending:
                        raise RuntimeError('Há um upscale anterior aguardando coleta. A imagem original foi preservada.')
                    progress(0.9, desc=f'Aplicando SeedVR2 na imagem {i+1}/{len(originais)}')
                    job = seedvr2.run(path, 'Imagem', seedvr2.DEFAULT, escala, (seed+i) % 2**53,
                                      seedvr2.DEFAULT_TILE, OUT, progress)
                    details['job_seedvr2'] = {key: job[key] for key in ('id', 'status', 'model', 'checkpoint')}
                    if not job.get('result'):
                        pending = job['status'] in ('enviado', 'aguardando_coleta', 'envio_indeterminado')
                        raise RuntimeError(f"{job.get('error', job['status'])} · job {job['id']}")
                    result = OUT / job['id'] / job['result']
                    final = path.with_name(path.stem + '_final.png')
                    if nitidez > 0:
                        with Image.open(result) as image:
                            postprocessar(image, 'Nenhum', 1, 0, 0, 'cpu', nitidez).save(final)
                    else:
                        shutil.copyfile(result, final)
                    paths[i] = str(final)
                    details['final'] = str(final)
                except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
                    notices.append(f'SeedVR2 não finalizou a imagem {i+1}: {exc}. Original preservado.')
                details['avisos'] = notices
                report.extend(notices)
                details_path.write_text(json.dumps(details, ensure_ascii=False, indent=2))
        archive=OUT/('lote_'+uuid.uuid4().hex[:10]+'.zip')
        with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED) as z:
            for p in dict.fromkeys(originais+paths+[str(Path(x).with_suffix('.json')) for x in originais]): z.write(p,arcname=Path(p).name)
        return paths,originais,json.dumps({**meta,'arquivos_finais':paths,'originais':originais,'avisos':report},ensure_ascii=False,indent=2),str(archive)
    except Exception as e:
        if isinstance(e, torch.cuda.OutOfMemoryError):
            phase('cuda_oom')
        traceback.print_exc(); raise gr.Error(f'Falha na geração: {e}. Veja logs no Colab; verifique formato da LoRA e memória disponível.')
    finally:
        if torch.cuda.is_available(): torch.cuda.empty_cache()


def baixar_catalogo(ids):
    from huggingface_hub import hf_hub_download
    import shutil
    added=[]
    for ident in ids or []:
        if ident not in CATALOGO_BY_ID: raise ValueError('Entrada de catálogo desconhecida.')
        item=CATALOGO_BY_ID[ident]; dest=LORAS/Path(item['file']).name
        if dest.exists():
            added.append(dest.name); continue
        src=hf_hub_download(repo_id=item['repo'],filename=item['file'],revision=item['revision'],token=os.environ.get('HF_TOKEN') or None)
        tmp=LORAS/(uuid.uuid4().hex+'.part')
        try:
            shutil.copyfile(src,tmp)
            from safetensors import safe_open
            with safe_open(str(tmp),framework='pt',device='cpu') as safe: list(safe.keys())
            os.replace(tmp,dest)
        finally:
            if tmp.exists(): tmp.unlink()
        added.append(dest.name)
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
    gpu=torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'Nenhuma GPU detectada'
    disk=shutil.disk_usage(BASE)
    credentials='HF: '+('disponível' if os.environ.get('HF_TOKEN') else 'não configurado')+' · Civitai: '+('disponível' if os.environ.get('CIVITAI_TOKEN') else 'não configurado')
    running=current_config[0] if current_config else 'Nenhum modelo carregado'
    return f'{gpu} | Espaço livre: {disk.free/1024**3:.1f} GiB | {credentials} | Modelo em memória: {running}'

def listar_historico():
    out=[]
    for p in sorted(OUT.glob('*.json'),key=lambda x:x.stat().st_mtime,reverse=True)[:150]:
        try:
            data=json.loads(p.read_text())
            if not isinstance(data,dict) or 'final' not in data: continue
            final=Path(data['final'])
            if final.parent.resolve()!=OUT.resolve() or not final.is_file(): continue
            label=f"{time.strftime('%d/%m %H:%M:%S',time.localtime(p.stat().st_mtime))} · seed {data.get('seed','?')} · {str(data.get('prompt',''))[:65]}"
            out.append((label,p.name))
        except (OSError,ValueError): continue
    return gr.update(choices=out,value=None)

def abrir_historico(item):
    if not item: return None,''
    try:
        p=OUT/Path(item).name; data=json.loads(p.read_text()); final=Path(data['final'])
        if final.parent.resolve()!=OUT.resolve() or not final.is_file(): raise ValueError('Arquivo de saída indisponível.')
        return str(final),json.dumps(data,ensure_ascii=False,indent=2)
    except (OSError,ValueError,KeyError): raise gr.Error('Não consegui abrir este registro.')




# The preceding notebook cell extracts the workflow bundle.
STUDIO_MODULES = Path(__file__).resolve().parent / 'workflows'
import cf_seedvr2 as seedvr2
import cf_workflows as workflows
import cf_wan as wan
import cf_finish as finish
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
    ('Imagem', 'Criar imagem', 'Transforme uma descrição em imagem.', 'Qwen 2.1', 'criar', ''),
    ('Imagem', 'Editar com referências', 'Descreva o que muda e o que precisa ser preservado.', 'Qwen 2.1', 'criar', 'editar'),
    ('Identidade', 'Retrato por referência', 'Use duas imagens para guiar a identidade e a composição.', 'Qwen 2.1', 'criar', 'retrato'),
    ('Vídeo', wan.IMAGE_MODE, 'Anime uma foto com instruções de movimento e câmera.', 'Wan 2.2 · 5B', 'video', wan.IMAGE_MODE),
    ('Vídeo', wan.TEXT_MODE, 'Crie um clipe curto descrevendo a cena.', 'Wan 2.2 · 5B', 'video', wan.TEXT_MODE),
    ('Melhorar', 'Upscale de imagem', 'Amplie fotos e ilustrações com o Real-ESRGAN.', 'Real-ESRGAN', 'upscale-rapido', ''),
    ('Melhorar', 'Upscale de imagem ou vídeo', 'Recupere detalhe e amplie com SeedVR2.', 'SeedVR2 · INT8', 'seedvr2', ''),
    ('Identidade', 'Trocar personagem · OpenJutsu', 'Aplique uma referência a um clipe com um worker H3 preparado.', 'H3 · classe 96 GB', 'openjutsu', ''),
    ('Melhorar', finish.LOOK, 'Aplique um look com intensidade ajustável e compare com a foto de entrada.', 'Imagem · CPU', 'acabamento', finish.LOOK),
    ('Imagem', finish.FRAME, 'Prepare a foto para feed, stories ou paisagem e exporte em PNG, JPEG ou WebP.', 'Imagem · CPU', 'acabamento', finish.FRAME),
    ('Vídeo', finish.CLIP, 'Recorte o trecho e ajuste a proporção, com áudio opcional.', 'Vídeo · CPU', 'montagem', finish.CLIP),
    ('Vídeo', finish.STILL, 'Salve um quadro de um ponto do clipe como PNG.', 'Vídeo · CPU', 'montagem', finish.STILL),
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


CSS = """
.gradio-container {max-width: 1500px !important; background: #111217 !important;}
#hero {padding: 1rem 1.3rem; border:1px solid #38303a; border-radius:14px; background:linear-gradient(110deg,#25171c,#17171e);}
#hero h1 {font-size: 2rem; margin:0;}
#primary button {font-weight:700;}
#cf-app-grid {display:grid; grid-template-columns:repeat(auto-fill,minmax(min(100%,254px),1fr)); gap:12px;}
#cf-app-grid .cf-app-card {justify-content:space-between;}
#cf-app-grid .cf-app-card button {justify-content:flex-start;}
#cf-app-grid .cf-app-card h3 {font-size:1.08rem;}
#cf-app-grid .cf-app-card strong {font-size:.76rem; color:#eeabbc;}
#cf-tool-count p {margin:0; font-size:.9rem;}
@media (max-width:600px) {
  #hero {padding:.8rem;}
  #hero h1 {font-size:1.55rem;}
}
.cf-app-card {padding:16px; min-width:0 !important; border:1px solid #453742;
  border-radius:14px; background:linear-gradient(148deg,#2a1d29,#191920); color:#f7edf6;}
.cf-app-card h3 {color:#fff; margin:.35rem 0;}
.cf-app-card p {color:#e2d5e1;}
"""
with gr.Blocks(title='ClonField Studio',theme=gr.themes.Soft(primary_hue='red',neutral_hue='slate'),css=CSS) as demo:
    gr.Markdown('# ClonField Studio\nCrie, edite e amplie mídia. Os modelos são preparados quando você inicia um job.',elem_id='hero')
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
                        model=gr.Dropdown([QWEN_DEFAULT,QWEN_TURBO],value=QWEN_DEFAULT,allow_custom_value=True,label='Modelo Diffusers')
                        num=gr.Slider(1,4,value=1,step=1,label='Variações')
                    with gr.Row():
                        w=gr.Slider(256,2048,value=512,step=32,label='Largura'); h=gr.Slider(256,2048,value=512,step=32,label='Altura')
                    with gr.Accordion('LoRAs',open=False):
                        choices=gr.Dropdown(choices=nomes(),multiselect=True,label='Arquivos locais')
                        curated=gr.Dropdown(choices=list(CATALOGO_BY_ID),multiselect=True,label='Catálogo • baixar ao gerar',filterable=True)
                        weights=gr.Textbox(value='1.0',label='Pesos em ordem, separados por vírgula')
                        gr.Markdown('Confira a família da LoRA. Turbo e LoRAs de aceleração podem exigir configurações próprias.')
                    with gr.Accordion('Configurações avançadas',open=False):
                        neg=gr.Textbox(label='Prompt negativo • aplicado quando True CFG > 1')
                        with gr.Row():
                            steps=gr.Slider(1,80,value=40,step=1,label='Passos'); cfg=gr.Slider(1,8,value=1,step=.1,label='True CFG'); seed=gr.Number(value=-1,precision=0,label='Seed • -1 aleatório')
                        with gr.Row():
                            quant=gr.Checkbox(value=True,label='Quantização NF4 · 4 bits'); offload=gr.Checkbox(value=False,label='Offload para CPU');kv_cache=gr.Checkbox(value=True,label='Cache KV')
                        transparent=gr.Checkbox(label='Solicitar imagem transparente')
                        sigmas=gr.Textbox(label='Sigmas personalizados • opcional')
                    with gr.Accordion('Composição por máscara',open=False):
                        gr.Markdown('Branco revela o resultado; preto preserva a cena. A composição acontece após gerar; não é inpainting.')
                        with gr.Row():
                            composite_scene=gr.File(label='Cena',file_types=['image'],type='filepath');mask_file=gr.File(label='Máscara',file_types=['image'],type='filepath')
                        feather=gr.Slider(0,64,value=4,step=1,label='Suavização da borda')
                    with gr.Accordion('Pós-processamento',open=False):
                        modo=gr.Dropdown(choices=['Nenhum','Lanczos (rápido, sem IA)']+list(UP_MODELS)+[SEEDVR2_POST],value='Nenhum',label='Upscale após gerar')
                        gr.Markdown('SeedVR2 usa o worker local e libera o Qwen antes do upscale. Bloco, margem e dispositivo abaixo se aplicam ao Real-ESRGAN.')
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
            model.input(model_defaults, model, [steps, cfg], queue=False)
            generate = run.click(gerar,[prompt,neg,imgs,w,h,steps,cfg,seed,num,choices,weights,transparent,kv_cache,sigmas,modo,escala,tile,pad,device,nitidez,model,quant,offload,curated,composite_scene,mask_file,feather],[gallery,originals,meta,download_zip],api_name='gerar', concurrency_id='gpu', concurrency_limit=1)
            generate.success(lambda: 0, None, gallery_index, queue=False, api_name=False)
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
                             queue=False, api_name=False)
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
                                    queue=False, api_name=False)
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
                                    queue=False, api_name=False)
            finish_clip_button.click(finish_clip, [finish_video_input, finish_video_mode, finish_start,
                                    finish_length, clip_ratio, clip_fit, clip_mute],
                                    [finish_video_output, finish_clip_image, finish_clip_download, finish_clip_status],
                                    api_name='montagem_video')
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
        with gr.Tab('Histórico'):
            gr.Markdown('### Resultados desta pasta\nCom o Drive montado, os resultados também permanecem após a sessão.')
            hist_reload=gr.Button('Atualizar histórico');hist_list=gr.Dropdown(label='Escolher resultado');hist_img=gr.Image(label='Imagem',type='filepath');hist_meta=gr.Textbox(label='Parâmetros',lines=10)
            hist_finish = gr.Button('Abrir em Acabamento', size='sm')
            hist_reload.click(listar_historico,None,hist_list);hist_list.change(abrir_historico,hist_list,[hist_img,hist_meta])
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
                past_seedvr2 = gr.Dropdown(choices=seedvr2.recent_jobs(OUT), label='Upscales anteriores')
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
                civ_file = gr.Dropdown(downloaded_workflows(), label='Arquivo')
                civ_download = gr.File(label='Abrir ou baixar')
                gr.Button('Atualizar lista').click(
                    lambda: gr.update(choices=downloaded_workflows(), value=None), None, civ_file, api_name=False)
                gr.Button('Abrir arquivo').click(open_civitai_workflow, civ_file, civ_download, api_name=False)
            with gr.Accordion('Executar API JSON no ComfyUI local',open=False):
                wf = gr.File(file_types=['.json'], type='filepath', label='Workflow API JSON')
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
                go.click(api_workflow, [wf, server, wm], workflow_outputs, concurrency_id='gpu', concurrency_limit=1)
                with gr.Accordion('Histórico e retomada de workflows', open=False):
                    old_workflows = gr.Dropdown(choices=workflows.recent(OUT), label='Workflows anteriores')
                    gr.Button('Atualizar lista').click(list_workflow_jobs, None, old_workflows)
                    gr.Button('Abrir ou retomar coleta').click(
                        reopen_workflow, old_workflows, workflow_outputs, concurrency_id='gpu', concurrency_limit=1)
        with gr.Tab('Configurações e diagnóstico'):
            gr.Markdown('### Ambiente\nOs Secrets são carregados no Colab antes de iniciar esta interface. Os valores não aparecem aqui.')
            env_status=gr.Textbox(value=ambiente,label='Estado local',interactive=False,lines=3)
            gr.Button('Atualizar diagnóstico').click(ambiente,None,env_status)
            gr.Markdown("""**Hugging Face:** use o Secret `HF_TOKEN`. **Civitai:** use `CIVITAI_TOKEN`. Modelos públicos podem funcionar sem eles.\n\n**Armazenamento:** ative o Drive na célula indicada se quiser preservar arquivos.\n\n**T4:** o padrão é 512×512, uma imagem e NF4 carregado direto na GPU. O offload é opcional e usa RAM do sistema.\n\n**SeedVR2:** usa ComfyUI no mesmo Colab. Os jobs e resultados ficam no diretório de saída do Studio.""")

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
    to_image_finish.click(finish_gallery, [gallery, gallery_index], finish_image_route, queue=False, api_name=False)
    hist_finish.click(partial(send_to_finish, 'acabamento', finish.LOOK), hist_img, finish_image_route,
                      queue=False, api_name=False)
    to_clip_finish.click(partial(send_to_finish, 'montagem', finish.CLIP), video_preview, finish_video_route,
                         queue=False, api_name=False)
    finish_clip_extract.click(partial(send_to_finish, 'montagem', finish.STILL), finish_video_output,
                              finish_video_route, queue=False, api_name=False)
    finish_image_reframe.click(partial(send_to_finish, 'acabamento', finish.FRAME), finish_image_output,
                               finish_image_route, queue=False, api_name=False)
    for button, media in ((finish_image_animate, finish_image_output), (finish_clip_animate, finish_clip_image)):
        button.click(animate_image, media, [main_tabs, video_mode, video_image], queue=False, api_name=False)

demo.queue(default_concurrency_limit=1)
if '--probe-qwen' in sys.argv:
    iniciar(QWEN_DEFAULT, True, False)
    def probe_step(_pipeline, step, _timestep, values):
        phase('qwen_first_step' if step == 0 else 'qwen_decode')
        return values
    try:
        phase('qwen_encode_and_first_step')
        result = pipe(prompt='Uma esfera vermelha sobre uma mesa branca', width=512, height=512,
                      num_inference_steps=2, true_cfg_scale=1, generator=torch.Generator('cpu').manual_seed(42),
                      callback_on_step_end=probe_step).images[0]
        result.save(OUT / 'qwen-probe.png')
        phase('qwen_image_ready')
    except torch.cuda.OutOfMemoryError:
        phase('cuda_oom')
        raise
    raise SystemExit(0)

import secrets
GRADIO_USUARIO='clonfield';GRADIO_SENHA=secrets.token_urlsafe(16)
print('Iniciando Gradio; aguarde a URL...',flush=True)
demo.launch(share=True,debug=False,auth=(GRADIO_USUARIO,GRADIO_SENHA),prevent_thread_lock=True,show_error=True)
url=getattr(demo,'share_url',None)
print(('LINK DO GRADIO: '+str(url)) if url else 'Sem link público; confira a mensagem de erro acima.',flush=True)
print('USUÁRIO: '+GRADIO_USUARIO+' | SENHA: '+GRADIO_SENHA,flush=True)
print('Mantenha esta célula executando.',flush=True)
import threading
try:threading.Event().wait()
finally:demo.close()
