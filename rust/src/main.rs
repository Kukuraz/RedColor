// RedColor — редактор PDF для проверки работ. Автор: Maksim Belonoskin, Zelenograd, Moscow, Russia.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod actions;
mod clip;
mod blanks;
mod docops;
mod edit;
mod features;
mod formula_bridge;
mod images;
mod instance;
mod items;
mod panel;
mod pdfio;
mod render;
mod settings;
mod text;
mod textedit;

use std::cell::RefCell;
use std::path::{Path, PathBuf};
use std::rc::Rc;

use slint::{ComponentHandle, Image, Model, ModelRc, Rgb8Pixel, SharedPixelBuffer, SharedString, VecModel};

use render::{RenderService, Rendered, Req};
use settings::Settings;

slint::include_modules!();

pub const APP_VERSION: &str = "2.0";
const PAGE_GAP: f32 = 14.0;
pub(crate) const MARGIN: f32 = 8.0;
const ZOOM_STEPS: [f32; 21] = [
    0.1, 0.125, 0.25, 0.333, 0.5, 0.667, 0.75, 0.8, 0.9, 1.0, 1.1, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0, 4.0, 5.0, 6.4, 8.0,
];
const IMG_EXT: [&str; 9] = ["png", "jpg", "jpeg", "bmp", "gif", "tif", "tiff", "webp", "jfif"];

#[derive(Clone, Copy, PartialEq)]
enum Fit {
    Auto,
    Width,
    Page,
    None,
}

pub(crate) struct PageSlot {
    w: f32,
    h: f32,
    y: f32,
    img: Option<(Image, f32)>,
}

struct Doc {
    key: u64,
    ver: u64,
    path: Option<PathBuf>,
    title: String,
    pages: Vec<PageSlot>,
    zoom: f32,
    fit: Fit,
    content_w: f32,
    content_h: f32,
    view_y: f32,
    view_x: f32,
    modified: bool,
    src: Rc<Vec<u8>>,
    items: Vec<Vec<items::Item>>,
    undo: Vec<docops::Snap>,
    redo: Vec<docops::Snap>,
    sel: Vec<(usize, usize)>,
    ov_page: usize,
}

impl Doc {
    fn max_w(&self) -> f32 {
        self.pages.iter().map(|p| p.w).fold(1.0, f32::max)
    }

    fn relayout(&mut self) {
        let mut y = PAGE_GAP;
        for p in self.pages.iter_mut() {
            p.y = y;
            y += p.h + PAGE_GAP;
        }
        self.content_w = (self.max_w() + 2.0 * MARGIN) * self.zoom;
        self.content_h = (y + PAGE_GAP) * self.zoom;
    }

    fn current_page(&self, view_h: f32) -> usize {
        let top = self.view_y / self.zoom;
        let bottom = top + view_h / self.zoom;
        let mut best = (0.0f32, 0usize);
        for (i, p) in self.pages.iter().enumerate() {
            let vis = (p.y + p.h).min(bottom) - p.y.max(top);
            if vis > best.0 + 1e-6 {
                best = (vis, i);
            }
        }
        best.1
    }
}

struct App {
    win: slint::Weak<AppWindow>,
    settings: Settings,
    docs: Vec<Doc>,
    cur: Option<usize>,
    next_key: u64,
    render: RenderService,
    pages_model: Rc<VecModel<PageView>>,
    tabs_model: Rc<VecModel<TabInfo>>,
    recent_model: Rc<VecModel<RecentItem>>,
    toast_timer: slint::Timer,
    scale: f32,
    tool: String,
    blanks: Vec<(String, PathBuf)>,
    blanks_timer: slint::Timer,
    fonts: panel::FontFamilies,
    drag: Option<edit::Drag>,
    editing: Option<textedit::Editing>,
    text_cache: text::FontCache,
    formula_imgs: RefCell<std::collections::HashMap<(String, String), Image>>,
    quotes: blanks::QuoteBank,
    signature_id: Option<String>,
    hits: Vec<(usize, f64, f64, f64, f64)>,
    hit_idx: usize,
    last_mouse: Option<(f64, f64)>,
    sig_strokes: Vec<Vec<(f64, f64)>>,
    sig_kind: String,
    image_cache: RefCell<std::collections::HashMap<(Rc<str>, String), Image>>,
    clipboard_items: Vec<items::Item>,
    clipboard_marker: String,
}

