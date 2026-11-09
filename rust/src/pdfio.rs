// RedColor — редактор PDF для проверки работ. Автор: Maksim Belonoskin, Zelenograd, Moscow, Russia.
//! Редактируемый слой RedColor в PDF — тот же формат, что у версии на Python:
//! у страницы ключ /RedColorItems → поток JSON {"v":1,"items":[…]}, /RedColorContent → поток с пометками.

use mupdf::pdf::{PdfDocument, PdfObject};
use mupdf::{Buffer, Error};

use crate::items::{Item, pdf_ops};

type Res<T> = Result<T, String>;

fn e(err: Error) -> String {
    err.to_string()
}

/// Читает слой RedColor и убирает его из страниц. Страницы, где есть объекты, которые Rust-версия ещё
/// не умеет (текст, картинки), не трогаются: их пометки остаются частью страницы, ничего не теряется.
/// Возвращает (объекты по страницам, новые байты документа — если что-то сняли).
pub fn extract_layers(data: &[u8], n: usize) -> (Vec<Vec<Item>>, Option<Vec<u8>>, usize) {
    let mut out = vec![Vec::new(); n];
    let mut skipped = 0;
    let Ok(doc) = PdfDocument::from_bytes(data) else { return (out, None, 0) };
    let mut changed = false;
    for i in 0..n {
        match extract_page(&doc, i) {
            Ok(Some(items)) => {
                out[i] = items;
                changed = true;
            }
            Ok(None) => {}
            Err(msg) => {
                if msg == "unsupported" {
                    skipped += 1;
                } else {
                    eprintln!("layer restore error (стр. {}): {msg}", i + 1);
                }
            }
        }
    }
    if !changed {
        return (out, None, skipped);
    }
    let mut buf = Vec::new();
    match doc.write_to(&mut buf) {
        Ok(_) => (out, Some(buf), skipped),
        Err(err) => {
            eprintln!("layer restore write error: {err}");
            (vec![Vec::new(); n], None, skipped)
        }
    }
}

fn extract_page(doc: &PdfDocument, i: usize) -> Res<Option<Vec<Item>>> {
    let mut page = doc.find_page(i as i32).map_err(e)?;
    let Some(iref) = page.get_dict("RedColorItems").map_err(e)? else { return Ok(None) };
    if !iref.is_indirect().map_err(e)? {
        return Ok(None);
    }
    // поток читается по косвенной ссылке (у разрешённого словаря нет номера объекта)
    let raw = iref.read_stream().map_err(e)?;
    let v: serde_json::Value = serde_json::from_slice(&raw).map_err(|x| x.to_string())?;
    let arr = v.get("items").and_then(|x| x.as_array()).cloned().ok_or("unsupported")?;
    let mut items = Vec::with_capacity(arr.len());
    for st in arr {
        match serde_json::from_value::<Item>(st) {
            Ok(it) => items.push(it),
            Err(_) => return Err("unsupported".into()),
        }
    }
    // снимаем поток пометок из содержимого страницы
    let cref = page.get_dict("RedColorContent").map_err(e)?.ok_or("unsupported")?;
    if !cref.is_indirect().map_err(e)? { return Err("unsupported".into()); }
    let cx = cref.as_indirect().map_err(e)?;
    let contents = page.get_dict("Contents").map_err(e)?.ok_or("unsupported")?;
    if contents.is_array().map_err(e)? {
        let mut arr = doc.new_array().map_err(e)?;
        let mut found = false;
        for x in contents.array_iter().map_err(e)? {
            let x = x.map_err(e)?;
            if x.is_indirect().map_err(e)? && x.as_indirect().map_err(e)? == cx {
                found = true;
                continue;
            }
            arr.array_push(x).map_err(e)?;
        }
        if !found { return Err("unsupported".into()); }
        if arr.len().map_err(e)? == 0 {
            page.dict_put("Contents", PdfObject::new_null()).map_err(e)?;
        } else {
            page.dict_put("Contents", arr).map_err(e)?;
        }
    } else if contents.is_indirect().map_err(e)? && contents.as_indirect().map_err(e)? == cx {
        page.dict_put("Contents", PdfObject::new_null()).map_err(e)?;
    } else {
        return Err("unsupported".into());
    }
    page.dict_delete("RedColorItems").map_err(e)?;
    page.dict_delete("RedColorContent").map_err(e)?;
    Ok(Some(items))
}

