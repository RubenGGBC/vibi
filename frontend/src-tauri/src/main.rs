#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::{
    env,
    fs,
    io::{BufRead, BufReader, Write},
    path::PathBuf,
    process::{Child, ChildStdin, Command, Stdio},
    sync::Mutex,
    thread,
    time::{Duration, Instant},
};

use serde::Deserialize;
use tauri::{
    menu::{Menu, MenuItem},
    tray::TrayIconBuilder,
    AppHandle, Emitter, Manager, State, WebviewUrl, WebviewWindowBuilder, Wry,
};
use tauri_plugin_autostart::{MacosLauncher, ManagerExt as AutostartManagerExt};

const TRAY_ID: &str = "vibi";
/// Un detector que ha aguantado vivo este tiempo no cuenta como fallo en cadena.
const HEALTHY_RUN: Duration = Duration::from_secs(60);

#[derive(Clone, Default, PartialEq)]
enum ListenerStatus {
    #[default]
    Starting,
    Listening,
    Paused,
    Down(String),
}

impl ListenerStatus {
    fn label(&self) -> String {
        match self {
            ListenerStatus::Starting => "Preparando la escucha…".to_string(),
            ListenerStatus::Listening => "Vibi está escuchando".to_string(),
            ListenerStatus::Paused => "Escucha en pausa".to_string(),
            ListenerStatus::Down(motivo) => format!("Sin escucha: {motivo}"),
        }
    }
}

#[derive(Default)]
struct WakeProcess {
    child: Option<Child>,
    stdin: Option<ChildStdin>,
    user_paused: bool,
    last_error: Option<String>,
    status: ListenerStatus,
    shutting_down: bool,
}

struct WakeState(Mutex<WakeProcess>);

/// El elemento de menú que refleja el estado, para poder reescribir su texto.
struct TrayHandles {
    status_item: MenuItem<Wry>,
}

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

/// Deja constancia en disco: una sordera silenciosa es imposible de diagnosticar.
fn log_line(app: &AppHandle, mensaje: &str) {
    let Ok(directorio) = app.path().app_log_dir() else {
        return;
    };
    let _ = fs::create_dir_all(&directorio);
    let ruta = directorio.join("wake.log");
    if fs::metadata(&ruta)
        .map(|datos| datos.len() > 1_000_000)
        .unwrap_or(false)
    {
        let _ = fs::remove_file(&ruta);
    }
    if let Ok(mut fichero) = fs::OpenOptions::new().create(true).append(true).open(&ruta) {
        let _ = writeln!(fichero, "{} {mensaje}", marca_de_tiempo());
    }
}

#[cfg(target_os = "windows")]
fn marca_de_tiempo() -> String {
    use windows_sys::Win32::System::SystemInformation::GetLocalTime;
    let mut ahora = unsafe { std::mem::zeroed() };
    unsafe { GetLocalTime(&mut ahora) };
    format!(
        "{:04}-{:02}-{:02} {:02}:{:02}:{:02}",
        ahora.wYear, ahora.wMonth, ahora.wDay, ahora.wHour, ahora.wMinute, ahora.wSecond
    )
}

#[cfg(not(target_os = "windows"))]
fn marca_de_tiempo() -> String {
    use std::time::{SystemTime, UNIX_EPOCH};
    let segundos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duracion| duracion.as_secs())
        .unwrap_or(0);
    format!("t+{segundos}")
}

fn set_status(app: &AppHandle, status: ListenerStatus) {
    {
        let state = app.state::<WakeState>();
        let Ok(mut process) = state.0.lock() else {
            return;
        };
        if process.status == status {
            return;
        }
        process.status = status.clone();
    }
    let etiqueta = status.label();
    log_line(app, &format!("estado: {etiqueta}"));
    if let Some(tray) = app.tray_by_id(TRAY_ID) {
        let _ = tray.set_tooltip(Some(&etiqueta));
    }
    if let Some(handles) = app.try_state::<TrayHandles>() {
        let _ = handles.status_item.set_text(&etiqueta);
    }
}