thread_local! {
    static APP: RefCell<Option<Rc<RefCell<App>>>> = const { RefCell::new(None) };
}

fn with_app<R>(f: impl FnOnce(&mut App) -> R) -> Option<R> {
    let app = APP.with(|a| a.borrow().clone())?;
    let mut b = app.try_borrow_mut().ok()?;
    Some(f(&mut b))
}

fn quant_zoom(z: f32) -> f32 {
    let step: f32 = 1.18;
    step.powf((z.max(0.05).ln() / step.ln()).ceil())
}

fn open_bytes(path: &Path) -> Result<(Vec<u8>, mupdf::Document), String> {
    let data = std::fs::read(path).map_err(|e| format!("не удалось прочитать файл: {e}"))?;
    let ext = path.extension().and_then(|e| e.to_str()).unwrap_or("pdf").to_lowercase();
    if IMG_EXT.contains(&ext.as_str()) {
        let img = mupdf::Document::from_bytes(&data, &ext).map_err(|e| e.to_string())?;
        let pdf = img.convert_to_pdf(0, -1, 0).map_err(|e| e.to_string())?;
        let mut out = Vec::new();
        pdf.write_to(&mut out).map_err(|e| e.to_string())?;
        let d = mupdf::Document::from_bytes(&out, "application/pdf").map_err(|e| e.to_string())?;
        return Ok((out, d));
    }
    let d = mupdf::Document::from_bytes(&data, "application/pdf").map_err(|e| e.to_string())?;
    Ok((data, d))
}

impl App {
    fn win(&self) -> AppWindow {
        self.win.upgrade().expect("window")
    }

    fn toast(&mut self, text: &str) {
        let w = self.win();
        w.set_toast(text.into());
        let weak = self.win.clone();
        self.toast_timer.start(slint::TimerMode::SingleShot, std::time::Duration::from_millis(2800), move || {
            if let Some(w) = weak.upgrade() {
                w.set_toast(SharedString::new());
            }
        });
    }

    fn refresh_recent(&mut self) {
        let items: Vec<RecentItem> = self
            .settings
            .recent()
            .into_iter()
            .filter(|p| Path::new(p).exists())
            .map(|p| {
                let pb = PathBuf::from(&p);
                RecentItem {
                    name: pb.file_name().map(|s| s.to_string_lossy().to_string()).unwrap_or_default().into(),
                    folder: pb.parent().map(|s| s.to_string_lossy().to_string()).unwrap_or_default().into(),
                    path: p.into(),
                }
            })
            .collect();
        self.recent_model.set_vec(items);
    }

    fn refresh_tabs(&mut self) {
        let tabs: Vec<TabInfo> = self
            .docs
            .iter()
            .map(|d| TabInfo { title: d.title.clone().into(), modified: d.modified })
            .collect();
        self.tabs_model.set_vec(tabs);
        self.win().set_current_tab(self.cur.map(|c| c as i32).unwrap_or(-1));
    }

