use std::net::TcpListener;
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;

use anyhow::Context;
use serde::Serialize;
use tauri::Manager;

const SERVICE: &str = "github-sourcer";
const USERNAME: &str = "github-token";

#[derive(Default)]
struct BackendState {
    child: Option<Child>,
    url: Option<String>,
}

#[derive(Serialize)]
struct BackendStatus {
    running: bool,
    url: Option<String>,
}

fn keyring_entry() -> keyring::Entry {
    keyring::Entry::new(SERVICE, USERNAME).expect("keyring entry")
}

fn pick_free_port() -> anyhow::Result<u16> {
    // Bind to port 0 to let OS choose a free port.
    let listener = TcpListener::bind(("127.0.0.1", 0)).context("bind port 0")?;
    let port = listener.local_addr()?.port();
    drop(listener);
    Ok(port)
}

fn port_available(host: &str, port: u16) -> bool {
    TcpListener::bind((host, port)).is_ok()
}

fn pick_preferred_port() -> anyhow::Result<u16> {
    // Prefer a stable port so external tools (curl, MCP connectors) can talk to the app.
    let preferred: u16 = 8000;
    if port_available("127.0.0.1", preferred) {
        Ok(preferred)
    } else {
        pick_free_port()
    }
}

#[tauri::command]
fn token_get() -> Result<String, String> {
    keyring_entry()
        .get_password()
        .map_err(|e| format!("no token: {e}"))
}

#[tauri::command]
fn token_set(token: String) -> Result<(), String> {
    keyring_entry()
        .set_password(token.trim())
        .map_err(|e| format!("failed: {e}"))
}

#[tauri::command]
fn token_clear() -> Result<(), String> {
    keyring_entry()
        .delete_password()
        .map_err(|e| format!("failed: {e}"))
}

#[tauri::command]
fn backend_status(state: tauri::State<'_, Mutex<BackendState>>) -> Result<BackendStatus, String> {
    let st = state.lock().map_err(|_| "lock poisoned".to_string())?;
    Ok(BackendStatus {
        running: st.child.is_some(),
        url: st.url.clone(),
    })
}

#[tauri::command]
fn open_url(url: String) -> Result<(), String> {
    let url = url.trim().to_string();
    if url.is_empty() {
        return Ok(());
    }

    #[cfg(target_os = "windows")]
    {
        // Try Chrome first, then fallback to system default.
        let candidates = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        ];
        for p in candidates {
            if std::path::Path::new(p).exists() {
                let _ = Command::new(p).arg(&url).spawn();
                return Ok(());
            }
        }
    }

    tauri_plugin_opener::open_url(&url, None::<&str>).map_err(|e| e.to_string())
}

fn find_sidecar_exe(app: &tauri::AppHandle) -> Option<std::path::PathBuf> {
    // In bundled builds, Tauri places externalBin executables next to the main exe
    // (with platform-specific extension). We'll look in the current exe directory.
    let exe = std::env::current_exe().ok()?;
    let dir = exe.parent()?.to_path_buf();

    // Preferred exact name(s)
    let exact = dir.join("sourceress-backend.exe");
    if exact.exists() {
        return Some(exact);
    }
    let exact2 = dir.join("sourceress-backend-x86_64-pc-windows-msvc.exe");
    if exact2.exists() {
        return Some(exact2);
    }

    // Fallback: any file containing our name
    let rd = std::fs::read_dir(&dir).ok()?;
    for e in rd.flatten() {
        let p = e.path();
        if !p.is_file() {
            continue;
        }
        let name = p.file_name().and_then(|s| s.to_str()).unwrap_or("").to_lowercase();
        if name.contains("sourceress-backend") {
            return Some(p);
        }
    }

    // Debug fallback: allow running from src-tauri/bin
    let debug = app.path().resolve("bin/sourceress-backend.exe", tauri::path::BaseDirectory::Resource).ok();
    debug
}

#[tauri::command]
fn backend_start(app: tauri::AppHandle, state: tauri::State<'_, Mutex<BackendState>>) -> Result<String, String> {
    // If already running, return URL
    {
        let st = state.lock().map_err(|_| "lock poisoned".to_string())?;
        if let Some(url) = &st.url {
            return Ok(url.clone());
        }
    }

    let token = keyring_entry()
        .get_password()
        .map_err(|_| "GitHub token not set. Please paste it in Settings.".to_string())?;

    let port = pick_preferred_port().map_err(|e| e.to_string())?;
    let url = format!("http://127.0.0.1:{port}");

    // Start bundled backend sidecar (no Python install needed).
    let sidecar = find_sidecar_exe(&app)
        .ok_or_else(|| "backend sidecar not found (did you run build_sidecar.ps1?)".to_string())?;

    let data_dir = app
        .path()
        .app_data_dir()
        .map_err(|e| format!("app data dir: {e}"))?;
    let _ = std::fs::create_dir_all(&data_dir);

    // Log backend output to a file for debugging.
    let log_path = data_dir.join("backend.log");
    let log_file = std::fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(&log_path)
        .map_err(|e| format!("open log file failed: {e}"))?;
    let log_file2 = log_file
        .try_clone()
        .map_err(|e| format!("clone log file failed: {e}"))?;

    let mut child = Command::new(sidecar)
        .args(["--host", "127.0.0.1", "--port", &port.to_string(), "--data-dir"])
        .arg(data_dir.to_string_lossy().to_string())
        .env("GITHUB_TOKEN", token)
        .stdout(Stdio::from(log_file))
        .stderr(Stdio::from(log_file2))
        .spawn()
        .map_err(|e| format!("failed to start backend: {e}"))?;

    // Wait for backend to start listening before returning URL.
    let addr = format!("127.0.0.1:{}", port);
    let mut ok = false;
    for _ in 0..40 {
        if TcpListener::bind(&addr).is_ok() {
            // If we can bind, backend is NOT listening yet.
        } else {
            ok = true;
            break;
        }
        std::thread::sleep(std::time::Duration::from_millis(125));
    }

    if !ok {
        let _ = child.kill();
        return Err(format!(
            "backend failed to start (port {}). See log: {}",
            port,
            log_path.to_string_lossy()
        ));
    }

    let child = child;

    let mut st = state.lock().map_err(|_| "lock poisoned".to_string())?;
    st.child = Some(child);
    st.url = Some(url.clone());
    Ok(url)
}

#[tauri::command]
fn backend_stop(state: tauri::State<'_, Mutex<BackendState>>) -> Result<(), String> {
    let mut st = state.lock().map_err(|_| "lock poisoned".to_string())?;
    if let Some(mut child) = st.child.take() {
        let _ = child.kill();
    }
    st.url = None;
    Ok(())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .manage(Mutex::new(BackendState::default()))
        .invoke_handler(tauri::generate_handler![
            token_get,
            token_set,
            token_clear,
            backend_status,
            backend_start,
            backend_stop,
            open_url
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
