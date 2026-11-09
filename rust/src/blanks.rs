// RedColor — редактор PDF для проверки работ. Автор: Maksim Belonoskin, Zelenograd, Moscow, Russia.
//! Бланки проверки и случайные цитаты (перенос blanks.py).
//!
//! При вставке бланка красная «1» (остаток текстового поля) удаляется, а на её место тем же кеглем
//! ставится случайная цитата. Если «1» нет — цитата встаёт под надписью «Комментарий эксперта:».

use std::cell::RefCell;
use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::time::SystemTime;

use mupdf::pdf::{PdfAnnotationType, PdfDocument, PdfPage, PdfRedactImageMethod, PdfRedactLineArtMethod, PdfRedactOptions, PdfRedactTextMethod};
use mupdf::{Colorspace, Matrix, Rect, TextPageFlags};

use crate::settings::{Settings, data_dir};

const DPI: f32 = 50.0;
static LABEL_PNG: &[u8] = include_bytes!("../../assets/comment_label.png");

// ============================================================================ цитаты

#[derive(Default)]
pub struct QuoteBank {
    pub quotes: Vec<String>,
    pub path: PathBuf,
}

pub fn quotes_path(s: &Settings) -> PathBuf {
    let p = s.str("quotes_file", "");
    if p.is_empty() { data_dir().join("цитаты.txt") } else { PathBuf::from(p) }
}

impl QuoteBank {
    pub fn reload(&mut self, s: &Settings) {
        self.path = quotes_path(s);
        let txt = std::fs::read_to_string(&self.path).unwrap_or_default();
        let txt = txt.trim_start_matches('\u{feff}');
        self.quotes = txt.lines().map(|l| l.trim().to_string()).filter(|l| !l.is_empty()).collect();
    }

    pub fn save(&mut self, s: &mut Settings, text: &str) {
        if let Some(d) = self.path.parent() {
            let _ = std::fs::create_dir_all(d);
        }
        let t = text.trim();
        let _ = std::fs::write(&self.path, if t.is_empty() { String::new() } else { format!("{t}\n") });
        s.set("quote_bag", serde_json::json!([]));
        s.save();
        self.reload(s);
    }

    /// Случайная цитата без повторов, пока не пройдём весь список.
    pub fn next(&mut self, s: &mut Settings) -> Option<String> {
        self.reload(s);
        if self.quotes.is_empty() {
            return None;
        }
        let n = self.quotes.len();
        let mut bag: Vec<usize> = s
            .get_value("quote_bag")
            .and_then(|v| v.as_array().cloned())
            .unwrap_or_default()
            .iter()
            .filter_map(|x| x.as_u64().map(|v| v as usize))
            .filter(|&i| i < n)
            .collect();
        if bag.is_empty() {
            bag = (0..n).collect();
            shuffle(&mut bag);
        }
        let i = bag.pop()?;
        s.set("quote_bag", serde_json::json!(bag));
        s.save();
        Some(self.quotes[i].clone())
    }
}

fn shuffle(v: &mut [usize]) {
    let mut x = SystemTime::now().duration_since(SystemTime::UNIX_EPOCH).map(|d| d.as_nanos() as u64).unwrap_or(7) | 1;
    for i in (1..v.len()).rev() {
        x ^= x << 13;
        x ^= x >> 7;
        x ^= x << 17;
        let j = (x % (i as u64 + 1)) as usize;
        v.swap(i, j);
    }
}

// ============================================================================ анализ бланка

fn template() -> &'static (usize, usize, Vec<bool>) {
    static T: std::sync::OnceLock<(usize, usize, Vec<bool>)> = std::sync::OnceLock::new();
    T.get_or_init(|| {
        let dec = png::Decoder::new(std::io::Cursor::new(LABEL_PNG));
        let Ok(mut r) = dec.read_info() else { return (1, 1, vec![false]) };
        let mut buf = vec![0; r.output_buffer_size()];
        let Ok(info) = r.next_frame(&mut buf) else { return (1, 1, vec![false]) };
        let (w, h) = (info.width as usize, info.height as usize);
        let ch = match info.color_type {
            png::ColorType::Grayscale => 1,
            png::ColorType::GrayscaleAlpha => 2,
            png::ColorType::Rgb => 3,
            png::ColorType::Rgba => 4,
            png::ColorType::Indexed => 1,
        };
        let stride = info.line_size;
        let mut out = vec![false; w * h];
        for y in 0..h {
            for x in 0..w {
                let o = y * stride + x * ch;
                let g = if ch >= 3 {
                    (0.299 * buf[o] as f32 + 0.587 * buf[o + 1] as f32 + 0.114 * buf[o + 2] as f32) as u8
                } else {
                    buf[o]
                };
                // прозрачные пиксели — фон
                let a = if ch == 2 { buf[o + 1] } else if ch == 4 { buf[o + 3] } else { 255 };
                out[y * w + x] = a > 127 && g < 128;
            }
        }
        (w, h, out)
    })
}

