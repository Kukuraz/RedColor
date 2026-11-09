// RedColor — редактор PDF для проверки работ. Автор: Maksim Belonoskin, Zelenograd, Moscow, Russia.
//! Данные левой панели: шрифты, бланки из папки, подписи, названия команд.

use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

use crate::settings::data_dir;

pub const FAVORITES: [&str; 17] = [
    "Minion Pro", "Times New Roman", "Arial", "Calibri", "Segoe Print", "Segoe Script", "Gabriola",
    "Comic Sans MS", "Georgia", "Myriad Pro", "Verdana", "Caveat", "Marck Script", "Bad Script", "Pacifico",
    "Lobster", "Amatic SC",
];

pub const ACROBAT_FONT_DIR: &str = r"C:\Program Files\Adobe\Acrobat DC\Resource\Font";

/// Семейство → файлы начертаний: r, b, i, bi.
pub type FontFamilies = BTreeMap<String, BTreeMap<&'static str, PathBuf>>;

fn style_key(name: &str) -> (String, &'static str) {
    let lower = name.to_lowercase();
    for (suffix, key) in [
        (" bold italic", "bi"),
        (" bold oblique", "bi"),
        (" bold", "b"),
        (" italic", "i"),
        (" oblique", "i"),
    ] {
        if lower.ends_with(suffix) {
            return (name[..name.len() - suffix.len()].trim().to_string(), key);
        }
    }
    (name.to_string(), "r")
}

fn split_camel(s: &str) -> String {
    let mut out = String::new();
    let mut prev_lower = false;
    for ch in s.chars() {
        if ch.is_uppercase() && prev_lower {
            out.push(' ');
        }
        prev_lower = ch.is_lowercase();
        out.push(ch);
    }
    out
}

/// Шрифты из папки: имя семейства по имени файла (MinionPro-BoldIt.otf → Minion Pro, bi).
fn file_fonts(folder: &Path, out: &mut FontFamilies) {
    let Ok(rd) = std::fs::read_dir(folder) else { return };
    for e in rd.flatten() {
        let p = e.path();
        let ext = p.extension().and_then(|x| x.to_str()).unwrap_or("").to_lowercase();
        if ext != "ttf" && ext != "otf" {
            continue;
        }
        let stem = p.file_stem().and_then(|x| x.to_str()).unwrap_or("").to_string();
        let (base, style) = stem.split_once('-').unwrap_or((&stem, ""));
        let style_l = style.to_lowercase().replace('_', "");
        let mut fam = split_camel(&base.replace('_', " ")).trim().to_string();
        let key = match style_l.as_str() {
            "" | "regular" | "roman" | "book" | "normal" => "r",
            s if s.starts_with("variable") => "r",
            "bold" | "bd" => "b",
            "it" | "italic" | "oblique" => "i",
            "boldit" | "bolditalic" | "bi" => "bi",
            _ => {
                fam = format!("{fam} {}", split_camel(style));
                "r"
            }
        };
        out.entry(fam).or_default().insert(key, p);
    }
}

pub fn scan_fonts() -> FontFamilies {
    let mut fams = FontFamilies::new();
    let win_fonts = PathBuf::from(std::env::var("WINDIR").unwrap_or_else(|_| r"C:\Windows".into())).join("Fonts");
    use winreg::RegKey;
    use winreg::enums::{HKEY_CURRENT_USER, HKEY_LOCAL_MACHINE};
    for root in [HKEY_LOCAL_MACHINE, HKEY_CURRENT_USER] {
        let Ok(k) = RegKey::predef(root).open_subkey(r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts") else {
            continue;
        };
        for (name, val) in k.enum_values().flatten() {
            let file = val.to_string();
            let mut p = PathBuf::from(file.trim());
            if !p.is_absolute() {
                p = win_fonts.join(p);
            }
            let ext = p.extension().and_then(|x| x.to_str()).unwrap_or("").to_lowercase();
            if ext != "ttf" && ext != "otf" {
                continue;
            }
            let name = name.trim_end_matches(" (TrueType)").trim_end_matches(" (OpenType)").trim().to_string();
            if name.contains('&') {
                continue;
            }
            let (fam, key) = style_key(&name);
            fams.entry(fam).or_default().insert(key, p);
        }
    }
    let mut extra = FontFamilies::new();
    file_fonts(Path::new(ACROBAT_FONT_DIR), &mut extra);
    file_fonts(&data_dir().join("fonts"), &mut extra);
    fams.extend(extra);
    fams.retain(|_, v| v.contains_key("r"));
    fams
}