    fn open_paths(&mut self, paths: Vec<PathBuf>) {
        let mut last = None;
        for p in paths {
            let p = std::fs::canonicalize(&p).unwrap_or(p);
            if let Some(i) = self.docs.iter().position(|d| d.path.as_deref() == Some(p.as_path())) {
                last = Some(i);
                continue;
            }
            match open_bytes(&p) {
                Ok((data, doc)) => {
                    let n = doc.page_count().unwrap_or(0);
                    if n <= 0 {
                        self.toast(&format!("В файле {} нет доступных страниц", p.display()));
                        continue;
                    }
                    let mut pages = Vec::with_capacity(n as usize);
                    for i in 0..n {
                        let (w, h) = doc
                            .load_page(i)
                            .and_then(|pg| pg.bounds())
                            .map(|r| (r.x1 - r.x0, r.y1 - r.y0))
                            .unwrap_or((595.0, 842.0));
                        pages.push(PageSlot { w, h, y: 0.0, img: None });
                    }
                    let key = self.next_key;
                    self.next_key += 1;
                    // редактируемые пометки RedColor (сохранённые любой версией) — снова объекты
                    let (items, stripped, skipped) = pdfio::extract_layers(&data, n as usize);
                    let src = stripped.unwrap_or(data);
                    if skipped > 0 {
                        self.toast(&format!(
                            "На {skipped} стр. есть неподдерживаемые пометки RedColor — они остаются частью страницы"
                        ));
                    }
                    self.render.load(key, 1, src.clone());
                    let is_pdf = p.extension().map(|e| e.eq_ignore_ascii_case("pdf")).unwrap_or(false);
                    let mut title = p.file_name().map(|s| s.to_string_lossy().to_string()).unwrap_or_default();
                    if !is_pdf {
                        title = p.with_extension("pdf").file_name().map(|s| s.to_string_lossy().to_string()).unwrap_or(title);
                    }
                    let mut d = Doc {
                        key,
                        ver: 1,
                        path: if is_pdf { Some(p.clone()) } else { None },
                        title,
                        src: Rc::new(src),
                        items,
                        undo: Vec::new(),
                        redo: Vec::new(),
                        sel: Vec::new(),
                        ov_page: usize::MAX,
                        pages,
                        zoom: 1.0,
                        fit: match self.settings.str("zoom_mode", "auto").as_str() {
                            "width" => Fit::Width,
                            "page" => Fit::Page,
                            _ => Fit::Auto,
                        },
                        content_w: 0.0,
                        content_h: 0.0,
                        view_y: 0.0,
                        view_x: 0.0,
                        modified: false,
                    };
                    d.relayout();
                    self.docs.push(d);
                    last = Some(self.docs.len() - 1);
                    self.settings.add_recent(&p.to_string_lossy());
                }
                Err(e) => self.toast(&format!("Не удалось открыть {}: {e}", p.display())),
            }
        }
        self.refresh_recent();
        if let Some(i) = last {
            let fresh = !self.docs[i].modified && self.docs[i].undo.is_empty();
            self.activate(Some(i));
            // красные «1» в комментариях бланков — сразу при открытии (с отменой)
            if fresh && self.settings.bool("auto_remove_ones", true) {
                self.clean_ones_current(true);
            }
        }
    }

    fn activate(&mut self, i: Option<usize>) {
        // Не удерживать декодированные изображения закрытых или неактивных вкладок.
        if self.cur != i {
            self.image_cache.borrow_mut().clear();
            self.formula_imgs.borrow_mut().clear();
        }
        if let Some(c) = self.cur {
            // запоминаем прокрутку уходящей вкладки и освобождаем её картинки
            let w = self.win();
            if let Some(d) = self.docs.get_mut(c) {
                d.view_y = -w.get_view_y() / 1.0;
                d.view_x = -w.get_view_x();
                for p in d.pages.iter_mut() {
                    p.img = None;
                }
            }
        }
        self.cur = i.filter(|&i| i < self.docs.len());
        self.refresh_tabs();
        self.apply_fit();
        self.push_layout();
        if let Some(d) = self.cur.and_then(|c| self.docs.get(c)) {
            let w = self.win();
            w.set_view_y(-d.view_y);
            w.set_view_x(-d.view_x);
        }
        self.update_render();
    }

    fn doc(&mut self) -> Option<&mut Doc> {
        let c = self.cur?;
        self.docs.get_mut(c)
    }

    /// Передаёт в интерфейс размеры и позиции страниц при текущем масштабе.
    fn push_layout(&mut self) {
        let w = self.win();
        let Some(c) = self.cur else {
            self.pages_model.set_vec(Vec::new());
            return;
        };
        let d = &self.docs[c];
        let z = d.zoom;
        let maxw = d.max_w();
        let rows: Vec<PageView> = d
            .pages
            .iter()
            .map(|p| PageView {
                x: (MARGIN + (maxw - p.w) / 2.0) * z,
                y: p.y * z,
                w: p.w * z,
                h: p.h * z,
                img: p.img.as_ref().map(|i| i.0.clone()).unwrap_or_default(),
                has_img: p.img.is_some(),
            })
            .collect();
        self.pages_model.set_vec(rows);
        w.set_content_w(d.content_w);
        w.set_content_h(d.content_h);
        w.set_total_pages(d.pages.len() as i32);
        w.set_zoom_pct((z * 72.0 / 96.0 * 100.0).round() as i32);
        self.push_overlay();
    }