pub struct Gray {
    pub w: usize,
    pub h: usize,
    pub px: Vec<u8>,
}

impl Gray {
    fn at(&self, x: usize, y: usize) -> u8 {
        self.px[y * self.w + x]
    }
}

pub fn render_gray(page: &mupdf::Page, dpi: f32, annots: bool) -> Option<Gray> {
    let m = Matrix::new_scale(dpi / 72.0, dpi / 72.0);
    let pix = page.to_pixmap(&m, &Colorspace::device_gray(), false, annots).ok()?;
    let (w, h) = (pix.width() as usize, pix.height() as usize);
    let stride = pix.stride() as usize;
    let s = pix.samples();
    let mut px = Vec::with_capacity(w * h);
    for y in 0..h {
        px.extend_from_slice(&s[y * stride..y * stride + w]);
    }
    Some(Gray { w, h, px })
}

/// Поиск надписи «Комментарий эксперта:» по образцу (в левой нижней части страницы).
fn find_label(a: &Gray) -> Option<Rect> {
    let (tw, th, tn) = template();
    let (tw, th) = (*tw, *th);
    let (ww, hh) = (a.w, a.h);
    if ww < tw || hh < th {
        return None;
    }
    let d: Vec<bool> = a.px.iter().map(|&v| v < 128).collect();
    let tsum = tn.iter().filter(|&&b| b).count();
    let mut best = (usize::MAX, 0, 0);
    let y0 = (hh as f64 * 0.3) as usize;
    let y1 = ((hh as f64 * 0.97) as usize).saturating_sub(th).max(y0 + 1).min(hh - th);
    let xmax = ((ww as f64 * 0.2) as usize).max(1).min(ww - tw);
    for y in y0..y1 {
        for x in 0..xmax {
            let mut diff = 0;
            for ty in 0..th {
                let row = (y + ty) * ww + x;
                let trow = ty * tw;
                for tx in 0..tw {
                    if d[row + tx] != tn[trow + tx] {
                        diff += 1;
                    }
                }
                if diff >= best.0 {
                    break;
                }
            }
            if diff < best.0 {
                best = (diff, x, y);
            }
        }
    }
    let (score, x, y) = best;
    if score as f64 > tsum as f64 * 0.6 {
        return None;
    }
    let k = 72.0 / DPI;
    Some(Rect { x0: x as f32 * k, y0: y as f32 * k, x1: (x + tw) as f32 * k, y1: (y + th) as f32 * k })
}

#[derive(Clone, Debug)]
pub struct Stray {
    pub rect: Rect,
    pub size: f64,
}

/// Короткие красные надписи (например, «1»), оставшиеся от текстовых полей.
pub fn strays(page: &mupdf::Page) -> Vec<Stray> {
    let mut out = Vec::new();
    let Ok(tp) = page.to_text_page(TextPageFlags::empty()) else { return out };
    for b in tp.blocks() {
        for l in b.lines() {
            // соседние символы одного цвета и кегля — один «span»
            let mut spans: Vec<(String, Rect, f32, u32)> = Vec::new();
            for ch in l.chars() {
                let c = ch.char().unwrap_or(' ');
                let q = ch.quad();
                let r = Rect {
                    x0: q.ul.x.min(q.ll.x),
                    y0: q.ul.y.min(q.ur.y),
                    x1: q.ur.x.max(q.lr.x),
                    y1: q.ll.y.max(q.lr.y),
                };
                let (argb, size) = (ch.argb() & 0xffffff, ch.size());
                match spans.last_mut() {
                    Some(s) if s.3 == argb && (s.2 - size).abs() < 0.01 => {
                        s.0.push(c);
                        s.1 = Rect { x0: s.1.x0.min(r.x0), y0: s.1.y0.min(r.y0), x1: s.1.x1.max(r.x1), y1: s.1.y1.max(r.y1) };
                    }
                    _ => spans.push((c.to_string(), r, size, argb)),
                }
            }
            for (t, r, size, argb) in spans {
                let t = t.trim().to_string();
                let (rr, gg, bb) = ((argb >> 16) & 255, (argb >> 8) & 255, argb & 255);
                if !t.is_empty() && t.chars().count() <= 2 && rr > 180 && gg < 80 && bb < 80 {
                    out.push(Stray { rect: r, size: size as f64 });
                }
            }
        }
    }
    out
}

