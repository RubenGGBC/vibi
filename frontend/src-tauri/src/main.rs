#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::{
    env,
    io::{BufRead, BufReader, Write},
    path::PathBuf,
    process::{Child, ChildStdin, Command, Stdio},
    sync::Mutex,
    thread,
};

use serde::Deserialize;
use tauri::{
    menu::{Menu, MenuItem},
    tray::TrayIconBuilder,
    AppHandle, Emitter, Manager, State,
};
use tauri_plugin_autostart::{MacosLauncher, ManagerExt as AutostartManagerExt};

#[derive(Default)]
struct WakeProcess {
    child: Option<Child>,
    stdin: Option<ChildStdin>,
    user_paused: bool,
    last_error: Option<String>,
}

struct WakeState(Mutex<WakeProcess>);

#[derive(Deserialize)]
struct WakeEvent {
    #[serde(rename = "type")]
    event_type: String,
    message: Option<String>,
}

fn write_listener(state: &WakeState, command: &str) {
    let Ok(mut process) = state.0.lock() else {
        return;
    };
    if let Some(stdin) = process.stdin.as_mut() {
        let _ = writeln!(stdin, "{command}");
        let _ = stdin.flush();
    }
}

#[cfg(target_os = "windows")]
fn play_wake_sound() {
    use windows_sys::Win32::{
        System::Diagnostics::Debug::MessageBeep,
        UI::WindowsAndMessaging::MB_ICONASTERISK,
    };
    unsafe {
        MessageBeep(MB_ICONASTERISK);
    }
}

#[cfg(not(target_os = "windows"))]
fn play_wake_sound() {}

fn show_companion(app: &AppHandle, play_sound: bool) {
    if play_sound {
        play_wake_sound();
    }
    if let Some(window) = app.get_webview_window("companion") {
        let _ = window.show();
        let _ = window.unminimize();
        let _ = window.set_focus();
    }
    let _ = app.emit("morgana://wake", ());
}

fn resolve_wake_paths(app: &AppHandle) -> Result<(Command, PathBuf), String> {
    let current = env::current_dir().map_err(|error| error.to_string())?;
    let executable_dir = env::current_exe()
        .map_err(|error| error.to_string())?
        .parent()
        .map(PathBuf::from)
        .ok_or_else(|| "No se pudo resolver la carpeta de Morgana".to_string())?;
    let resource_dir = app.path().resource_dir().map_err(|error| error.to_string())?;
    let model_name = "vosk-model-small-es-0.42";
    let model = if let Some(configured) = env::var_os("MORGANA_WAKE_MODEL") {
        PathBuf::from(configured)
    } else {
        [
            executable_dir.join("wake/models").join(model_name),
            resource_dir.join("wake/models").join(model_name),
            current.join("src-tauri/wake/models").join(model_name),
            current.join("wake/models").join(model_name),
        ]
        .into_iter()
        .find(|path| path.is_dir())
        .ok_or_else(|| {
            format!(
                "Modelo de escucha no encontrado junto a {}.",
                executable_dir.display()
            )
        })?
    };

    if !model.is_dir() {
        return Err(format!(
            "Modelo de escucha no encontrado en {}. Ejecuta wake/download-model.ps1.",
            model.display()
        ));
    }

    let wake_binary = [
        executable_dir.join("wake/morgana-wake.exe"),
        resource_dir.join("wake/morgana-wake.exe"),
        current.join("src-tauri/wake/dist/morgana-wake.exe"),
        current.join("wake/dist/morgana-wake.exe"),
    ]
    .into_iter()
    .find(|path| path.is_file());
    let command = if let Some(binary) = wake_binary {
        Command::new(binary)
    } else {
        let script = [
            current.join("src-tauri/wake/wake_listener.py"),
            current.join("wake/wake_listener.py"),
        ]
        .into_iter()
        .find(|path| path.is_file())
        .ok_or_else(|| {
            format!(
                "Detector local no encontrado junto a {}",
                executable_dir.display()
            )
        })?;
        if !script.is_file() {
            return Err(format!("Detector local no encontrado en {}", script.display()));
        }
        let python = env::var_os("MORGANA_PYTHON").unwrap_or_else(|| "python".into());
        let mut python_command = Command::new(python);
        python_command.arg(script);
        python_command
    };
    Ok((command, model))
}

fn spawn_wake_listener(app: AppHandle) -> Result<(), String> {
    let (mut command, model) = resolve_wake_paths(&app)?;
    let mut child = command
        .arg("--model")
        .arg(model)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|error| format!("No se pudo iniciar el detector: {error}"))?;

    let stdin = child.stdin.take();
    let stdout = child
        .stdout
        .take()
        .ok_or_else(|| "El detector no expuso stdout".to_string())?;
    let stderr = child.stderr.take();

    {
        let state = app.state::<WakeState>();
        let mut process = state.0.lock().map_err(|_| "Estado de escucha bloqueado")?;
        process.stdin = stdin;
        process.child = Some(child);
    }

    let events_app = app.clone();
    thread::spawn(move || {
        for line in BufReader::new(stdout).lines().map_while(Result::ok) {
            let Ok(event) = serde_json::from_str::<WakeEvent>(&line) else {
                continue;
            };
            match event.event_type.as_str() {
                "wake" => show_companion(&events_app, true),
                "error" => {
                    let message = event.message.unwrap_or_else(|| "Fallo de escucha".into());
                    if let Ok(mut process) = events_app.state::<WakeState>().0.lock() {
                        process.last_error = Some(message.clone());
                    }
                    if let Some(window) = events_app.get_webview_window("companion") {
                        let _ = window.show();
                        let _ = window.set_focus();
                    }
                    let _ = events_app.emit("morgana://listener-error", message);
                }
                _ => {}
            }
        }
    });

    if let Some(stderr) = stderr {
        thread::spawn(move || {
            for line in BufReader::new(stderr).lines().map_while(Result::ok) {
                eprintln!("morgana-wake: {line}");
            }
        });
    }
    Ok(())
}

