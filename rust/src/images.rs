// RedColor — редактор PDF для проверки работ. Автор: Maksim Belonoskin, Zelenograd, Moscow, Russia.
//! Картинки и подписи на странице; хранилище подписей (общее с версией на Python).

use std::path::PathBuf;

use base64::Engine;
use mupdf::pdf::{PdfDocument, PdfObject};
use mupdf::{Colorspace, Matrix};
use serde_json::{Value, json};
use slint::{Image, Rgba8Pixel, SharedPixelBuffer};

use crate::App;
use crate::items::{ImageObj, Item, P};
use crate::settings::data_dir;

pub fn b64(data: &[u8]) -> String {
    base64::engine::general_purpose::STANDARD.encode(data)
}

pub fn unb64(s: &str) -> Vec<u8> {
    base64::engine::general_purpose::STANDARD.decode(s.trim()).unwrap_or_default()
}

/// Картинка → RGBA (с альфой, домноженной), не больше max_px по большей стороне.
pub fn decode_rgba(data: &[u8], max_px: u32) -> Option<(u32, u32, Vec<u8>)> {
    let doc = ["png", "jpg", "bmp", "gif", "webp", "tif"].iter().find_map(|m| mupdf::Document::from_bytes(data, m).ok())?;
    let page = doc.load_page(0).ok()?;
    let b = page.bounds().ok()?;
    let (w, h) = ((b.x1 - b.x0).max(1.0), (b.y1 - b.y0).max(1.0));
    let k = (max_px as f32 / w.max(h)).min(1.0);
    // у картинок 1 pt = 1 пиксель исходника при 72 dpi; масштаб к реальным пикселям
    let img = mupdf::Image::from_bytes(data).ok();
    let (iw, ih) = img.as_ref().map(|i| (i.width() as f32, i.height() as f32)).unwrap_or((w, h));
    let s = (iw / w) * k;
    let pix = page.to_pixmap(&Matrix::new_scale(s, s * (ih / h) / (iw / w)), &Colorspace::device_rgb(), true, false).ok()?;
    let (pw, ph, n, stride) = (pix.width(), pix.height(), pix.n() as usize, pix.stride() as usize);
    let src = pix.samples();
    let mut out = Vec::with_capacity((pw * ph * 4) as usize);
    for y in 0..ph as usize {
        for x in 0..pw as usize {
            let o = y * stride + x * n;
            if n >= 4 {
                out.extend_from_slice(&src[o..o + 4]);
            } else {
                out.extend_from_slice(&[src[o], src[o + 1], src[o + 2], 255]);
            }
        }
    }
    Some((pw, ph, out))
}

/// Перекраска подписи: цвет — заданный, прозрачность — исходная (как CompositionMode_SourceIn).
pub fn tint(rgba: &mut [u8], color: &str) {
    let (r, g, b) = crate::items::rgb(color);
    for px in rgba.chunks_exact_mut(4) {
        let a = px[3] as f64;
        px[0] = (r * a) as u8;
        px[1] = (g * a) as u8;
        px[2] = (b * a) as u8;
    }
}

/// Размер картинки в пикселях.
pub fn image_size(data: &[u8]) -> Option<(u32, u32)> {
    let i = mupdf::Image::from_bytes(data).ok()?;
    Some((i.width(), i.height()))
}

/// XObject картинки для PDF (перекрашенной — через пиксельную карту с альфой).
pub fn pdf_image(doc: &mut PdfDocument, im: &ImageObj) -> Result<PdfObject, String> {
    let data = unb64(&im.data);
    match im.tint.as_deref().filter(|t| !t.is_empty()) {
        None => {
            let img = mupdf::Image::from_bytes(&data).map_err(|e| e.to_string())?;
            doc.add_image(&img).map_err(|e| e.to_string())
        }
        Some(t) => {
            let (w, h, mut rgba) = decode_rgba(&data, 2400).ok_or("картинка")?;
            tint(&mut rgba, t);
            let mut pix = mupdf::Pixmap::new_with_w_h(&Colorspace::device_rgb(), w as i32, h as i32, true).map_err(|e| e.to_string())?;
            let stride = pix.stride() as usize;
            let s = pix.samples_mut();
            for y in 0..h as usize {
                s[y * stride..y * stride + w as usize * 4].copy_from_slice(&rgba[y * w as usize * 4..(y + 1) * w as usize * 4]);
            }
            let img = mupdf::Image::from_pixmap(&pix).map_err(|e| e.to_string())?;
            doc.add_image(&img).map_err(|e| e.to_string())
        }
    }
}