#[derive(Clone, Debug)]
pub struct Info {
    pub label: Option<Rect>,
    pub zone: Option<Rect>,
    pub strays: Vec<Stray>,
    pub w: f64,
    pub h: f64,
}

/// Разбор страницы-бланка: надпись, поле комментария, красные «1».
pub fn analyze_page(page: &mupdf::Page, st: Option<Vec<Stray>>) -> Info {
    let b = page.bounds().unwrap_or(Rect { x0: 0.0, y0: 0.0, x1: 595.0, y1: 842.0 });
    let (ww, hh) = ((b.x1 - b.x0) as f64, (b.y1 - b.y0) as f64);
    let st = st.unwrap_or_else(|| strays(page));
    let Some(a) = render_gray(page, DPI, true) else { return Info { label: None, zone: None, strays: st, w: ww, h: hh } };
    let label = find_label(&a);
    let mut zone = None;
    if let Some(lb) = label {
        let k = DPI as f64 / 72.0;
        let top = lb.y1 as f64 + 3.0;
        let ty = (top * k) as usize;
        let mut bottom = hh - 30.0;
        let lx0 = (lb.x0 as f64 * k) as usize;
        let lx1 = (((lb.x0 as f64 + 60.0) * k) as usize).min(a.w);
        for y in (ty + (12.0 * k) as usize)..a.h {
            if (lx0..lx1).filter(|&x| a.at(x, y) < 128).count() >= 2 {
                bottom = y as f64 / k - 4.0;
                break;
            }
        }
        let mut right = ww - lb.x0 as f64;
        let yb = ((bottom * k) as usize).min(a.h);
        if yb > ty {
            let start = ((lb.x0 as f64 + 60.0) * k) as usize;
            for x in start..a.w {
                let dark = (ty..yb).filter(|&y| a.at(x, y) < 215).count() as f64 / (yb - ty) as f64;
                if dark > 0.2 {
                    right = x as f64 / k - 8.0;
                    break;
                }
            }
        }
        zone = Some(Rect { x0: lb.x0, y0: top as f32, x1: right as f32, y1: bottom as f32 });
    }
    Info { label, zone, strays: st, w: ww, h: hh }
}

thread_local! {
    static CACHE: RefCell<HashMap<PathBuf, (SystemTime, Info)>> = RefCell::new(HashMap::new());
    static FULL_CACHE: RefCell<HashMap<PathBuf, (SystemTime, FullMarks)>> = RefCell::new(HashMap::new());
}

fn mtime(p: &Path) -> SystemTime {
    std::fs::metadata(p).and_then(|m| m.modified()).unwrap_or(SystemTime::UNIX_EPOCH)
}

/// Разбор бланка из файла (кешируется по времени изменения; ручная зона из настроек).
pub fn analyze(path: &Path, s: &Settings) -> Option<Info> {
    let mt = mtime(path);
    if let Some(i) = CACHE.with(|c| c.borrow().get(path).filter(|v| v.0 == mt).map(|v| v.1.clone())) {
        return Some(i);
    }
    let data = std::fs::read(path).ok()?;
    let doc = mupdf::Document::from_bytes(&data, "application/pdf").ok()?;
    let page = doc.load_page(0).ok()?;
    let mut info = analyze_page(&page, None);
    let name = path.file_name()?.to_string_lossy().to_string();
    if let Some(z) = s.get_value("blank_zones").and_then(|v| v.get(&name).cloned()).and_then(|v| v.as_array().cloned()) {
        if z.len() == 4 {
            let g = |i: usize| z[i].as_f64().unwrap_or(0.0) as f32;
            info.zone = Some(Rect { x0: g(0), y0: g(1), x1: g(2), y1: g(3) });
        }
    }
    CACHE.with(|c| c.borrow_mut().insert(path.to_path_buf(), (mt, info.clone())));
    Some(info)
}