/// Dos notas cortas ascendentes, en PCM de 16 bits y un solo canal.
///
/// Se sintetiza en lugar de empaquetar un `.wav` para no arrastrar un recurso
/// más ni una biblioteca de audio: son unas pocas decenas de kilobytes que se
/// generan en menos de un milisegundo.
#[cfg(target_os = "windows")]
fn wake_chime() -> Vec<u8> {
    const SAMPLE_RATE: u32 = 44_100;
    // La5 y Do#6: un intervalo alegre y corto, sin la gravedad de un aviso de
    // sistema. La segunda entra cuando la primera casi se ha apagado.
    const NOTES: [(f32, f32, f32); 2] = [(880.0, 0.0, 0.075), (1108.73, 0.105, 0.13)];
    let total = 0.235_f32;
    let frames = (SAMPLE_RATE as f32 * total) as usize;

    let mut samples = Vec::with_capacity(frames);
    for frame in 0..frames {
        let t = frame as f32 / SAMPLE_RATE as f32;
        let mut value = 0.0_f32;
        for (freq, start, duration) in NOTES {
            if t < start || t >= start + duration {
                continue;
            }
            let elapsed = t - start;
            // Ataque muy corto y caída exponencial: sin esto, empezar y cortar
            // la onda de golpe suena a chasquido.
            let attack = (elapsed / 0.004).min(1.0);
            let decay = (-3.5 * (elapsed / duration)).exp();
            value += 0.32 * attack * decay
                * (std::f32::consts::TAU * freq * elapsed).sin();
        }
        samples.push((value.clamp(-1.0, 1.0) * i16::MAX as f32) as i16);
    }

    let data_len = (samples.len() * 2) as u32;
    let mut wav = Vec::with_capacity(44 + data_len as usize);
    wav.extend_from_slice(b"RIFF");
    wav.extend_from_slice(&(36 + data_len).to_le_bytes());
    wav.extend_from_slice(b"WAVEfmt ");
    wav.extend_from_slice(&16u32.to_le_bytes()); // tamaño del bloque fmt
    wav.extend_from_slice(&1u16.to_le_bytes()); // PCM sin comprimir
    wav.extend_from_slice(&1u16.to_le_bytes()); // mono
    wav.extend_from_slice(&SAMPLE_RATE.to_le_bytes());
    wav.extend_from_slice(&(SAMPLE_RATE * 2).to_le_bytes()); // bytes por segundo
    wav.extend_from_slice(&2u16.to_le_bytes()); // alineación de bloque
    wav.extend_from_slice(&16u16.to_le_bytes()); // bits por muestra
    wav.extend_from_slice(b"data");
    wav.extend_from_slice(&data_len.to_le_bytes());
    for sample in samples {
        wav.extend_from_slice(&sample.to_le_bytes());
    }
    wav
}

#[cfg(target_os = "windows")]
fn play_wake_sound() {
    use windows_sys::Win32::Media::Audio::{
        PlaySoundW, SND_MEMORY, SND_NODEFAULT, SND_SYNC,
    };

    // En un hilo aparte y de forma síncrona: con SND_ASYNC habría que mantener
    // vivo el buffer por nuestra cuenta mientras suena, y aquí basta con que el
    // hilo lo sostenga hasta que PlaySoundW vuelva. Así tampoco se congela la
    // ventana los doscientos milisegundos que dura.
    std::thread::spawn(|| {
        let wav = wake_chime();
        unsafe {
            PlaySoundW(
                wav.as_ptr() as *const u16,
                std::ptr::null_mut(),
                SND_MEMORY | SND_SYNC | SND_NODEFAULT,
            );
        }
    });
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
    let _ = app.emit("vibi://wake", ());
}

fn resolve_wake_paths(app: &AppHandle) -> Result<(Command, PathBuf), String> {
    let current = env::current_dir().map_err(|error| error.to_string())?;
    let executable_dir = env::current_exe()
        .map_err(|error| error.to_string())?
        .parent()
        .map(PathBuf::from)
        .ok_or_else(|| "No se pudo resolver la carpeta de Vibi".to_string())?;
    let resource_dir = app.path().resource_dir().map_err(|error| error.to_string())?;
    let model_name = "vosk-model-small-es-0.42";
    let model = if let Some(configured) = env::var_os("VIBI_WAKE_MODEL")
        .or_else(|| env::var_os("MORGANA_WAKE_MODEL"))
    {
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
        executable_dir.join("wake/vibi-wake.exe"),
        resource_dir.join("wake/vibi-wake.exe"),
        current.join("src-tauri/wake/dist/vibi-wake.exe"),
        current.join("wake/dist/vibi-wake.exe"),
        executable_dir.join("wake/morgana-wake.exe"),
        resource_dir.join("wake/morgana-wake.exe"),
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
        let python = env::var_os("VIBI_PYTHON")
            .or_else(|| env::var_os("MORGANA_PYTHON"))
            .unwrap_or_else(|| "python".into());
        let mut python_command = Command::new(python);
        python_command.arg(script);
        python_command
    };
    Ok((command, model))
}