fn num(o: &PdfObject) -> f64 {
    o.as_float().map(|v| v as f64).unwrap_or(0.0)
}

/// Матрица «экранные координаты страницы (pt, y вниз, с учётом поворота) → пространство PDF».
fn display_to_pdf(page: &PdfObject) -> Res<[f64; 6]> {
    let bx = page
        .get_dict_inheritable("CropBox")
        .map_err(e)?
        .or(page.get_dict_inheritable("MediaBox").map_err(e)?);
    let (mut x0, mut y0, mut x1, mut y1) = (0.0, 0.0, 595.0, 842.0);
    if let Some(b) = bx {
        if b.len().map_err(e)? >= 4 {
            let g = |k: i32| b.get_array(k).ok().flatten().map(|o| num(&o)).unwrap_or(0.0);
            x0 = g(0).min(g(2));
            x1 = g(0).max(g(2));
            y0 = g(1).min(g(3));
            y1 = g(1).max(g(3));
        }
    }
    let rot = page
        .get_dict_inheritable("Rotate")
        .map_err(e)?
        .map(|o| o.as_int().unwrap_or(0))
        .unwrap_or(0)
        .rem_euclid(360);
    Ok(match rot {
        90 => [0.0, 1.0, 1.0, 0.0, x0, y0],
        180 => [-1.0, 0.0, 0.0, 1.0, x1, y0],
        270 => [0.0, -1.0, -1.0, 0.0, x1, y1],
        _ => [1.0, 0.0, 0.0, -1.0, x0, y1],
    })
}

fn ensure_sub_dict(doc: &PdfDocument, res: &mut PdfObject, key: &str) -> Res<PdfObject> {
    if let Some(d) = res.get_dict(key).map_err(e)? {
        if d.is_dict().map_err(e)? {
            return Ok(d);
        }
    }
    let d = doc.new_dict().map_err(e)?;
    res.dict_put(key, d).map_err(e)?;
    Ok(res.get_dict(key).map_err(e)?.expect("dict"))
}

/// Шрифты и формулы, уже добавленные в документ при сохранении.
struct TextRes {
    fonts: std::collections::HashMap<std::path::PathBuf, (String, PdfObject)>,
    forms: std::collections::HashMap<(String, String), (String, PdfObject, [f64; 4])>,
    images: usize,
}

/// Формула (SVG) → Form XObject: SVG → одностраничный PDF → содержимое и ресурсы переносятся в документ.
fn formula_form(doc: &mut PdfDocument, svg: &str) -> Res<(PdfObject, [f64; 4])> {
    let sdoc = mupdf::Document::from_bytes(svg.as_bytes(), "image/svg+xml").map_err(e)?;
    let pdf = sdoc.convert_to_pdf(0, -1, 0).map_err(e)?;
    let page = pdf.find_page(0).map_err(e)?;
    let mb = page.get_dict_inheritable("MediaBox").map_err(e)?.ok_or("MediaBox")?;
    let g = |k: i32| mb.get_array(k).ok().flatten().map(|o| num(&o)).unwrap_or(0.0);
    let bbox = [g(0), g(1), g(2), g(3)];
    let mut content = Vec::new();
    if let Some(c) = page.get_dict("Contents").map_err(e)? {
        if c.is_array().map_err(e)? {
            for x in c.array_iter().map_err(e)? {
                content.extend(x.map_err(e)?.read_stream().map_err(e)?);
                content.push(b'\n');
            }
        } else {
            content = c.read_stream().map_err(e)?;
        }
    }
    let mut dict = doc
        .new_object_from_str(&format!(
            "<</Type/XObject/Subtype/Form/BBox[{} {} {} {}]>>",
            bbox[0], bbox[1], bbox[2], bbox[3]
        ))
        .map_err(e)?;
    if let Some(res) = page.get_dict_inheritable("Resources").map_err(e)? {
        let gr = doc.graft_object(&res).map_err(e)?;
        dict.dict_put("Resources", gr).map_err(e)?;
    }
    let buf = Buffer::from_bytes(&content).map_err(e)?;
    let stream = doc.add_stream(&buf, Some(&dict), false).map_err(e)?;
    Ok((stream, bbox))
}