/// Красные «1» в поле «Комментарий эксперта» на странице-бланке.
pub fn comment_ones(page: &mupdf::Page) -> Vec<Stray> {
    let st = strays(page);
    if st.is_empty() {
        return vec![];
    }
    let info = analyze_page(page, Some(st.clone()));
    let Some(label) = info.label else { return vec![] };
    let bottom = info.zone.map(|z| z.y1 as f64 + 6.0).unwrap_or(label.y1 as f64 + 220.0);
    let right = info.zone.map(|z| z.x1 as f64 + 30.0).unwrap_or(info.w * 0.8);
    st.into_iter()
        .filter(|s| {
            let cy = (s.rect.y0 + s.rect.y1) as f64 / 2.0;
            label.y0 as f64 - 4.0 <= cy && cy <= bottom && s.rect.x1 as f64 <= right
        })
        .collect()
}

fn redact(page: &mut PdfPage, rects: &[Rect]) -> bool {
    for r in rects {
        if page.add_redact_annotation(*r).is_err() {
            return false;
        }
    }
    let opts = PdfRedactOptions {
        black_boxes: false,
        image_method: PdfRedactImageMethod::None,
        line_art: PdfRedactLineArtMethod::None,
        text: PdfRedactTextMethod::Remove,
    };
    page.apply_redactions_with_options(opts).is_ok()
}

/// Убирает «1» из комментариев на всех страницах документа. Возвращает (новые байты, сколько убрано).
pub fn remove_comment_ones_doc(data: &[u8], only_pages: Option<&[usize]>) -> Option<(Vec<u8>, usize)> {
    let doc = PdfDocument::from_bytes(data).ok()?;
    let n = doc.page_count().ok()? as usize;
    let mut count = 0;
    for i in 0..n {
        if only_pages.map(|p| !p.contains(&i)).unwrap_or(false) {
            continue;
        }
        let Ok(mut page) = doc.load_pdf_page(i as i32) else { continue };
        if page.rotation().unwrap_or(0) != 0 {
            continue;
        }
        let found = comment_ones(&page);
        if found.is_empty() {
            continue;
        }
        let rects: Vec<Rect> = found.iter().map(|s| Rect { x0: s.rect.x0 + 0.3, y0: s.rect.y0, x1: s.rect.x1 - 0.3, y1: s.rect.y1 }).collect();
        if redact(&mut page, &rects) {
            count += found.len();
        }
    }
    if count == 0 {
        return Some((data.to_vec(), 0));
    }
    let mut out = Vec::new();
    doc.write_to(&mut out).ok()?;
    Some((out, count))
}

/// Копия бланка (байты) — с удалённой «1», если включено.
pub fn prepared_blank(path: &Path, remove_stray: bool) -> Result<Vec<u8>, String> {
    let data = std::fs::read(path).map_err(|e| e.to_string())?;
    if !remove_stray {
        return Ok(data);
    }
    let doc = PdfDocument::from_bytes(&data).map_err(|e| e.to_string())?;
    let mut page = doc.load_pdf_page(0).map_err(|e| e.to_string())?;
    let st = strays(&page);
    if st.is_empty() {
        return Ok(data);
    }
    let rects: Vec<Rect> = st.iter().map(|s| s.rect).collect();
    redact(&mut page, &rects);
    let mut out = Vec::new();
    doc.write_to(&mut out).map_err(|e| e.to_string())?;
    Ok(out)
}

/// Куда и каким кеглем ставить цитату: (x, y, ширина, кегль, макс. высота) в pt бланка.
pub fn quote_placement(info: &Info, default_size: f64) -> (f64, f64, f64, f64, f64) {
    if let Some(s) = info.strays.first() {
        let size = s.size;
        let (x, y) = (s.rect.x0 as f64, s.rect.y0 as f64);
        let right = info.zone.map(|z| z.x1 as f64).unwrap_or(info.w - 40.0);
        let bottom = info.zone.map(|z| z.y1 as f64).unwrap_or(y + size * 4.0);
        return (x, y, (right - x).max(80.0), size, (bottom - y).max(size * 1.3));
    }
    if let Some(z) = info.zone {
        return (z.x0 as f64, z.y0 as f64, ((z.x1 - z.x0) as f64).max(80.0), default_size, ((z.y1 - z.y0) as f64).max(default_size * 1.3));
    }
    (info.w * 0.07, info.h * 0.7, info.w * 0.55, default_size, info.h * 0.15)
}

