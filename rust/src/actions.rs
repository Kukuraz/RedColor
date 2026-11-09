// RedColor — редактор PDF для проверки работ. Автор: Maksim Belonoskin, Zelenograd, Moscow, Russia.
//! Команды интерфейса: режимы левой панели, инструменты, формат текста, бланки, подписи.

use std::path::PathBuf;
use std::rc::Rc;

use serde_json::{Value, json};
use slint::{ComponentHandle, Image, ModelRc, SharedString, VecModel};

use crate::panel::{self, action_name, color, hex};
use crate::{App, AppWindow, BlankItem, Fit, SigItem, TextProps, with_app};
#[allow(unused_imports)]
use crate::features;

const MODES: [&str; 4] = ["all", "edit", "convert", "sign"];

impl App {
    pub(crate) fn init_panel(&mut self) {
        let w = self.win();
        let fonts: Vec<SharedString> = panel::font_list(&self.fonts).into_iter().map(Into::into).collect();
        w.set_fonts(ModelRc::new(VecModel::from(fonts)));
        let tab = self.settings.i64("left_tab", 1).clamp(0, 3) as usize;
        w.set_mode(MODES[tab].into());
        w.set_panel_visible(self.settings.bool("left_panel", true));
        w.set_float_x(self.settings.f64("rust_float_x", 12.0).max(0.0) as f32);
        w.set_float_y(self.settings.f64("rust_float_y", 12.0).max(0.0) as f32);
        w.set_float_pinned(self.settings.bool("rust_float_pinned", false));
        w.set_ink_color(color(&self.settings.str("ink_color", "#ff0000")));
        w.set_ink_width(fmt_num(self.settings.f64("ink_width", 1.5)).into());
        let sig = self.settings.str("signature_color", "");
        let sig = if sig.is_empty() { self.settings.str("text_color", "#ff0000") } else { sig };
        w.set_sig_color(color(&sig));
        self.push_text_props();
        self.refresh_blanks();
        self.refresh_signatures();
        // папка бланков обновляется сама: положили новый PDF — он сразу в списке
        self.blanks_timer.start(slint::TimerMode::Repeated, std::time::Duration::from_secs(3), || {
            with_app(|a| a.refresh_blanks());
        });
    }

    pub(crate) fn push_text_props(&mut self) {
        let s = &self.settings;
        let mut font = s.str("text_font", "Minion Pro");
        if !self.fonts.contains_key(&font) {
            font = ["Minion Pro", "Times New Roman", "Arial"]
                .into_iter()
                .find(|f| self.fonts.contains_key(*f))
                .unwrap_or("Arial")
                .to_string();
        }
        let props = TextProps {
            font: font.into(),
            size: fmt_num(s.f64("text_size", 12.0)).into(),
            color: color(&s.str("text_color", "#ff0000")),
            bold: s.bool("text_bold", false),
            italic: s.bool("text_italic", false),
            align: s.str("text_align", "left").into(),
            auto: s.bool("text_size_auto", true),
        };
        self.win().set_text_props(props);
    }

    pub(crate) fn toggle_panel(&mut self) {
        let w = self.win();
        let vis = !w.get_panel_visible();
        w.set_panel_visible(vis);
        self.settings.set_save("left_panel", json!(vis));
    }

    pub(crate) fn set_mode(&mut self, mode: &str) {
        let w = self.win();
        w.set_mode(mode.into());
        w.set_panel_visible(true);
        if let Some(i) = MODES.iter().position(|m| *m == mode) {
            self.settings.set("left_tab", json!(i));
        }
        self.settings.set_save("left_panel", json!(true));
    }

    pub(crate) fn set_tool(&mut self, tool: &str) {
        if tool != "text" && self.editing.is_some() {
            self.finish_edit();
        }
        self.tool = tool.to_string();
        let w = self.win();
        w.set_tool(tool.into());
        // формат текста виден при выделенном тексте и для текстовых инструментов
        let show = matches!(tool, "text" | "quote" | "formula") || !self.selected_texts().is_empty();
        w.set_show_format(show);
        if tool == "signature" && self.signature_id.is_none() && crate::images::sig_index().is_empty() {
            self.open_signature_dialog("signature");
        }
    }