/// Порядок для списка: сначала избранные, потом остальные по алфавиту.
pub fn font_list(fams: &FontFamilies) -> Vec<String> {
    let mut out: Vec<String> = FAVORITES.iter().filter(|f| fams.contains_key(**f)).map(|s| s.to_string()).collect();
    let mut rest: Vec<String> = fams.keys().filter(|k| !FAVORITES.contains(&k.as_str())).cloned().collect();
    rest.sort_by_key(|s| s.to_lowercase());
    out.extend(rest);
    out
}

/// Все PDF из папки бланков (с подпапками; папки, начинающиеся с «_» или «.», пропускаются).
pub fn blank_files(dir: &str) -> Vec<(String, PathBuf)> {
    let d = PathBuf::from(dir);
    if dir.trim().is_empty() || !d.is_dir() {
        return Vec::new();
    }
    let mut out = Vec::new();
    let mut stack = vec![d.clone()];
    while let Some(cur) = stack.pop() {
        let Ok(rd) = std::fs::read_dir(&cur) else { continue };
        for e in rd.flatten() {
            let p = e.path();
            let name = e.file_name().to_string_lossy().to_string();
            if p.is_dir() {
                if !name.starts_with('_') && !name.starts_with('.') {
                    stack.push(p);
                }
            } else if p.extension().and_then(|x| x.to_str()).map(|x| x.eq_ignore_ascii_case("pdf")).unwrap_or(false) {
                let rel = p.strip_prefix(&d).unwrap_or(&p).with_extension("");
                let label = rel.to_string_lossy().replace('\\', " / ");
                out.push((label, p));
            }
        }
    }
    out.sort_by_key(|(l, _)| l.to_lowercase());
    out
}

pub struct Signature {
    pub id: String,
    pub name: String,
    pub file: PathBuf,
}

/// Подписи из %APPDATA%\RedColor\signatures\index.json (общие с версией на Python).
pub fn signatures() -> Vec<Signature> {
    let dir = data_dir().join("signatures");
    let Ok(txt) = std::fs::read_to_string(dir.join("index.json")) else { return Vec::new() };
    let Ok(v) = serde_json::from_str::<serde_json::Value>(&txt) else { return Vec::new() };
    v.as_array()
        .map(|a| {
            a.iter()
                .filter_map(|x| {
                    let file = dir.join(x.get("file")?.as_str()?);
                    if !file.exists() {
                        return None;
                    }
                    Some(Signature {
                        id: x.get("id")?.as_str()?.to_string(),
                        name: x.get("name").and_then(|n| n.as_str()).unwrap_or("Подпись").to_string(),
                        file,
                    })
                })
                .collect()
        })
        .unwrap_or_default()
}