fn handle_wake_event(app: &AppHandle, line: &str) {
    let Ok(event) = serde_json::from_str::<WakeEvent>(line) else {
        return;
    };
    match event.event_type.as_str() {
        "wake" => {
            log_line(app, "despertar detectado");
            show_companion(app, true);
        }
        "listening" => set_status(app, ListenerStatus::Listening),
        "paused" => set_status(app, ListenerStatus::Paused),
        "resumed" => set_status(app, ListenerStatus::Starting),
        "ready" => log_line(app, "el detector ha arrancado"),
        // Un aviso es recuperable (el micro tarda, o se ha ido y volverá):
        // queda en el log y en la bandeja, pero no interrumpe al usuario.
        "warning" => {
            let mensaje = event.message.unwrap_or_else(|| "aviso del detector".into());
            log_line(app, &format!("aviso: {mensaje}"));
            set_status(app, ListenerStatus::Down("buscando micrófono".into()));
        }
        "error" => {
            let message = event.message.unwrap_or_else(|| "Fallo de escucha".into());
            log_line(app, &format!("error: {message}"));
            if let Ok(mut process) = app.state::<WakeState>().0.lock() {
                process.last_error = Some(message.clone());
            }
            set_status(app, ListenerStatus::Down(message.clone()));
            if let Some(window) = app.get_webview_window("companion") {
                let _ = window.show();
                let _ = window.set_focus();
            }
            let _ = app.emit("vibi://listener-error", message);
        }
        _ => {}
    }
}

/// Arranca el detector y bloquea hasta que muere. Devuelve Ok si llegó a correr.
fn run_listener_session(app: &AppHandle) -> Result<(), String> {
    let (mut command, model) = resolve_wake_paths(app)?;
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

    let user_paused = {
        let state = app.state::<WakeState>();
        let mut process = state.0.lock().map_err(|_| "Estado de escucha bloqueado")?;
        process.stdin = stdin;
        process.child = Some(child);
        process.user_paused
    };
    // Un detector recién nacido escucha por defecto; si el usuario había
    // pausado desde la bandeja, hay que devolverlo a ese estado.
    if user_paused {
        write_listener(&app.state::<WakeState>(), "pause");
    }

    if let Some(stderr) = stderr {
        let log_app = app.clone();
        thread::spawn(move || {
            for line in BufReader::new(stderr).lines().map_while(Result::ok) {
                log_line(&log_app, &format!("detector (stderr): {line}"));
            }
        });
    }

    for line in BufReader::new(stdout).lines().map_while(Result::ok) {
        handle_wake_event(app, &line);
    }

    // Stdout cerrado: el detector ha muerto. Lo recogemos para no dejar zombis.
    let salida = {
        let state = app.state::<WakeState>();
        let recogido = state.0.lock().ok().and_then(|mut process| {
            process.stdin = None;
            process.child.take()
        });
        recogido.and_then(|mut child| child.wait().ok())
    };
    match salida {
        Some(estado) => log_line(app, &format!("el detector terminó ({estado})")),
        None => log_line(app, "el detector terminó"),
    }
    Ok(())
}

fn backoff_delay(failures: u32) -> Duration {
    if failures == 0 {
        return Duration::from_secs(0);
    }
    let exponente = (failures - 1).min(5);
    Duration::from_secs((1u64 << exponente).min(30))
}

fn is_shutting_down(app: &AppHandle) -> bool {
    app.state::<WakeState>()
        .0
        .lock()
        .map(|process| process.shutting_down)
        .unwrap_or(true)
}

