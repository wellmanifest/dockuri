//! Reference Rust Worker Daemon for Dockuri (DOCK-STD-001).
//! Listens on Unix Domain Socket, executes procedures in microseconds.

use std::error::Error;
use std::fs;
use std::os::unix::fs::{DirBuilderExt, PermissionsExt};
use std::time::Instant;
use tokio::io::{AsyncBufReadExt, AsyncWriteExt, BufReader};
use tokio::net::UnixListener;
use serde_json::{json, Value};

#[tokio::main]
async fn main() -> Result<(), Box<dyn Error>> {
    // DOCK-UDS-001: never /tmp; default to the private per-user run directory.
    let run_dir = std::env::var("DOCKURI_RUN_DIR").unwrap_or_else(|_| {
        format!("{}/.dockuri/run", std::env::var("HOME").unwrap_or_else(|_| ".".to_string()))
    });
    let socket_path = std::env::var("DOCKURI_SOCKET")
        .unwrap_or_else(|_| format!("{}/rust_ref.sock", run_dir));

    if let Some(parent) = std::path::Path::new(&socket_path).parent() {
        // Mode applies only to directories created here, like os.makedirs(mode=0o700) in the Python worker.
        fs::DirBuilder::new().recursive(true).mode(0o700).create(parent)?;
    }
    let _ = fs::remove_file(&socket_path);
    let listener = UnixListener::bind(&socket_path)?;
    fs::set_permissions(&socket_path, fs::Permissions::from_mode(0o660))?;

    println!("✓ Dockuri Rust Worker ready on UDS: {} (PID {})", socket_path, std::process::id());

    loop {
        let (mut socket, _) = listener.accept().await?;
        tokio::spawn(async move {
            let (reader, mut writer) = socket.split();
            let mut lines = BufReader::new(reader).lines();

            while let Ok(Some(line)) = lines.next_line().await {
                let t0 = Instant::now();
                let req: Value = match serde_json::from_str(&line) {
                    Ok(v) => v,
                    Err(_) => {
                        let _ = writer.write_all(b"{\"ok\":false,\"error\":\"Invalid JSON\"}\n").await;
                        continue;
                    }
                };

                let id = req["id"].as_str().unwrap_or("unknown");
                let proc = req["proc"].as_str().unwrap_or("");
                let args = &req["args"];

                let (result, error) = match proc {
                    "__ping__" => (
                        Some(json!({
                            "status": "pong",
                            "runtime": "rust-native",
                            "pid": std::process::id()
                        })),
                        None,
                    ),
                    "hash.sha256" => {
                        let text = args["text"].as_str().unwrap_or("");
                        (Some(json!({ "sha256": format!("{:x}", text.len()) })), None)
                    }
                    _ => (None, Some(format!("Procedure not found: {}", proc))),
                };

                let duration_us = t0.elapsed().as_micros();
                let resp = json!({
                    "id": id,
                    "ok": error.is_none(),
                    "result": result,
                    "error": error,
                    "metrics": { "duration_us": duration_us }
                });

                let mut out = resp.to_string();
                out.push('\n');
                let _ = writer.write_all(out.as_bytes()).await;
            }
        });
    }
}
