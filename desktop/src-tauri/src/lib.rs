use std::net::TcpListener;
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;

use anyhow::Context;
use serde::Serialize;
use tauri::Manager;

const SERVICE: &str = "sourceress";
const USERNAME: &str = "github-token";

const ANTHROPIC_USERNAME: &str = "anthropic-api-key";

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

fn keyring_entry(username: &str) -> keyring::Entry {
    keyring::Entry::new(SERVICE, username).expect("keyring entry")
}

fn pick_free_port() -> anyhow::Result<u16> {
    // Bind to port 0 to let OS choose a free port.
    let listener = TcpListener::bind(("127.0.0.1", 0)).context("bind port 0")?;
    let port = listener.local_addr()?.port();
    drop(listener);
    Ok(port)
}

// (port_available removed; we always pick an ephemeral free port)

fn pick_preferred_port() -> anyhow::Result<u16> {
    // IMPORTANT: don't prefer a stable port.
    // The app can race itself (multiple windows or restart loops) and lose the bind after the check,
    // causing "backend failed to start". Always picking an ephemeral free port avoids conflicts.
    pick_free_port()
}

#[tauri::command]
fn token_get() -> Result<String, String> {
    keyring_entry(USERNAME)
        .get_password()
        .map_err(|e| format!("no token: {e}"))
}

#[tauri::command]
fn token_set(token: String) -> Result<(), String> {
    keyring_entry(USERNAME)
        .set_password(token.trim())
        .map_err(|e| format!("failed: {e}"))
}

#[tauri::command]
fn token_clear() -> Result<(), String> {
    keyring_entry(USERNAME)
        .delete_password()
        .map_err(|e| format!("failed: {e}"))
}

#[tauri::command]
fn anthropic_key_get() -> Result<String, String> {
    keyring_entry(ANTHROPIC_USERNAME)
        .get_password()
        .map_err(|e| format!("no key: {e}"))
}

#[tauri::command]
fn anthropic_key_set(key: String) -> Result<(), String> {
    let k = key.trim();
    if k.is_empty() {
        return Err("empty key".to_string());
    }
    keyring_entry(ANTHROPIC_USERNAME)
        .set_password(k)
        .map_err(|e| format!("failed: {e}"))
}

#[tauri::command]
fn anthropic_key_clear() -> Result<(), String> {
    keyring_entry(ANTHROPIC_USERNAME)
        .delete_password()
        .map_err(|e| format!("failed: {e}"))
}

#[tauri::command]
fn backend_status(app: tauri::AppHandle, state: tauri::State<'_, Mutex<BackendState>>) -> Result<BackendStatus, String> {
    // Fast path: current session state
    {
        let st = state.lock().map_err(|_| "lock poisoned".to_string())?;
        if let Some(url) = &st.url {
            return Ok(BackendStatus { running: st.child.is_some(), url: Some(url.clone()) });
        }
    }

    // Resilience: after app restart, we lose the Child handle.
    // Try to recover the last URL and probe health.
    let data_dir = app.path().app_data_dir().map_err(|e| format!("app data dir: {e}"))?;
    let p = data_dir.join("backend-url.txt");
    if let Ok(s) = std::fs::read_to_string(&p) {
        let url = s.trim().to_string();
        if !url.is_empty() {
            // Best-effort health probe.
            let ok = std::net::TcpStream::connect_timeout(
                &url.replace("http://", "").parse().unwrap_or_else(|_| "127.0.0.1:0".parse().unwrap()),
                std::time::Duration::from_millis(150),
            )
            .is_ok();

            if ok {
                // Store url back into state (no child handle, but UI can use the URL).
                let mut st = state.lock().map_err(|_| "lock poisoned".to_string())?;
                st.url = Some(url.clone());
                return Ok(BackendStatus { running: true, url: Some(url) });
            }
        }
    }

    Ok(BackendStatus { running: false, url: None })
}