fn hex_gids(font: &crate::text::LoadedFont, s: &str) -> String {
    let mut h = String::with_capacity(s.len() * 4 + 2);
    h.push('<');
    for ch in s.chars() {
        h += &format!("{:04X}", font.glyph(ch).0.max(0) as u16);
    }
    h.push('>');
    h
}

/// Операторы текста одного объекта (в координатах страницы «как на экране»).
fn text_ops(
    doc: &mut PdfDocument,
    res: &mut TextRes,
    fonts_dict: &mut PdfObject,
    xobj_dict: &mut PdfObject,
    t: &crate::text::Text,
    fams: &crate::panel::FontFamilies,
    cache: &crate::text::FontCache,
) -> Res<String> {
    let font = cache.for_text(fams, t);
    if font.is_none() && t.blocks.iter().flat_map(|b| &b.runs).any(|r| matches!(r, crate::text::Run::T(s) if !s.trim().is_empty())) {
        return Err(format!("Не удалось загрузить шрифт «{}» для сохранения текста", t.font));
    }
    let lay = crate::text::layout(t, font.as_deref(), t.w);
    let (r, g, b) = crate::items::rgb(&t.color);
    let (sn, cs) = t.rot.to_radians().sin_cos();
    let mut s = format!("q {cs:.6} {sn:.6} {:.6} {cs:.6} {:.3} {:.3} cm\n", -sn, t.x, t.y);
    if let Some(f) = font.as_ref() {
        let fname = match res.fonts.get(&f.path) {
            Some((n, _)) => n.clone(),
            None => {
                let obj = doc.add_font(&f.font).map_err(e)?;
                let n = format!("RCF{}", res.fonts.len());
                res.fonts.insert(f.path.clone(), (n.clone(), obj));
                n
            }
        };
        let fobj = res.fonts[&f.path].1.clone();
        fonts_dict.dict_put(fname.as_str(), fobj).map_err(e)?;
        for line in &lay.lines {
            for sg in &line.segs {
                let txt = sg.text.trim_end();
                if txt.trim().is_empty() {
                    continue;
                }
                s += &format!(
                    "BT {r:.4} {g:.4} {b:.4} rg /{fname} {:.3} Tf 1 0 0 -1 {:.3} {:.3} Tm {} Tj ET\n",
                    t.size,
                    sg.x,
                    line.baseline,
                    hex_gids(f, txt)
                );
            }
        }
    }
    for line in &lay.lines {
        for fb in &line.formulas {
            let Some(fm) = t.formulas.get(&fb.key) else { return Err("Не найдены данные формулы".into()) };
            let key = (fb.key.clone(), t.color.clone());
            if !res.forms.contains_key(&key) {
                match formula_form(doc, &fm.colored_svg(&t.color)) {
                    Ok((obj, bbox)) => {
                        let n = format!("RCX{}", res.forms.len());
                        res.forms.insert(key.clone(), (n, obj, bbox));
                    }
                    Err(err) => return Err(format!("Не удалось сохранить формулу: {err}")),
                }
            }
            let (n, obj, bb) = res.forms[&key].clone();
            xobj_dict.dict_put(n.as_str(), obj).map_err(e)?;
            let (fw, fh) = ((bb[2] - bb[0]).max(1e-3), (bb[3] - bb[1]).max(1e-3));
            let (sx, sy) = (fb.w / fw, fb.h / fh);
            s += &format!(
                "q {sx:.6} 0 0 {:.6} {:.3} {:.3} cm /{n} Do Q\n",
                -sy,
                fb.x - bb[0] * sx,
                fb.y + fb.h + bb[1] * sy
            );
        }
    }
    s += "Q\n";
    Ok(s)
}

