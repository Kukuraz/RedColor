//! On-demand compatibility process for the existing formula renderer and HTML parser.
//! No Python/Qt/matplotlib process remains resident when a request completes.
use std::io::Write;
use std::path::PathBuf;
use std::process::{Command, Stdio};

fn helper() -> Option<PathBuf> {
    let exe = std::env::current_exe().ok()?;
    let cwd = std::env::current_dir().ok()?;
    for dir in exe.ancestors().chain(cwd.ancestors()) {
        for path in [dir.join("formula_helper.py"), dir.join("rust").join("formula_helper.py")] {
            if path.is_file() && path.parent()?.parent()?.join("rp").join("formula.py").is_file() {
                return Some(path);
            }
        }
    }
    None
}

fn python() -> PathBuf {
    if let Some(path) = std::env::var_os("REDCOLOR_PYTHON") {
        return PathBuf::from(path);
    }
    if let Some(local) = std::env::var_os("LOCALAPPDATA") {
        let path = PathBuf::from(local).join("Python").join("bin").join("python.exe");
        if path.is_file() { return path; }
    }
    PathBuf::from("python")
}

pub fn run(request: serde_json::Value) -> Result<serde_json::Value, String> {
    let path = helper().ok_or("Не найден модуль формул RedColor рядом с программой")?;
    let mut cmd = Command::new(python());
    cmd.arg(path).env("PYTHONUTF8", "1").stdin(Stdio::piped()).stdout(Stdio::piped()).stderr(Stdio::piped());
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        cmd.creation_flags(0x08000000); // CREATE_NO_WINDOW
    }
    let mut child = cmd.spawn().map_err(|e| format!("Не удалось запустить Python для формул: {e}"))?;
    let bytes = serde_json::to_vec(&request).map_err(|e| e.to_string())?;
    child.stdin.take().ok_or("Нет ввода модуля формул")?.write_all(&bytes).map_err(|e| e.to_string())?;
    let output = child.wait_with_output().map_err(|e| e.to_string())?;
    let reply: serde_json::Value = serde_json::from_slice(&output.stdout)
        .map_err(|_| format!("Ошибка модуля формул: {}", String::from_utf8_lossy(&output.stderr)))?;
    if reply.get("ok").and_then(|v| v.as_bool()) != Some(true) {
        return Err(reply.get("error").and_then(|v| v.as_str()).unwrap_or("Ошибка модуля формул").to_string());
    }
    Ok(reply.get("result").cloned().unwrap_or_default())
}
