// RedColor — редактор PDF для проверки работ. Автор: Maksim Belonoskin, Zelenograd, Moscow, Russia.
//! Настройки — тот же файл %APPDATA%\RedColor\settings.json, что и у версии на Python:
//! недавние файлы, тема, бланки, горячие клавиши переходят без переноса. Незнакомые ключи сохраняются как есть.

use serde_json::{Map, Value};
use std::path::PathBuf;

pub fn data_dir() -> PathBuf {
    let base = std::env::var_os("APPDATA").map(PathBuf::from).unwrap_or_else(|| PathBuf::from("."));
    let d = base.join("RedColor");
    let _ = std::fs::create_dir_all(&d);
    d
}

pub struct Settings {
    map: Map<String, Value>,
    path: PathBuf,
}

impl Settings {
    pub fn load() -> Self {
        let path = data_dir().join("settings.json");
        let map = std::fs::read_to_string(&path)
            .ok()
            .and_then(|s| serde_json::from_str::<Value>(&s).ok())
            .and_then(|v| v.as_object().cloned())
            .unwrap_or_default();
        Settings { map, path }
    }

    pub fn save(&self) {
        let tmp = self.path.with_extension("tmp");
        if let Ok(s) = serde_json::to_string_pretty(&Value::Object(self.map.clone())) {
            if std::fs::write(&tmp, s).is_ok() {
                let _ = std::fs::rename(&tmp, &self.path);
            }
        }
    }

    pub fn str(&self, key: &str, default: &str) -> String {
        self.map.get(key).and_then(|v| v.as_str()).unwrap_or(default).to_string()
    }

    pub fn set(&mut self, key: &str, v: Value) {
        self.map.insert(key.to_string(), v);
    }

    pub fn get_value(&self, key: &str) -> Option<&Value> {
        self.map.get(key)
    }

    pub fn f64(&self, key: &str, default: f64) -> f64 {
        self.map.get(key).and_then(|v| v.as_f64()).unwrap_or(default)
    }

    pub fn bool(&self, key: &str, default: bool) -> bool {
        self.map.get(key).and_then(|v| v.as_bool()).unwrap_or(default)
    }

    pub fn i64(&self, key: &str, default: i64) -> i64 {
        self.map.get(key).and_then(|v| v.as_i64()).unwrap_or(default)
    }

    pub fn set_save(&mut self, key: &str, v: Value) {
        self.set(key, v);
        self.save();
    }

    pub fn recent(&self) -> Vec<String> {
        self.map
            .get("recent")
            .and_then(|v| v.as_array())
            .map(|a| a.iter().filter_map(|x| x.as_str().map(String::from)).collect())
            .unwrap_or_default()
    }

    pub fn add_recent(&mut self, path: &str) {
        let mut rec: Vec<String> = self.recent().into_iter().filter(|p| p != path).collect();
        rec.insert(0, path.to_string());
        rec.truncate(15);
        self.set("recent", Value::Array(rec.into_iter().map(Value::String).collect()));
        self.save();
    }
}