/// Готовый PDF: исходный документ + пометки отдельным слоем (+ их описание для правки).
pub fn build_output(
    src: &[u8],
    items: &[Vec<Item>],
    creator: &str,
    fams: &crate::panel::FontFamilies,
    cache: &crate::text::FontCache,
) -> Res<Vec<u8>> {
    let mut doc = PdfDocument::from_bytes(src).map_err(e)?;
    let mut tres = TextRes { fonts: Default::default(), forms: Default::default(), images: 0 };
    for (i, page_items) in items.iter().enumerate() {
        if page_items.is_empty() {
            continue;
        }
        let mut page = doc.load_pdf_page(i as i32).map_err(e)?;
        let pobj = page.object();
        let m = display_to_pdf(&pobj)?;
        // ресурсы для пометок: шрифт для номеров овалов и прозрачность маркера
        let mut res = page.resources().map_err(e)?;
        let mut fonts = ensure_sub_dict(&doc, &mut res, "Font")?;
        let font = doc
            .new_object_from_str("<</Type/Font/Subtype/Type1/BaseFont/Helvetica-Bold/Encoding/WinAnsiEncoding>>")
            .map_err(e)?;
        fonts.dict_put("RCHB", font).map_err(e)?;
        let mut gs = ensure_sub_dict(&doc, &mut res, "ExtGState")?;
        let g = doc.new_object_from_str("<</Type/ExtGState/CA 0.4/ca 0.4/BM/Multiply>>").map_err(e)?;
        gs.dict_put("RCa0", g).map_err(e)?;

        let mut xobjs = ensure_sub_dict(&doc, &mut res, "XObject")?;
        // порядок как на экране: каждый объект поверх предыдущих
        let mut body = String::new();
        for it in page_items {
            match it {
                Item::Text(t) => body += &text_ops(&mut doc, &mut tres, &mut fonts, &mut xobjs, t, fams, cache)?,
                Item::Image(im) => {
                    match crate::images::pdf_image(&mut doc, im) {
                        Ok(obj) => {
                            let n = format!("RCI{}", tres.images);
                            tres.images += 1;
                            xobjs.dict_put(n.as_str(), obj).map_err(e)?;
                            let (sn, cs) = im.rot.to_radians().sin_cos();
                            // картинка рисуется в квадрат 1×1 (y вверх) — переворачиваем под «экранные» координаты
                            body += &format!(
                                "q {cs:.6} {sn:.6} {:.6} {cs:.6} {:.3} {:.3} cm {:.3} 0 0 {:.3} 0 {:.3} cm /{n} Do Q\n",
                                -sn,
                                im.x,
                                im.y,
                                im.w,
                                -im.h,
                                im.h
                            );
                        }
                        Err(err) => return Err(format!("Не удалось сохранить изображение на странице {}: {err}", i + 1)),
                    }
                }
                other => body += &pdf_ops(std::slice::from_ref(other)),
            }
        }
        page.wrap_contents(&mut doc).map_err(e)?;
        let ops = format!("q {} {} {} {} {} {} cm\n{}Q\n", m[0], m[1], m[2], m[3], m[4], m[5], body);
        let cx = page.insert_contents(&mut doc, ops.as_bytes(), true).map_err(e)?;
        let json = serde_json::json!({"v": 1, "items": page_items});
        let buf = Buffer::from_bytes(serde_json::to_string(&json).map_err(|x| x.to_string())?.as_bytes()).map_err(e)?;
        let stream = doc.add_stream(&buf, None, true).map_err(e)?;
        let mut pobj = page.object();
        pobj.dict_put("RedColorItems", stream).map_err(e)?;
        pobj.dict_put("RedColorContent", doc.new_indirect(cx, 0).map_err(e)?).map_err(e)?;
    }
    // создатель документа
    if let Ok(mut trailer) = doc.trailer() {
        if let Ok(Some(mut info)) = trailer.get_dict("Info") {
            if let Ok(s) = doc.new_string(creator) {
                let _ = info.dict_put("Creator", s);
            }
        } else if let (Ok(mut info), Ok(s)) = (doc.new_dict(), doc.new_string(creator)) {
            let _ = info.dict_put("Creator", s);
            if let Ok(ind) = doc.add_object(&info) {
                let _ = trailer.dict_put("Info", ind);
            }
        }
    }
    let mut out = Vec::new();
    doc.write_to(&mut out).map_err(e)?;
    Ok(out)
}