// ============================================================================ хранилище подписей

fn sig_dir() -> PathBuf {
    let d = data_dir().join("signatures");
    let _ = std::fs::create_dir_all(&d);
    d
}

pub fn sig_index() -> Vec<Value> {
    std::fs::read_to_string(sig_dir().join("index.json"))
        .ok()
        .and_then(|s| serde_json::from_str::<Value>(&s).ok())
        .and_then(|v| v.as_array().cloned())
        .unwrap_or_default()
        .into_iter()
        .filter(|x| x.get("file").and_then(|f| f.as_str()).map(|f| sig_dir().join(f).exists()).unwrap_or(false))
        .collect()
}

fn save_index(items: &[Value]) {
    let _ = std::fs::write(sig_dir().join("index.json"), serde_json::to_string_pretty(&Value::Array(items.to_vec())).unwrap_or_default());
}

pub fn sig_add(png: &[u8], name: &str, kind: &str) -> String {
    let now = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap_or_default();
    let sid = format!("{:010x}", now.as_nanos() as u64 & 0xff_ffff_ffff);
    let file = format!("{sid}.png");
    let _ = std::fs::write(sig_dir().join(&file), png);
    let mut items = sig_index();
    items.push(json!({"id": sid, "name": name, "file": file, "kind": kind, "created": now.as_secs_f64()}));
    save_index(&items);
    sid
}

pub fn sig_rename(sid: &str, name: &str) {
    let mut items = sig_index();
    for x in items.iter_mut() {
        if x.get("id").and_then(|v| v.as_str()) == Some(sid) {
            x["name"] = json!(name);
        }
    }
    save_index(&items);
}

pub fn sig_remove(sid: &str) {
    let items: Vec<Value> = sig_index()
        .into_iter()
        .filter(|x| {
            let keep = x.get("id").and_then(|v| v.as_str()) != Some(sid);
            if !keep {
                if let Some(f) = x.get("file").and_then(|f| f.as_str()) {
                    let _ = std::fs::remove_file(sig_dir().join(f));
                }
            }
            keep
        })
        .collect();
    save_index(&items);
}

pub fn sig_get(sid: &str) -> Option<(Vec<u8>, String)> {
    let x = sig_index().into_iter().find(|x| x.get("id").and_then(|v| v.as_str()) == Some(sid))?;
    let data = std::fs::read(sig_dir().join(x.get("file")?.as_str()?)).ok()?;
    Some((data, x.get("kind").and_then(|k| k.as_str()).unwrap_or("signature").to_string()))
}

/// PNG с прозрачным фоном из RGBA (неумноженная альфа).
pub fn encode_png(w: u32, h: u32, rgba: &[u8]) -> Vec<u8> {
    let mut out = Vec::new();
    {
        let mut enc = png::Encoder::new(&mut out, w, h);
        enc.set_color(png::ColorType::Rgba);
        enc.set_depth(png::BitDepth::Eight);
        if let Ok(mut wr) = enc.write_header() {
            let _ = wr.write_image_data(rgba);
        }
    }
    out
}

/// Подпись из картинки: светлый фон становится прозрачным, края обрезаются.
pub fn signature_from_image(data: &[u8]) -> Option<Vec<u8>> {
    let (w, h, px) = decode_rgba(data, 1600)?;
    let mut out = vec![0u8; px.len()];
    let (mut x0, mut y0, mut x1, mut y1) = (w, h, 0, 0);
    for y in 0..h {
        for x in 0..w {
            let o = ((y * w + x) * 4) as usize;
            let a = px[o + 3] as f64 / 255.0;
            // яркость на белом фоне
            let lum = (0.299 * px[o] as f64 + 0.587 * px[o + 1] as f64 + 0.114 * px[o + 2] as f64) / 255.0 + (1.0 - a);
            let ink = ((0.86 - lum.min(1.0)) / 0.5).clamp(0.0, 1.0);
            if ink > 0.02 {
                out[o] = 0;
                out[o + 1] = 0;
                out[o + 2] = 0;
                out[o + 3] = (ink * 255.0) as u8;
                x0 = x0.min(x);
                y0 = y0.min(y);
                x1 = x1.max(x);
                y1 = y1.max(y);
            }
        }
    }
    if x1 <= x0 || y1 <= y0 {
        return None;
    }
    let (cw, ch) = (x1 - x0 + 1, y1 - y0 + 1);
    let mut crop = Vec::with_capacity((cw * ch * 4) as usize);
    for y in y0..=y1 {
        let o = ((y * w + x0) * 4) as usize;
        crop.extend_from_slice(&out[o..o + (cw * 4) as usize]);
    }
    Some(encode_png(cw, ch, &crop))
}