#[tauri::command]
fn end_conversation(app: AppHandle, state: State<'_, WakeState>) {
    if let Some(window) = app.get_webview_window("companion") {
        let _ = window.hide();
    }
    let should_resume = state
        .0
        .lock()
        .map(|process| !process.user_paused)
        .unwrap_or(false);
    if should_resume {
        write_listener(&state, "resume");
    }
}

#[tauri::command]
fn manual_wake(app: AppHandle, state: State<'_, WakeState>) {
    write_listener(&state, "pause");
    show_companion(&app, true);
}

#[tauri::command]
fn set_listener_paused(paused: bool, state: State<'_, WakeState>) {
    if let Ok(mut process) = state.0.lock() {
        process.user_paused = paused;
    }
    write_listener(&state, if paused { "pause" } else { "resume" });
}

#[tauri::command]
fn listener_error(state: State<'_, WakeState>) -> Option<String> {
    state
        .0
        .lock()
        .ok()
        .and_then(|process| process.last_error.clone())
}

fn open_main_app() {
    let url = env::var("MORGANA_BASE_URL").unwrap_or_else(|_| "http://localhost:8000".into());
    let _ = open::that(url);
}

fn build_tray(app: &tauri::App) -> tauri::Result<()> {
    let wake = MenuItem::with_id(app, "wake", "Despertar a Morgana", true, None::<&str>)?;
    let pause = MenuItem::with_id(app, "pause", "Pausar escucha", true, None::<&str>)?;
    let resume = MenuItem::with_id(app, "resume", "Reanudar escucha", true, None::<&str>)?;
    let open_app = MenuItem::with_id(app, "open", "Abrir Morgana", true, None::<&str>)?;
    let quit = MenuItem::with_id(app, "quit", "Salir", true, None::<&str>)?;
    let menu = Menu::with_items(app, &[&wake, &pause, &resume, &open_app, &quit])?;

    let mut tray = TrayIconBuilder::new();
    if let Some(icon) = app.default_window_icon() {
        tray = tray.icon(icon.clone());
    }

    tray
        .tooltip("Morgana está escuchando")
        .menu(&menu)
        .show_menu_on_left_click(false)
        .on_menu_event(|app, event| match event.id.as_ref() {
            "wake" => {
                let state = app.state::<WakeState>();
                write_listener(&state, "pause");
                show_companion(app, true);
            }
            "pause" => {
                let state = app.state::<WakeState>();
                if let Ok(mut process) = state.0.lock() {
                    process.user_paused = true;
                }
                write_listener(&state, "pause");
            }
            "resume" => {
                let state = app.state::<WakeState>();
                if let Ok(mut process) = state.0.lock() {
                    process.user_paused = false;
                }
                write_listener(&state, "resume");
            }
            "open" => open_main_app(),
            "quit" => {
                let state = app.state::<WakeState>();
                write_listener(&state, "quit");
                if let Ok(mut process) = state.0.lock() {
                    if let Some(child) = process.child.as_mut() {
                        let _ = child.kill();
                    }
                }
                app.exit(0);
            }
            _ => {}
        })
        .build(app)?;
    Ok(())
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _, _| {
            if let Some(window) = app.get_webview_window("companion") {
                let _ = window.show();
                let _ = window.set_focus();
            }
        }))
        .plugin(tauri_plugin_window_state::Builder::default().build())
        .plugin(tauri_plugin_autostart::init(
            MacosLauncher::LaunchAgent,
            Some(vec!["--autostart"]),
        ))
        .manage(WakeState(Mutex::new(WakeProcess::default())))
        .invoke_handler(tauri::generate_handler![
            end_conversation,
            manual_wake,
            set_listener_paused,
            listener_error
        ])
        .setup(|app| {
            build_tray(app)?;
            let autostart = app.autolaunch();
            if !autostart.is_enabled().unwrap_or(false) {
                let _ = autostart.enable();
            }
            if let Err(message) = spawn_wake_listener(app.handle().clone()) {
                if let Ok(mut process) = app.state::<WakeState>().0.lock() {
                    process.last_error = Some(message.clone());
                }
                if let Some(window) = app.get_webview_window("companion") {
                    let _ = window.show();
                    let _ = window.set_focus();
                }
                let _ = app.emit("morgana://listener-error", message);
            }
            Ok(())
        })
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                api.prevent_close();
                let _ = window.hide();
                let app = window.app_handle();
                let state = app.state::<WakeState>();
                let should_resume = state
                    .0
                    .lock()
                    .map(|process| !process.user_paused)
                    .unwrap_or(false);
                if should_resume {
                    write_listener(&state, "resume");
                }
            }
        })
        .build(tauri::generate_context!())
        .expect("No se pudo construir Morgana Desktop")
        .run(|_app, event| {
            if let tauri::RunEvent::ExitRequested { code, api, .. } = event {
                // Una aplicación de bandeja debe seguir viva cuando se oculta
                // su última ventana. `Some(code)` viene de `app.exit()` y sí
                // corresponde a «Salir» en el menú.
                if code.is_none() {
                    api.prevent_exit();
                }
            }
        });
}