// ============================================================================ полный бланк: все «+» и максимальные баллы

pub fn task_number(path: &Path) -> Option<String> {
    let stem: Vec<char> = path.file_stem()?.to_string_lossy().chars().collect();
    for i in 0..stem.len().saturating_sub(1) {
        let a = stem[i];
        let b = stem[i + 1];
        let before = i == 0 || !stem[i - 1].is_ascii_digit();
        let after = i + 2 >= stem.len() || !stem[i + 2].is_ascii_digit();
        if a == '2' && ('1'..='6').contains(&b) && before && after {
            return Some(format!("{a}{b}"));
        }
    }
    None
}

/// Баллы «полного» бланка (переопределяются в настройках: blank_full_scores). None — окошко пустое.
pub fn full_scores(path: &Path, s: &Settings) -> Vec<Option<i64>> {
    let name = path.file_name().map(|x| x.to_string_lossy().to_string()).unwrap_or_default();
    if let Some(v) = s.get_value("blank_full_scores").and_then(|m| m.get(&name).cloned()).and_then(|v| v.as_array().cloned()) {
        return v.iter().map(|x| x.as_i64()).collect();
    }
    match task_number(path).as_deref() {
        Some("21") | Some("24") | Some("25") => vec![Some(3)],
        Some("22") | Some("23") => vec![Some(2)],
        Some("26") => vec![Some(3), None],
        _ => vec![],
    }
}

fn is_red(c: &Option<mupdf::color::AnnotationColor>) -> bool {
    match c {
        Some(mupdf::color::AnnotationColor::Rgb { red, green, blue }) => *red > 0.55 && *green < 0.4 && *blue < 0.4,
        _ => false,
    }
}

/// Где дорисовать «|», чтобы «–» стали «+»: (x, y центра, полудлина, толщина).
pub fn plus_marks(page: &PdfPage) -> Vec<(f64, f64, f64, f64)> {
    let b = page.bounds().unwrap_or(Rect { x0: 0.0, y0: 0.0, x1: 595.0, y1: 842.0 });
    let ww = (b.x1 - b.x0) as f64;
    let mut hs: Vec<[f64; 4]> = Vec::new();
    let mut vs: Vec<(f64, f64, f64)> = Vec::new();
    for a in page.annotations() {
        if !is_red(&a.color().ok().flatten()) {
            continue;
        }
        let bw = a.border_width().map(|v| v as f64).unwrap_or(-1.0);
        let strokes: Vec<Vec<(f64, f64)>> = match a.r#type() {
            Ok(PdfAnnotationType::Line) => match a.line() {
                Ok((p1, p2)) => vec![vec![(p1.x as f64, p1.y as f64), (p2.x as f64, p2.y as f64)]],
                Err(_) => vec![],
            },
            Ok(PdfAnnotationType::Ink) => a
                .ink_list()
                .map(|v| v.into_iter().map(|s| s.into_iter().map(|q| (q.x as f64, q.y as f64)).collect()).collect())
                .unwrap_or_default(),
            _ => vec![],
        };
        for s in strokes {
            if s.is_empty() {
                continue;
            }
            let (x0, x1) = (s.iter().map(|q| q.0).fold(f64::MAX, f64::min), s.iter().map(|q| q.0).fold(f64::MIN, f64::max));
            let (y0, y1) = (s.iter().map(|q| q.1).fold(f64::MAX, f64::min), s.iter().map(|q| q.1).fold(f64::MIN, f64::max));
            let (dx, dy) = (x1 - x0, y1 - y0);
            if dx > 8.0 && dx > 2.5 * dy {
                hs.push([x0, x1, (y0 + y1) / 2.0, bw]);
            } else if dy > 8.0 && dy > 2.5 * dx {
                vs.push(((x0 + x1) / 2.0, y0, y1));
            }
        }
    }
    hs.retain(|h| (h[0] + h[1]) / 2.0 > ww * 0.6);
    hs.sort_by(|a, b| a[2].partial_cmp(&b[2]).unwrap());
    let mut rows: Vec<[f64; 4]> = Vec::new();
    for h in hs {
        match rows.last_mut() {
            Some(r) if (r[2] - h[2]).abs() < 8.0 => {
                r[0] = r[0].min(h[0]);
                r[1] = r[1].max(h[1]);
                r[3] = r[3].max(h[3]);
            }
            _ => rows.push(h),
        }
    }
    let mut gaps: Vec<f64> = rows.windows(2).map(|w| w[1][2] - w[0][2]).collect();
    gaps.sort_by(|a, b| a.partial_cmp(b).unwrap());
    let step = if gaps.is_empty() {
        45.0
    } else if gaps.len() % 2 == 1 {
        gaps[gaps.len() / 2]
    } else {
        (gaps[gaps.len() / 2 - 1] + gaps[gaps.len() / 2]) / 2.0
    };
    let mut out = Vec::new();
    for r in rows {
        let xc = (r[0] + r[1]) / 2.0;
        if vs.iter().any(|v| (v.0 - xc).abs() < (r[1] - r[0]) / 2.0 && v.1 < r[2] && r[2] < v.2) {
            continue; // уже «+»
        }
        let width = if r[3] > 0.0 { r[3] } else { 2.0 };
        out.push((xc, r[2], step * 0.33, width.clamp(1.5, 5.0)));
    }
    out
}