/// Подпись из штрихов (нарисованная мышью): рисуем векторно в PDF и растрируем с прозрачностью.
pub fn signature_from_strokes(strokes: &[Vec<(f64, f64)>], w: f64, h: f64, width: f64) -> Option<Vec<u8>> {
    let mut ops = format!("q 0 0 0 RG {width:.2} w 1 J 1 j 1 0 0 -1 0 {h:.2} cm\n");
    let (mut x0, mut y0, mut x1, mut y1) = (f64::MAX, f64::MAX, f64::MIN, f64::MIN);
    for s in strokes {
        for (i, (x, y)) in s.iter().enumerate() {
            ops += &format!("{x:.2} {y:.2} {}\n", if i == 0 { "m" } else { "l" });
            x0 = x0.min(*x);
            y0 = y0.min(*y);
            x1 = x1.max(*x);
            y1 = y1.max(*y);
        }
        if s.len() == 1 {
            ops += &format!("{:.2} {:.2} l\n", s[0].0 + 0.3, s[0].1 + 0.3);
        }
        ops += "S\n";
    }
    ops += "Q\n";
    if x1 < x0 {
        return None;
    }
    render_ops_png(&ops, w, h, (x0 - width, y0 - width, x1 + width, y1 + width))
}

/// Подпись из текста красивым шрифтом.
pub fn signature_from_text(text: &str, font: &crate::text::LoadedFont) -> Option<Vec<u8>> {
    let size = 60.0;
    let tw = font.width(text, size) + 20.0;
    let h = size * 1.6;
    let mut hex = String::from("<");
    for ch in text.chars() {
        hex += &format!("{:04X}", font.glyph(ch).0.max(0) as u16);
    }
    hex.push('>');
    let mut doc = PdfDocument::new();
    let mut page = doc.new_page(mupdf::Size::new(tw as f32, h as f32)).ok()?;
    let fobj = doc.add_font(&font.font).ok()?;
    let mut res = page.resources().ok()?;
    let mut fd = doc.new_dict().ok()?;
    fd.dict_put("F0", fobj).ok()?;
    res.dict_put("Font", fd).ok()?;
    let ops = format!("BT 0 0 0 rg /F0 {size} Tf 10 {:.2} Td {hex} Tj ET\n", h * 0.35);
    page.insert_contents(&mut doc, ops.as_bytes(), true).ok()?;
    let mut bytes = Vec::new();
    doc.write_to(&mut bytes).ok()?;
    rasterize_crop(&bytes, 4.0)
}

fn render_ops_png(ops: &str, w: f64, h: f64, _bbox: (f64, f64, f64, f64)) -> Option<Vec<u8>> {
    let mut doc = PdfDocument::new();
    let mut page = doc.new_page(mupdf::Size::new(w as f32, h as f32)).ok()?;
    page.insert_contents(&mut doc, ops.as_bytes(), true).ok()?;
    let mut bytes = Vec::new();
    doc.write_to(&mut bytes).ok()?;
    rasterize_crop(&bytes, 3.0)
}

/// Растр страницы с прозрачным фоном, обрезанный по содержимому.
fn rasterize_crop(pdf: &[u8], scale: f32) -> Option<Vec<u8>> {
    let doc = mupdf::Document::from_bytes(pdf, "application/pdf").ok()?;
    let page = doc.load_page(0).ok()?;
    let pix = page.to_pixmap(&Matrix::new_scale(scale, scale), &Colorspace::device_rgb(), true, false).ok()?;
    let (w, h, n, stride) = (pix.width(), pix.height(), pix.n() as usize, pix.stride() as usize);
    let s = pix.samples();
    let (mut x0, mut y0, mut x1, mut y1) = (w, h, 0, 0);
    for y in 0..h {
        for x in 0..w {
            if s[y as usize * stride + x as usize * n + n - 1] > 8 {
                x0 = x0.min(x);
                y0 = y0.min(y);
                x1 = x1.max(x);
                y1 = y1.max(y);
            }
        }
    }
    if x1 <= x0 || y1 <= y0 {
        return None;
    }
    let mut out = Vec::new();
    for y in y0..=y1 {
        for x in x0..=x1 {
            let o = y as usize * stride + x as usize * n;
            let a = s[o + n - 1];
            // снимаем домножение на альфу
            let un = |v: u8| if a > 0 { ((v as u32 * 255) / a as u32).min(255) as u8 } else { 0 };
            out.extend_from_slice(&[un(s[o]), un(s[o + 1]), un(s[o + 2]), a]);
        }
    }
    Some(encode_png(x1 - x0 + 1, y1 - y0 + 1, &out))
}