    /// Изменение формата текста из панели (пока — настройки для нового текста).
    pub(crate) fn format(&mut self, key: &str, val: &str) {
        let s = &mut self.settings;
        match key {
            "font" => s.set("text_font", json!(val)),
            "size" => {
                if let Ok(v) = val.replace(',', ".").parse::<f64>() {
                    if (1.0..=400.0).contains(&v) {
                        s.set("text_size", json!(v));
                        s.set("text_size_auto", json!(false));
                    }
                }
            }
            "color" => s.set("text_color", json!(val)),
            "bold" => s.set("text_bold", json!(val == "1")),
            "italic" => s.set("text_italic", json!(val == "1")),
            "align" => s.set("text_align", json!(val)),
            "auto" => s.set("text_size_auto", json!(val == "1")),
            "fit" => {
                s.set("text_size_auto", json!(true));
            }
            _ => {}
        }
        self.settings.save();
        self.push_text_props();
        if matches!(key, "font" | "size" | "color" | "bold" | "italic" | "align" | "fit") {
            self.format_selected_texts(key, val);
        }
        if key == "color" {
            // цвет — также для выделенных фигур и рисунков
            self.apply_to_selection(Some(val), None);
        }
    }

    pub(crate) fn size_step(&mut self, d: i32) {
        let sizes = [6.0, 7.0, 8.0, 9.0, 10.0, 11.0, 12.0, 13.0, 14.0, 16.0, 18.0, 20.0, 24.0, 28.0, 32.0, 36.0, 48.0, 60.0, 72.0];
        let cur = self.settings.f64("text_size", 12.0);
        let next = if d > 0 {
            sizes.iter().copied().find(|&s| s > cur + 0.01).unwrap_or(72.0)
        } else {
            sizes.iter().rev().copied().find(|&s| s < cur - 0.01).unwrap_or(6.0)
        };
        self.format("size", &next.to_string());
    }

    pub(crate) fn refresh_blanks(&mut self) {
        let dir = self.settings.str("blanks_dir", "");
        let files = panel::blank_files(&dir);
        let w = self.win();
        let set = !dir.trim().is_empty() && PathBuf::from(&dir).is_dir();
        w.set_blanks_dir_set(set);
        w.set_blanks_dir_label(
            if set {
                format!("Папка: {}", PathBuf::from(&dir).file_name().map(|s| s.to_string_lossy().to_string()).unwrap_or(dir.clone()))
            } else {
                "Выбрать папку с бланками…".to_string()
            }
            .into(),
        );
        if files == self.blanks {
            return;
        }
        let items: Vec<BlankItem> = files
            .iter()
            .map(|(l, p)| BlankItem { label: l.clone().into(), path: p.to_string_lossy().to_string().into() })
            .collect();
        w.set_blanks(ModelRc::new(VecModel::from(items)));
        self.blanks = files;
    }

    pub(crate) fn refresh_signatures(&mut self) {
        let items: Vec<SigItem> = panel::signatures()
            .into_iter()
            .map(|s| SigItem {
                id: s.id.into(),
                name: s.name.into(),
                img: Image::load_from_path(&s.file).unwrap_or_default(),
            })
            .collect();
        self.win().set_signatures(ModelRc::from(Rc::new(VecModel::from(items))));
    }

    fn choose_blanks_dir(&mut self) {
        let mut dlg = rfd::FileDialog::new().set_title("Папка с бланками");
        let cur = self.settings.str("blanks_dir", "");
        if !cur.is_empty() {
            dlg = dlg.set_directory(cur);
        }
        if let Some(d) = dlg.pick_folder() {
            self.settings.set_save("blanks_dir", json!(d.to_string_lossy()));
            self.blanks.clear();
            self.refresh_blanks();
            let n = self.blanks.len();
            self.toast(&format!("Бланков в папке: {n}"));
        }
    }

