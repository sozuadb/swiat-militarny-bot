#!/usr/bin/env python3
"""
Módulo de Geração e Localização de Thumbnails - Świat Militarny
Cobre marcas d'água em português e reconstrói a identidade visual para o público polonês.
"""

import os
import re
import logging
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

# Fontes padrão
FONT_EXTRA_BOLD = "/usr/share/fonts/TTF/OpenSans-ExtraBold.ttf"
FONT_BOLD = "/usr/share/fonts/TTF/OpenSans-Bold.ttf"
FALLBACK_FONT = "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf"

def get_font(path, size):
    for f in [path, FONT_EXTRA_BOLD, FONT_BOLD, FALLBACK_FONT]:
        if os.path.exists(f):
            try:
                return ImageFont.truetype(f, size)
            except Exception:
                pass
    return ImageFont.load_default()

def parse_title_components(title_pl):
    """
    Divide o título polonês em Hook (Linha 1) e Subtítulo/Pergunta (Linha 2).
    """
    # 1. Separadores comuns
    separators = [" – ", " — ", " - ", ": ", " // "]
    for sep in separators:
        if sep in title_pl:
            parts = title_pl.split(sep, 1)
            hook = parts[0].strip()
            sub = parts[1].strip()
            if not hook.endswith("//"):
                hook = f"{hook} //"
            return hook, sub

    # 2. Se tiver aspas no início (ex: „Teraz chcę Europy”)
    quote_match = re.match(r'^(„[^”]+”|["][^"]+["])\s*(.*)$', title_pl)
    if quote_match:
        hook = f"{quote_match.group(1).strip()} //"
        sub = quote_match.group(2).strip()
        if sub:
            return hook, sub

    # 3. Fallback inteligente por quebra de palavras
    words = title_pl.split()
    if len(words) <= 5:
        return f"{title_pl} //", ""
    mid = min(4, len(words) // 2)
    hook = " ".join(words[:mid]) + " //"
    sub = " ".join(words[mid:])
    return hook, sub

def generate_localized_thumbnail(input_thumb_path, title_pl, output_thumb_path):
    """
    Sobrepõe a faixa preta no topo (com Świat Militarny) e a faixa inferior com o título traduzido.
    """
    input_thumb = Path(input_thumb_path)
    if not input_thumb.exists():
        logging.warning(f"Thumbnail original não encontrada: {input_thumb_path}")
        return False

    try:
        im = Image.open(input_thumb).convert("RGBA")
        W, H = im.size

        # Cria camada de sobreposição
        overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)

        # 1. Badge Top-Left: "Świat Militarny"
        badge_w = int(W * 0.22) # ~280px em 1280
        badge_h = int(H * 0.055) # ~40px em 720
        badge_font_size = max(14, int(H * 0.032))
        
        draw.rectangle([0, 0, badge_w, badge_h], fill=(0, 0, 0, 255))
        badge_font = get_font(FONT_EXTRA_BOLD, badge_font_size)
        draw.text((int(W * 0.012), int(H * 0.008)), "Świat Militarny", font=badge_font, fill=(255, 255, 255, 255))

        # 2. Barra Inferior: Cobrir texto original em português
        strip_y = int(H * 0.855) # ~615px em 720
        draw.rectangle([0, strip_y, W, H], fill=(0, 0, 0, 255))

        hook, sub = parse_title_components(title_pl)

        # Linha 1: Hook
        hook_font_size = max(18, int(H * 0.038)) # ~27px
        hook_font = get_font(FONT_EXTRA_BOLD, hook_font_size)
        draw.text((int(W * 0.016), strip_y + int(H * 0.014)), hook, font=hook_font, fill=(255, 255, 255, 255))

        # Linha 2: Subtítulo
        if sub:
            sub_font_size = max(15, int(H * 0.032)) # ~23px
            sub_font = get_font(FONT_BOLD, sub_font_size)
            # Trunca se for gigantesco para não vazar a tela
            if len(sub) > 85:
                sub = sub[:82] + "..."
            draw.text((int(W * 0.016), strip_y + int(H * 0.065)), sub, font=sub_font, fill=(255, 255, 255, 255))

        # Composição final
        final_im = Image.alpha_composite(im, overlay).convert("RGB")
        out_p = Path(output_thumb_path)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        final_im.save(str(out_p), quality=95)
        logging.info(f"[+] Thumbnail localizada gerada com sucesso: {output_thumb_path}")
        return True

    except Exception as e:
        logging.error(f"Erro ao gerar thumbnail localizada: {e}")
        return False

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 3:
        generate_localized_thumbnail(sys.argv[1], sys.argv[2], sys.argv[3])
    else:
        print("Uso: python thumbnail_generator.py <input> <title_pl> <output>")