/// Entierra detectores de sesiones anteriores.
///
/// En Windows matar al padre no se lleva a los hijos por delante: si la app se
/// fue de mala manera —un cuelgue, un instalador que la cierra, un kill— su
/// detector sigue vivo con el micrófono cogido, y al arrancar otra vez se
/// acumula uno más. Antes de levantar el nuestro, limpiamos.
///
/// El plugin de instancia única garantiza que no hay otra copia legítima cuyo
/// detector estemos matando por error.
fn kill_orphan_listeners() {
    for image in ["vibi-wake.exe", "morgana-wake.exe"] {
        let _ = Command::new("taskkill")
            .args(["/F", "/IM", image])
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .status();
    }
}

/// Mantiene vivo el detector pase lo que pase: si muere, vuelve a levantarlo.
fn supervise_wake_listener(app: AppHandle) {
    kill_orphan_listeners();
    thread::spawn(move || {
        let mut failures: u32 = 0;
        let mut avisado = false;
        loop {
            if is_shutting_down(&app) {
                break;
            }
            set_status(&app, ListenerStatus::Starting);
            let arrancado = Instant::now();
            match run_listener_session(&app) {
                Ok(()) => {
                    // Si aguantó vivo un buen rato, el fallo es puntual y no
                    // merece heredar la espera de intentos anteriores.
                    if arrancado.elapsed() >= HEALTHY_RUN {
                        failures = 0;
                    }
                    failures += 1;
                }
                Err(mensaje) => {
                    failures += 1;
                    log_line(&app, &format!("no se pudo arrancar el detector: {mensaje}"));
                    if let Ok(mut process) = app.state::<WakeState>().0.lock() {
                        process.last_error = Some(mensaje.clone());
                    }
                    // Sólo molestamos al usuario la primera vez: a partir de
                    // ahí el estado vive en la bandeja y en el log.
                    if !avisado {
                        avisado = true;
                        if let Some(window) = app.get_webview_window("companion") {
                            let _ = window.show();
                            let _ = window.set_focus();
                        }
                        let _ = app.emit("vibi://listener-error", mensaje);
                    }
                }
            }
            if is_shutting_down(&app) {
                break;
            }
            let espera = backoff_delay(failures);
            set_status(
                &app,
                ListenerStatus::Down(format!("reintentando en {}s", espera.as_secs())),
            );
            thread::sleep(espera);
        }
        log_line(&app, "supervisor detenido");
    });
}

#[cfg(target_os = "windows")]
fn start_alt_wake_monitor(app: AppHandle) {
    thread::spawn(move || {
        const VK_MENU: i32 = 0x12;
        const VK_TAB: i32 = 0x09;
        const VK_CONTROL: i32 = 0x11;
        const VK_SHIFT: i32 = 0x10;
        const VK_ESCAPE: i32 = 0x1B;
        const HOLD_DURATION: Duration = Duration::from_millis(400);

        let mut press_start: Option<Instant> = None;
        let mut woken = false;

        extern "system" {
            fn GetAsyncKeyState(vKey: i32) -> i16;
        }

        loop {
            if is_shutting_down(&app) {
                break;
            }
            thread::sleep(Duration::from_millis(30));

            let is_alt_down = unsafe { (GetAsyncKeyState(VK_MENU) as u16 & 0x8000) != 0 };
            let is_other_down = unsafe {
                (GetAsyncKeyState(VK_TAB) as u16 & 0x8000) != 0
                    || (GetAsyncKeyState(VK_CONTROL) as u16 & 0x8000) != 0
                    || (GetAsyncKeyState(VK_SHIFT) as u16 & 0x8000) != 0
                    || (GetAsyncKeyState(VK_ESCAPE) as u16 & 0x8000) != 0
            };

            if is_alt_down && !is_other_down {
                if !woken {
                    match press_start {
                        Some(start) => {
                            if start.elapsed() >= HOLD_DURATION {
                                woken = true;
                                log_line(&app, "despertar por tecla Alt sostenida");
                                let state = app.state::<WakeState>();
                                write_listener(&state, "pause");
                                show_companion(&app, true);
                            }
                        }
                        None => {
                            press_start = Some(Instant::now());
                        }
                    }
                }
            } else {
                press_start = None;
                if !is_alt_down {
                    woken = false;
                }
            }
        }
    });
}

