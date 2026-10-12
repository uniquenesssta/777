"""Complete quote attachments rendered from frozen output; independent of Tk/DPI."""
from dataclasses import dataclass
import json
import os
from pathlib import Path
import uuid

from quote_core import DiscountLine
from quote_core.numbers import money_text
from .images import save_png, filename_part
from .transactions import digest, transact


@dataclass(frozen=True)
class QuoteImageResult:
    directory: str
    paths: tuple
    manifest: str
    last_commit: object


def quote_rows(payload, role):
    if role not in {'manager', 'sales'}:raise ValueError('未知报价角色')
    headings = ('序号', '项目', '规格 / 数量', '销售单价 / K / 折扣', '销售额')
    if role == 'manager':headings += ('成本', '利润', '利润率')
    rows = []
    for line in payload.result.lines:
        n = dict(line.normalized)
        discount = isinstance(line.raw, DiscountLine)
        specs = '' if discount else ('数量 ' + n['q'] + ('' if line.price.single else f"\n高 {n['h']} × 宽 {n['w']}") )
        price = n['percent'] + '%' if discount else f"{n['sale']}\nK {n['k']}"
        amounts = line.amounts.display()
        cells = (str(line.sequence), line.raw.name, specs, price, amounts['income'])
        if role == 'manager':cells += (amounts['cost'], amounts['profit'], amounts['margin'] or '—')
        rows.append(cells)
    totals = {'销售额': money_text(payload.result.totals.income_cents)}
    if role == 'manager':
        display = payload.result.totals.display()
        totals.update({'总成本':display['cost'],'利润':display['profit'],'利润率':display['margin'] or '—'})
    return headings, tuple(rows), totals