    fn apply_fit(&mut self) {
        let w = self.win();
        let (vw, vh) = (w.get_view_w() - 48.0, w.get_view_h() - 24.0);
        let vh_full = w.get_view_h();
        let Some(d) = self.doc() else { return };
        if d.pages.is_empty() {
            return;
        }
        let cur = d.current_page(vh_full);
        let z = match d.fit {
            Fit::Auto => (vw.max(50.0) / (d.max_w() + 2.0 * MARGIN)).min(96.0 / 72.0),
            Fit::Width => vw.max(50.0) / (d.max_w() + 2.0 * MARGIN),
            Fit::Page => {
                let p = &d.pages[cur];
                (vw.max(50.0) / p.w).min(vh.max(50.0) / (p.h + 2.0 * PAGE_GAP))
            }
            Fit::None => return,
        };
        if (z - d.zoom).abs() > 1e-4 {
            self.set_zoom(z, None);
        }
    }

    /// Масштаб с сохранением точки под курсором (anchor — в координатах окна просмотра).
    fn set_zoom(&mut self, z: f32, anchor: Option<(f32, f32)>) {
        let z = z.clamp(0.05, 16.0);
        let w = self.win();
        let (vw, vh) = (w.get_view_w(), w.get_view_h());
        let (vx, vy) = (-w.get_view_x(), -w.get_view_y());
        let Some(d) = self.doc() else { return };
        let (ax, ay) = anchor.unwrap_or((vw / 2.0, vh / 2.0));
        let old = d.zoom;
        let old_cw = d.content_w.max(vw);
        // точка документа под якорем (pt)
        let off_old = (old_cw - d.content_w) / 2.0;
        let px = (vx + ax - off_old) / old;
        let py = (vy + ay) / old;
        d.zoom = z;
        d.relayout();
        let new_cw = d.content_w.max(vw);
        let off_new = (new_cw - d.content_w) / 2.0;
        let nx = (px * z + off_new - ax).clamp(0.0, (new_cw - vw).max(0.0));
        let ny = (py * z - ay).clamp(0.0, (d.content_h - vh).max(0.0));
        self.push_layout();
        w.set_view_x(-nx);
        w.set_view_y(-ny);
        self.update_render();
    }

    fn zoom_step(&mut self, dir: i32) {
        let Some(d) = self.doc() else { return };
        d.fit = Fit::None;
        let z = d.zoom;
        let nz = if dir > 0 {
            ZOOM_STEPS.iter().copied().find(|&s| s > z * 1.01).unwrap_or(8.0)
        } else {
            ZOOM_STEPS.iter().rev().copied().find(|&s| s < z * 0.99).unwrap_or(0.1)
        };
        self.set_zoom(nz, None);
    }

    fn go_to_page(&mut self, i: i64) {
        let w = self.win();
        let vh = w.get_view_h();
        let Some(d) = self.doc() else { return };
        if d.pages.is_empty() {
            return;
        }
        let i = i.clamp(0, d.pages.len() as i64 - 1) as usize;
        let y = (d.pages[i].y * d.zoom - 8.0).clamp(0.0, (d.content_h - vh).max(0.0));
        w.set_view_y(-y);
        self.update_render();
    }

    fn page_step(&mut self, delta: i64) {
        let vh = self.win().get_view_h();
        let Some(d) = self.doc() else { return };
        let cur = d.current_page(vh) as i64;
        self.go_to_page(cur + delta);
    }