    /// Команда по идентификатору (как QAction в версии на Python).
    pub(crate) fn action(&mut self, id: &str) {
        if let Some(q) = id.strip_prefix("search:") {
            return self.search_action(q);
        }
        if let Some(m) = id.strip_prefix("mode.") {
            return self.set_mode(m);
        }
        if let Some(t) = id.strip_prefix("tool.") {
            return self.set_tool(t);
        }
        match id {
            "file.open" => slint::Timer::single_shot(std::time::Duration::from_millis(1), || {
                with_app(|a| a.open_dialog());
            }),
            "file.close" => {
                if let Some(c) = self.cur {
                    self.close_doc(c);
                }
            }
            "file.quit" => {
                let _ = slint::quit_event_loop();
            }
            "edit.undo" => self.undo(),
            "edit.redo" => self.redo(),
            "edit.delete" => self.delete_selected(),
            "edit.duplicate" => self.duplicate(),
            "edit.select_all" => self.select_all(),
            "file.save" | "file.save_as" => {
                let as_new = id == "file.save_as";
                slint::Timer::single_shot(std::time::Duration::from_millis(1), move || {
                    with_app(|a| {
                        if let Some(c) = a.cur {
                            if as_new {
                                a.save_as_doc(c);
                            } else {
                                a.save_doc(c, None);
                            }
                        }
                    });
                });
            }
            "view.zoom_in" => self.zoom_step(1),
            "view.zoom_out" => self.zoom_step(-1),
            "view.actual" => {
                if let Some(d) = self.doc() {
                    d.fit = Fit::None;
                }
                self.set_zoom(96.0 / 72.0, None);
            }
            "view.fit_width" | "view.fit_page" => {
                if let Some(d) = self.doc() {
                    d.fit = if id == "view.fit_width" { Fit::Width } else { Fit::Page };
                }
                self.apply_fit();
            }
            "view.next_page" => self.page_step(1),
            "view.prev_page" => self.page_step(-1),
            "view.first_page" => self.go_to_page(0),
            "view.last_page" => self.go_to_page(i64::MAX / 2),
            "view.panel" => self.toggle_panel(),
            "blank.choose_dir" => slint::Timer::single_shot(std::time::Duration::from_millis(1), || {
                with_app(|a| a.choose_blanks_dir());
            }),
            "blank.open_dir" => {
                let d = self.settings.str("blanks_dir", "");
                if !d.is_empty() {
                    let _ = std::process::Command::new("explorer").arg(d).spawn();
                }
            }
            "file.new" => self.new_blank_pdf(),
            "file.merge" => self.later(|a| a.merge_files()),
            "file.compress" => self.later(|a| a.compress()),
            "file.export_images" => self.later(|a| a.export_images()),
            "file.print" => self.later(|a| a.print_doc()),
            "app.menu" => self.app_menu(),
            "page.rotate_cw" | "page.rotate_ccw" => {
                let cur = self.current_page_index();
                self.rotate_pages(&[cur], if id == "page.rotate_cw" { 90 } else { -90 });
            }
            "page.delete" => {
                let cur = self.current_page_index();
                self.delete_pages(&[cur]);
            }
            "page.insert_file" => self.later(|a| a.insert_from_file_dialog()),
            "page.insert_blank" => {
                let at = self.current_page_index() + 1;
                self.insert_blank_page(at);
            }
            "page.extract" => {
                let cur = self.current_page_index() + 1;
                self.input_dialog("Извлечь страницы", "Страницы (например, 1-3, 5):", &cur.to_string(), "extract");
            }
            "page.move_up" => self.move_page(-1),
            "page.move_down" => self.move_page(1),
            "page.replace" => self.later(|a| a.replace_page_dialog()),
            "view.organize" => self.show_menu(
                "Систематизация страниц",
                ["page.rotate_cw", "page.rotate_ccw", "page.delete", "page.move_up", "page.move_down", "page.insert_blank", "page.insert_file", "page.replace", "page.extract"]
                    .iter()
                    .map(|i| crate::features::menu(i, action_name(i)))
                    .collect(),
            ),
            "view.goto" => {
                let cur = self.current_page_index() + 1;
                self.input_dialog("Перейти к странице", "Номер страницы:", &cur.to_string(), "goto");
            }
            "view.find" => {
                let w = self.win();
                w.set_find_visible(true);
                w.set_find_gen(w.get_find_gen() + 1);
            }
            "blank.menu" => self.blank_menu(),
            "blank.toggle_quote" => {
                let v = !self.settings.bool("auto_quote_on_blank", true);
                self.settings.set_save("auto_quote_on_blank", json!(v));
            }
            "blank.clean_doc" => self.clean_ones_current(false),
            "blank.clean_folder" => self.later(|a| a.clean_ones_folder()),
            "quote.here" => self.quote_here(),
            "app.quotes" => self.quotes_dialog(),
            "edit.add_quote" => self.add_selected_to_quotes(),
            "sign.menu" => self.sign_menu(),
            "sign.new" => self.open_signature_dialog("signature"),
            "sign.new_initials" => self.open_signature_dialog("initials"),
            "app.hotkeys" => self.hotkeys_dialog(),
            "app.settings" => self.settings_dialog(),
            "app.default_pdf" => self.later(|a| a.make_default()),
            "app.about" => self.about(),
            "app.info" => self.show_info(),
            _ => {
                if !self.param_action(id) {
                    self.toast(&format!("Команда «{}» недоступна", action_name(id)));
                }
            }
        }
    }