impl App {
    /// Картинка для показа (кеш по данным и цвету).
    pub(crate) fn image_for(&self, im: &ImageObj) -> Image {
        let key = (im.data.clone(), im.tint.clone().unwrap_or_default());
        if let Some(i) = self.image_cache.borrow().get(&key) {
            return i.clone();
        }
        let img = decode_rgba(&unb64(&im.data), 2400)
            .map(|(w, h, mut px)| {
                if let Some(t) = im.tint.as_deref().filter(|t| !t.is_empty()) {
                    tint(&mut px, t);
                }
                Image::from_rgba8_premultiplied(SharedPixelBuffer::<Rgba8Pixel>::clone_from_slice(&px, w, h))
            })
            .unwrap_or_default();
        let mut cache = self.image_cache.borrow_mut();
        // Декодированные изображения могут занимать десятки мегабайт каждое.
        if cache.len() >= 32 {
            cache.clear();
        }
        cache.insert(key, img.clone());
        img
    }

    /// Вставка картинки: по центру точки, вписывается в страницу (как insert_image_data в версии на Python).
    pub(crate) fn insert_image_data(&mut self, page: usize, q: P, data: &[u8], signature: bool, tint: Option<String>, width: Option<f64>) {
        let Some((iw, ih)) = image_size(data) else {
            self.toast("Не удалось прочитать изображение");
            return;
        };
        let (pw, ph) = self.page_size_pt(page);
        let (iw, ih) = (iw.max(1) as f64, ih.max(1) as f64);
        let (w, h) = match width {
            Some(w) => (w, ih * w / iw),
            None => {
                let sc = (pw * 0.5 / iw).min(ph * 0.6 / ih).min(1.0);
                (iw * sc, ih * sc)
            }
        };
        let it = ImageObj {
            x: (q.x - w / 2.0).clamp(0.0, (pw - w).max(0.0)),
            y: (q.y - h / 2.0).clamp(0.0, (ph - h).max(0.0)),
            w,
            h,
            rot: 0.0,
            tint,
            signature,
            data: b64(data).into(),
        };
        self.add_item(page, Item::Image(it), true);
    }

    pub(crate) fn place_image_dialog(&mut self, page: usize, q: P) {
        let mut dlg = rfd::FileDialog::new().set_title("Изображение").add_filter("Изображения", &["png", "jpg", "jpeg", "bmp", "gif", "webp"]);
        let last = self.settings.str("last_dir", "");
        if !last.is_empty() {
            dlg = dlg.set_directory(last);
        }
        if let Some(p) = dlg.pick_file() {
            if let Ok(data) = std::fs::read(&p) {
                self.insert_image_data(page, q, &data, false, None, None);
            }
        }
        self.set_tool("select");
    }

    pub(crate) fn signature_color(&self) -> String {
        let c = self.settings.str("signature_color", "");
        if c.is_empty() { self.settings.str("text_color", "#ff0000") } else { c }
    }

    pub(crate) fn place_signature(&mut self, page: usize, q: P) {
        let sid = self
            .signature_id
            .clone()
            .or_else(|| sig_index().first().and_then(|x| x.get("id").and_then(|v| v.as_str()).map(String::from)));
        let Some(sid) = sid else {
            self.open_signature_dialog("signature");
            return;
        };
        let Some((data, kind)) = sig_get(&sid) else { return };
        let (pw, _) = self.page_size_pt(page);
        let w = pw * if kind == "initials" { 0.09 } else { 0.2 };
        let col = self.signature_color();
        self.insert_image_data(page, q, &data, true, Some(col), Some(w));
        self.set_tool("select");
    }

    pub(crate) fn arm_signature(&mut self, sid: &str) {
        self.signature_id = Some(sid.to_string());
        self.set_tool("signature");
        self.toast("Щёлкните на странице, чтобы поставить подпись");
    }
}