/// Сначала полностью записываем временный файл рядом с оригиналом, затем заменяем оригинал.
pub fn replace_file(data: &[u8], dst: &std::path::Path) -> Res<()> {
    use std::io::Write;
    let mut temp = None;
    for n in 0..100 {
        let tmp = dst.with_extension(format!("pdf.redcolor.{}.{n}.tmp", std::process::id()));
        match std::fs::OpenOptions::new().write(true).create_new(true).open(&tmp) {
            Ok(mut file) => {
                if let Err(err) = file.write_all(data).and_then(|_| file.sync_all()) {
                    drop(file);
                    let _ = std::fs::remove_file(&tmp);
                    return Err(err.to_string());
                }
                drop(file);
                temp = Some(tmp);
                break;
            }
            Err(err) if err.kind() == std::io::ErrorKind::AlreadyExists => continue,
            Err(err) => return Err(err.to_string()),
        }
    }
    let tmp = temp.ok_or("Не удалось создать временный файл")?;
    for attempt in 0..10 {
        match std::fs::rename(&tmp, dst) {
            Ok(()) => return Ok(()),
            Err(err) if err.kind() == std::io::ErrorKind::PermissionDenied => {
                std::thread::sleep(std::time::Duration::from_millis(200 + 150 * attempt));
            }
            Err(err) => {
                let _ = std::fs::remove_file(&tmp);
                return Err(err.to_string());
            }
        }
    }
    let _ = std::fs::remove_file(&tmp);
    Err("locked".to_string())
}

#[cfg(test)]
mod save_tests {
    use super::*;

    #[test]
    fn shape_layer_round_trips_through_pdf() {
        let mut pdf = PdfDocument::new();
        pdf.new_page(mupdf::Size::new(300.0, 400.0)).unwrap();
        let mut source = Vec::new();
        pdf.write_to(&mut source).unwrap();
        let item = Item::Shape(crate::items::Shape {
            x: 10.0, y: 20.0, w: 30.0, h: 40.0, rot: 0.0,
            shape: "rect".into(), color: "#ff0000".into(), width: 1.0,
            direction: 0, number: None, num_size: 12.0,
        });
        let output = build_output(&source, &[vec![item.clone()]], "test", &Default::default(), &Default::default()).unwrap();
        let (items, stripped, skipped) = extract_layers(&output, 1);
        assert_eq!(skipped, 0);
        assert_eq!(items, vec![vec![item]]);
        assert!(stripped.is_some());
    }

    #[test]
    fn layer_without_matching_content_is_not_extracted() {
        let mut pdf = PdfDocument::new();
        pdf.new_page(mupdf::Size::new(300.0, 400.0)).unwrap();
        let mut source = Vec::new();
        pdf.write_to(&mut source).unwrap();
        let item = Item::Shape(crate::items::Shape {
            x: 10.0, y: 20.0, w: 30.0, h: 40.0, rot: 0.0, shape: "rect".into(),
            color: "#ff0000".into(), width: 1.0, direction: 0, number: None, num_size: 12.0,
        });
        let output = build_output(&source, &[vec![item]], "test", &Default::default(), &Default::default()).unwrap();
        let pdf = PdfDocument::from_bytes(&output).unwrap();
        let mut page = pdf.find_page(0).unwrap();
        page.dict_delete("RedColorContent").unwrap();
        let mut broken = Vec::new();
        pdf.write_to(&mut broken).unwrap();
        let (items, stripped, skipped) = extract_layers(&broken, 1);
        assert_eq!(skipped, 1);
        assert!(items[0].is_empty());
        assert!(stripped.is_none());
    }

    #[test]
    fn replace_existing_file_uses_complete_new_data() {
        let dir = std::env::current_dir().unwrap().join(format!("redcolor-save-test-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let path = dir.join("document.pdf");
        std::fs::write(&path, b"old contents").unwrap();
        replace_file(b"new", &path).unwrap();
        assert_eq!(std::fs::read(&path).unwrap(), b"new");
        std::fs::remove_file(path).unwrap();
        std::fs::remove_dir(dir).unwrap();
    }
}