/// Названия команд (как в версии на Python) — для поиска и сообщений.
pub const ACTIONS: &[(&str, &str)] = &[
    ("file.open", "Открыть…"),
    ("file.save", "Сохранить"),
    ("file.save_as", "Сохранить как…"),
    ("file.close", "Закрыть документ"),
    ("file.print", "Печать…"),
    ("file.new", "Пустой PDF"),
    ("file.merge", "Объединение файлов"),
    ("file.compress", "Сжать PDF"),
    ("file.export_images", "Экспорт страниц в изображения"),
    ("file.quit", "Выход"),
    ("edit.undo", "Отменить"),
    ("edit.redo", "Повторить"),
    ("edit.add_quote", "Добавить выделенный текст в цитаты"),
    ("view.zoom_in", "Увеличить"),
    ("view.zoom_out", "Уменьшить"),
    ("view.actual", "Реальный размер"),
    ("view.fit_width", "По ширине"),
    ("view.fit_page", "Страница целиком"),
    ("view.next_page", "Следующая страница"),
    ("view.prev_page", "Предыдущая страница"),
    ("view.first_page", "Первая страница"),
    ("view.last_page", "Последняя страница"),
    ("view.panel", "Показать/скрыть левую панель"),
    ("view.organize", "Систематизация страниц"),
    ("view.find", "Найти в документе"),
    ("mode.all", "Все инструменты"),
    ("mode.edit", "Редактировать PDF"),
    ("mode.convert", "Преобразовать"),
    ("mode.sign", "Электронное подписание"),
    ("page.rotate_cw", "Повернуть страницу вправо"),
    ("page.rotate_ccw", "Повернуть страницу влево"),
    ("page.delete", "Удалить страницу"),
    ("page.insert_file", "Вставить страницы из файла…"),
    ("page.insert_blank", "Вставить пустую страницу после текущей"),
    ("page.extract", "Извлечь страницы…"),
    ("page.move_up", "Переместить страницу выше"),
    ("page.move_down", "Переместить страницу ниже"),
    ("page.replace", "Заменить текущую страницу…"),
    ("view.goto", "Перейти к странице…"),
    ("app.menu", "Меню"),
    ("sign.menu", "Подписи"),
    ("tool.select", "Выделение"),
    ("tool.hand", "Рука"),
    ("tool.text", "Добавить текст"),
    ("tool.pencil", "Карандаш"),
    ("tool.highlighter", "Маркер"),
    ("tool.eraser", "Ластик"),
    ("tool.ellipse", "Овал"),
    ("tool.ellipse_num", "Овал с номером"),
    ("tool.rect", "Прямоугольник"),
    ("tool.line", "Линия"),
    ("tool.arrow", "Стрелка"),
    ("tool.check", "Галочка ✓"),
    ("tool.cross", "Крестик ✗"),
    ("tool.plus", "Плюс +"),
    ("tool.minus", "Минус –"),
    ("tool.dot", "Точка •"),
    ("tool.quote", "Случайная цитата"),
    ("tool.formula", "Формула"),
    ("tool.image", "Изображение"),
    ("tool.signature", "Поставить подпись"),
    ("blank.menu", "Вставить бланк"),
    ("blank.open_dir", "Открыть папку бланков"),
    ("blank.choose_dir", "Выбрать папку бланков…"),
    ("blank.clean_doc", "Убрать «1» в комментариях бланков (документ)"),
    ("blank.clean_folder", "Убрать «1» во всех бланках папки…"),
    ("quote.here", "Случайная цитата под курсором"),
    ("app.quotes", "Цитаты…"),
    ("sign.new", "Добавить подпись…"),
    ("sign.new_initials", "Добавить инициалы…"),
    ("app.hotkeys", "Горячие клавиши…"),
    ("app.settings", "Настройки…"),
    ("app.default_pdf", "Сделать RedColor программой для PDF"),
    ("app.about", "О программе"),
    ("app.info", "Информация (инструкция)"),
];

pub fn action_name(id: &str) -> &str {
    ACTIONS.iter().find(|(a, _)| *a == id).map(|(_, n)| *n).unwrap_or(id)
}

/// Горячие клавиши инструментов (одна буква, без Ctrl) — как в версии на Python.
pub const TOOL_KEYS: &[(&str, &str)] = &[
    ("v", "select"), ("h", "hand"), ("t", "text"), ("p", "pencil"), ("u", "highlighter"), ("e", "eraser"),
    ("o", "ellipse"), ("n", "ellipse_num"), ("r", "rect"), ("l", "line"), ("a", "arrow"), ("k", "check"),
    ("x", "cross"), ("=", "plus"), ("-", "minus"), (".", "dot"), ("q", "quote"), ("f", "formula"),
    ("i", "image"), ("s", "signature"),
];

/// Русская раскладка → латинская (по положению клавиш), чтобы сочетания работали в любой раскладке.
pub fn ru_to_en(s: &str) -> String {
    const RU: &str = "йцукенгшщзхъфывапролджэячсмитьбюё";
    const EN: &str = "qwertyuiop[]asdfghjkl;'zxcvbnm,.`";
    s.chars()
        .map(|c| {
            let lc = c.to_lowercase().next().unwrap_or(c);
            match RU.chars().position(|r| r == lc) {
                Some(i) => EN.chars().nth(i).unwrap_or(c),
                None => lc,
            }
        })
        .collect()
}

pub fn hex(c: slint::Color) -> String {
    format!("#{:02x}{:02x}{:02x}", c.red(), c.green(), c.blue())
}

pub fn color(hex: &str) -> slint::Color {
    let v = u32::from_str_radix(hex.trim().trim_start_matches('#'), 16).unwrap_or(0xff0000);
    slint::Color::from_argb_encoded(0xff000000 | v)
}