    /// Какие страницы видны: заказываем рендер нужного качества, дальние освобождаем.
    fn update_render(&mut self) {
        let w = self.win();
        let (vh, scale) = (w.get_view_h(), self.scale);
        let vy = -w.get_view_y();
        let Some(c) = self.cur else {
            self.render.want(Vec::new());
            return;
        };
        self.docs[c].view_y = vy;
        let cur = self.docs[c].current_page(vh);
        if self.docs[c].ov_page != cur {
            // пометки рисуются для страниц рядом с текущей
            self.docs[c].ov_page = cur;
            self.push_overlay();
        }
        let d = &mut self.docs[c];
        w.set_cur_page(cur as i32 + 1);
        let top = vy / d.zoom;
        let bottom = top + vh / d.zoom;
        let span = bottom - top;
        let center = (top + bottom) / 2.0;
        let need = quant_zoom(d.zoom * scale);
        let mut cand: Vec<(f32, usize, f32)> = Vec::new();
        for (i, p) in d.pages.iter().enumerate() {
            if p.y + p.h >= top - span && p.y <= bottom + span {
                let mut z = need;
                let maxpx = 3600.0f32 * 3600.0;
                if p.w * p.h * z * z > maxpx {
                    z = (maxpx / (p.w * p.h)).sqrt();
                }
                let z = (z * 10000.0).round() / 10000.0;
                let inview = p.y + p.h >= top && p.y <= bottom;
                let dist = ((p.y + p.h / 2.0) - center).abs();
                let has = p.img.as_ref().map(|i| i.1 >= z * 0.97).unwrap_or(false);
                if !has {
                    cand.push((if inview { 0.0 } else { 10.0 } + dist / 10000.0, i, z));
                }
            }
        }
        cand.sort_by(|a, b| a.0.partial_cmp(&b.0).unwrap());
        let reqs = cand.into_iter().map(|(_, idx, zoom)| Req { key: d.key, ver: d.ver, idx, zoom }).collect();
        self.render.want(reqs);
        // память: далёкие страницы без картинки
        let mut changed = false;
        for (i, p) in d.pages.iter_mut().enumerate() {
            if p.img.is_some() && (i + 4 < cur || i > cur + 6) {
                p.img = None;
                changed = true;
                self.pages_model.set_row_data(
                    i,
                    PageView { img: Image::default(), has_img: false, ..self.pages_model.row_data(i).unwrap() },
                );
            }
        }
        let _ = changed;
    }

    fn on_rendered(&mut self, r: Rendered) {
        let Some(c) = self.cur else { return };
        let d = &mut self.docs[c];
        if d.key != r.req.key || d.ver != r.req.ver || r.req.idx >= d.pages.len() {
            return;
        }
        let buf = SharedPixelBuffer::<Rgb8Pixel>::clone_from_slice(&r.rgb, r.width, r.height);
        let img = Image::from_rgb8(buf);
        let slot = &mut d.pages[r.req.idx];
        if slot.img.as_ref().map(|i| i.1 > r.req.zoom * 1.01).unwrap_or(false) {
            return;
        }
        slot.img = Some((img.clone(), r.req.zoom));
        if let Some(row) = self.pages_model.row_data(r.req.idx) {
            self.pages_model.set_row_data(r.req.idx, PageView { img, has_img: true, ..row });
        }
    }

    fn close_doc(&mut self, i: usize) {
        if i >= self.docs.len() {
            return;
        }
        if !self.ask_save(i) {
            return;
        }
        let d = self.docs.remove(i);
        self.render.close(d.key);
        if self.docs.is_empty() {
            self.image_cache.borrow_mut().clear();
            self.formula_imgs.borrow_mut().clear();
        }
        let next = if self.docs.is_empty() { None } else { Some(i.min(self.docs.len() - 1)) };
        self.cur = None;
        self.activate(next);
    }

    fn open_dialog(&mut self) {
        let mut dlg = rfd::FileDialog::new()
            .set_title("Открыть")
            .add_filter("PDF и изображения", &["pdf", "png", "jpg", "jpeg", "bmp", "gif", "tif", "tiff", "webp"])
            .add_filter("Все файлы", &["*"]);
        let last = self.settings.str("last_dir", "");
        if !last.is_empty() {
            dlg = dlg.set_directory(last);
        }
        if let Some(files) = dlg.pick_files() {
            if let Some(dir) = files.first().and_then(|f| f.parent()) {
                self.settings.set("last_dir", serde_json::Value::String(dir.to_string_lossy().to_string()));
            }
            self.open_paths(files);
        }
    }

