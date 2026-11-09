// RedColor — редактор PDF для проверки работ. Автор: Maksim Belonoskin, Zelenograd, Moscow, Russia.
//! Один экземпляр программы: повторный запуск передаёт файлы уже открытому окну по именованному каналу.

use interprocess::local_socket::{GenericNamespaced, ListenerOptions, Stream, ToNsName, prelude::*};
use std::io::{Read, Write};
use std::path::PathBuf;

fn name() -> String {
    let user = std::env::var("REDCOLOR_INSTANCE")
        .or_else(|_| std::env::var("USERNAME"))
        .unwrap_or_else(|_| "user".into());
    format!("RedColor2-{user}")
}

pub fn send_to_running(files: &[PathBuf]) -> bool {
    let Ok(n) = name().to_ns_name::<GenericNamespaced>() else { return false };
    let Ok(mut s) = Stream::connect(n) else { return false };
    let msg: Vec<String> = files
        .iter()
        .map(|f| std::fs::canonicalize(f).unwrap_or_else(|_| f.clone()).to_string_lossy().to_string())
        .collect();
    let body = if msg.is_empty() { "\0".to_string() } else { msg.join("\n") };
    s.write_all(body.as_bytes()).is_ok()
}

pub fn listen<F: Fn(Vec<PathBuf>) + Send + 'static>(on_files: F) {
    let Ok(n) = name().to_ns_name::<GenericNamespaced>() else { return };
    let Ok(listener) = ListenerOptions::new().name(n).create_sync() else { return };
    std::thread::Builder::new()
        .name("instance".into())
        .spawn(move || {
            for conn in listener.incoming().flatten() {
                let mut conn = conn;
                let mut buf = String::new();
                let _ = conn.read_to_string(&mut buf);
                let paths: Vec<PathBuf> =
                    buf.split('\n').filter(|p| !p.trim().is_empty() && *p != "\0").map(PathBuf::from).collect();
                on_files(paths);
            }
        })
        .ok();
}