#[derive(Serialize)]
struct Diagnostics {
    app_version: String,
    tauri_version: String,
    os: String,
    arch: String,
    backend_running: bool,
    backend_url: Option<String>,
    data_dir: String,
    backend_log: String,
    github_token_set: bool,
    anthropic_key_set: bool,
}

#[tauri::command]
fn diagnostics(app: tauri::AppHandle, state: tauri::State<'_, Mutex<BackendState>>) -> Result<Diagnostics, String> {
    let st = state.lock().map_err(|_| "lock poisoned".to_string())?;

    let data_dir = app
        .path()
        .app_data_dir()
        .map_err(|e| format!("app data dir: {e}"))?;
    let backend_log = data_dir.join("backend.log");

    let github_token_set = keyring_entry(USERNAME).get_password().ok().map(|s| !s.trim().is_empty()).unwrap_or(false);
    let anthropic_key_set = keyring_entry(ANTHROPIC_USERNAME).get_password().ok().map(|s| !s.trim().is_empty()).unwrap_or(false);

    Ok(Diagnostics {
        app_version: app.package_info().version.to_string(),
        tauri_version: tauri::VERSION.to_string(),
        os: std::env::consts::OS.to_string(),
        arch: std::env::consts::ARCH.to_string(),
        backend_running: st.child.is_some(),
        backend_url: st.url.clone(),
        data_dir: data_dir.to_string_lossy().to_string(),
        backend_log: backend_log.to_string_lossy().to_string(),
        github_token_set,
        anthropic_key_set,
    })
}

#[tauri::command]
fn open_log_folder(app: tauri::AppHandle) -> Result<(), String> {
    let data_dir = app.path().app_data_dir().map_err(|e| e.to_string())?;
    let _ = std::fs::create_dir_all(&data_dir);

    // Use the system opener for the directory.
    let p = data_dir.to_string_lossy().to_string();
    tauri_plugin_opener::open_path(&p, None::<&str>).map_err(|e| e.to_string())
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
    let candidates = [
        // Windows
        "sourceress-backend.exe",
        "sourceress-backend-x86_64-pc-windows-msvc.exe",
        // macOS/Linux (no extension)
        "sourceress-backend",
        "sourceress-backend-aarch64-apple-darwin",
        "sourceress-backend-x86_64-apple-darwin",
    ];

    for name in candidates {
        let p = dir.join(name);
        if p.exists() {
            return Some(p);
        }
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

    // Debug fallback: allow running from src-tauri/bin (resource dir)
    let debug = app.path().resolve("bin/sourceress-backend", tauri::path::BaseDirectory::Resource).ok();
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

    let token = keyring_entry(USERNAME)
        .get_password()
        .map_err(|_| "GitHub token not set. Please paste it in Settings.".to_string())?;

    // Optional for desktop beta: allow Fubuki only when user provides a key.
    let anthropic = keyring_entry(ANTHROPIC_USERNAME).get_password().ok();

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

    let mut cmd = Command::new(sidecar);
    cmd.args(["--host", "127.0.0.1", "--port", &port.to_string(), "--data-dir"])
        .arg(data_dir.to_string_lossy().to_string())
        .env("GITHUB_TOKEN", token)
        .stdout(Stdio::from(log_file))
        .stderr(Stdio::from(log_file2));

    if let Some(k) = anthropic {
        // Backend will accept x-anthropic-key anyway, but this also allows server-key usage.
        cmd.env("ANTHROPIC_API_KEY", k);
    }

    let mut child = cmd
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

    // Persist last URL so backend_status can recover after app restarts.
    let _ = std::fs::write(data_dir.join("backend-url.txt"), format!("{}\n", url));

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
    // Best-effort: remove persisted URL
    // (ignore errors; file may not exist).
    // Note: we don't have AppHandle here; backend_url will just be overwritten on next start.
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
            anthropic_key_get,
            anthropic_key_set,
            anthropic_key_clear,
            backend_status,
            diagnostics,
            backend_start,
            backend_stop,
            open_log_folder,
            open_url
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