    /// Перед выходом: вопрос о несохранённых документах, запоминание окна.
    fn can_quit(&mut self) -> bool {
        for i in 0..self.docs.len() {
            if self.docs[i].modified {
                self.activate(Some(i));
                if !self.ask_save(i) {
                    return false;
                }
            }
        }
        let max = self.win().window().is_maximized();
        self.settings.set_save("maximized", serde_json::json!(max));
        true
    }

    fn key(&mut self, text: &str, ctrl: bool, shift: bool, _alt: bool) {
        use slint::platform::Key;
        let k = |key: Key| -> SharedString { key.into() };
        // русская раскладка: те же клавиши
        let lat_s = panel::ru_to_en(text);
        let lat = lat_s.as_str();
        if self.editing.is_some() {
            // во время правки текста — только Esc и сочетания с Ctrl
            if text == k(Key::Escape).as_str() {
                return self.finish_edit();
            }
            if !ctrl {
                return;
            }
        }
        if self.win().get_dialog() != "" || self.win().get_menu_visible() {
            if text == k(Key::Escape).as_str() {
                self.win().set_dialog("".into());
                self.win().set_menu_visible(false);
            }
            return;
        }
        if text == k(Key::F4).as_str() {
            return self.toggle_panel();
        }
        if text == k(Key::Escape).as_str() {
            if self.clear_selection() {
                return;
            }
            return self.set_tool("select");
        }
        if text == k(Key::Delete).as_str() || text == k(Key::Backspace).as_str() {
            return self.delete_selected();
        }
        if !ctrl && self.has_selection() {
            let step = if shift { 10.0 } else { 1.0 };
            let d = if text == k(Key::LeftArrow).as_str() {
                Some((-step, 0.0))
            } else if text == k(Key::RightArrow).as_str() {
                Some((step, 0.0))
            } else if text == k(Key::UpArrow).as_str() {
                Some((0.0, -step))
            } else if text == k(Key::DownArrow).as_str() {
                Some((0.0, step))
            } else {
                None
            };
            if let Some((dx, dy)) = d {
                self.nudge(dx, dy);
                return;
            }
        }
        if text == k(Key::F1).as_str() {
            return self.show_info();
        }
        if ctrl && shift {
            let id = match lat {
                "n" => "view.goto",
                "t" => "page.insert_blank",
                "d" => "page.delete",
                "e" => "page.extract",
                "i" => "page.insert_file",
                "o" => "view.organize",
                "=" | "+" => "page.rotate_cw",
                "-" | "_" => "page.rotate_ccw",
                "f" => return self.format("fit", "1"),
                "l" => return self.format("align", "left"),
                "c" => return self.format("align", "center"),
                "r" => return self.format("align", "right"),
                _ => "",
            };
            if !id.is_empty() {
                return self.action(id);
            }
        }
        if ctrl && _alt {
            match lat {
                "1" => return self.action("blank.clean_doc"),
                "q" => return self.action("app.quotes"),
                "k" => return self.action("app.hotkeys"),
                _ => {}
            }
        }
        if ctrl {
            match lat {
                "o" => return self.open_dialog(),
                "n" => return self.action("file.new"),
                "k" => return self.action("app.settings"),
                "q" => {
                    if self.can_quit() {
                        let _ = slint::quit_event_loop();
                    }
                    return;
                }
                "d" => return self.duplicate(),
                "c" => return self.copy(false),
                "x" => return self.copy(true),
                "v" => return self.paste(),
                "a" => return self.select_all(),
                "b" => return self.format("bold", if self.settings.bool("text_bold", false) { "0" } else { "1" }),
                "i" => return self.format("italic", if self.settings.bool("text_italic", false) { "0" } else { "1" }),
                "]" => return self.size_step(1),
                "[" => return self.size_step(-1),
                "s" | "z" | "y" | "p" | "f" => {
                    let id = match lat {
                        "s" => if shift { "file.save_as" } else { "file.save" },
                        "z" => "edit.undo",
                        "y" => "edit.redo",
                        "p" => "file.print",
                        _ => "view.find",
                    };
                    return self.action(id);
                }
                "w" => {
                    if let Some(c) = self.cur {
                        self.close_doc(c);
                    }
                    return;
                }
                "=" | "+" => return self.zoom_step(1),
                "-" => return self.zoom_step(-1),
                "1" => {
                    if let Some(d) = self.doc() {
                        d.fit = Fit::None;
                    }
                    return self.set_zoom(96.0 / 72.0, None);
                }
                "2" => {
                    if let Some(d) = self.doc() {
                        d.fit = Fit::Width;
                    }
                    return self.apply_fit();
                }
                "0" => {
                    if let Some(d) = self.doc() {
                        d.fit = Fit::Page;
                    }
                    return self.apply_fit();
                }
                _ => {}
            }
            if text == k(Key::Tab).as_str() || text == "\t" {
                let n = self.docs.len();
                if n > 0 {
                    let c = self.cur.unwrap_or(0);
                    let next = if shift { (c + n - 1) % n } else { (c + 1) % n };
                    self.activate(Some(next));
                }
                return;
            }
            if text == k(Key::Home).as_str() {
                return self.go_to_page(0);
            }
            if text == k(Key::End).as_str() {
                return self.go_to_page(i64::MAX / 2);
            }
            if text == k(Key::PageDown).as_str() {
                return self.page_step(1);
            }
            if text == k(Key::PageUp).as_str() {
                return self.page_step(-1);
            }
        } else {
            if text == k(Key::PageDown).as_str() {
                return self.page_step(1);
            }
            if text == k(Key::PageUp).as_str() {
                return self.page_step(-1);
            }
            if _alt {
                let c = match lat {
                    "1" => "#ff0000",
                    "2" => "#000000",
                    "3" => "#1f4fd6",
                    "4" => "#118a2e",
                    _ => "",
                };
                if !c.is_empty() {
                    return self.format("color", c);
                }
                return;
            }
            if lat == "b" && !shift {
                return self.action("blank.menu");
            }
            if lat == "q" && shift {
                return self.action("quote.here");
            }
            if let Some((_, tool)) = panel::TOOL_KEYS.iter().find(|(key, _)| *key == lat) {
                if !shift {
                    return self.set_tool(tool);
                }
            }
        }
    }
}