#[cfg(not(target_os = "windows"))]
fn start_alt_wake_monitor(_app: AppHandle) {}

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

/// Abre la consola: bandeja, archivos y permisos pendientes.
///
/// Va en una ventana aparte de la cara porque la cara mide 320×360, no se
/// puede redimensionar y vive siempre encima de todo. Esta sí es una ventana
/// normal: se mueve, se agranda y se queda donde la dejaste.
///
/// `async` no es un adorno: Tauri ejecuta los comandos síncronos en el hilo
/// principal, y en Windows crear una webview desde ahí bloquea a WebView2
/// contra el propio bucle de eventos que tendría que atenderla. El resultado
/// es una ventana en blanco y la aplicación entera congelada —ni la cara, ni
/// la bandeja, ni la X responden— hasta matar el proceso. Marcarlo `async`
/// lo saca a otro hilo, que es lo que documenta Tauri para este caso.
#[tauri::command]
async fn open_panel(app: AppHandle) {
    if let Some(window) = app.get_webview_window("panel") {
        let _ = window.show();
        let _ = window.unminimize();
        let _ = window.set_focus();
        return;
    }

    // Sin fragmento en la URL: esto es una ruta de archivo dentro del bundle, y
    // un `companion.html#panel` se buscaría tal cual, como nombre literal. Quién
    // es cada ventana lo decide su etiqueta, que el frontend consulta al cargar.
    let built = WebviewWindowBuilder::new(
        &app,
        "panel",
        WebviewUrl::App("companion.html".into()),
    )
    .title("Vibi")
    .inner_size(430.0, 640.0)
    .min_inner_size(360.0, 420.0)
    .resizable(true)
    .decorations(true)
    .skip_taskbar(false)
    .build();

    if let Ok(window) = built {
        let _ = window.set_focus();
    }
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
    let url = env::var("VIBI_BASE_URL")
        .or_else(|_| env::var("MORGANA_BASE_URL"))
        .unwrap_or_else(|_| "http://localhost:8000".into());
    let _ = open::that(url);
}