def chinese_font(size=22):
    from PIL import ImageFont
    if os.name == 'nt':
        folder = Path(os.environ.get('WINDIR', r'C:\Windows')) / 'Fonts'
        choices = [folder/'msyh.ttc', folder/'simhei.ttf', folder/'simsun.ttc']
    else:
        # Auxiliary rendering only; Windows product never silently uses a font
        # without Chinese glyphs. No font dependency is downloaded at runtime.
        choices = [Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf')]
    for path in choices:
        if path.is_file():return ImageFont.truetype(str(path), size)
    raise ValueError('未找到可用的中文字体，报价图未保存；请检查Windows字体。')


def wrap_text(text, font, width):
    """Pixel-width wrapping retains every character, including long names."""
    result = []
    for paragraph in str(text).split('\n'):
        if font.getlength(paragraph) <= width:
            result.append(paragraph);continue
        line = ''
        for char in paragraph:
            if line and font.getlength(line + char) > width:
                result.append(line);line = ''
            line += char
        result.append(line)
    return tuple(result)


def quote_layout(payload, role, font=None):
    font = font or chinese_font()
    headings, rows, totals = quote_rows(payload, role)
    widths = (70, 290, 330, 280, 220) + ((180, 180, 150) if role == 'manager' else ())
    line_height = max(30, font.getbbox('国Ag')[3] - font.getbbox('国Ag')[1] + 8)
    header = ['完整报价图', '客户：' + payload.details.customer, '订单号：' + payload.details.order_ref,
              '微信：' + payload.details.wechat, f'共{len(rows)}条明细；金额按完整订单计算']
    width = sum(widths) + 48
    header_lines = tuple(line for text in header for line in wrap_text(text, font, width - 48))
    top = 36 + len(header_lines) * line_height + line_height * 2
    bottom = 100 + (len(totals) + 1) * line_height
    capacity = 2400 - top - bottom
    if capacity < 200:raise ValueError('订单身份文本过长，报价图未保存')
    pages, page, used = [], [], 0
    for index, cells in enumerate(rows):
        wrapped = tuple(wrap_text(value, font, col - 20) for value, col in zip(cells, widths))
        height = max(len(lines) for lines in wrapped) * line_height + 16
        if height > capacity:raise ValueError('单行文本超出报价图容量，未静默截断')
        if page and (used + height > capacity or len(page) >= 40):
            pages.append(tuple(page));page, used = [], 0
        page.append((index + 1, wrapped, height));used += height
    if page:pages.append(tuple(page))
    return {'font':font,'headings':headings,'rows':rows,'totals':totals,'widths':widths,
            'width':width,'line_height':line_height,'header':header_lines,'top':top,'bottom':bottom,'pages':tuple(pages)}


def render_page(layout, page_index):
    from PIL import Image, ImageDraw
    page = layout['pages'][page_index]
    height = layout['top'] + sum(row[2] for row in page) + layout['bottom']
    image = Image.new('RGB', (layout['width'], height), 'white')
    draw = ImageDraw.Draw(image);font = layout['font'];line_height = layout['line_height']
    def text(x,y,value):draw.text((x,y), value, font=font, fill='#172033', anchor='lt')
    y = 24
    for value in layout['header']:text(24,y,value);y += line_height
    text(24,y, f"第{page_index + 1}/{len(layout['pages'])}张 ｜ 明细{page[0][0]}–{page[-1][0]}")
    y += line_height
    x = 24
    for title,width in zip(layout['headings'],layout['widths']):text(x+10,y,title);x += width
    y = layout['top']
    for _, cells, height in page:
        x = 24
        draw.line((24,y,layout['width']-24,y),fill='#c8d0dc')
        for lines,width in zip(cells,layout['widths']):
            for n,value in enumerate(lines):text(x+10,y+8+n*line_height,value)
            x += width
        y += height
    y += 20
    text(24,y,'完整订单合计（不受本张分页影响）：');y += line_height
    for name,amount in layout['totals'].items():text(24,y,name+'：'+amount);y += line_height
    return image


def save_quote_images(folder, payload, role, *, on_request=None):
    layout = quote_layout(payload, role)
    folder = Path(folder);folder.mkdir(parents=True, exist_ok=True)
    directory = None
    for _ in range(3):
        candidate = folder / (f'报价_{filename_part(payload.details.customer)}_{filename_part(payload.details.order_ref)}_' + uuid.uuid4().hex)
        try:candidate.mkdir();directory=candidate;break
        except FileExistsError:continue
    if directory is None:raise ValueError('附件名称冲突，原文件保持')
    paths = []
    for index,page in enumerate(layout['pages']):
        path = directory / f'{index+1:03d}.png'
        image = render_page(layout,index)
        try:
            commit = save_png(path,image,on_request=lambda rid,p=path: on_request(str(p),rid) if on_request else None,
                              metadata={'777_attachment_kind':'complete_quote','777_page':str(index+1),
                                        '777_pages':str(len(layout['pages'])),'777_first_line':str(page[0][0]),
                                        '777_last_line':str(page[-1][0])})
            paths.append(str(path))
        except Exception as exc:
            exc.target_path = str(path)
            exc.published_paths = tuple(paths)
            raise
        finally:image.close()
    manifest = {'schema':'777-quote-image-v1','status':'complete','draft_revision':payload.revision,
                'role':role,'line_count':len(layout['rows']),'totals':layout['totals'],
                'pages':[{'file':Path(path).name,'first_line':page[0][0],'last_line':page[-1][0],
                          'sha256':digest(Path(path).read_bytes())} for path,page in zip(paths,layout['pages'])]}
    path = directory/'manifest.json';raw=(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n').encode()
    rid = str(uuid.uuid4());fingerprint=digest(raw);receipt={'fingerprint':fingerprint}
    if on_request:on_request(str(path),rid)
    try:
        commit = transact(path,rid,fingerprint,'quote_image_manifest',lambda before:(raw,receipt),
                          lambda data,req:receipt if digest(data)==fingerprint else None,expected_hash=None)
    except Exception as exc:
        exc.target_path=str(path);exc.published_paths=tuple(paths);raise
    return QuoteImageResult(str(directory),tuple(paths),str(path),commit)