    /// Выполнить после текущего события (диалоги Windows блокируют цикл событий).
    pub(crate) fn later(&mut self, f: impl FnOnce(&mut App) + 'static) {
        slint::Timer::single_shot(std::time::Duration::from_millis(1), move || {
            with_app(f);
        });
    }

    /// Строка «Найти текст или инструмент»: запускает команду с подходящим названием.
    fn search_action(&mut self, q: &str) {
        let q = q.trim().to_lowercase();
        if q.is_empty() {
            return;
        }
        if let Some((id, _)) = panel::ACTIONS.iter().find(|(_, n)| n.to_lowercase().contains(&q)) {
            return self.action(id);
        }
        self.toast("Такой команды нет. Поиск по тексту документа — следующим этапом");
    }
}

fn fmt_num(v: f64) -> String {
    if (v - v.round()).abs() < 0.05 { format!("{}", v.round() as i64) } else { format!("{v}") }
}

pub(crate) fn connect(win: &AppWindow) {
    win.on_float_position_changed(|x, y, pinned| {
        with_app(|a| {
            a.settings.set("rust_float_x", json!(x));
            a.settings.set("rust_float_y", json!(y));
            a.settings.set("rust_float_pinned", json!(pinned));
            a.settings.save();
        });
    });
    win.on_set_mode(|m| {
        with_app(|a| a.set_mode(m.as_str()));
    });
    win.on_action(|id| {
        with_app(|a| a.action(id.as_str()));
    });
    win.on_close_panel(|| {
        with_app(|a| {
            a.win().set_panel_visible(false);
            a.settings.set_save("left_panel", Value::Bool(false));
        });
    });
    win.on_format(|k, v| {
        with_app(|a| a.format(k.as_str(), v.as_str()));
    });
    win.on_text_color_picked(|c| {
        with_app(|a| a.format("color", &hex(c)));
    });
    win.on_ink_color_picked(|c| {
        with_app(|a| {
            a.settings.set_save("ink_color", json!(hex(c)));
            a.settings.set_save("shape_color", json!(hex(c)));
            a.win().set_ink_color(c);
            a.apply_to_selection(Some(&hex(c)), None);
        });
    });
    win.on_ink_width_set(|v| {
        with_app(|a| {
            if let Ok(x) = v.replace(',', ".").parse::<f64>() {
                a.settings.set("ink_width", json!(x));
                a.settings.set_save("shape_width", json!(x));
                a.win().set_ink_width(v);
                a.apply_to_selection(None, Some(x));
            }
        });
    });
    win.on_sig_color_picked(|c| {
        with_app(|a| {
            a.settings.set_save("signature_color", json!(hex(c)));
            a.win().set_sig_color(c);
        });
    });
    win.on_insert_blank(|p, full| {
        let p = PathBuf::from(p.as_str());
        with_app(|a| a.insert_blank(&p, full));
    });
    win.on_arm_signature(|id| {
        with_app(|a| a.arm_signature(id.as_str()));
    });
    win.on_signature_menu(|id| {
        with_app(|a| a.signature_context(id.as_str()));
    });
    let _ = win.as_weak();
}