fn build_tray(app: &tauri::App) -> tauri::Result<()> {
    let status = MenuItem::with_id(
        app,
        "status",
        ListenerStatus::Starting.label(),
        false,
        None::<&str>,
    )?;
    let wake = MenuItem::with_id(app, "wake", "Despertar a Vibi", true, None::<&str>)?;
    let pause = MenuItem::with_id(app, "pause", "Pausar escucha", true, None::<&str>)?;
    let resume = MenuItem::with_id(app, "resume", "Reanudar escucha", true, None::<&str>)?;
    let logs = MenuItem::with_id(app, "logs", "Ver registro de escucha", true, None::<&str>)?;
    let open_app = MenuItem::with_id(app, "open", "Abrir Vibi", true, None::<&str>)?;
    let proceso = MenuItem::with_id(
        app,
        "proceso",
        "Ver qué está haciendo",
        true,
        None::<&str>,
    )?;
    let quit = MenuItem::with_id(app, "quit", "Salir", true, None::<&str>)?;
    let menu = Menu::with_items(
        app,
        &[&status, &wake, &pause, &resume, &proceso, &logs, &open_app, &quit],
    )?;
    app.manage(TrayHandles {
        status_item: status,
    });

    let mut tray = TrayIconBuilder::with_id(TRAY_ID);
    if let Some(icon) = app.default_window_icon() {
        tray = tray.icon(icon.clone());
    }

    tray.tooltip(ListenerStatus::Starting.label())
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
            "logs" => {
                if let Ok(directorio) = app.path().app_log_dir() {
                    let _ = fs::create_dir_all(&directorio);
                    let _ = open::that(directorio.join("wake.log"));
                }
            }
            "proceso" => {
                // Vive oculta y se enseña cuando la piden: es una ventana para
                // asomarse, no para tener delante todo el rato.
                if let Some(window) = app.get_webview_window("proceso") {
                    let _ = window.show();
                    let _ = window.set_focus();
                }
            }
            "open" => open_main_app(),
            "quit" => {
                let state = app.state::<WakeState>();
                if let Ok(mut process) = state.0.lock() {
                    // Evita que el supervisor resucite el detector al salir.
                    process.shutting_down = true;
                }
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

/// Devuelve al centro las ventanas que quedaron fuera de toda pantalla.
///
/// `tauri_plugin_window_state` guarda dónde estaba cada ventana y la repone
/// ahí al arrancar. Eso está bien hasta que desenchufas un monitor: la posición
/// guardada apunta a un escritorio que ya no existe —vistas coordenadas como
/// `x: -1816`— y la ventana se abre donde nadie puede verla. La aplicación
/// funciona, arranca, escucha y responde, pero para quien la usa «no va»: no
/// hay nada en la pantalla.
///
/// Pasó de verdad el 19/08/2026 y costó una tarde de diagnóstico, porque todo
/// lo demás daba señales de estar perfectamente.
fn rescatar_ventanas_perdidas(app: &AppHandle) {
    for window in app.webview_windows().values() {
        // Solo se mira lo que el estado guardado puede haber estropeado. Que
        // una ventana esté oculta a propósito es normal aquí —la cara vive
        // escondida entre invocación e invocación—, así que no se fuerza a
        // mostrar nada: solo se recoloca.
        let Ok(posicion) = window.outer_position() else {
            continue;
        };
        let visible_en_algun_monitor = window
            .available_monitors()
            .map(|monitores| {
                monitores.iter().any(|monitor| {
                    let origen = monitor.position();
                    let tamano = monitor.size();
                    posicion.x >= origen.x
                        && posicion.y >= origen.y
                        && posicion.x < origen.x + tamano.width as i32
                        && posicion.y < origen.y + tamano.height as i32
                })
            })
            .unwrap_or(true);
        if !visible_en_algun_monitor {
            log_line(
                app,
                &format!(
                    "la ventana {} estaba fuera de pantalla; la recoloco",
                    window.label()
                ),
            );
            let _ = window.center();
        }
    }
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
        .plugin(tauri_plugin_notification::init())
        .plugin(tauri_plugin_autostart::init(
            MacosLauncher::LaunchAgent,
            Some(vec!["--autostart"]),
        ))
        .manage(WakeState(Mutex::new(WakeProcess::default())))
        .invoke_handler(tauri::generate_handler![
            end_conversation,
            manual_wake,
            open_panel,
            set_listener_paused,
            listener_error
        ])
        .setup(|app| {
            build_tray(app)?;
            let autostart = app.autolaunch();
            if !autostart.is_enabled().unwrap_or(false) {
                let _ = autostart.enable();
            }
            log_line(&app.handle().clone(), "Vibi arrancada");
            rescatar_ventanas_perdidas(&app.handle().clone());
            supervise_wake_listener(app.handle().clone());
            start_alt_wake_monitor(app.handle().clone());
            Ok(())
        })
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                api.prevent_close();
                let _ = window.hide();
                // Cerrar la consola no es despedirse de Vibi: si aquí no se
                // distinguiera una ventana de otra, mirar los permisos en mitad
                // de una conversación la archivaría y la dejaría muda.
                if window.label() != "companion" {
                    return;
                }
                let app = window.app_handle();
                // Ocultar la cara termina la sesión: que el webview archive la
                // conversación para que el próximo despertar empiece en blanco.
                let _ = app.emit("vibi://end-session", ());
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
        .expect("No se pudo construir Vibi Desktop")
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

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn la_espera_crece_y_se_satura() {
        assert_eq!(backoff_delay(0), Duration::from_secs(0));
        assert_eq!(backoff_delay(1), Duration::from_secs(1));
        assert_eq!(backoff_delay(2), Duration::from_secs(2));
        assert_eq!(backoff_delay(3), Duration::from_secs(4));
        assert_eq!(backoff_delay(6), Duration::from_secs(30));
        // El supervisor no se rinde nunca: por muchos fallos que acumule, la
        // espera se queda en el tope y sigue reintentando.
        assert_eq!(backoff_delay(1_000), Duration::from_secs(30));
    }

    #[test]
    fn el_estado_se_describe_en_castellano() {
        assert_eq!(ListenerStatus::Listening.label(), "Vibi está escuchando");
        assert!(ListenerStatus::Down("sin micrófono".into())
            .label()
            .contains("sin micrófono"));
    }
}