fn main() {
    let files: Vec<PathBuf> = std::env::args().skip(1).filter(|a| !a.starts_with('-')).map(PathBuf::from).collect();
    // уже запущен — передаём файлы ему
    if instance::send_to_running(&files) {
        return;
    }
    if std::env::var_os("SLINT_BACKEND").is_none() {
        // OpenGL (femtovg): чёткий шрифт. Меньше памяти, но мыльнее текст — SLINT_BACKEND=winit-software
        unsafe { std::env::set_var("SLINT_BACKEND", "winit-femtovg") };
    }
    let settings = Settings::load();
    let win = AppWindow::new().expect("window");
    Theme::get(&win).set_dark(settings.str("theme", "dark") != "light");
    Theme::get(&win).set_accent(
        slint::Color::from_argb_encoded(
            0xff000000 | u32::from_str_radix(settings.str("accent", "#2680eb").trim_start_matches('#'), 16).unwrap_or(0x2680eb),
        ),
    );
    win.set_version(APP_VERSION.into());

    let weak = win.as_weak();
    let render = RenderService::start(move |r| {
        let _ = slint::invoke_from_event_loop(move || {
            with_app(|a| a.on_rendered(r));
        });
    });
    let _ = weak;

    let app = Rc::new(RefCell::new(App {
        win: win.as_weak(),
        settings,
        docs: Vec::new(),
        cur: None,
        next_key: 1,
        render,
        pages_model: Rc::new(VecModel::default()),
        tabs_model: Rc::new(VecModel::default()),
        recent_model: Rc::new(VecModel::default()),
        toast_timer: slint::Timer::default(),
        scale: win.window().scale_factor(),
        tool: "select".into(),
        blanks: Vec::new(),
        blanks_timer: slint::Timer::default(),
        fonts: panel::scan_fonts(),
        drag: None,
        editing: None,
        text_cache: text::FontCache::default(),
        formula_imgs: RefCell::new(Default::default()),
        quotes: blanks::QuoteBank::default(),
        signature_id: None,
        hits: Vec::new(),
        hit_idx: 0,
        last_mouse: None,
        sig_strokes: Vec::new(),
        sig_kind: String::new(),
        image_cache: RefCell::new(Default::default()),
        clipboard_items: Vec::new(),
        clipboard_marker: String::new(),
    }));
    APP.with(|a| *a.borrow_mut() = Some(app.clone()));
    {
        let a = app.borrow();
        win.set_pages(ModelRc::from(a.pages_model.clone()));
        win.set_tabs(ModelRc::from(a.tabs_model.clone()));
        win.set_recent(ModelRc::from(a.recent_model.clone()));
    }
    app.borrow_mut().refresh_recent();
    app.borrow_mut().init_panel();
    actions::connect(&win);
    edit::connect(&win);
    features::connect(&win);
    win.window().on_close_requested(|| {
        let ok = with_app(|a| a.can_quit()).unwrap_or(true);
        if ok { slint::CloseRequestResponse::HideWindow } else { slint::CloseRequestResponse::KeepWindowShown }
    });

    win.on_open_file(|| {
        // диалог блокирует цикл событий — вызываем после текущего события
        slint::Timer::single_shot(std::time::Duration::from_millis(1), || {
            with_app(|a| a.open_dialog());
        });
    });
    win.on_open_recent(|p| {
        with_app(|a| a.open_paths(vec![PathBuf::from(p.as_str())]));
    });
    win.on_tab_activate(|i| {
        with_app(|a| a.activate(Some(i as usize)));
    });
    win.on_tab_close(|i| {
        with_app(|a| a.close_doc(i as usize));
    });
    win.on_show_home(|| {
        with_app(|a| a.activate(None));
    });
    win.on_viewport_changed(|| {
        with_app(|a| {
            a.scale = a.win().window().scale_factor();
            if a.doc().map(|d| d.fit != Fit::None).unwrap_or(false) {
                a.apply_fit();
            }
            a.update_render();
        });
    });
    win.on_wheel_zoom(|dy, mx, my| {
        with_app(|a| {
            let w = a.win();
            let (vx, vy) = (-w.get_view_x(), -w.get_view_y());
            let Some(d) = a.doc() else { return };
            d.fit = Fit::None;
            let z = d.zoom * 1.0015f32.powf(dy);
            // mx, my — в координатах содержимого; якорь — в координатах окна
            a.set_zoom(z, Some((mx - vx, my - vy)));
        });
    });
    win.on_goto(|n| {
        with_app(|a| a.go_to_page(n as i64 - 1));
    });
    win.on_page_step(|d| {
        with_app(|a| a.page_step(d as i64));
    });
    win.on_fit_width(|| {
        with_app(|a| {
            if let Some(d) = a.doc() {
                d.fit = Fit::Width;
            }
            a.apply_fit();
        });
    });
    win.on_fit_page(|| {
        with_app(|a| {
            if let Some(d) = a.doc() {
                d.fit = Fit::Page;
            }
            a.apply_fit();
        });
    });
    win.on_zoom_step(|d| {
        with_app(|a| a.zoom_step(d));
    });
    win.on_key(|t, c, s, al| {
        with_app(|a| a.key(t.as_str(), c, s, al));
    });

    instance::listen(|paths| {
        let _ = slint::invoke_from_event_loop(move || {
            with_app(|a| {
                a.open_paths(paths);
                let w = a.win();
                w.window().set_minimized(false);
                w.show().ok();
            });
        });
    });

    if !files.is_empty() {
        slint::Timer::single_shot(std::time::Duration::from_millis(10), move || {
            with_app(|a| a.open_paths(files));
        });
    }
    // развернуть уже показанное окно (до показа OpenGL-окно игнорирует это)
    win.show().expect("show");
    let maximized = app.borrow().settings.bool("maximized", true);
    let weak = win.as_weak();
    slint::Timer::single_shot(std::time::Duration::from_millis(30), move || {
        if let Some(w) = weak.upgrade() {
            w.window().set_maximized(maximized);
        }
    });
    slint::run_event_loop().expect("run");
}