/// Окошки «/N» в поле «Балл»: (x0, y0, x1, y1) в pt (по рендеру нижнего левого угла).
pub fn score_slots(page: &mupdf::Page) -> Vec<(f64, f64, f64, f64)> {
    let Some(a) = render_gray(page, 72.0, false) else { return vec![] };
    let (hh, ww) = (a.h, a.w);
    let (y0, y1, x0, x1) = ((hh as f64 * 0.84) as usize, (hh as f64 * 0.985) as usize, (ww as f64 * 0.02) as usize, (ww as f64 * 0.45) as usize);
    let dark = |x: usize, y: usize| a.at(x, y) < 110;
    let rowsum: Vec<usize> = (y0..y1).map(|y| (x0..x1).filter(|&x| dark(x, y)).count()).collect();
    let mut lines = Vec::new();
    let (mut inside, mut start) = (false, 0);
    for (y, &v) in rowsum.iter().enumerate() {
        if v > 0 && !inside {
            start = y;
            inside = true;
        } else if v == 0 && inside {
            lines.push((start, y));
            inside = false;
        }
    }
    if inside {
        lines.push((start, rowsum.len()));
    }
    lines.retain(|l| l.1 - l.0 >= 6);
    let Some(&(ly0, ly1)) = lines.last() else { return vec![] };
    let colsum: Vec<usize> = (x0..x1).map(|x| (y0 + ly0..y0 + ly1).filter(|&y| dark(x, y)).count()).collect();
    let mut clusters = Vec::new();
    let (mut inside, mut gap, mut end, mut st) = (false, 0, 0, 0);
    for (x, &v) in colsum.iter().enumerate() {
        if v > 0 {
            if !inside {
                st = x;
                inside = true;
            }
            gap = 0;
            end = x;
        } else if inside {
            gap += 1;
            if gap > 6 {
                clusters.push((st, end + 1));
                inside = false;
            }
        }
    }
    if inside {
        clusters.push((st, end + 1));
    }
    clusters
        .into_iter()
        .map(|(c0, c1)| ((x0 + c0) as f64, (y0 + ly0) as f64, (x0 + c1) as f64, (y0 + ly1) as f64))
        .collect()
}

#[derive(Clone, Debug, Default)]
pub struct FullMarks {
    pub plus: Vec<(f64, f64, f64, f64)>,
    /// текст, правый край, базовая линия, высота прописной
    pub scores: Vec<(String, f64, f64, f64)>,
}

pub fn full_marks(path: &Path, s: &Settings) -> FullMarks {
    let mt = mtime(path);
    if let Some(m) = FULL_CACHE.with(|c| c.borrow().get(path).filter(|v| v.0 == mt).map(|v| v.1.clone())) {
        return m;
    }
    let mut out = FullMarks::default();
    if let Ok(data) = std::fs::read(path) {
        if let Ok(doc) = PdfDocument::from_bytes(&data) {
            if let Ok(page) = doc.load_pdf_page(0) {
                let mut plus = plus_marks(&page);
                let slots = score_slots(&page);
                // у 26-го нижняя строка («Обоснование») остаётся с «–»
                let skip = if task_number(path).as_deref() == Some("26") { 1 } else { 0 };
                if skip > 0 && plus.len() > skip {
                    plus.truncate(plus.len() - skip);
                }
                out.plus = plus;
                let vals = full_scores(path, s);
                if !vals.is_empty() && !slots.is_empty() {
                    let targets: Vec<(f64, f64, f64, f64)> = if vals.len() == 2 && slots.len() >= 2 {
                        vec![slots[0], *slots.last().unwrap()]
                    } else {
                        slots.iter().take(vals.len()).copied().collect()
                    };
                    for ((cx0, cy0, _cx1, cy1), v) in targets.into_iter().zip(vals) {
                        if let Some(v) = v {
                            out.scores.push((v.to_string(), cx0 - 1.5, cy1, cy1 - cy0));
                        }
                    }
                }
            }
        }
    }
    FULL_CACHE.with(|c| c.borrow_mut().insert(path.to_path_buf(), (mt, out.clone())));
    out
}

#[cfg(test)]
mod real_blank_tests {
    use super::*;
    #[test]
    fn preserves_annotations_when_inserting_user_blank() {
        let Ok(path) = std::env::var("REDCOLOR_TEST_BLANK") else { return };
        let data = std::fs::read(path).unwrap();
        let original = PdfDocument::from_bytes(&data).unwrap();
        let before = original.load_pdf_page(0).unwrap().annotations().count();
        let original_render = original.load_page(0).unwrap().to_pixmap(&Matrix::new_scale(0.5, 0.5), &Colorspace::device_rgb(), false, true).unwrap();
        let original_pixels = original_render.samples().to_vec();
        let info = analyze_page(&original.load_page(0).unwrap(), None);
        eprintln!("quote placement={:?}, label={:?}", quote_placement(&info, 16.0), info.label);
        let (x, y, _, _, _) = quote_placement(&info, 16.0);
        assert!((x - 41.76).abs() < 6.0 && (y - 580.44).abs() < 6.0, "unexpected quote location: {x}, {y}");
        assert!(!score_slots(&original.load_page(0).unwrap()).is_empty(), "score field must be detected");
        let mut target = PdfDocument::new();
        target.new_page(mupdf::Size::new(612.0, 792.0)).unwrap();
        crate::docops::insert_with_annotations(&mut target, &original, 1, mupdf::pdf::InsertPdfOptions { target: mupdf::pdf::InsertPosition::Append, copy_annotations: true, copy_links: true, copy_widgets: true, ..Default::default() }).unwrap();
        let mut bytes = Vec::new(); target.write_to(&mut bytes).unwrap();
        let reopened = PdfDocument::from_bytes(&bytes).unwrap();
        let page = reopened.load_pdf_page(1).unwrap();
        let after = page.annotations().count();
        eprintln!("annotations before={before}, after={after}, score slots={:?}", score_slots(&page));
        assert_eq!(after, before, "annotations must survive insertion");
        let target_page = reopened.load_page(1).unwrap();
        let matrix = Matrix::new_scale(0.5, 0.5);
        let after = target_page.to_pixmap(&matrix, &Colorspace::device_rgb(), false, true).unwrap();
        assert_eq!(original_pixels.len(), after.samples().len());
        let changed = original_pixels.iter().zip(after.samples()).filter(|(a, b)| a.abs_diff(**b) > 8).count();
        assert!(changed * 1000 < original_pixels.len(), "rendered blank differs in {changed} channels of {}", original_pixels.len());
    }
}

/// Убирает «1» из файла бланка (оригинал — в backup_dir). Возвращает число удалённых.
pub fn clean_blank_file(path: &Path, backup_dir: &Path) -> usize {
    let Ok(data) = std::fs::read(path) else { return 0 };
    let Some((out, n)) = remove_comment_ones_doc(&data, None) else { return 0 };
    if n == 0 {
        return 0;
    }
    let _ = std::fs::create_dir_all(backup_dir);
    if let Some(name) = path.file_name() {
        let dst = backup_dir.join(name);
        if !dst.exists() {
            let _ = std::fs::copy(path, &dst);
        }
    }
    let tmp = path.with_extension("pdf.tmp");
    if std::fs::write(&tmp, out).is_ok() && std::fs::rename(&tmp, path).is_ok() {
        CACHE.with(|c| c.borrow_mut().remove(path));
        n
    } else {
        0
    }
}
